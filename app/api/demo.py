"""
Demo endpoint for minimal Maps UI.
Defines the HTTP contract and delegates the closed-loop demo pipeline to
DemoOrchestrator.
"""

import os
from dotenv import load_dotenv
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from app.services.demo_orchestrator import DemoOrchestrator

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
    return await DemoOrchestrator().run(req)
