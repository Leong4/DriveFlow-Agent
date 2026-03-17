from fastapi import FastAPI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from app.api.parse import router as parse_router

app = FastAPI(title="DriveFlow Agent API")

app.include_router(parse_router)

@app.get("/health")
async def health_check():
    return {"status": "ok"}
