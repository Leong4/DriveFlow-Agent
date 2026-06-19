import pytest

from app.models.task import Task
from app.services.task_graph_builder import TaskGraphBuilder, graph_to_text


def _task(task_id: str, task_type: str, order_hint: int, *, name: str | None = None) -> Task:
    return Task(
        id=task_id,
        type=task_type,
        name=name,
        brand=None,
        constraints=None,
        order_hint=order_hint,
        payload=None,
    )


def test_build_sorts_tasks_and_creates_linear_edges() -> None:
    graph = TaskGraphBuilder().build(
        [
            _task("task_3", "destination", 3, name="East Midlands Airport"),
            _task("task_1", "stop", 1, name="Starbucks"),
            _task("task_2", "stop", 2, name="Tesco"),
        ]
    )

    assert [node.task_id for node in graph.nodes] == ["task_1", "task_2", "task_3"]
    assert graph.entry_node == "task_1"
    assert [(edge.source, edge.target, edge.relation) for edge in graph.edges] == [
        ("task_1", "task_2", "next"),
        ("task_2", "task_3", "next"),
    ]


def test_build_merges_task_payload_into_node_payload() -> None:
    task = Task(
        id="task_1",
        type="stop",
        name=None,
        brand="Starbucks",
        constraints={"open_now": True},
        order_hint=1,
        payload={"query": "Starbucks near route", "brand": "Starbucks"},
    )

    graph = TaskGraphBuilder().build([task])

    assert graph.nodes[0].payload == {
        "brand": "Starbucks",
        "constraints": {"open_now": True},
        "query": "Starbucks near route",
    }


def test_graph_to_text_walks_linear_graph() -> None:
    graph = TaskGraphBuilder().build(
        [
            _task("task_1", "stop", 1, name="Starbucks"),
            _task("task_2", "destination", 2, name="East Midlands Airport"),
        ]
    )

    assert graph_to_text(graph) == "Start -> stop -> destination"


def test_build_rejects_empty_task_list() -> None:
    with pytest.raises(ValueError, match="Cannot build graph"):
        TaskGraphBuilder().build([])

