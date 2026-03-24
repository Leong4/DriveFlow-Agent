from fastapi import FastAPI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from app.api.parse import router as parse_router
from app.api.graph import router as graph_router
from app.api.planner import router as planner_router
from app.api.state import router as state_router

app = FastAPI(title="DriveFlow Agent API")

app.include_router(parse_router)
app.include_router(graph_router)
app.include_router(planner_router)
app.include_router(state_router)

@app.get("/health")
async def health_check():
    return {"status": "ok"}
