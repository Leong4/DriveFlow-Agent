"""
Demo endpoint for minimal Maps UI.
Aggregates the entire DriveFlow Agent closed loop into a single POST route.
Does not break the upper-layer boundaries; it simply orchestrates them.
"""

import os
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from app.tools.poi_search import PoiSearchTool
from app.tools.schemas import ToolInput
from app.models.context import CarStateContext
from app.models.task import Task
from app.services.car_state_rules import maybe_insert_charging_task
from app.services.stop_selector import select_best_stop
from app.services.route_optimizer import optimize_stop_order
from app.services.task_graph_builder import TaskGraphBuilder
from app.services.task_planner import TaskPlanner
from app.services.executor import Executor
from app.services.state_manager import StateManager
from app.services.pre_route_service import empty_map_data, run_pre_route_stage

load_dotenv()
_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

router = APIRouter()


class DemoRequest(BaseModel):
    query: str
    origin: Optional[str] = None
    battery_level: Optional[int] = None
    remaining_range_km: Optional[int] = None
    # Edit mode: supply the current task list to apply a natural-language edit
    existing_tasks: Optional[List[Dict[str, Any]]] = None
    # Candidate resolution: user selected a specific POI from the candidate list.
    # When set together with existing_tasks, the matching task is replaced with
    # the selected POI and the pre-route filter is skipped.
    selected_candidate: Optional[Dict[str, Any]] = None
    # Clarification follow-up: opaque context returned by a previous clarification_needed
    # response. When set, the follow-up interpreter runs before the normal parse path.
    pending_clarification: Optional[Dict[str, Any]] = None
    # Continuation flag: when True and existing_tasks is set, the query is parsed fresh
    # and merged into the existing itinerary rather than replacing it.
    is_continuation: bool = False


class DemoResponse(BaseModel):
    parsed_tasks: List[Dict[str, Any]]
    graph_text: str
    planner_result: Optional[Dict[str, Any]]
    tool_result: Optional[Dict[str, Any]]
    state: Dict[str, Any]
    clarification_text: Optional[str]
    guardrail_message: Optional[str]
    map_data: Dict[str, Any]
    # ── Step 1: Pre-route clarification / candidate selection ──────────────────
    # "ready_for_routing" (default) | "clarification_needed" | "candidate_selection_needed"
    pre_route_status: str = "ready_for_routing"
    # Narrowing question shown to the user when pre_route_status == "clarification_needed"
    pre_route_question: Optional[str] = None
    # Ranked POI options when pre_route_status == "candidate_selection_needed"
    # Each entry: {name, address, lat, lng, reason_tag, task_id}
    pre_route_candidates: Optional[List[Dict[str, Any]]] = None
    # Opaque context for the follow-up interpreter; set only when clarification_needed.
    # The frontend must forward this in the next request as pending_clarification.
    pending_clarification: Optional[Dict[str, Any]] = None
    # B1: explicit action representation — inspectable intermediate layer result.
    # Always present; null only when the pipeline did not reach action classification.
    route_action: Optional[Dict[str, Any]] = None


# ── Config endpoint ───────────────────────────────────────────────────────────

@router.get("/demo/config")
def get_config():
    """Returns frontend configuration like the Maps API Key."""
    return {"google_maps_api_key": _API_KEY}


# ── Main demo endpoint ────────────────────────────────────────────────────────

@router.post("/demo/run", response_model=DemoResponse)
async def run_demo(req: DemoRequest):
    # ── 1. Init Core Services ──────────────────────────────────────────────────
    builder  = TaskGraphBuilder()
    planner  = TaskPlanner()
    executor = Executor()
    state_mgr = StateManager()
    poi_tool  = PoiSearchTool()

    origin_text = req.origin or os.getenv("GOOGLE_ROUTE_ORIGIN_TEXT", "University of Nottingham")

    # ── 2. Parsing / Editing / Pre-Route Handling ────────────────────────────
    pre_route_result = await run_pre_route_stage(
        query=req.query,
        origin_text=origin_text,
        existing_tasks=req.existing_tasks,
        selected_candidate=req.selected_candidate,
        pending_clarification=req.pending_clarification,
        is_continuation=req.is_continuation,
        poi_tool=poi_tool,
    )
    if pre_route_result.should_return_early:
        return DemoResponse(**pre_route_result.response_payload)
    task_dicts = pre_route_result.task_dicts

    # ── 3. Rule Augmentation ──────────────────────────────────────────────────
    if req.battery_level is not None and req.remaining_range_km is not None:
        ctx = CarStateContext(
            battery_level=req.battery_level,
            remaining_range_km=req.remaining_range_km,
        )
        task_objs = [Task(**t) for t in task_dicts]
        augmented  = maybe_insert_charging_task(task_objs, ctx)
        task_dicts = [t.model_dump() for t in augmented]

    # ── 3.5. Route Optimization ───────────────────────────────────────────────
    try:
        task_objs_for_opt  = [Task(**t) for t in task_dicts]
        optimized_task_objs = optimize_stop_order(task_objs_for_opt, origin_text)
        task_dicts          = [t.model_dump() for t in optimized_task_objs]
    except Exception:
        pass  # optimizer failure must never crash the demo pipeline

    if not task_dicts:
        return DemoResponse(
            parsed_tasks=[],
            graph_text="(empty itinerary)",
            planner_result=None,
            tool_result=None,
            state={
                "current_task_id":    None,
                "completed_task_ids": [],
                "remaining_task_ids": [],
                "status":             "completed",
                "clarification_needed": False,
            },
            clarification_text=None,
            guardrail_message=None,
            map_data=empty_map_data(origin_text),
        )

    # ── 4. Graph Building ─────────────────────────────────────────────────────
    try:
        task_objs  = [Task(**t) for t in task_dicts]
        graph_obj  = builder.build(task_objs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph Error: {str(e)}")

    # ── 4.5. Init Execution State ─────────────────────────────────────────────
    from app.models.graph import ExecutionState
    all_ids       = [node.task_id for node in graph_obj.nodes]
    current_state = ExecutionState(
        current_task_id=None,
        completed_task_ids=[],
        remaining_task_ids=all_ids,
        status="idle",
        clarification_needed=False,
    )

    guardrail_message  = None
    clarification_text = None
    planner_res_dict   = None
    tool_result_dict   = None

    # ── 5. Planner & Executor (Single Step for Demo) ──────────────────────────
    if (
        current_state.remaining_task_ids
        and not current_state.clarification_needed
        and current_state.status != "failed"
    ):
        decision = planner.plan(graph_obj, current_state)
        planner_res_dict = decision.model_dump()

        if decision.next_task_id and decision.planner_decision != "finished":
            current_state = state_mgr.mark_current(current_state, decision.next_task_id)
            exec_result   = executor.execute(decision, graph_obj)
            tool_result_dict = exec_result.model_dump()

            if exec_result.execution_status == "clarification_needed":
                current_state      = state_mgr.mark_clarification_needed(current_state)
                clarification_text = exec_result.message
            elif exec_result.execution_status == "failed":
                guardrail_message = exec_result.message
                current_state     = current_state.model_copy(update={"status": "failed"})
            else:
                current_state = state_mgr.mark_completed(current_state, decision.next_task_id)
                current_state = state_mgr.recompute_remaining(current_state, graph_obj)

    # ── 6. Map Data Extraction ────────────────────────────────────────────────
    map_data = empty_map_data(origin_text)

    # Geocode origin
    res_orig = poi_tool.run(ToolInput(
        task_id="demo_orig",
        task_type="destination",
        payload={"name": origin_text},
    ))
    if res_orig.data.get("candidates"):
        map_data["origin"].update({
            "lat": res_orig.data["candidates"][0]["lat"],
            "lng": res_orig.data["candidates"][0]["lng"],
        })

    # Geocode destination node
    for node in graph_obj.nodes:
        if node.task_type == "destination":
            dest_name = node.payload.get("destination", node.payload.get("name", "Destination"))
            map_data["destination"]["label"]   = dest_name
            map_data["destination"]["present"] = True
            res_dest = poi_tool.run(ToolInput(
                task_id="demo_dest",
                task_type="destination",
                payload={"name": dest_name},
            ))
            if res_dest.data.get("candidates"):
                map_data["destination"].update({
                    "lat": res_dest.data["candidates"][0]["lat"],
                    "lng": res_dest.data["candidates"][0]["lng"],
                })

    # Derive route endpoint coords for detour ranking
    _origin_coords = None
    _dest_coords   = None
    if map_data["origin"]["lat"] is not None:
        _origin_coords = (map_data["origin"]["lat"], map_data["origin"]["lng"])
    if map_data["destination"]["lat"] is not None:
        _dest_coords = (map_data["destination"]["lat"], map_data["destination"]["lng"])

    # Geocode all stop tasks from the full (optimised) task list
    _stop_types = {"stop", "restaurant", "charging_station"}
    for task_dict in task_dicts:
        task_type = task_dict.get("type", "")
        if task_type not in _stop_types:
            continue

        payload     = task_dict.get("payload") or {}
        search_query = (
            payload.get("query")
            or payload.get("brand")
            or payload.get("label")
            or task_dict.get("brand")
            or task_dict.get("name")
            or task_type
        )
        res_stop = poi_tool.run(ToolInput(
            task_id=task_dict.get("id", "demo_stop"),
            task_type=task_type,
            payload={"query": search_query, "brand": task_dict.get("brand"), "name": task_dict.get("name")},
        ))
        if res_stop.status == "success" and res_stop.data.get("candidates"):
            cand = select_best_stop(_origin_coords, _dest_coords, res_stop.data["candidates"])
            map_data["stops"].append({
                "label":   cand.get("name", search_query),
                "lat":     cand.get("lat"),
                "lng":     cand.get("lng"),
                "type":    task_type,
                "address": cand.get("address", ""),
            })

    # ── 7. Formatting ─────────────────────────────────────────────────────────
    graph_text = f"Nodes: {len(graph_obj.nodes)}\n"
    for node in graph_obj.nodes:
        graph_text += f"- {node.task_id} ({node.task_type})\n"

    return DemoResponse(
        parsed_tasks=task_dicts,
        graph_text=graph_text,
        planner_result=planner_res_dict,
        tool_result=tool_result_dict,
        state=current_state.model_dump(),
        clarification_text=clarification_text,
        guardrail_message=guardrail_message,
        map_data=map_data,
        # ready_for_routing path: no pre-route interception
        pre_route_status="ready_for_routing",
        pre_route_question=None,
        pre_route_candidates=None,
        route_action=pre_route_result.route_action,
    )
