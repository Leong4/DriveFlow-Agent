"""
RouteOptimizer — small-scale multi-stop reordering for demo-safe route improvement.

Reorders ordinary stops (type='stop' or legacy 'restaurant') to minimize total
Haversine trip distance:

    origin → stop1 → stop2 → ... → stopN → destination

Design constraints:
    - charging_station tasks are ANCHORED before all movable stops (original relative order kept).
    - destination tasks are FIXED at the end (original relative order kept).
    - stop / restaurant tasks are reordered to minimize total route cost.

Optimization strategy:
    - For N ≤ 6 movable stops: brute-force enumeration of all N! permutations.
    - For N > 6 movable stops: nearest-neighbor greedy (explicit, documented fallback).
    - Falls back to the original task order (with recomputed order_hints) if:
        · fewer than 2 movable stops (nothing to reorder)
        · geocoding fails for origin, destination, or any movable stop
        · no destination task present

Geocoding: Google Places Text Search (same endpoint as route_plan.py).
Env var: GOOGLE_MAPS_API_KEY
"""

import itertools
import math
import os
from typing import List, Optional, Tuple

import httpx
from dotenv import load_dotenv

from app.models.task import Task

load_dotenv()

_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
_PLACES_BASE = os.getenv("GOOGLE_PLACES_BASE_URL", "https://places.googleapis.com")

# Brute-force permutation cap — above this, nearest-neighbor greedy is used
_BRUTE_FORCE_LIMIT = 6

# Task type classification
_MOVABLE_TYPES = {"stop", "restaurant"}
_ANCHOR_TYPES = {"charging_station"}    # fixed, placed before movable stops
_TAIL_TYPES = {"destination"}           # fixed, placed after movable stops


# ── Geo helpers ────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return great-circle distance in km between two lat/lng points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _geocode(text: str) -> Optional[Tuple[float, float]]:
    """Resolve a place name to (lat, lng) via Places Text Search.

    Returns None on failure so callers can fall back safely.
    """
    if not text or not _API_KEY:
        return None
    url = f"{_PLACES_BASE}/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _API_KEY,
        "X-Goog-FieldMask": "places.location",
    }
    try:
        resp = httpx.post(
            url, headers=headers, json={"textQuery": text, "pageSize": 1}, timeout=10.0
        )
        if resp.status_code != 200:
            return None
        places = resp.json().get("places", [])
        if not places:
            return None
        loc = places[0].get("location", {})
        lat, lng = loc.get("latitude"), loc.get("longitude")
        if lat is None or lng is None:
            return None
        return (float(lat), float(lng))
    except Exception:
        return None


# ── Task label extraction ──────────────────────────────────────────────────

def _search_text(task: Task) -> str:
    """Extract the best available search string from a task for geocoding."""
    if task.payload:
        return (
            task.payload.get("query")
            or task.payload.get("brand")
            or task.payload.get("label")
            or ""
        )
    return task.name or task.brand or ""


def _dest_text(task: Task) -> str:
    """Extract the destination name for geocoding."""
    return task.name or (task.payload or {}).get("name", "")


# ── Trip cost ──────────────────────────────────────────────────────────────

def _trip_cost(
    origin: Tuple[float, float],
    stop_coords: List[Tuple[float, float]],
    destination: Tuple[float, float],
) -> float:
    """Total Haversine distance along the route: origin → stops → destination."""
    waypoints = [origin] + stop_coords + [destination]
    return sum(
        _haversine_km(waypoints[i][0], waypoints[i][1],
                      waypoints[i + 1][0], waypoints[i + 1][1])
        for i in range(len(waypoints) - 1)
    )


# ── Ordering strategies ────────────────────────────────────────────────────

def _best_order(
    movable_tasks: List[Task],
    movable_coords: List[Tuple[float, float]],
    origin: Tuple[float, float],
    destination: Tuple[float, float],
) -> List[Task]:
    """Return the movable task list in the order that minimizes total trip cost.

    Strategy:
        N ≤ _BRUTE_FORCE_LIMIT → brute-force over all N! permutations.
        N > _BRUTE_FORCE_LIMIT → nearest-neighbor greedy (documented fallback).
    """
    n = len(movable_tasks)
    if n <= 1:
        return movable_tasks

    paired = list(zip(movable_tasks, movable_coords))

    if n <= _BRUTE_FORCE_LIMIT:
        # Brute-force: evaluate all permutations, pick minimum-cost ordering
        best_perm: Optional[tuple] = None
        best_cost = float("inf")
        for perm in itertools.permutations(paired):
            coords_seq = [c for _, c in perm]
            cost = _trip_cost(origin, coords_seq, destination)
            if cost < best_cost:
                best_cost = cost
                best_perm = perm
        return [t for t, _ in best_perm]
    else:
        # Nearest-neighbor greedy: at each step go to the closest remaining stop
        # This is a deterministic O(n²) fallback for larger stop counts.
        remaining = list(paired)
        result: List[Task] = []
        current = origin
        while remaining:
            nearest_i = min(
                range(len(remaining)),
                key=lambda i: _haversine_km(
                    current[0], current[1],
                    remaining[i][1][0], remaining[i][1][1],
                ),
            )
            task, coord = remaining.pop(nearest_i)
            result.append(task)
            current = coord
        return result


# ── Order-hint recomputation ───────────────────────────────────────────────

def _recompute_hints(tasks: List[Task]) -> List[Task]:
    """Return a new list with order_hint reassigned sequentially from 1."""
    return [t.model_copy(update={"order_hint": i + 1}) for i, t in enumerate(tasks)]


# ── Public API ─────────────────────────────────────────────────────────────

def optimize_stop_order(tasks: List[Task], origin_text: str) -> List[Task]:
    """Reorder ordinary stops to minimize total Haversine trip distance.

    Args:
        tasks:       flat task list (any mix of stop/restaurant/charging_station/destination)
        origin_text: human-readable origin name for geocoding (e.g. "University of Nottingham")

    Returns:
        Task list with optimized stop order and recomputed order_hints.
        Falls back to original order (recomputed hints) on any geocoding failure.

    Partition logic:
        anchor_tasks  (charging_station) → placed first, original relative order
        movable_tasks (stop, restaurant) → reordered to minimize cost
        tail_tasks    (destination)      → placed last, original relative order
    """
    sorted_tasks = sorted(tasks, key=lambda t: t.order_hint)

    anchor_tasks = [t for t in sorted_tasks if t.type in _ANCHOR_TYPES]
    movable_tasks = [t for t in sorted_tasks if t.type in _MOVABLE_TYPES]
    tail_tasks = [t for t in sorted_tasks if t.type in _TAIL_TYPES]

    # Nothing to reorder if fewer than 2 movable stops
    if len(movable_tasks) < 2:
        return _recompute_hints(anchor_tasks + movable_tasks + tail_tasks)

    # No destination → cannot anchor the end of the route cost; fall back
    if not tail_tasks:
        return _recompute_hints(sorted_tasks)

    # Geocode origin
    origin_coords = _geocode(origin_text)
    if origin_coords is None:
        return _recompute_hints(sorted_tasks)

    # Geocode destination (first destination task)
    dest_label = _dest_text(tail_tasks[0])
    if not dest_label:
        return _recompute_hints(sorted_tasks)
    dest_coords = _geocode(dest_label)
    if dest_coords is None:
        return _recompute_hints(sorted_tasks)

    # Geocode each movable stop
    stop_coords: List[Optional[Tuple[float, float]]] = [
        _geocode(_search_text(t)) if _search_text(t) else None
        for t in movable_tasks
    ]

    # Fall back if any stop could not be geocoded
    if any(c is None for c in stop_coords):
        return _recompute_hints(sorted_tasks)

    # Find the minimum-cost ordering of movable stops
    optimized_movable = _best_order(
        movable_tasks, stop_coords, origin_coords, dest_coords  # type: ignore[arg-type]
    )

    # Reassemble: anchors → optimized stops → destination
    final = anchor_tasks + optimized_movable + tail_tasks
    return _recompute_hints(final)
