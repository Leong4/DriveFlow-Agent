from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.models.graph import TaskGraph, ExecutionState
from app.services.task_planner import TaskPlanner, PlannerDecisionResult

router = APIRouter()

planner = TaskPlanner()


class PlannerRequest(BaseModel):
    graph: TaskGraph
    state: ExecutionState


@router.post("/planner/next", response_model=PlannerDecisionResult)
async def plan_next(request: PlannerRequest):
    try:
        result = planner.plan(request.graph, request.state)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
