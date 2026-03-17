from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app.models import Task, IntentParseResult, ParseErrorResponse
from app.services.intent_parser import parse_intent
from app.services.exceptions import IntentParseException, LLMServiceError

router = APIRouter()

class ParseRequest(BaseModel):
    query: str

@router.post("/parse", response_model=IntentParseResult, responses={400: {"model": ParseErrorResponse}, 500: {"model": ParseErrorResponse}})
async def parse_intent_api(request: ParseRequest):
    try:
        result = await parse_intent(request.query)
        return result
    except IntentParseException as e:
        error_resp = ParseErrorResponse(
            status="error",
            error_type=e.detail.get("error_type", "unknown_error"),
            message=e.detail.get("message", "An intent parsing error occurred.")
        )
        return JSONResponse(status_code=400, content=error_resp.model_dump())
    except LLMServiceError as e:
        error_resp = ParseErrorResponse(
            status="error",
            error_type="llm_service_error",
            message=e.message
        )
        return JSONResponse(status_code=500, content=error_resp.model_dump())
