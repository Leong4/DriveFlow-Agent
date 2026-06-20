from app.tools.poi_search import PoiSearchTool
from app.tools.schemas import ToolInput


class FakePlacesProvider:
    def __init__(self, candidates: list[dict]):
        self.candidates = candidates
        self.queries: list[tuple[str, int]] = []

    def search_text(self, query: str, max_results: int = 5) -> list[dict]:
        self.queries.append((query, max_results))
        return self.candidates


def test_poi_search_tool_uses_injected_provider() -> None:
    provider = FakePlacesProvider([
        {"name": "Starbucks Beeston", "address": "Beeston", "lat": 52.927, "lng": -1.214}
    ])
    tool = PoiSearchTool(provider=provider)

    result = tool.run(ToolInput(
        task_id="task_1",
        task_type="stop",
        payload={"query": "Starbucks"},
    ))

    assert result.status == "success"
    assert result.data["candidates"] == provider.candidates
    assert provider.queries == [("Starbucks", 5)]


def test_poi_search_tool_preserves_failure_contract_when_provider_has_no_results() -> None:
    provider = FakePlacesProvider([])
    tool = PoiSearchTool(provider=provider)

    result = tool.run(ToolInput(
        task_id="task_1",
        task_type="destination",
        payload={"name": "Unknown Place"},
    ))

    assert result.status == "failed"
    assert result.data == {"candidates": []}
    assert result.message == "No POI results found for query: 'Unknown Place'"


def test_poi_search_tool_still_rejects_unsupported_task_type() -> None:
    provider = FakePlacesProvider([])
    tool = PoiSearchTool(provider=provider)

    result = tool.run(ToolInput(
        task_id="task_1",
        task_type="unsupported",
        payload={"query": "Starbucks"},
    ))

    assert result.status == "failed"
    assert "Unsupported task type" in result.message
    assert provider.queries == []

