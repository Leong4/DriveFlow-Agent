from typing import List
from app.models.task import Task
from app.models.graph import TaskNode, TaskEdge, TaskGraph


class TaskGraphBuilder:
    """Converts a flat list of Tasks into a linear TaskGraph (A → B → C)."""

    def build(self, tasks: List[Task]) -> TaskGraph:
        if not tasks:
            raise ValueError("Cannot build graph from an empty task list.")

        # Sort by order_hint to determine linear execution order
        sorted_tasks = sorted(tasks, key=lambda t: t.order_hint)

        # Map each Task to a TaskNode
        nodes = [self._task_to_node(task) for task in sorted_tasks]

        # Create sequential edges between adjacent nodes
        edges = [
            TaskEdge(source=nodes[i].task_id, target=nodes[i + 1].task_id, relation="next")
            for i in range(len(nodes) - 1)
        ]

        return TaskGraph(
            nodes=nodes,
            edges=edges,
            entry_node=nodes[0].task_id,
        )

    @staticmethod
    def _task_to_node(task: Task) -> TaskNode:
        payload = {}
        if task.name:
            payload["name"] = task.name
        if task.brand:
            payload["brand"] = task.brand
        if task.constraints:
            payload["constraints"] = task.constraints
        return TaskNode(
            task_id=task.id,
            task_type=task.type,
            payload=payload,
        )


def graph_to_text(graph: TaskGraph) -> str:
    """Return a simple text representation of the linear graph for debugging."""
    if not graph.nodes:
        return "(empty graph)"

    # Walk the graph linearly from entry_node, with cycle protection
    visited = []
    seen_ids: set[str] = set()
    current_id = graph.entry_node
    while current_id and current_id not in seen_ids:
        node = graph.get_node(current_id)
        if node is None:
            break
        seen_ids.add(current_id)
        visited.append(node.task_type)
        next_nodes = graph.get_next_nodes(current_id)
        current_id = next_nodes[0].task_id if next_nodes else None

    return "Start -> " + " -> ".join(visited)
