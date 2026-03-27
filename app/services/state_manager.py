from app.models.graph import ExecutionState, TaskGraph


class StateManager:
    """Manages ExecutionState transitions. Read-only on TaskGraph — never modifies it.

    Does NOT decide next task (Planner's job) or execute tools (Executor's job).
    """

    def mark_current(self, state: ExecutionState, task_id: str) -> ExecutionState:
        """Set the current executing task. Switches status from idle to running."""
        updates = {"current_task_id": task_id}
        if state.status == "idle":
            updates["status"] = "running"
        return state.model_copy(update=updates)

    def mark_completed(self, state: ExecutionState, task_id: str) -> ExecutionState:
        """Record a task as completed. Clears current_task_id if it matches."""
        completed = list(state.completed_task_ids)
        if task_id not in completed:
            completed.append(task_id)

        updates = {"completed_task_ids": completed}
        if state.current_task_id == task_id:
            updates["current_task_id"] = None
        return state.model_copy(update=updates)

    def recompute_remaining(self, state: ExecutionState, graph: TaskGraph) -> ExecutionState:
        """Recompute remaining_task_ids from graph nodes minus completed. Update status if all done."""
        completed = set(state.completed_task_ids)
        all_ids = [node.task_id for node in graph.nodes]
        remaining = [tid for tid in all_ids if tid not in completed]

        updates = {"remaining_task_ids": remaining}
        if not remaining:
            updates["status"] = "completed"
        return state.model_copy(update=updates)

    def mark_clarification_needed(self, state: ExecutionState) -> ExecutionState:
        """Flag that the system is waiting for user clarification before proceeding."""
        return state.model_copy(update={"clarification_needed": True})

