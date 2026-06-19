import asyncio

import pytest

from app.models.intent_result import IntentParseResult
from app.models.task import Task
from app.services import pre_route_service
from app.services.pre_route_service import run_pre_route_stage
from app.tools.schemas import ToolInput, ToolResult


ORIGIN = "University of Nottingham"


class FakePoiTool:
    """Deterministic POI tool for pre-route integration tests."""

    def __init__(self) -> None:
        self.calls: list[ToolInput] = []

    def run(self, tool_input: ToolInput) -> ToolResult:
        self.calls.append(tool_input)
        query = (
            tool_input.payload.get("query")
            or tool_input.payload.get("name")
            or tool_input.payload.get("label")
            or ""
        )
        candidates = _candidates_for(query)
        return ToolResult(
            tool_name="fake_poi_search",
            status="success" if candidates else "failed",
            data={"candidates": candidates},
        )


def _candidates_for(query: str) -> list[dict]:
    normalized = query.lower()
    if "university of nottingham" in normalized:
        return [
            {
                "name": "University of Nottingham",
                "address": "University Park, Nottingham",
                "lat": 52.938,
                "lng": -1.198,
            }
        ]
    if "mcdonald" in normalized:
        return [
            {
                "name": "McDonald's Nottingham",
                "address": "Clumber Street, Nottingham",
                "lat": 52.954,
                "lng": -1.149,
            },
            {
                "name": "McDonald's Beeston",
                "address": "Beeston, Nottingham",
                "lat": 52.925,
                "lng": -1.215,
            },
        ]
    if "east midlands airport" in normalized:
        return [
            {
                "name": "East Midlands Airport",
                "address": "Castle Donington",
                "lat": 52.831,
                "lng": -1.328,
            }
        ]
    return []


def _destination_task(task_id: str, name: str, order_hint: int = 1) -> Task:
    return Task(
        id=task_id,
        type="destination",
        name=name,
        brand=None,
        constraints=None,
        order_hint=order_hint,
    )


@pytest.fixture(autouse=True)
def no_real_llm_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep integration tests deterministic even when a local .env has LLM keys."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)


def test_broad_need_returns_clarification_without_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_parse_intent(query: str) -> IntentParseResult:
        raise AssertionError(f"parse_intent should not run for broad need query: {query}")

    monkeypatch.setattr(pre_route_service, "parse_intent", fail_parse_intent)

    result = asyncio.run(
        run_pre_route_stage(
            query="I want to eat something",
            origin_text=ORIGIN,
            poi_tool=FakePoiTool(),
        )
    )

    assert result.should_return_early is True
    assert result.response_payload is not None
    assert result.response_payload["pre_route_status"] == "clarification_needed"
    assert result.response_payload["pre_route_question"] == "What type of food are you looking for?"
    assert result.response_payload["pending_clarification"] == {
        "domain": "food",
        "question_asked": "What type of food are you looking for?",
        "original_query": "I want to eat something",
    }
    assert result.route_action["action_type"] == "clarify_missing_slot"


def test_brand_destination_uses_mock_parser_and_surfaces_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_parse_intent(query: str) -> IntentParseResult:
        return IntentParseResult(
            raw_query=query,
            tasks=[_destination_task("task_1", "McDonald's")],
            meta={"parser": "fake"},
            parse_status="success",
        )

    monkeypatch.setattr(pre_route_service, "parse_intent", fake_parse_intent)
    poi_tool = FakePoiTool()

    result = asyncio.run(
        run_pre_route_stage(
            query="Take me to McDonald's",
            origin_text=ORIGIN,
            poi_tool=poi_tool,
        )
    )

    assert result.should_return_early is True
    assert result.response_payload is not None
    assert result.response_payload["pre_route_status"] == "candidate_selection_needed"
    assert result.response_payload["pre_route_candidates"] is not None
    assert [candidate["name"] for candidate in result.response_payload["pre_route_candidates"]] == [
        "McDonald's Nottingham",
        "McDonald's Beeston",
    ]
    assert all(
        candidate["task_id"] == "task_1"
        for candidate in result.response_payload["pre_route_candidates"]
    )
    assert result.route_action["action_type"] == "set_destination"
    assert any(call.payload.get("query") == "McDonald's" for call in poi_tool.calls)


def test_selected_candidate_updates_destination_and_skips_blocking_filter() -> None:
    existing_tasks = [_destination_task("task_1", "McDonald's").model_dump()]
    selected_candidate = {
        "task_id": "task_1",
        "name": "McDonald's Nottingham",
        "address": "Clumber Street, Nottingham",
        "lat": 52.954,
        "lng": -1.149,
        "reason_tag": "best along route",
    }

    result = asyncio.run(
        run_pre_route_stage(
            query="Take me to McDonald's",
            origin_text=ORIGIN,
            existing_tasks=existing_tasks,
            selected_candidate=selected_candidate,
            poi_tool=FakePoiTool(),
        )
    )

    assert result.should_return_early is False
    assert result.suppress_execution is False
    assert result.route_action["action_type"] == "resolve_candidate"
    assert result.task_dicts[0]["type"] == "destination"
    assert result.task_dicts[0]["name"] == "McDonald's Nottingham, Clumber Street, Nottingham"
    assert result.task_dicts[0]["payload"] == {
        "query": "McDonald's Nottingham, Clumber Street, Nottingham",
        "label": "McDonald's Nottingham",
        "address": "Clumber Street, Nottingham",
        "lat": 52.954,
        "lng": -1.149,
        "brand": None,
    }

