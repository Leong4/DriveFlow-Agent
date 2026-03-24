from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.models.task import Task
from app.models.graph import TaskGraph
from app.services.task_graph_builder import TaskGraphBuilder

router = APIRouter()

builder = TaskGraphBuilder()


class GraphBuildRequest(BaseModel):
    tasks: List[Task] = Field(..., description="List of parsed tasks to build a graph from")


@router.post("/graph/build", response_model=TaskGraph)
async def build_graph(request: GraphBuildRequest):
    try:
        graph = builder.build(request.tasks)
        return graph
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
