from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from app.models.task import Task

class IntentParseResult(BaseModel):
    raw_query: str = Field(..., description="The original raw user query")
    tasks: List[Task] = Field(..., description="List of structured tasks parsed from the query")
    meta: Optional[Dict[str, Any]] = Field(None, description="Additional metadata, e.g., parser_version or latency_ms")
    parse_status: str = Field(..., description="Status of the parsing operation (e.g., 'success' or 'failed')")
