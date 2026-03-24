from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.models.graph import TaskGraph, ExecutionState
from app.services.state_manager import StateManager

router = APIRouter()

sm = StateManager()


class StateUpdateRequest(BaseModel):
    action: str = Field(..., description="Action to perform: 'mark_current' | 'mark_completed' | 'recompute_remaining'")
    task_id: Optional[str] = Field(None, description="Target task_id (required for mark_current and mark_completed)")
    state: ExecutionState
    graph: Optional[TaskGraph] = Field(None, description="Required only for recompute_remaining")


@router.post("/state/update", response_model=ExecutionState)
async def update_state(request: StateUpdateRequest):
    if request.action == "mark_current":
        if not request.task_id:
            raise HTTPException(status_code=400, detail="task_id is required for mark_current")
        return sm.mark_current(request.state, request.task_id)

    elif request.action == "mark_completed":
        if not request.task_id:
            raise HTTPException(status_code=400, detail="task_id is required for mark_completed")
        return sm.mark_completed(request.state, request.task_id)

    elif request.action == "recompute_remaining":
        if not request.graph:
            raise HTTPException(status_code=400, detail="graph is required for recompute_remaining")
        return sm.recompute_remaining(request.state, request.graph)

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: '{request.action}'. Must be 'mark_current', 'mark_completed', or 'recompute_remaining'.")
