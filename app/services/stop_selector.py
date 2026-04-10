"""
StopSelector — route-aware stop candidate ranking.

Ranks POI candidates by estimated detour cost and returns the best one.
Applies to all stop types: restaurants, charging stations, etc.

Heuristic (detour cost):
    detour = dist(origin → candidate) + dist(candidate → destination)
             − dist(origin → destination)

    The candidate that adds the least extra distance to the trip is preferred.

Uses the Haversine formula for all distances — deterministic, no API call required.
Falls back to candidates[0] if origin/destination coordinates are unavailable.
"""

import math
from typing import Optional


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


def select_best_stop(
    origin_coords: Optional[tuple],
    dest_coords: Optional[tuple],
    candidates: list,
) -> dict:
    """Return the candidate with minimum detour cost.

    Args:
        origin_coords: (lat, lng) of trip origin, or None.
        dest_coords:   (lat, lng) of trip destination, or None.
        candidates:    list of candidate dicts with 'lat' and 'lng' keys.

    Returns:
        The best candidate dict, or {} if the list is empty.

    Fallback: if origin or destination coords are missing, or no candidate
    has valid coordinates, returns candidates[0] without ranking.
    """
    if not candidates:
        return {}

    # Fallback: can't rank without route endpoints
    if origin_coords is None or dest_coords is None:
        return candidates[0]

    o_lat, o_lng = origin_coords
    d_lat, d_lng = dest_coords
    direct_dist = _haversine_km(o_lat, o_lng, d_lat, d_lng)

    best: Optional[dict] = None
    best_cost = float("inf")

    for c in candidates:
        c_lat = c.get("lat")
        c_lng = c.get("lng")
        if c_lat is None or c_lng is None:
            continue
        detour_cost = (
            _haversine_km(o_lat, o_lng, c_lat, c_lng)
            + _haversine_km(c_lat, c_lng, d_lat, d_lng)
            - direct_dist
        )
        if detour_cost < best_cost:
            best_cost = detour_cost
            best = c

    # Fallback if no candidate had valid coordinates
    return best if best is not None else candidates[0]


def filter_candidates_by_radius(
    candidates: list,
    origin_coords: Optional[tuple],
    dest_coords: Optional[tuple] = None,
    abs_max_km: float = 50.0,
) -> list:
    """Remove candidates that are unreasonably far from the route corridor.

    Sanity-filters the candidate list before ranking so that distant results
    (e.g. a Sheffield location in a Nottingham-only demo flow) do not pollute
    the top of the list.

    The threshold is:
    - If both origin and destination are known: min(direct_dist * 3, abs_max_km)
      (generous corridor that allows reasonable detours without leaving the region).
    - If only origin is known: abs_max_km as a hard radius cap.

    Falls back to the original list if filtering would eliminate all candidates.
    """
    if not candidates or origin_coords is None:
        return candidates

    o_lat, o_lng = origin_coords

    if dest_coords is not None:
        d_lat, d_lng = dest_coords
        direct_dist = _haversine_km(o_lat, o_lng, d_lat, d_lng)
        # At least 15 km so a very short route still has a reasonable window.
        max_km = min(max(direct_dist * 3, 15.0), abs_max_km)
    else:
        max_km = abs_max_km

    filtered = [
        c for c in candidates
        if c.get("lat") is not None
        and c.get("lng") is not None
        and _haversine_km(o_lat, o_lng, float(c["lat"]), float(c["lng"])) <= max_km
    ]
    # If the filter removes everything, fall back to the original list.
    return filtered if filtered else candidates


def rank_stops(
    origin_coords: Optional[tuple],
    dest_coords: Optional[tuple],
    candidates: list,
) -> list:
    """Return all candidates sorted by detour cost (lowest first).

    Useful for debugging. Falls back to the original order if ranking is impossible.
    """
    if not candidates or origin_coords is None or dest_coords is None:
        return candidates

    o_lat, o_lng = origin_coords
    d_lat, d_lng = dest_coords
    direct_dist = _haversine_km(o_lat, o_lng, d_lat, d_lng)

    def detour(c: dict) -> float:
        c_lat = c.get("lat")
        c_lng = c.get("lng")
        if c_lat is None or c_lng is None:
            return float("inf")
        return (
            _haversine_km(o_lat, o_lng, c_lat, c_lng)
            + _haversine_km(c_lat, c_lng, d_lat, d_lng)
            - direct_dist
        )

    return sorted(candidates, key=detour)
