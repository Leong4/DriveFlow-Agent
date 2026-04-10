"""
PreRouteService — demo-layer orchestration for the Step 1 pre-route stage.

Owns:
  - parse / edit / selected-candidate re-entry handling
  - pre-route classification
  - blocking clarification / candidate-selection response shaping

This keeps app/api/demo.py focused on the normal route execution pipeline.
"""

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel

from app.models.task import Task
from app.services.action_intent import ActionType, RouteAction, classify_route_action
from app.services.clarification_followup import (
    ClarificationContext,
    interpret_clarification_followup,
)
from app.services.intent_parser import parse_intent
from app.services.itinerary_editor import (
    EditIntent,
    apply_edit,
    insert_before as _insert_before,
    replace as _replace,
    remove as _remove,
)
from app.services.pre_route_filter import PreRouteDecision, classify_tasks
from app.services.semantic_intent import (
    SemanticIntentMode,
    classify_semantic_intent,
)
from app.services.stop_selector import filter_candidates_by_radius, rank_stops
from app.tools.poi_search import PoiSearchTool
from app.tools.schemas import ToolInput


class PreRouteStageResult(BaseModel):
    """Result of the demo pre-route stage."""

    task_dicts: List[Dict[str, Any]]
    should_return_early: bool = False
    response_payload: Optional[Dict[str, Any]] = None
    # Explicit action representation — included in all responses for inspectability.
    route_action: Optional[Dict[str, Any]] = None


def empty_map_data(origin_text: str) -> Dict[str, Any]:
    return {
        "origin": {"label": origin_text, "lat": None, "lng": None},
        "stops": [],
        "destination": {"label": None, "lat": None, "lng": None, "present": False},
    }


def _build_pre_route_candidates(
    candidates: list,
    trigger_task_id: str,
    origin_coords: Optional[tuple],
    dest_coords: Optional[tuple],
    is_delegation: bool,
    max_candidates: int = 4,
) -> List[Dict[str, Any]]:
    """Rank raw POI candidates and attach reason tags for the UI."""
    # Sanity-filter out candidates that are implausibly far from the route corridor
    # before ranking, so distant results don't pollute the top of the list.
    sane = filter_candidates_by_radius(candidates, origin_coords, dest_coords)
    if origin_coords and dest_coords:
        ranked = rank_stops(origin_coords, dest_coords, sane)
    else:
        ranked = list(sane)

    tags = (
        ["recommended", "nearest", "also nearby", "also nearby"]
        if is_delegation
        else ["best along route", "also nearby", "also nearby", "also nearby"]
    )

    result = []
    for i, c in enumerate(ranked[:max_candidates]):
        result.append({
            "name": c.get("name", ""),
            "address": c.get("address", ""),
            "lat": c.get("lat"),
            "lng": c.get("lng"),
            "reason_tag": tags[i] if i < len(tags) else "also nearby",
            "task_id": trigger_task_id,
        })
    return result


def _make_semantic_stop_task(category: str) -> Dict[str, Any]:
    """Create a minimal vague stop task from a semantic broad-need category."""
    return Task(
        id="task_semantic_1",
        type="stop",
        name=None,
        brand=None,
        constraints=None,
        order_hint=1,
        payload={
            "label": category,
            "query": category,
            "original_text": category,
        },
    ).model_dump()


def _make_specific_stop_task(
    task_id: str,
    search_text: str,
    original_text: str,
) -> Dict[str, Any]:
    """Create a minimal explicit stop task from semantic along-route framing."""
    return Task(
        id=task_id,
        type="stop",
        name=None,
        brand=None,
        constraints=None,
        order_hint=1,
        payload={
            "label": search_text,
            "query": search_text,
            "original_text": original_text,
        },
    ).model_dump()


def _normalize_destination_tasks(task_dicts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only the last destination as final; demote earlier destinations to stops."""
    if not task_dicts:
        return []

    last_destination_idx = None
    for idx, task_dict in enumerate(task_dicts):
        if task_dict.get("type") == "destination":
            last_destination_idx = idx

    if last_destination_idx is None:
        return [dict(t, order_hint=i + 1) for i, t in enumerate(task_dicts)]

    normalized: List[Dict[str, Any]] = []
    for idx, task_dict in enumerate(task_dicts):
        t_copy = dict(task_dict)
        if t_copy.get("type") == "destination" and idx != last_destination_idx:
            t_copy["type"] = "stop"
            dest_name = t_copy.get("name") or ""
            payload = dict(t_copy.get("payload") or {})
            if dest_name:
                payload.setdefault("label", dest_name)
                payload.setdefault("query", dest_name)
            t_copy["payload"] = payload or None
        normalized.append(dict(t_copy, order_hint=idx + 1))
    return normalized


def _merge_continuation_tasks(
    existing_tasks: List[Dict[str, Any]],
    new_tasks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge a continuation query's parsed tasks into the existing task list.

    Rules:
    - New stop tasks are appended after existing stops.
    - If a new destination appears AND an existing destination is already present,
      the existing destination is demoted to a stop (it becomes a waypoint en route
      to the new final destination).
    - Order hints are recomputed sequentially from 1.

    This preserves the original itinerary by default — nothing is removed.
    """
    existing_sorted = sorted(_normalize_destination_tasks(existing_tasks), key=lambda t: t.get("order_hint", 0))
    normalized_new_tasks = _normalize_destination_tasks(new_tasks)
    new_stops = [t for t in normalized_new_tasks if t.get("type") in {"stop", "restaurant"}]
    new_destination = next((t for t in normalized_new_tasks if t.get("type") == "destination"), None)

    if new_destination:
        result: List[Dict[str, Any]] = []
        for et in existing_sorted:
            if et.get("type") == "destination":
                # Demote the old destination to a stop so it becomes a waypoint.
                demoted = dict(et)
                demoted["type"] = "stop"
                dest_name = et.get("name") or ""
                if dest_name:
                    payload = dict(demoted.get("payload") or {})
                    payload.setdefault("label", dest_name)
                    payload.setdefault("query", dest_name)
                    demoted["payload"] = payload
                result.append(demoted)
            else:
                result.append(et)
        result.extend(new_stops)
        result.append(new_destination)
    else:
        result = list(existing_sorted) + new_stops

    return _normalize_destination_tasks(result)


def _resolve_selected_candidate(
    existing_tasks: List[Dict[str, Any]],
    selected_candidate: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Replace the matching vague/brand task with the chosen place."""
    task_dicts = [t.copy() for t in existing_tasks]
    target_id = selected_candidate.get("task_id")
    for td in task_dicts:
        if td.get("id") == target_id:
            selected_name = selected_candidate.get("name", "")
            selected_address = selected_candidate.get("address", "")
            resolved_query = (
                f"{selected_name}, {selected_address}"
                if selected_name and selected_address
                else selected_name or selected_address
            )
            payload = dict(td.get("payload") or {})
            payload["query"] = resolved_query
            payload["label"] = selected_name
            payload["address"] = selected_address
            payload["lat"] = selected_candidate.get("lat")
            payload["lng"] = selected_candidate.get("lng")
            payload["brand"] = None
            td["payload"] = payload
            # For destination tasks, also update `name` so TaskGraphBuilder
            # picks up the specific selected place (it copies task.name into
            # payload["name"] which demo.py uses for geocoding).
            if td.get("type") == "destination" and resolved_query:
                td["name"] = resolved_query
            break
    return task_dicts


def _build_blocking_response_payload(
    task_dicts: List[Dict[str, Any]],
    origin_text: str,
    pre_decision: PreRouteDecision,
    poi_tool: PoiSearchTool,
    raw_query: str = "",
    route_action: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the demo response payload for blocking Step 1 states."""
    origin_map = {"label": origin_text, "lat": None, "lng": None}
    res_orig = poi_tool.run(ToolInput(
        task_id="demo_orig",
        task_type="destination",
        payload={"name": origin_text},
    ))
    if res_orig.data.get("candidates"):
        origin_map["lat"] = res_orig.data["candidates"][0]["lat"]
        origin_map["lng"] = res_orig.data["candidates"][0]["lng"]
    origin_coords = (
        (origin_map["lat"], origin_map["lng"])
        if origin_map["lat"] is not None else None
    )

    dest_map = {"label": None, "lat": None, "lng": None, "present": False}
    dest_coords = None
    suppress_unresolved_destination = any(
        td.get("id") == pre_decision.trigger_task_id and td.get("type") == "destination"
        for td in task_dicts
    ) and pre_decision.status == "candidate_selection_needed"
    if not suppress_unresolved_destination:
        for td in task_dicts:
            if td.get("type") != "destination":
                continue
            dest_name = td.get("name") or ""
            if dest_name:
                dest_map["label"] = dest_name
                dest_map["present"] = True
                res_dest = poi_tool.run(ToolInput(
                    task_id="demo_dest",
                    task_type="destination",
                    payload={"name": dest_name},
                ))
                if res_dest.data.get("candidates"):
                    dest_map["lat"] = res_dest.data["candidates"][0]["lat"]
                    dest_map["lng"] = res_dest.data["candidates"][0]["lng"]
                    if dest_map["lat"] is not None:
                        dest_coords = (dest_map["lat"], dest_map["lng"])
            break

    pre_route_candidates = None
    if pre_decision.status == "candidate_selection_needed" and pre_decision.candidate_query:
        cand_result = poi_tool.run(ToolInput(
            task_id="pre_route_cands",
            task_type="stop",
            payload={"query": pre_decision.candidate_query},
        ))
        if cand_result.status == "success" and cand_result.data.get("candidates"):
            pre_route_candidates = _build_pre_route_candidates(
                candidates=cand_result.data["candidates"],
                trigger_task_id=pre_decision.trigger_task_id or "",
                origin_coords=origin_coords,
                dest_coords=dest_coords,
                is_delegation=pre_decision.is_delegation,
                max_candidates=4,
            )

    # Geocode already-resolved stops so they stay visible on the map during
    # blocking states.  Runs for both candidate_selection_needed AND clarification_needed
    # so that stops already on the route don't vanish when a new category query is added.
    # Skips: the pending candidate/clarification task, destination tasks, charging_station.
    resolved_map_stops: List[Dict[str, Any]] = []
    if pre_decision.status in ("candidate_selection_needed", "clarification_needed"):
        _stop_types = {"stop", "restaurant"}
        for td in task_dicts:
            if td.get("id") == pre_decision.trigger_task_id:
                continue   # this task is the one awaiting user selection — skip
            if td.get("type") not in _stop_types:
                continue
            s_payload = td.get("payload") or {}
            s_query = (
                s_payload.get("query")
                or s_payload.get("label")
                or td.get("name")
                or "point of interest"
            )
            s_result = poi_tool.run(ToolInput(
                task_id=td.get("id", "demo_resolved"),
                task_type="stop",
                payload={"query": s_query, "brand": td.get("brand"), "name": td.get("name")},
            ))
            if s_result.status == "success" and s_result.data.get("candidates"):
                best = s_result.data["candidates"][0]
                resolved_map_stops.append({
                    "label":   best.get("name", s_query),
                    "lat":     best.get("lat"),
                    "lng":     best.get("lng"),
                    "type":    td.get("type", "stop"),
                    "address": best.get("address", ""),
                })

    is_clarification = pre_decision.status == "clarification_needed"

    # Build pending_clarification context so the frontend can send it back
    # with the user's follow-up answer.
    pending_clarification = None
    if is_clarification and pre_decision.clarification_domain:
        pending_clarification = {
            "domain": pre_decision.clarification_domain,
            "question_asked": pre_decision.question or "",
            "original_query": raw_query,
        }

    return {
        "parsed_tasks": task_dicts,
        "graph_text": (
            "(awaiting clarification — please narrow your request)"
            if is_clarification
            else "(awaiting candidate selection)"
        ),
        "planner_result": None,
        "tool_result": None,
        "state": {
            "current_task_id": None,
            "completed_task_ids": [],
            "remaining_task_ids": [],
            "status": "idle",
            "clarification_needed": is_clarification,
        },
        "clarification_text": pre_decision.question if is_clarification else None,
        "guardrail_message": None,
        "map_data": {
            "origin": origin_map,
            "stops": resolved_map_stops,   # already-resolved stops stay visible
            "destination": dest_map,
        },
        "pre_route_status": pre_decision.status,
        "pre_route_question": pre_decision.question if is_clarification else None,
        "pre_route_candidates": pre_route_candidates,
        "pending_clarification": pending_clarification,
        "route_action": route_action,
    }


async def run_pre_route_stage(
    query: str,
    origin_text: str,
    existing_tasks: Optional[List[Dict[str, Any]]] = None,
    selected_candidate: Optional[Dict[str, Any]] = None,
    pending_clarification: Optional[Dict[str, Any]] = None,
    is_continuation: bool = False,
    poi_tool: Optional[PoiSearchTool] = None,
) -> PreRouteStageResult:
    """Resolve Step 1 inputs and return either updated tasks or a blocking response."""
    poi_tool = poi_tool or PoiSearchTool()
    semantic_intent = classify_semantic_intent(
        query,
        has_existing_tasks=existing_tasks is not None,
        has_selected_candidate=selected_candidate is not None,
    )

    # ── B1: classify explicit route action ───────────────────────────────────
    # Translates the semantic intent into a named action that drives dispatch.
    # Deterministic — no LLM calls.
    route_action = classify_route_action(
        semantic_intent,
        query,
        is_continuation=is_continuation,
        has_existing_tasks=existing_tasks is not None,
    )
    print(
        f"[demo] route_action={route_action.action_type!r}"
        + (f" domain={route_action.domain!r}" if route_action.domain else "")
        + (f" requires_candidates={route_action.requires_candidate_selection}" if route_action.requires_candidate_selection else "")
        + (f" requires_clarification={route_action.requires_clarification}" if route_action.requires_clarification else "")
    )

    # ── Priority 1: candidate resolution (selected_candidate + existing_tasks) ──
    # (handled further below via mode detection)

    # ── Priority 2: clarification follow-up ──────────────────────────────────
    # If there is a pending clarification context and the user has NOT selected a
    # candidate and has NOT submitted existing_tasks (those paths take priority),
    # ask the LLM whether this query answers the clarification.
    if (
        pending_clarification
        and not selected_candidate
        and not existing_tasks
    ):
        ctx = ClarificationContext(**pending_clarification)
        interpretation = await interpret_clarification_followup(query, ctx)
        print(
            f"[demo] followup_check: is_followup={interpretation.is_followup_answer!r} "
            f"search_query={interpretation.search_query!r} "
            f"delegation={interpretation.delegation!r}"
        )
        if interpretation.is_followup_answer and interpretation.search_query:
            # Build a synthetic stop task using the resolved search_query
            from app.models.task import Task as TaskModel
            synthetic_task = TaskModel(
                id="task_followup_1",
                type="stop",
                name=interpretation.resolved_subtype,
                brand=None,
                constraints=None,
                order_hint=1,
                payload={
                    "label": interpretation.search_query,
                    "query": interpretation.search_query,
                    "original_text": query,
                },
            ).model_dump()
            task_dicts = [synthetic_task]
            # Route directly to candidate selection
            pre_decision = PreRouteDecision(
                status="candidate_selection_needed",
                trigger_task_id="task_followup_1",
                candidate_query=interpretation.search_query,
                is_delegation=interpretation.delegation,
            )
            return PreRouteStageResult(
                task_dicts=task_dicts,
                should_return_early=True,
                route_action=route_action.model_dump(),
                response_payload=_build_blocking_response_payload(
                    task_dicts=task_dicts,
                    origin_text=origin_text,
                    pre_decision=pre_decision,
                    poi_tool=poi_tool,
                    raw_query=query,
                    route_action=route_action.model_dump(),
                ),
            )
        # LLM said not a follow-up — fall through to normal parse

    # ── Priority 3: continuation / append ────────────────────────────────────
    # Triggered by the explicit route_action — not by the raw is_continuation flag.
    # Both "and take me to Tesco" (is_continuation=True) and "Starbucks on the way"
    # (along_route_append=True) now flow through the same action-driven gate.
    if route_action.action_type == ActionType.APPEND_STOP and existing_tasks:
        try:
            if route_action.stop_query:
                # stop_query is set when the action was produced from along_route_append;
                # the search text is already extracted — no parser call needed.
                raw_new_tasks = [
                    _make_specific_stop_task(
                        task_id="task_cont_1",
                        search_text=route_action.stop_query,
                        original_text=query,
                    )
                ]
            else:
                parse_result = await parse_intent(query)
                if parse_result.parse_status == "failed":
                    raise HTTPException(status_code=400, detail="Parse Error: Status failed")
                raw_new_tasks = [t.model_dump() for t in parse_result.tasks]

            # Re-ID new tasks to avoid collision with existing task IDs.
            # Without this, _resolve_selected_candidate could update the wrong task
            # when both lists share the same parser-generated IDs (e.g. "task_1").
            existing_ids = {t.get("id", "") for t in existing_tasks}
            new_task_dicts = []
            for i, t in enumerate(raw_new_tasks):
                t_copy = dict(t)
                if t_copy.get("id") in existing_ids:
                    t_copy["id"] = f"task_cont_{i + 1}"
                new_task_dicts.append(t_copy)

            task_dicts = _merge_continuation_tasks(existing_tasks, new_task_dicts)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        # Filter ONLY the new tasks — existing tasks were already processed in
        # prior turns and must not be re-checked (doing so would cause a demoted
        # destination like "McDonald's" to trigger candidate_selection again).
        new_task_objs = [Task(**t) for t in new_task_dicts]
        pre_decision = classify_tasks(new_task_objs, query)
        print(f"[demo] continuation merge | new_tasks={len(new_task_dicts)} | pre_route_status={pre_decision.status!r}")

        if pre_decision.status not in ("clarification_needed", "candidate_selection_needed"):
            return PreRouteStageResult(
                task_dicts=task_dicts,
                route_action=route_action.model_dump(),
            )

        return PreRouteStageResult(
            task_dicts=task_dicts,
            should_return_early=True,
            route_action=route_action.model_dump(),
            response_payload=_build_blocking_response_payload(
                task_dicts=task_dicts,
                origin_text=origin_text,
                pre_decision=pre_decision,
                poi_tool=poi_tool,
                raw_query=query,
                route_action=route_action.model_dump(),
            ),
        )

    # ── Mode dispatch — driven by explicit action type ────────────────────────
    # Derives the internal processing mode from the route_action rather than
    # directly from semantic_intent.mode, making the dispatch explicitly named.
    mode = (
        "candidate_resolve"  if route_action.action_type == ActionType.RESOLVE_CANDIDATE
        else "edit"          if route_action.action_type == ActionType.REPLACE_STOP
        else "broad_need"    if route_action.action_type == ActionType.CLARIFY_MISSING_SLOT
        else "search_category" if route_action.action_type == ActionType.SEARCH_POI_CATEGORY
        else "parse"   # SET_DESTINATION, APPEND_STOP, UNKNOWN — parser resolves details
    )
    print(f"[demo] mode={mode!r} | action={route_action.action_type!r} | query={query!r}")

    skip_pre_route_filter = False
    task_dicts: List[Dict[str, Any]] = []

    if mode == "candidate_resolve":
        try:
            task_dicts = _resolve_selected_candidate(existing_tasks, selected_candidate)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Candidate Resolution Error: {str(e)}")
        task_dicts = _normalize_destination_tasks(task_dicts)
        skip_pre_route_filter = True

    elif mode == "edit":
        try:
            existing_task_objs = [Task(**t) for t in existing_tasks]
            target = route_action.target_query
            edit_op = (route_action.constraints or {}).get("edit_op")

            if target is not None and edit_op:
                # Operands and sub-operation were extracted once in classify_route_action.
                # Dispatch directly from the action — no re-parse of the query string.
                if edit_op == EditIntent.INSERT_BEFORE:
                    edited_task_objs = _insert_before(
                        existing_task_objs, target, route_action.replacement_query or ""
                    )
                elif edit_op == EditIntent.REPLACE:
                    edited_task_objs = _replace(
                        existing_task_objs, target, route_action.replacement_query or ""
                    )
                else:  # EditIntent.REMOVE
                    edited_task_objs = _remove(existing_task_objs, target)
                print(
                    f"[demo] edit dispatch from action: op={edit_op!r}"
                    f" target={target!r} replacement={route_action.replacement_query!r}"
                )
            else:
                # Action could not extract operands (e.g. unknown pattern) — fall back.
                edited_task_objs, _ = apply_edit(existing_task_objs, query)
                print(f"[demo] edit dispatch: fell back to apply_edit for query={query!r}")

            task_dicts = [t.model_dump() for t in edited_task_objs]
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Edit Error: {str(e)}")
        task_dicts = _normalize_destination_tasks(task_dicts)

    elif mode == "broad_need":
        task_dicts = [_make_semantic_stop_task(semantic_intent.category or "point of interest")]

    elif mode == "search_category":
        # B2: vocabulary-normalised category query (e.g. "I need a pharmacy" → "pharmacy").
        # The category is already extracted and canonical; no parser call needed.
        category = route_action.category or route_action.stop_query or "point of interest"
        new_task_dict = _make_semantic_stop_task(category)

        # Route context is a first-class signal: if an active itinerary exists, merge
        # the new category stop in rather than replacing the whole route.
        if (route_action.constraints or {}).get("append_to_existing") and existing_tasks:
            task_dicts = _merge_continuation_tasks(existing_tasks, [new_task_dict])
        else:
            task_dicts = [new_task_dict]

        # Classify only the new task so existing (already-processed) tasks do not
        # re-trigger candidate selection for previously resolved stops.
        new_task_obj = Task(**new_task_dict)
        pre_decision = classify_tasks([new_task_obj], query)
        print(
            f"[demo] search_category: category={category!r} "
            f"append={bool((route_action.constraints or {}).get('append_to_existing'))} "
            f"pre_route_status={pre_decision.status!r}"
        )

        if pre_decision.status not in ("clarification_needed", "candidate_selection_needed"):
            return PreRouteStageResult(
                task_dicts=task_dicts,
                route_action=route_action.model_dump(),
            )

        return PreRouteStageResult(
            task_dicts=task_dicts,
            should_return_early=True,
            route_action=route_action.model_dump(),
            response_payload=_build_blocking_response_payload(
                task_dicts=task_dicts,
                origin_text=origin_text,
                pre_decision=pre_decision,
                poi_tool=poi_tool,
                raw_query=query,
                route_action=route_action.model_dump(),
            ),
        )

    else:
        try:
            parse_result = await parse_intent(query)
            if parse_result.parse_status == "failed":
                raise HTTPException(status_code=400, detail="Parse Error: Status failed")
            task_dicts = [t.model_dump() for t in parse_result.tasks]
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        task_dicts = _normalize_destination_tasks(task_dicts)

    if skip_pre_route_filter:
        return PreRouteStageResult(
            task_dicts=task_dicts,
            route_action=route_action.model_dump(),
        )

    task_objs_for_filter = [Task(**t) for t in task_dicts]
    pre_decision = classify_tasks(task_objs_for_filter, query)
    print(f"[demo] pre_route_status={pre_decision.status!r}")

    # ── Destination candidate override ────────────────────────────────────────
    # classify_tasks only inspects stop/restaurant tasks; destination tasks slip
    # through to ready_for_routing even when the action requires candidate selection
    # (e.g. "Take me to McDonald's" — branded, non-unique destination).
    # Use route_action.requires_candidate_selection as the explicit signal to
    # intercept and force candidate_selection_needed for such destinations.
    if (
        pre_decision.status == "ready_for_routing"
        and route_action.requires_candidate_selection
    ):
        for t_obj in task_objs_for_filter:
            if t_obj.type == "destination" and t_obj.name:
                pre_decision = PreRouteDecision(
                    status="candidate_selection_needed",
                    trigger_task_id=t_obj.id,
                    candidate_query=t_obj.name,
                    is_delegation=False,
                )
                print(f"[demo] action override → candidate_selection_needed for {t_obj.name!r}")
                break

    if pre_decision.status not in ("clarification_needed", "candidate_selection_needed"):
        return PreRouteStageResult(
            task_dicts=task_dicts,
            route_action=route_action.model_dump(),
        )

    return PreRouteStageResult(
        task_dicts=task_dicts,
        should_return_early=True,
        route_action=route_action.model_dump(),
        response_payload=_build_blocking_response_payload(
            task_dicts=task_dicts,
            origin_text=origin_text,
            pre_decision=pre_decision,
            poi_tool=poi_tool,
            raw_query=query,
            route_action=route_action.model_dump(),
        ),
    )
