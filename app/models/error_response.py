from pydantic import BaseModel, Field

class ParseErrorResponse(BaseModel):
    status: str = Field(default="error", description="Indicates an error occurred")
    error_type: str = Field(..., description="The classification of the error, e.g., 'invalid_json', 'schema_validation_error', 'llm_service_error'")
    message: str = Field(..., description="A clear description of what went wrong, suitable for developers")
