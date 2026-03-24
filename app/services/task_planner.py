from typing import Optional
from pydantic import BaseModel, Field
from app.models.graph import TaskGraph, ExecutionState


class PlannerDecisionResult(BaseModel):
    next_task_id: Optional[str] = Field(None, description="The task_id to execute next, or None if finished")
    next_task_type: Optional[str] = Field(None, description="The task_type of the next task, for readability")
    planner_decision: str = Field(..., description="Decision label: 'next_task' | 'finished'")


class TaskPlanner:
    """Determines the next task to execute based on graph topology and current state.

    Does NOT modify graph or state — read-only decision making only.
    """

    def plan(self, graph: TaskGraph, state: ExecutionState) -> PlannerDecisionResult:
        if not graph.nodes:
            raise ValueError("Cannot plan on an empty graph.")

        completed = set(state.completed_task_ids)

        # If all nodes are completed, we are finished
        all_ids = {node.task_id for node in graph.nodes}
        if all_ids == completed:
            return PlannerDecisionResult(
                next_task_id=None,
                next_task_type=None,
                planner_decision="finished",
            )

        # Determine the starting point for search
        if state.current_task_id and state.current_task_id in completed:
            # Current task is done — look at its successors first
            candidates = graph.get_next_nodes(state.current_task_id)
            for node in candidates:
                if node.task_id not in completed:
                    return self._make_next(node)

        # Fallback: start from entry_node and walk forward to find first incomplete
        current_id = graph.entry_node
        seen: set[str] = set()
        while current_id and current_id not in seen:
            seen.add(current_id)
            if current_id not in completed:
                node = graph.get_node(current_id)
                if node:
                    return self._make_next(node)
            next_nodes = graph.get_next_nodes(current_id)
            current_id = next_nodes[0].task_id if next_nodes else None

        # Should not reach here if graph and state are consistent
        raise ValueError("Planner could not determine next task — graph/state may be inconsistent.")

    @staticmethod
    def _make_next(node) -> PlannerDecisionResult:
        return PlannerDecisionResult(
            next_task_id=node.task_id,
            next_task_type=node.task_type,
            planner_decision="next_task",
        )
