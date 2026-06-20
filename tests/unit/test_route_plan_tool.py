from app.tools.route_plan import RoutePlanTool
from app.tools.schemas import ToolInput


class FakePlacesProvider:
    def __init__(self, candidates_by_query: dict[str, list[dict]]):
        self.candidates_by_query = candidates_by_query
        self.queries: list[tuple[str, int]] = []

    def search_text(self, query: str, max_results: int = 5) -> list[dict]:
        self.queries.append((query, max_results))
        return self.candidates_by_query.get(query, [])


class FakeRoutesProvider:
    def __init__(self, result: dict | None):
        self.result = result
        self.calls: list[tuple[tuple[float, float], tuple[float, float]]] = []

    def compute_route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
    ) -> dict | None:
        self.calls.append((origin, destination))
        return self.result


def test_route_plan_tool_uses_injected_providers(monkeypatch) -> None:
    monkeypatch.setattr("app.tools.route_plan._DEFAULT_ORIGIN", "University of Nottingham")
    places_provider = FakePlacesProvider({
        "University of Nottingham": [
            {"name": "University of Nottingham", "lat": 52.938, "lng": -1.198}
        ],
        "East Midlands Airport": [
            {"name": "East Midlands Airport", "lat": 52.831, "lng": -1.328}
        ],
    })
    routes_provider = FakeRoutesProvider({
        "distance_km": 35.2,
        "eta_min": 32,
        "summary": "Route planned via the recommended path.",
    })
    tool = RoutePlanTool(
        places_provider=places_provider,
        routes_provider=routes_provider,
    )

    result = tool.run(ToolInput(
        task_id="task_dest",
        task_type="destination",
        payload={"name": "East Midlands Airport"},
    ))

    assert result.status == "success"
    assert result.data == {
        "distance_km": 35.2,
        "eta_min": 32,
        "summary": "Route planned via the recommended path.",
    }
    assert places_provider.queries == [
        ("University of Nottingham", 1),
        ("East Midlands Airport", 1),
    ]
    assert routes_provider.calls == [((52.938, -1.198), (52.831, -1.328))]


def test_route_plan_tool_returns_controlled_failure_when_destination_missing() -> None:
    tool = RoutePlanTool(
        places_provider=FakePlacesProvider({}),
        routes_provider=FakeRoutesProvider(None),
    )

    result = tool.run(ToolInput(
        task_id="task_dest",
        task_type="destination",
        payload={},
    ))

    assert result.status == "failed"
    assert result.message == "Missing 'name' in payload — cannot plan a route without a destination."


def test_route_plan_tool_returns_controlled_failure_when_geocoding_fails(monkeypatch) -> None:
    monkeypatch.setattr("app.tools.route_plan._DEFAULT_ORIGIN", "University of Nottingham")
    tool = RoutePlanTool(
        places_provider=FakePlacesProvider({"University of Nottingham": []}),
        routes_provider=FakeRoutesProvider(None),
    )

    result = tool.run(ToolInput(
        task_id="task_dest",
        task_type="destination",
        payload={"name": "East Midlands Airport"},
    ))

    assert result.status == "failed"
    assert result.message == "Failed to geocode origin: 'University of Nottingham'"


def test_route_plan_tool_returns_controlled_failure_when_route_provider_fails(monkeypatch) -> None:
    monkeypatch.setattr("app.tools.route_plan._DEFAULT_ORIGIN", "University of Nottingham")
    places_provider = FakePlacesProvider({
        "University of Nottingham": [
            {"name": "University of Nottingham", "lat": 52.938, "lng": -1.198}
        ],
        "East Midlands Airport": [
            {"name": "East Midlands Airport", "lat": 52.831, "lng": -1.328}
        ],
    })
    tool = RoutePlanTool(
        places_provider=places_provider,
        routes_provider=FakeRoutesProvider(None),
    )

    result = tool.run(ToolInput(
        task_id="task_dest",
        task_type="destination",
        payload={"name": "East Midlands Airport"},
    ))

    assert result.status == "failed"
    assert result.message == "Route computation failed for 'University of Nottingham' → 'East Midlands Airport'"

