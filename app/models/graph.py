from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class TaskNode(BaseModel):
    task_id: str = Field(..., description="Unique identifier for the task node")
    task_type: str = Field(..., description="Type of task: 'restaurant' | 'destination' | 'charging_station'")
    # Task status: pending | running | done | failed
    status: str = Field(default="pending")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Flexible task data (brand, name, constraints, etc.)")


class TaskEdge(BaseModel):
    source: str = Field(..., description="Source task_id")
    target: str = Field(..., description="Target task_id")
    # Edge relation: next | depends_on
    relation: str = Field(default="next")


class TaskGraph(BaseModel):
    nodes: List[TaskNode] = Field(..., description="All task nodes in the graph")
    edges: List[TaskEdge] = Field(default_factory=list, description="Directed edges between nodes")
    entry_node: str = Field(..., description="task_id of the entry point node")

    @model_validator(mode="after")
    def validate_entry_node(self) -> "TaskGraph":
        node_ids = {node.task_id for node in self.nodes}
        if self.entry_node not in node_ids:
            raise ValueError(
                f"entry_node '{self.entry_node}' does not exist in nodes. "
                f"Valid task_ids: {node_ids}"
            )
        return self

    def get_node(self, task_id: str) -> Optional[TaskNode]:
        """Return the node matching task_id, or None if not found."""
        for node in self.nodes:
            if node.task_id == task_id:
                return node
        return None

    def get_next_nodes(self, task_id: str) -> List[TaskNode]:
        """Return all direct successor nodes reachable from the given task_id."""
        target_ids = {edge.target for edge in self.edges if edge.source == task_id}
        return [node for node in self.nodes if node.task_id in target_ids]


class ExecutionState(BaseModel):
    current_task_id: Optional[str] = Field(default=None, description="The task_id currently being executed")
    completed_task_ids: List[str] = Field(default_factory=list, description="List of completed task_ids")
    remaining_task_ids: List[str] = Field(default_factory=list, description="List of task_ids yet to be completed")
    # Execution status: idle | running | completed | failed
    status: str = Field(default="idle")
    clarification_needed: bool = Field(default=False, description="Whether the system needs user clarification to proceed")
