"""Routes provider boundary for route computation."""

import os
from typing import Optional, Protocol

import httpx
from dotenv import load_dotenv

load_dotenv()


class RoutesProvider(Protocol):
    """Synchronous route-computation provider used by RoutePlanTool."""

    def compute_route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
    ) -> Optional[dict]:
        """Return {distance_km, eta_min, summary}, or None on failure."""
        ...


class GoogleRoutesProvider:
    """Google Routes API computeRoutes provider."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("GOOGLE_MAPS_API_KEY", "")
        self.base_url = base_url or os.getenv("GOOGLE_ROUTES_BASE_URL", "https://routes.googleapis.com")

    def compute_route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
    ) -> Optional[dict]:
        """Call Google Routes API and return a normalized route summary.

        Raises no exceptions: failures return None to preserve RoutePlanTool's
        existing controlled-failure behavior.
        """
        url = f"{self.base_url}/directions/v2:computeRoutes"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
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
        distance_m = route.get("distanceMeters", 0)
        distance_km = round(distance_m / 1000, 1)

        duration_str = route.get("duration", "0s")
        try:
            duration_sec = int(duration_str.rstrip("s"))
        except (ValueError, AttributeError):
            duration_sec = 0
        eta_min = round(duration_sec / 60)

        description = route.get("description", "")
        summary = f"Route via {description}" if description else "Route planned via the recommended path."

        return {
            "distance_km": distance_km,
            "eta_min": eta_min,
            "summary": summary,
        }

