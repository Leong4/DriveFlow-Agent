from app.models.graph import TaskNode
from app.tools.base_tool import BaseTool
from app.tools.poi_search import PoiSearchTool
from app.tools.route_plan import RoutePlanTool
from app.services.exceptions import UnsupportedToolRouteError


class ToolRouter:
    """Routes a TaskNode to the appropriate tool instance based on task_type.

    Does NOT execute the tool — that is the Executor's responsibility.
    """

    def __init__(self):
        self._poi_search = PoiSearchTool()
        self._route_plan = RoutePlanTool()

        self._route_map: dict[str, BaseTool] = {
            "stop": self._poi_search,
            "restaurant": self._poi_search,       # legacy alias
            "charging_station": self._poi_search,
            "destination": self._route_plan,
        }

    def route(self, task_node: TaskNode) -> BaseTool:
        """Return the tool instance responsible for handling the given task_node."""
        tool = self._route_map.get(task_node.task_type)
        if tool is None:
            raise UnsupportedToolRouteError(task_node.task_type)
        return tool
