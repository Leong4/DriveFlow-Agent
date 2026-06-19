"""Charging augmentation for the demo route pipeline."""

from typing import Any, Dict, List, Optional

from app.models.context import CarStateContext
from app.models.task import Task
from app.services.car_state_rules import maybe_insert_charging_task
from app.tools.schemas import ToolInput


class ChargingAugmenter:
    """Insert a charging task when car range is insufficient for the route."""

    def __init__(self, poi_tool: Any):
        self.poi_tool = poi_tool

    def augment(
        self,
        task_dicts: List[Dict[str, Any]],
        context: Optional[CarStateContext],
        origin_text: str,
    ) -> List[Dict[str, Any]]:
        if context is None:
            return task_dicts

        task_objs = [Task(**t) for t in task_dicts]
        origin_coords = self._geocode_first(origin_text, task_id="chg_orig")
        dest_coords = None
        for task_dict in task_dicts:
            if task_dict.get("type") == "destination" and task_dict.get("name"):
                dest_coords = self._geocode_first(task_dict["name"], task_id="chg_dest")
                break

        augmented = maybe_insert_charging_task(
            task_objs,
            context,
            origin_coords=origin_coords,
            dest_coords=dest_coords,
        )
        return [task.model_dump() for task in augmented]

    def _geocode_first(self, name: str, *, task_id: str) -> Optional[tuple[float, float]]:
        result = self.poi_tool.run(ToolInput(
            task_id=task_id,
            task_type="destination",
            payload={"name": name},
        ))
        if not result.data.get("candidates"):
            return None

        candidate = result.data["candidates"][0]
        lat = candidate.get("lat")
        lng = candidate.get("lng")
        if lat is None or lng is None:
            return None
        return (lat, lng)

