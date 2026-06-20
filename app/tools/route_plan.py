"""
RoutePlanTool — Google Routes API implementation.

Replaces the previous mock tool. Uses the Routes API computeRoutes endpoint
to plan a real route, then maps the response into the project's unified
ToolResult contract.

Two-step approach:
    1. Resolve origin / destination text → lat/lng via Places Text Search.
    2. Call Routes API computeRoutes with waypoints.

Env vars:
    GOOGLE_MAPS_API_KEY        – required
    GOOGLE_PLACES_BASE_URL     – default https://places.googleapis.com
    GOOGLE_ROUTES_BASE_URL     – default https://routes.googleapis.com
    GOOGLE_ROUTE_ORIGIN_TEXT   – default "University of Nottingham"
"""

import os
from typing import Optional

from dotenv import load_dotenv

from app.tools.base_tool import BaseTool
from app.tools.providers import (
    GooglePlacesProvider,
    GoogleRoutesProvider,
    PlacesProvider,
    RoutesProvider,
)
from app.tools.schemas import ToolInput, ToolResult

load_dotenv()

_DEFAULT_ORIGIN = os.getenv("GOOGLE_ROUTE_ORIGIN_TEXT", "University of Nottingham")


# ── Helper: geocode text → (lat, lng) via Places Text Search ──

def _geocode_text(text: str, places_provider: PlacesProvider) -> Optional[tuple[float, float]]:
    """Resolve a place name to (lat, lng) using Places Text Search.

    Returns None on failure so the caller can emit a controlled ToolResult.
    """
    candidates = places_provider.search_text(text, max_results=1)
    if not candidates:
        return None
    candidate = candidates[0]
    lat = candidate.get("lat")
    lng = candidate.get("lng")
    if lat is None or lng is None:
        return None
    return (lat, lng)


class RoutePlanTool(BaseTool):
    """Route planning tool backed by Google Routes API."""

    def __init__(
        self,
        *,
        places_provider: Optional[PlacesProvider] = None,
        routes_provider: Optional[RoutesProvider] = None,
    ):
        self.places_provider = places_provider or GooglePlacesProvider()
        self.routes_provider = routes_provider or GoogleRoutesProvider()

    @property
    def name(self) -> str:
        return "route_plan"

    def run(self, tool_input: ToolInput) -> ToolResult:
        destination_text = tool_input.payload.get("name")

        if not destination_text:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                data={},
                message="Missing 'name' in payload — cannot plan a route without a destination.",
            )

        # ── Step 1: Geocode origin & destination ──
        origin_text = _DEFAULT_ORIGIN
        origin_coords = _geocode_text(origin_text, self.places_provider)
        if origin_coords is None:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                data={},
                message=f"Failed to geocode origin: '{origin_text}'",
            )

        dest_coords = _geocode_text(destination_text, self.places_provider)
        if dest_coords is None:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                data={},
                message=f"Failed to geocode destination: '{destination_text}'",
            )

        # ── Step 2: Compute route ──
        result = self.routes_provider.compute_route(origin_coords, dest_coords)
        if result is None:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                data={},
                message=f"Route computation failed for '{origin_text}' → '{destination_text}'",
            )

        return ToolResult(
            tool_name=self.name,
            status="success",
            data=result,
        )
