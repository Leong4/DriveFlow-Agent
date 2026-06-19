"""Map-data projection for the demo frontend."""

from typing import Any, Dict, List

from app.models.graph import TaskGraph
from app.services.pre_route_service import empty_map_data
from app.services.stop_selector import select_best_stop
from app.tools.schemas import ToolInput


class MapDataBuilder:
    """Build frontend map_data from a graph and optimized task list."""

    def __init__(self, poi_tool: Any):
        self.poi_tool = poi_tool

    def build(
        self,
        *,
        origin_text: str,
        graph_obj: TaskGraph,
        task_dicts: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        map_data = empty_map_data(origin_text)
        self._geocode_origin(map_data, origin_text)
        self._geocode_destination(map_data, graph_obj)
        origin_coords, dest_coords = self._route_endpoint_coords(map_data)
        self._geocode_stops(map_data, task_dicts, origin_coords, dest_coords)
        return map_data

    def _geocode_origin(self, map_data: Dict[str, Any], origin_text: str) -> None:
        result = self.poi_tool.run(ToolInput(
            task_id="demo_orig",
            task_type="destination",
            payload={"name": origin_text},
        ))
        if result.data.get("candidates"):
            candidate = result.data["candidates"][0]
            map_data["origin"].update({
                "lat": candidate["lat"],
                "lng": candidate["lng"],
            })

    def _geocode_destination(self, map_data: Dict[str, Any], graph_obj: TaskGraph) -> None:
        for node in graph_obj.nodes:
            if node.task_type != "destination":
                continue

            dest_name = node.payload.get("destination", node.payload.get("name", "Destination"))
            map_data["destination"]["label"] = dest_name
            map_data["destination"]["present"] = True
            result = self.poi_tool.run(ToolInput(
                task_id="demo_dest",
                task_type="destination",
                payload={"name": dest_name},
            ))
            if result.data.get("candidates"):
                candidate = result.data["candidates"][0]
                map_data["destination"].update({
                    "lat": candidate["lat"],
                    "lng": candidate["lng"],
                })
            break

    def _route_endpoint_coords(self, map_data: Dict[str, Any]) -> tuple[Any, Any]:
        origin_coords = None
        dest_coords = None
        if map_data["origin"]["lat"] is not None:
            origin_coords = (map_data["origin"]["lat"], map_data["origin"]["lng"])
        if map_data["destination"]["lat"] is not None:
            dest_coords = (map_data["destination"]["lat"], map_data["destination"]["lng"])
        return origin_coords, dest_coords

    def _geocode_stops(
        self,
        map_data: Dict[str, Any],
        task_dicts: List[Dict[str, Any]],
        origin_coords: Any,
        dest_coords: Any,
    ) -> None:
        stop_types = {"stop", "restaurant", "charging_station"}
        for task_dict in task_dicts:
            task_type = task_dict.get("type", "")
            if task_type not in stop_types:
                continue

            payload = task_dict.get("payload") or {}
            search_query = (
                payload.get("query")
                or payload.get("brand")
                or payload.get("label")
                or task_dict.get("brand")
                or task_dict.get("name")
                or task_type
            )
            result = self.poi_tool.run(ToolInput(
                task_id=task_dict.get("id", "demo_stop"),
                task_type=task_type,
                payload={"query": search_query, "brand": task_dict.get("brand"), "name": task_dict.get("name")},
            ))
            if result.status == "success" and result.data.get("candidates"):
                candidate = select_best_stop(origin_coords, dest_coords, result.data["candidates"])
                map_data["stops"].append({
                    "label": candidate.get("name", search_query),
                    "lat": candidate.get("lat"),
                    "lng": candidate.get("lng"),
                    "type": task_type,
                    "address": candidate.get("address", ""),
                })

