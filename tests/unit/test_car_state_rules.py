from app.models.context import CarStateContext
from app.models.task import Task
from app.services.car_state_rules import maybe_insert_charging_task


def _stop(order_hint: int = 1) -> Task:
    return Task(
        id=f"task_stop_{order_hint}",
        type="stop",
        name=None,
        brand=None,
        constraints=None,
        order_hint=order_hint,
        payload={"label": "Starbucks", "query": "Starbucks"},
    )


def _destination(name: str = "East Midlands Airport", order_hint: int = 2) -> Task:
    return Task(
        id="task_dest",
        type="destination",
        name=name,
        brand=None,
        constraints=None,
        order_hint=order_hint,
    )


def _charging_task(order_hint: int = 1) -> Task:
    return Task(
        id="task_existing_charge",
        type="charging_station",
        name=None,
        brand=None,
        constraints=None,
        order_hint=order_hint,
    )


def test_low_range_inserts_charging_task_before_route() -> None:
    tasks = [_stop(1), _destination(order_hint=2)]
    context = CarStateContext(battery_level=10, remaining_range_km=20)

    updated = maybe_insert_charging_task(tasks, context)

    assert [task.type for task in updated] == ["charging_station", "stop", "destination"]
    assert updated[0].id == "task_auto_charge"
    assert [task.order_hint for task in updated] == [1, 2, 3]


def test_sufficient_range_keeps_tasks_unchanged() -> None:
    tasks = [_stop(1), _destination(order_hint=2)]
    context = CarStateContext(battery_level=80, remaining_range_km=100)

    updated = maybe_insert_charging_task(tasks, context)

    assert updated == tasks


def test_existing_charging_task_prevents_duplicate_insertion() -> None:
    tasks = [_charging_task(1), _destination(order_hint=2)]
    context = CarStateContext(battery_level=10, remaining_range_km=1)

    updated = maybe_insert_charging_task(tasks, context)

    assert updated == tasks


def test_no_destination_skips_range_check() -> None:
    tasks = [_stop(1)]
    context = CarStateContext(battery_level=10, remaining_range_km=1)

    updated = maybe_insert_charging_task(tasks, context)

    assert updated == tasks

