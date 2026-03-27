from typing import Optional
from pydantic import BaseModel, Field
from app.models.graph import TaskGraph
from app.tools.schemas import ToolInput, ToolResult
from app.services.tool_router import ToolRouter
from app.services.task_planner import PlannerDecisionResult
from app.services.exceptions import UnsupportedToolRouteError
from app.services.guardrails import apply_guardrails


class ExecutionResult(BaseModel):
    task_id: Optional[str] = Field(None, description="The task_id that was executed")
    task_type: Optional[str] = Field(None, description="The task_type that was executed")
    tool_name: Optional[str] = Field(None, description="Name of the tool that was invoked")
    execution_status: str = Field(..., description="Execution outcome: 'success' | 'failed' | 'skipped'")
    tool_result: Optional[ToolResult] = Field(None, description="The raw ToolResult from the tool, if executed")
    message: Optional[str] = Field(None, description="Human-readable status or error message")


class Executor:
    """Executes a single task by routing it to the appropriate tool.

    Does NOT update state or decide the next task — those are
    StateManager's and Planner's responsibilities respectively.
    """

    def __init__(self, router: Optional[ToolRouter] = None):
        self._router = router or ToolRouter()

    def execute(self, planner_result: PlannerDecisionResult, graph: TaskGraph) -> ExecutionResult:
        # Case 1: Planner says all tasks are finished
        if planner_result.planner_decision == "finished":
            return ExecutionResult(
                execution_status="skipped",
                message="No task to execute. Planner is finished.",
            )

        # Case 2: Planner returned no next_task_id
        if not planner_result.next_task_id:
            return ExecutionResult(
                execution_status="failed",
                message="Planner did not provide a next_task_id.",
            )

        # Look up the full TaskNode from the graph
        task_node = graph.get_node(planner_result.next_task_id)
        if task_node is None:
            return ExecutionResult(
                task_id=planner_result.next_task_id,
                execution_status="failed",
                message=f"TaskNode '{planner_result.next_task_id}' not found in graph.",
            )

        # Route to the correct tool
        try:
            tool = self._router.route(task_node)
        except UnsupportedToolRouteError as e:
            return ExecutionResult(
                task_id=task_node.task_id,
                task_type=task_node.task_type,
                execution_status="failed",
                message=str(e),
            )

        # Build standardised input and execute
        tool_input = ToolInput(
            task_id=task_node.task_id,
            task_type=task_node.task_type,
            payload=task_node.payload,
        )
        tool_result = tool.run(tool_input)

        # Apply guardrails before returning
        tool_result = apply_guardrails(tool_result)

        return ExecutionResult(
            task_id=task_node.task_id,
            task_type=task_node.task_type,
            tool_name=tool.name,
            execution_status=tool_result.status,
            tool_result=tool_result,
            message=tool_result.message,
        )

