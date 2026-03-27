from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ToolInput(BaseModel):
    task_id: str = Field(..., description="The task_id this tool call is associated with")
    task_type: str = Field(..., description="Type of the task (e.g., 'restaurant', 'destination', 'charging_station')")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Task-specific data passed to the tool")


class ToolResult(BaseModel):
    tool_name: str = Field(..., description="Name of the tool that produced this result")
    status: str = Field(..., description="Execution status: 'success' or 'failed'")
    data: Dict[str, Any] = Field(default_factory=dict, description="Structured result data from the tool")
    message: Optional[str] = Field(None, description="Optional human-readable message (e.g., error detail)")
