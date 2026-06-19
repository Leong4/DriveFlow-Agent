from app.models.task import Task
from app.services.itinerary_editor import apply_edit, insert_before, remove, replace


def _stop(task_id: str, label: str, order_hint: int) -> Task:
    return Task(
        id=task_id,
        type="stop",
        name=None,
        brand=None,
        constraints=None,
        order_hint=order_hint,
        payload={"label": label, "query": label, "original_text": label},
    )


def _destination(task_id: str, name: str, order_hint: int) -> Task:
    return Task(
        id=task_id,
        type="destination",
        name=name,
        brand=None,
        constraints=None,
        order_hint=order_hint,
    )


def _labels(tasks: list[Task]) -> list[str]:
    labels = []
    for task in tasks:
        labels.append(task.name or (task.payload or {}).get("label"))
    return labels


def test_insert_before_destination_preserves_destination_and_reorders() -> None:
    tasks = [
        _stop("task_1", "Starbucks", 1),
        _destination("task_2", "East Midlands Airport", 2),
    ]

    updated = insert_before(tasks, "the airport", "Boots")

    assert _labels(updated) == ["Starbucks", "Boots", "East Midlands Airport"]
    assert [task.order_hint for task in updated] == [1, 2, 3]
    assert updated[-1].type == "destination"


def test_replace_first_matching_stop_keeps_final_destination() -> None:
    tasks = [
        _stop("task_1", "McDonald's", 1),
        _destination("task_2", "Nottingham Castle", 2),
    ]

    updated = replace(tasks, "McDonald's", "Starbucks")

    assert _labels(updated) == ["Starbucks", "Nottingham Castle"]
    assert [task.order_hint for task in updated] == [1, 2]
    assert updated[-1].type == "destination"


def test_remove_stop_keeps_remaining_tasks_ordered() -> None:
    tasks = [
        _stop("task_1", "Tesco", 1),
        _stop("task_2", "Starbucks", 2),
        _destination("task_3", "East Midlands Airport", 3),
    ]

    updated = remove(tasks, "Tesco")

    assert _labels(updated) == ["Starbucks", "East Midlands Airport"]
    assert [task.order_hint for task in updated] == [1, 2]


def test_apply_edit_unknown_query_returns_original_tasks() -> None:
    tasks = [
        _stop("task_1", "Tesco", 1),
        _destination("task_2", "East Midlands Airport", 2),
    ]

    updated, message = apply_edit(tasks, "Make this route nicer")

    assert updated == tasks
    assert message == "Edit not recognized — no changes applied."

