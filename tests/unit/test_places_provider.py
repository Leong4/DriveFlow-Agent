from app.tools.providers.places_provider import GooglePlacesProvider


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_google_places_provider_maps_google_response(monkeypatch) -> None:
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse(
            200,
            {
                "places": [
                    {
                        "displayName": {"text": "Starbucks Beeston"},
                        "formattedAddress": "Beeston, Nottingham",
                        "location": {"latitude": 52.927, "longitude": -1.214},
                    }
                ]
            },
        )

    monkeypatch.setattr("app.tools.providers.places_provider.httpx.post", fake_post)

    provider = GooglePlacesProvider(api_key="test-key", base_url="https://places.example")
    candidates = provider.search_text("Starbucks", max_results=3)

    assert candidates == [
        {
            "name": "Starbucks Beeston",
            "address": "Beeston, Nottingham",
            "lat": 52.927,
            "lng": -1.214,
        }
    ]
    assert captured["url"] == "https://places.example/v1/places:searchText"
    assert captured["headers"]["X-Goog-Api-Key"] == "test-key"
    assert captured["json"] == {"textQuery": "Starbucks", "pageSize": 3}
    assert captured["timeout"] == 10.0


def test_google_places_provider_returns_empty_list_on_upstream_failure(monkeypatch) -> None:
    def fake_post(url, *, headers, json, timeout):
        return FakeResponse(500, {"error": "upstream failed"})

    monkeypatch.setattr("app.tools.providers.places_provider.httpx.post", fake_post)

    provider = GooglePlacesProvider(api_key="test-key", base_url="https://places.example")

    assert provider.search_text("Starbucks") == []

