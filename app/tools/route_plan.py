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

import httpx
from dotenv import load_dotenv

from app.tools.base_tool import BaseTool
from app.tools.schemas import ToolInput, ToolResult

load_dotenv()

_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
_PLACES_BASE = os.getenv("GOOGLE_PLACES_BASE_URL", "https://places.googleapis.com")
_ROUTES_BASE = os.getenv("GOOGLE_ROUTES_BASE_URL", "https://routes.googleapis.com")
_DEFAULT_ORIGIN = os.getenv("GOOGLE_ROUTE_ORIGIN_TEXT", "University of Nottingham")


# ── Helper: geocode text → (lat, lng) via Places Text Search ──

def _geocode_text(text: str) -> Optional[tuple[float, float]]:
    """Resolve a place name to (lat, lng) using Places Text Search.

    Returns None on failure so the caller can emit a controlled ToolResult.
    """
    url = f"{_PLACES_BASE}/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _API_KEY,
        "X-Goog-FieldMask": "places.location",
    }
    body = {"textQuery": text, "pageSize": 1}

    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=10.0)
        if resp.status_code != 200:
            return None
        places = resp.json().get("places", [])
        if not places:
            return None
        loc = places[0].get("location", {})
        lat = loc.get("latitude")
        lng = loc.get("longitude")
        if lat is None or lng is None:
            return None
        return (lat, lng)
    except Exception:
        return None


# ── Helper: call Routes API computeRoutes ──

def _compute_route(
    origin: tuple[float, float],
    destination: tuple[float, float],
) -> Optional[dict]:
    """Call Google Routes API and return {distance_km, eta_min, summary}.

    Returns None on failure.
    """
    url = f"{_ROUTES_BASE}/directions/v2:computeRoutes"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _API_KEY,
        "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.description",
    }
    body = {
        "origin": {
            "location": {
                "latLng": {"latitude": origin[0], "longitude": origin[1]},
            },
        },
        "destination": {
            "location": {
                "latLng": {"latitude": destination[0], "longitude": destination[1]},
            },
        },
        "travelMode": "DRIVE",
    }

    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=10.0)
        if resp.status_code != 200:
            return None
        routes = resp.json().get("routes", [])
        if not routes:
            return None
    except Exception:
        return None

    route = routes[0]

    # Distance
    distance_m = route.get("distanceMeters", 0)
    distance_km = round(distance_m / 1000, 1)

    # Duration — returned as e.g. "1234s"
    duration_str = route.get("duration", "0s")
    try:
        duration_sec = int(duration_str.rstrip("s"))
    except (ValueError, AttributeError):
        duration_sec = 0
    eta_min = round(duration_sec / 60)

    # Description
    description = route.get("description", "")
    summary = f"Route via {description}" if description else "Route planned via the recommended path."

    return {
        "distance_km": distance_km,
        "eta_min": eta_min,
        "summary": summary,
    }


class RoutePlanTool(BaseTool):
    """Route planning tool backed by Google Routes API."""

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
        origin_coords = _geocode_text(origin_text)
        if origin_coords is None:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                data={},
                message=f"Failed to geocode origin: '{origin_text}'",
            )

        dest_coords = _geocode_text(destination_text)
        if dest_coords is None:
            return ToolResult(
                tool_name=self.name,
                status="failed",
                data={},
                message=f"Failed to geocode destination: '{destination_text}'",
            )

        # ── Step 2: Compute route ──
        result = _compute_route(origin_coords, dest_coords)
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
