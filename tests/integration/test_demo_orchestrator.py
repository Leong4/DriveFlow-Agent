import asyncio
from types import SimpleNamespace

import pytest

from app.services import demo_orchestrator
from app.services.demo_orchestrator import DemoOrchestrator
from app.services.pre_route_service import PreRouteStageResult


def test_demo_orchestrator_returns_pre_route_early_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_pre_route_stage(**kwargs) -> PreRouteStageResult:
        return PreRouteStageResult(
            task_dicts=[],
            should_return_early=True,
            route_action={"action_type": "clarify_missing_slot"},
            response_payload={
                "parsed_tasks": [],
                "graph_text": "(awaiting clarification - please narrow your request)",
                "planner_result": None,
                "tool_result": None,
                "state": {
                    "current_task_id": None,
                    "completed_task_ids": [],
                    "remaining_task_ids": [],
                    "status": "idle",
                    "clarification_needed": True,
                },
                "clarification_text": "What type of food are you looking for?",
                "guardrail_message": None,
                "map_data": {
                    "origin": {"label": "University of Nottingham", "lat": None, "lng": None},
                    "stops": [],
                    "destination": {"label": None, "lat": None, "lng": None, "present": False},
                },
                "pre_route_status": "clarification_needed",
                "pre_route_question": "What type of food are you looking for?",
                "pre_route_candidates": None,
                "pending_clarification": {
                    "domain": "food",
                    "question_asked": "What type of food are you looking for?",
                    "original_query": "I want to eat something",
                },
                "route_action": {"action_type": "clarify_missing_slot"},
            },
        )

    monkeypatch.setattr(demo_orchestrator, "run_pre_route_stage", fake_run_pre_route_stage)
    req = SimpleNamespace(
        query="I want to eat something",
        origin="University of Nottingham",
        existing_tasks=None,
        selected_candidate=None,
        pending_clarification=None,
        is_continuation=False,
        battery_level=None,
        remaining_range_km=None,
    )

    result = asyncio.run(DemoOrchestrator().run(req))

    assert result["pre_route_status"] == "clarification_needed"
    assert result["pending_clarification"]["domain"] == "food"
    assert result["route_action"]["action_type"] == "clarify_missing_slot"

