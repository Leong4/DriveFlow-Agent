from app.models.context import CarStateContext
from app.models.task import Task
from app.services.charging_augmenter import ChargingAugmenter
from app.tools.schemas import ToolInput, ToolResult


class FakePoiTool:
    def __init__(self) -> None:
        self.calls: list[ToolInput] = []

    def run(self, tool_input: ToolInput) -> ToolResult:
        self.calls.append(tool_input)
        name = (tool_input.payload.get("name") or "").lower()
        if "university of nottingham" in name:
            candidates = [{"name": "Origin", "lat": 52.938, "lng": -1.198}]
        elif "east midlands airport" in name:
            candidates = [{"name": "Airport", "lat": 52.831, "lng": -1.328}]
        else:
            candidates = []
        return ToolResult(
            tool_name="fake_poi",
            status="success" if candidates else "failed",
            data={"candidates": candidates},
        )


def _destination_task() -> dict:
    return Task(
        id="task_dest",
        type="destination",
        name="East Midlands Airport",
        brand=None,
        constraints=None,
        order_hint=1,
    ).model_dump()


def test_augment_inserts_charging_task_when_range_is_low() -> None:
    poi_tool = FakePoiTool()
    context = CarStateContext(battery_level=10, remaining_range_km=1)

    result = ChargingAugmenter(poi_tool).augment(
        [_destination_task()],
        context,
        "University of Nottingham",
    )

    assert [task["type"] for task in result] == ["charging_station", "destination"]
    assert result[0]["id"] == "task_auto_charge"
    assert [call.task_id for call in poi_tool.calls] == ["chg_orig", "chg_dest"]


def test_augment_returns_tasks_unchanged_without_car_context() -> None:
    task_dicts = [_destination_task()]
    poi_tool = FakePoiTool()

    result = ChargingAugmenter(poi_tool).augment(
        task_dicts,
        None,
        "University of Nottingham",
    )

    assert result == task_dicts
    assert poi_tool.calls == []

