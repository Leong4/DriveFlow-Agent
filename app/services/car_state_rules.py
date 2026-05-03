import math
from typing import List, Optional, Tuple
from app.models.task import Task
from app.models.context import CarStateContext

# Mock distance estimates for well-known destinations (km)
_DISTANCE_HINTS = {
    "airport": 35,
    "机场": 35,
}
_DEFAULT_DISTANCE_KM = 15

# Multiplier applied to haversine (straight-line) distance to approximate road distance.
# UK road routes are typically 20–30% longer than great-circle; 1.25 gives a
# conservative buffer that favours inserting a charging stop over missing one.
_ROAD_FACTOR = 1.25


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


def _estimate_distance(task: Task) -> float:
    """Return a rough mock distance estimate for a destination task (fallback only)."""
    name = (task.name or "").lower()
    for keyword, dist in _DISTANCE_HINTS.items():
        if keyword in name:
            return dist
    return _DEFAULT_DISTANCE_KM


def _has_charging_task(tasks: List[Task]) -> bool:
    return any(t.type == "charging_station" for t in tasks)


def maybe_insert_charging_task(
    tasks: List[Task],
    context: Optional[CarStateContext] = None,
    *,
    origin_coords: Optional[Tuple[float, float]] = None,
    dest_coords: Optional[Tuple[float, float]] = None,
) -> List[Task]:
    """Insert a charging_station task at the front of the task list if range is insufficient.

    Rules:
      1. Only triggers when context.remaining_range_km is provided.
      2. Only triggers when there is at least one destination task.
      3. Estimates trip distance:
           - If origin_coords and dest_coords are provided: haversine * 1.25 (road factor)
           - Otherwise: keyword-based mock fallback (_estimate_distance)
         Plus a per-stop buffer applied in both cases:
           - 1 intermediate stop  → +5 km
           - 2+ intermediate stops → +10 km
      4. Only triggers when estimated trip distance > remaining range.
      5. Never inserts if a charging_station task already exists.
      6. Inserts charging_station before the first non-charging task and
         recomputes order_hint for all tasks.
    """
    if context is None or context.remaining_range_km is None:
        return tasks

    if _has_charging_task(tasks):
        return tasks

    # Require a destination to trigger range check
    dest_task = next((t for t in tasks if t.type == "destination"), None)
    if dest_task is None:
        return tasks

    # Count intermediate stops (excludes destination and any future charging tasks)
    num_intermediate = sum(
        1 for t in tasks if t.type not in ("destination", "charging_station")
    )

    # Estimated trip distance: haversine * road factor when coordinates are available;
    # keyword-based mock estimate otherwise.
    if origin_coords is not None and dest_coords is not None:
        estimated_dist = _haversine_km(*origin_coords, *dest_coords) * _ROAD_FACTOR
    else:
        estimated_dist = _estimate_distance(dest_task)

    if num_intermediate == 1:
        estimated_dist += 5
    elif num_intermediate >= 2:
        estimated_dist += 10

    if context.remaining_range_km >= estimated_dist:
        return tasks

    # Sort existing tasks by order_hint
    sorted_tasks = sorted(tasks, key=lambda x: x.order_hint)
    first_hint = sorted_tasks[0].order_hint if sorted_tasks else 1

    # Insert charging_station at position 0; shift all other tasks by +1
    charging_task = Task(
        id="task_auto_charge",
        type="charging_station",
        name=None,
        brand=None,
        constraints=None,
        order_hint=first_hint,
    )
    result: List[Task] = [charging_task]
    for t in sorted_tasks:
        result.append(t.model_copy(update={"order_hint": t.order_hint + 1}))

    return result
