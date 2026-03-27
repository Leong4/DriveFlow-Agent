from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

from app.api.parse import router as parse_router
from app.api.graph import router as graph_router
from app.api.planner import router as planner_router
from app.api.state import router as state_router
from app.api.demo import router as demo_router

app = FastAPI(title="DriveFlow Agent API")

app.include_router(parse_router)
app.include_router(graph_router)
app.include_router(planner_router)
app.include_router(state_router)
app.include_router(demo_router)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

# Mount frontend directory as static files serving at /
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
