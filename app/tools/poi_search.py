"""
PoiSearchTool — Google Places API (New) implementation.

Replaces the previous mock tool. Uses the Places Text Search endpoint
to find real POI candidates, then maps the response into the project's
unified ToolResult contract.

Env vars:
    GOOGLE_MAPS_API_KEY        – required
    GOOGLE_PLACES_BASE_URL     – default https://places.googleapis.com
"""

import os
import httpx
from dotenv import load_dotenv

from app.tools.base_tool import BaseTool
from app.tools.schemas import ToolInput, ToolResult

load_dotenv()

_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
_PLACES_BASE = os.getenv("GOOGLE_PLACES_BASE_URL", "https://places.googleapis.com")

# Supported task types for POI search
_SUPPORTED_TYPES = {"stop", "restaurant", "charging_station", "destination"}

# Default search text per task_type (fallback when no brand/name provided)
_DEFAULT_SEARCH_TEXT = {
    "stop": "point of interest",
    "restaurant": "restaurant",
    "charging_station": "EV charging station",
    "destination": "destination",
}


def _build_search_text(task_type: str, payload: dict) -> str:
    """Derive the search query from payload fields, falling back to defaults."""
    brand = payload.get("brand")
    name = payload.get("name")

    if task_type == "stop":
        # Prefer explicit query, then brand, then label, then default
        return (
            payload.get("query")
            or payload.get("brand")
            or payload.get("label")
            or _DEFAULT_SEARCH_TEXT["stop"]
        )

    if task_type == "restaurant":
        return brand if brand else _DEFAULT_SEARCH_TEXT["restaurant"]

    if task_type == "charging_station":
        return brand if brand else _DEFAULT_SEARCH_TEXT["charging_station"]

    if task_type == "destination":
        return name if name else _DEFAULT_SEARCH_TEXT["destination"]

    return _DEFAULT_SEARCH_TEXT.get(task_type, task_type)


def _places_text_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Call Google Places API (New) Text Search and return a list of
    candidate dicts in the project's format: {name, address, lat, lng}.

    Raises no exceptions — returns an empty list on failure.
    """
    url = f"{_PLACES_BASE}/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _API_KEY,
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


class PoiSearchTool(BaseTool):
    """POI search tool backed by Google Places API (New)."""

    @property
    def name(self) -> str:
        return "poi_search"

    def run(self, tool_input: ToolInput) -> ToolResult:
        # ── Validate task type ──
        if tool_input.task_type not in _SUPPORTED_TYPES:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                data={},
                message=f"Unsupported task type for poi_search: '{tool_input.task_type}'",
            )

        # ── Build search query ──
        search_text = _build_search_text(tool_input.task_type, tool_input.payload)

        # ── Call Google Places API ──
        candidates = _places_text_search(search_text)

        if not candidates:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                data={"candidates": []},
                message=f"No POI results found for query: '{search_text}'",
            )

        return ToolResult(
            tool_name=self.name,
            status="success",
            data={"candidates": candidates},
        )
