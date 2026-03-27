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

from app.services.intent_parser import parse_intent
from app.tools.poi_search import PoiSearchTool
from app.tools.schemas import ToolInput
from app.models.context import CarStateContext
from app.models.task import Task
from app.models.graph import TaskGraph
from app.services.car_state_rules import maybe_insert_charging_task
from app.services.task_graph_builder import TaskGraphBuilder
from app.services.task_planner import TaskPlanner, PlannerDecisionResult
from app.services.executor import Executor
from app.services.state_manager import StateManager

load_dotenv()
_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

router = APIRouter()

class DemoRequest(BaseModel):
    query: str
    origin: Optional[str] = None
    battery_level: Optional[int] = None
    remaining_range_km: Optional[int] = None

class DemoResponse(BaseModel):
    parsed_tasks: List[Dict[str, Any]]
    graph_text: str
    planner_result: Optional[Dict[str, Any]]
    tool_result: Optional[Dict[str, Any]]
    state: Dict[str, Any]
    clarification_text: Optional[str]
    guardrail_message: Optional[str]
    map_data: Dict[str, Any]


@router.get("/demo/config")
def get_config():
    """Returns frontend configuration like the Maps API Key."""
    return {"google_maps_api_key": _API_KEY}


@router.post("/demo/run", response_model=DemoResponse)
async def run_demo(req: DemoRequest):
    # ── 1. Init Core Services ──
    # parser is now just the parse_intent function
    builder = TaskGraphBuilder()
    planner = TaskPlanner()
    executor = Executor()
    state_mgr = StateManager()

    # Create an empty state
    current_state = {
        "current_task_id": None,
        "completed_task_ids": [],
        "remaining_task_ids": [],
        "status": "idle",
        "clarification_needed": False,
        "guardrail_message": None,
        "clarification_text": None
    }

    # ── 2. Parsing ──
    try:
        parse_result = await parse_intent(req.query)
        if parse_result.parse_status == "failed":
            raise HTTPException(status_code=400, detail="Parse Error: Status failed")
        task_dicts = [t.model_dump() for t in parse_result.tasks]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # ── 3. Rule Augmentation ──
    if req.battery_level is not None and req.remaining_range_km is not None:
        ctx = CarStateContext(
            battery_level=req.battery_level,
            remaining_range_km=req.remaining_range_km
        )
        task_objs = [Task(**t) for t in task_dicts]
        augmented = maybe_insert_charging_task(task_objs, ctx)
        task_dicts = [t.model_dump() for t in augmented]

    # ── 4. Graph Building ──
    try:
        task_objs = [Task(**t) for t in task_dicts]
        graph_obj = builder.build(task_objs)
        raw_graph = graph_obj.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph Error: {str(e)}")

    # Init State remaining IDs
    from app.models.graph import ExecutionState
    all_ids = [node.task_id for node in graph_obj.nodes]
    current_state = ExecutionState(
        current_task_id=None,
        completed_task_ids=[],
        remaining_task_ids=all_ids,
        status="idle",
        clarification_needed=False
    )
    
    # Optional fields we add dynamically for UI
    guardrail_message = None
    clarification_text = None

    planner_res_dict = None
    executed_results = []
    tool_result_dict = None

    # ── 5. Planner & Executor (Single Step for Demo) ──
    # Instead of running the entire loop to completion, we just execute the *next* logical step.
    if current_state.remaining_task_ids and not current_state.clarification_needed and current_state.status != "failed":
        decision = planner.plan(graph_obj, current_state)
        planner_res_dict = decision.model_dump()
        
        if decision.next_task_id and decision.planner_decision != "finished":
            current_state = state_mgr.mark_current(current_state, decision.next_task_id)
            
            exec_result = executor.execute(decision, graph_obj)
            executed_results.append(exec_result)
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

    # ── 6. Map Data Extraction ──
    # Eagerly geocode all points for the frontend so it doesn't have to guess or wait for the executor.
    poi_tool = PoiSearchTool()
    origin_text = req.origin or os.getenv("GOOGLE_ROUTE_ORIGIN_TEXT", "University of Nottingham")
    
    map_data = {
        "origin": {"label": origin_text, "lat": None, "lng": None},
        "stops": [],
        "destination": {"label": "Destination", "lat": None, "lng": None}
    }

    # Geocode Origin
    res_orig = poi_tool.run(ToolInput(task_id="demo_orig", task_type="destination", payload={"name": origin_text}))
    if res_orig.data.get("candidates"):
        map_data["origin"].update({
            "lat": res_orig.data["candidates"][0]["lat"],
            "lng": res_orig.data["candidates"][0]["lng"]
        })

    # Geocode Graph Nodes for Dest
    for node in graph_obj.nodes:
        if node.task_type == "destination":
            dest_name = node.payload.get("destination", node.payload.get("name", "Destination"))
            map_data["destination"]["label"] = dest_name
            res_dest = poi_tool.run(ToolInput(task_id="demo_dest", task_type="destination", payload={"name": dest_name}))
            if res_dest.data.get("candidates") and res_dest.data["candidates"]:
                map_data["destination"].update({
                    "lat": res_dest.data["candidates"][0]["lat"],
                    "lng": res_dest.data["candidates"][0]["lng"]
                })
                
    # Extract Stops directly from executed operations
    for res in executed_results:
        # Check if the step used poi_search and successfully found candidates
        if res.tool_result and getattr(res.tool_result, "tool_name", "") == "poi_search" and res.tool_result.status == "success":
            if res.tool_result.data and "candidates" in res.tool_result.data and res.tool_result.data["candidates"]:
                cand = res.tool_result.data["candidates"][0]
                map_data["stops"].append({
                    "label": cand.get("name", res.task_type),
                    "lat": cand.get("lat"),
                    "lng": cand.get("lng"),
                    "type": res.task_type,
                    "address": cand.get("address", "")
                })

    # ── 7. Formatting ──
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
        map_data=map_data
    )
