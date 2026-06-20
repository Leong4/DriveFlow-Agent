"""Places provider boundary for POI text search.

This module keeps the current synchronous behavior while separating Google
Places HTTP details from PoiSearchTool's task-to-tool contract.
"""

import os
from typing import Protocol

import httpx
from dotenv import load_dotenv

load_dotenv()


class PlacesProvider(Protocol):
    """Synchronous text-search provider used by PoiSearchTool."""

    def search_text(self, query: str, max_results: int = 5) -> list[dict]:
        """Return candidates in {name, address, lat, lng} format."""
        ...


class GooglePlacesProvider:
    """Google Places API (New) Text Search provider."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("GOOGLE_MAPS_API_KEY", "")
        self.base_url = base_url or os.getenv("GOOGLE_PLACES_BASE_URL", "https://places.googleapis.com")

    def search_text(self, query: str, max_results: int = 5) -> list[dict]:
        """Call Google Places Text Search and return normalized candidates.

        Raises no exceptions: failures are represented as an empty candidate list
        to preserve the existing PoiSearchTool behavior.
        """
        url = f"{self.base_url}/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
        }
        body = {
            "textQuery": query,
            "pageSize": max_results,
        }

        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=10.0)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception:
            return []

        candidates = []
        for place in data.get("places", []):
            location = place.get("location", {})
            candidates.append({
                "name": place.get("displayName", {}).get("text", "Unknown"),
                "address": place.get("formattedAddress", ""),
                "lat": location.get("latitude"),
                "lng": location.get("longitude"),
            })
        return candidates

