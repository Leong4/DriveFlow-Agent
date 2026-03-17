import json
import re
from app.models.intent_result import IntentParseResult
from app.models.parse_error import ParseError
from app.services.llm_client import LLMClient
from app.services.exceptions import IntentParseException
from pydantic import ValidationError

PARSER_PROMPT = """You are a bilingual navigation intent parser.
The user query may be in English or Chinese.
Your job is to convert complex navigation requests into a structured JSON list of tasks.

Rules:
1. ONLY output valid JSON. Do not write markdown blocks like ```json.
2. Do not write any explanations.
3. Supported task types: "restaurant", "destination", "charging_station". 
   - Fuzzy English requests (e.g. "highly rated Italian place") map to "restaurant". Put "Italian", "highly rated" into `constraints`.
4. Map sequence words ("first", "then", "before", "on the way") or Chinese equivalents to `order_hint` correctly.
5. IF the request is for an unsupported intent (e.g., restroom, parking lot, gas station):
   - DO NOT invent new task types. 
   - Exclude the unsupported task from the `tasks` list.
   - Set `parse_status` to "partial_success".
   - Include `{{"unsupported_intent": true, "notes": "restroom/parking is not supported in current version"}}` in `meta`.
6. Output format must perfectly match this structure:

Example Input 1:
I want to go to the airport, but stop by a Starbucks on the way.

Example Output 1:
{{
  "raw_query": "I want to go to the airport, but stop by a Starbucks on the way.",
  "tasks": [
    {{
      "id": "task_1",
      "type": "restaurant",
      "name": null,
      "brand": "Starbucks",
      "constraints": null,
      "order_hint": 1
    }},
    {{
      "id": "task_2",
      "type": "destination",
      "name": "airport",
      "brand": null,
      "constraints": null,
      "order_hint": 2
    }}
  ],
  "meta": {{
    "parser_version": "v1.1"
  }},
  "parse_status": "success"
}}

Example Input 2 (Unsupported & Fuzzy):
Find a clean restroom before heading to a highly rated Italian restaurant.

Example Output 2:
{{
  "raw_query": "Find a clean restroom before heading to a highly rated Italian restaurant.",
  "tasks": [
    {{
      "id": "task_1",
      "type": "restaurant",
      "name": null,
      "brand": null,
      "constraints": {{"quality": "highly rated", "cuisine": "Italian"}},
      "order_hint": 2
    }}
  ],
  "meta": {{
    "parser_version": "v1.1",
    "unsupported_intent": true,
    "notes": "restroom is not supported in current version"
  }},
  "parse_status": "partial_success"
}}

User Query: {query}
"""

async def parse_intent(query: str) -> IntentParseResult:
    client = LLMClient()
    
    messages = [
        {"role": "system", "content": "You are a precise JSON parsing API. You never output conversational text."},
        {"role": "user", "content": PARSER_PROMPT.format(query=query)}
    ]
    
    raw_output = await client.chat(messages)
    
    # Attempt to clean up markdown if the LLM hallucinated it despite instructions
    clean_output = raw_output.strip()
    
    # Use regex to extract the JSON payload if it is wrapped in markdown
    match = re.search(r"```(?:json)?(.*?)```", clean_output, re.DOTALL)
    if match:
        clean_output = match.group(1).strip()
        
    if not clean_output:
        error = ParseError(
            error_type="empty_output",
            message="LLM returned an empty or completely invalid response.",
            raw_output=raw_output
        )
        raise IntentParseException(detail=error.model_dump())
        
    try:
        parsed_data = json.loads(clean_output)
    except json.JSONDecodeError as e:
        # LLM did not return valid JSON
        error = ParseError(
            error_type="invalid_json",
            message=f"Failed to decode output as JSON: {str(e)}",
            raw_output=raw_output
        )
        raise IntentParseException(detail=error.model_dump())
        
    try:
        # Validate against schema
        result = IntentParseResult.model_validate(parsed_data)
        
        # Post-processing: strict filter for supported task types
        supported_types = {"restaurant", "destination", "charging_station"}
        valid_tasks = []
        for t in result.tasks:
            if t.type in supported_types:
                valid_tasks.append(t)
                
        # If tasks were filtered out but parse_status wasn't caught by the LLM
        if len(valid_tasks) < len(result.tasks):
            result.parse_status = "partial_success"
            if result.meta is None:
                result.meta = {}
            result.meta["unsupported_intent"] = True
            result.meta["notes"] = "Filtered out unsupported task types internally."
            
        result.tasks = valid_tasks
        return result
    except ValidationError as e:
        # Output was JSON, but didn't match our Pydantic schema
        error = ParseError(
            error_type="schema_validation_error",
            message="LLM output did not match IntentParseResult schema.",
            raw_output=raw_output
        )
        raise IntentParseException(detail=error.model_dump())
