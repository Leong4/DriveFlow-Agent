from app.tools.providers.routes_provider import GoogleRoutesProvider


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_google_routes_provider_maps_google_response(monkeypatch) -> None:
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse(
            200,
            {
                "routes": [
                    {
                        "distanceMeters": 12345,
                        "duration": "1500s",
                        "description": "A52",
                    }
                ]
            },
        )

    monkeypatch.setattr("app.tools.providers.routes_provider.httpx.post", fake_post)

    provider = GoogleRoutesProvider(api_key="test-key", base_url="https://routes.example")
    result = provider.compute_route((52.938, -1.198), (52.831, -1.328))

    assert result == {
        "distance_km": 12.3,
        "eta_min": 25,
        "summary": "Route via A52",
    }
    assert captured["url"] == "https://routes.example/directions/v2:computeRoutes"
    assert captured["headers"]["X-Goog-Api-Key"] == "test-key"
    assert captured["json"]["origin"]["location"]["latLng"] == {
        "latitude": 52.938,
        "longitude": -1.198,
    }
    assert captured["json"]["destination"]["location"]["latLng"] == {
        "latitude": 52.831,
        "longitude": -1.328,
    }
    assert captured["timeout"] == 10.0


def test_google_routes_provider_returns_none_on_upstream_failure(monkeypatch) -> None:
    def fake_post(url, *, headers, json, timeout):
        return FakeResponse(500, {"error": "upstream failed"})

    monkeypatch.setattr("app.tools.providers.routes_provider.httpx.post", fake_post)

    provider = GoogleRoutesProvider(api_key="test-key", base_url="https://routes.example")

    assert provider.compute_route((52.938, -1.198), (52.831, -1.328)) is None

