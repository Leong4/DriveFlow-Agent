from typing import List, Optional
from app.models.task import Task
from app.models.context import CarStateContext

# Mock distance estimates for well-known destinations (km)
_DISTANCE_HINTS = {
    "airport": 35,
    "机场": 35,
}
_DEFAULT_DISTANCE_KM = 15


def _estimate_distance(task: Task) -> float:
    """Return a rough mock distance estimate for a destination task."""
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
) -> List[Task]:
    """Insert a charging_station task before the destination if range is insufficient.

    Rules (very constrained):
      1. Only triggers when context.remaining_range_km is provided.
      2. Only triggers when there is at least one destination task.
      3. Only triggers when estimated distance > remaining range.
      4. Never inserts if a charging_station task already exists.
    """
    if context is None or context.remaining_range_km is None:
        return tasks

    if _has_charging_task(tasks):
        return tasks

    # Find the first destination task
    dest_task = next((t for t in tasks if t.type == "destination"), None)
    if dest_task is None:
        return tasks

    estimated_dist = _estimate_distance(dest_task)
    if context.remaining_range_km >= estimated_dist:
        return tasks

    # Build a charging task and insert it just before the destination
    charging_task = Task(
        id=f"task_auto_charge",
        type="charging_station",
        name=None,
        brand=None,
        constraints=None,
        order_hint=dest_task.order_hint,
    )

    # Shift all tasks with order_hint >= dest's by +1
    result: List[Task] = []
    inserted = False
    for t in sorted(tasks, key=lambda x: x.order_hint):
        if t.type == "destination" and not inserted:
            result.append(charging_task)
            inserted = True
            result.append(t.model_copy(update={"order_hint": t.order_hint + 1}))
        else:
            if inserted:
                result.append(t.model_copy(update={"order_hint": t.order_hint + 1}))
            else:
                result.append(t)

    return result
