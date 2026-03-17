from typing import Optional
from pydantic import BaseModel, Field

class ParseError(BaseModel):
    error_type: str = Field(..., description="Type of parser error (e.g., 'invalid_json', 'schema_validation_error')")
    message: str = Field(..., description="Clear error description for developers")
    raw_output: Optional[str] = Field(None, description="Original LLM output or raw error content for debugging")
