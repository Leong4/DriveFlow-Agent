from app.models.task import Task
from app.services.map_data_builder import MapDataBuilder
from app.services.task_graph_builder import TaskGraphBuilder
from app.tools.schemas import ToolInput, ToolResult


class FakePoiTool:
    def __init__(self) -> None:
        self.calls: list[ToolInput] = []

    def run(self, tool_input: ToolInput) -> ToolResult:
        self.calls.append(tool_input)
        query = (
            tool_input.payload.get("query")
            or tool_input.payload.get("name")
            or ""
        ).lower()
        if "university of nottingham" in query:
            candidates = [{
                "name": "University of Nottingham",
                "address": "University Park",
                "lat": 52.938,
                "lng": -1.198,
            }]
        elif "east midlands airport" in query:
            candidates = [{
                "name": "East Midlands Airport",
                "address": "Castle Donington",
                "lat": 52.831,
                "lng": -1.328,
            }]
        elif "starbucks" in query:
            candidates = [{
                "name": "Starbucks Beeston",
                "address": "Beeston",
                "lat": 52.927,
                "lng": -1.214,
            }]
        else:
            candidates = []
        return ToolResult(
            tool_name="fake_poi",
            status="success" if candidates else "failed",
            data={"candidates": candidates},
        )


def _stop_task() -> Task:
    return Task(
        id="task_stop",
        type="stop",
        name=None,
        brand=None,
        constraints=None,
        order_hint=1,
        payload={"label": "Starbucks", "query": "Starbucks", "original_text": "Starbucks"},
    )


def _destination_task() -> Task:
    return Task(
        id="task_dest",
        type="destination",
        name="East Midlands Airport",
        brand=None,
        constraints=None,
        order_hint=2,
    )


def test_map_data_builder_geocodes_origin_destination_and_stops() -> None:
    tasks = [_stop_task(), _destination_task()]
    graph = TaskGraphBuilder().build(tasks)
    poi_tool = FakePoiTool()

    map_data = MapDataBuilder(poi_tool).build(
        origin_text="University of Nottingham",
        graph_obj=graph,
        task_dicts=[task.model_dump() for task in tasks],
    )

    assert map_data["origin"] == {
        "label": "University of Nottingham",
        "lat": 52.938,
        "lng": -1.198,
    }
    assert map_data["destination"] == {
        "label": "East Midlands Airport",
        "lat": 52.831,
        "lng": -1.328,
        "present": True,
    }
    assert map_data["stops"] == [{
        "label": "Starbucks Beeston",
        "lat": 52.927,
        "lng": -1.214,
        "type": "stop",
        "address": "Beeston",
    }]
    assert [call.task_id for call in poi_tool.calls] == [
        "demo_orig",
        "demo_dest",
        "task_stop",
    ]

