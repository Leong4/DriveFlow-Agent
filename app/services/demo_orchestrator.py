"""DemoOrchestrator - owns the full /demo/run pipeline outside the API layer.

The FastAPI route should stay focused on HTTP request/response handling. This
service keeps the existing demo behavior while making the closed-loop pipeline
callable and testable without going through FastAPI.
"""

import os
from typing import Any

from fastapi import HTTPException

from app.models.graph import ExecutionState
from app.models.task import Task
from app.models.context import CarStateContext
from app.services.charging_augmenter import ChargingAugmenter
from app.services.executor import Executor
from app.services.pre_route_service import empty_map_data, run_pre_route_stage
from app.services.map_data_builder import MapDataBuilder
from app.services.route_optimizer import optimize_stop_order
from app.services.state_manager import StateManager
from app.services.task_graph_builder import TaskGraphBuilder
from app.services.task_planner import TaskPlanner
from app.tools.poi_search import PoiSearchTool


class DemoOrchestrator:
    """Run the DriveFlow demo pipeline for one frontend request."""

    async def run(self, req: Any) -> dict[str, Any]:
        # ── 1. Init Core Services ─────────────────────────────────────────────
        builder = TaskGraphBuilder()
        planner = TaskPlanner()
        executor = Executor()
        state_mgr = StateManager()
        poi_tool = PoiSearchTool()

        origin_text = req.origin or os.getenv("GOOGLE_ROUTE_ORIGIN_TEXT", "University of Nottingham")

        # ── 2. Parsing / Editing / Pre-Route Handling ────────────────────────
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
            return pre_route_result.response_payload
        task_dicts = pre_route_result.task_dicts

        # ── 3. Rule Augmentation ─────────────────────────────────────────────
        if req.battery_level is not None and req.remaining_range_km is not None:
            ctx = CarStateContext(
                battery_level=req.battery_level,
                remaining_range_km=req.remaining_range_km,
            )
            task_dicts = ChargingAugmenter(poi_tool).augment(task_dicts, ctx, origin_text)

        # ── 3.5. Route Optimization ──────────────────────────────────────────
        try:
            task_objs_for_opt = [Task(**t) for t in task_dicts]
            optimized_task_objs = optimize_stop_order(task_objs_for_opt, origin_text)
            task_dicts = [t.model_dump() for t in optimized_task_objs]
        except Exception:
            pass  # optimizer failure must never crash the demo pipeline

        if not task_dicts:
            return {
                "parsed_tasks": [],
                "graph_text": "(empty itinerary)",
                "planner_result": None,
                "tool_result": None,
                "state": {
                    "current_task_id": None,
                    "completed_task_ids": [],
                    "remaining_task_ids": [],
                    "status": "completed",
                    "clarification_needed": False,
                },
                "clarification_text": None,
                "guardrail_message": None,
                "map_data": empty_map_data(origin_text),
            }

        # ── 4. Graph Building ────────────────────────────────────────────────
        try:
            task_objs = [Task(**t) for t in task_dicts]
            graph_obj = builder.build(task_objs)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Graph Error: {str(e)}")

        # ── 4.5. Init Execution State ────────────────────────────────────────
        all_ids = [node.task_id for node in graph_obj.nodes]
        current_state = ExecutionState(
            current_task_id=None,
            completed_task_ids=[],
            remaining_task_ids=all_ids,
            status="idle",
            clarification_needed=False,
        )

        guardrail_message = None
        clarification_text = None
        planner_res_dict = None
        tool_result_dict = None

        # ── 5. Planner & Executor (Single Step for Demo) ─────────────────────
        if (
            current_state.remaining_task_ids
            and not current_state.clarification_needed
            and current_state.status != "failed"
            and not pre_route_result.suppress_execution
        ):
            decision = planner.plan(graph_obj, current_state)
            planner_res_dict = decision.model_dump()

            if decision.next_task_id and decision.planner_decision != "finished":
                current_state = state_mgr.mark_current(current_state, decision.next_task_id)
                exec_result = executor.execute(decision, graph_obj)
                tool_result_dict = exec_result.model_dump()

                if exec_result.execution_status == "clarification_needed":
                    current_state = state_mgr.mark_clarification_needed(current_state)
                    clarification_text = exec_result.message
                elif exec_result.execution_status == "failed":
                    guardrail_message = exec_result.message
                    current_state = current_state.model_copy(update={"status": "failed"})
                else:
                    current_state = state_mgr.mark_completed(current_state, decision.next_task_id)
                    current_state = state_mgr.recompute_remaining(current_state, graph_obj)

        # ── 6. Map Data Extraction ────────────────────────────────────────────
        map_data = MapDataBuilder(poi_tool).build(
            origin_text=origin_text,
            graph_obj=graph_obj,
            task_dicts=task_dicts,
        )

        # ── 7. Formatting ─────────────────────────────────────────────────────
        graph_text = f"Nodes: {len(graph_obj.nodes)}\n"
        for node in graph_obj.nodes:
            graph_text += f"- {node.task_id} ({node.task_type})\n"

        return {
            "parsed_tasks": task_dicts,
            "graph_text": graph_text,
            "planner_result": planner_res_dict,
            "tool_result": tool_result_dict,
            "state": current_state.model_dump(),
            "clarification_text": clarification_text,
            "guardrail_message": guardrail_message,
            "map_data": map_data,
            # ready_for_routing path: no pre-route interception
            "pre_route_status": "ready_for_routing",
            "pre_route_question": None,
            "pre_route_candidates": None,
            "route_action": pre_route_result.route_action,
        }
