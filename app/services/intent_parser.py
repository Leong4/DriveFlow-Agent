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
3. Supported task types:
   - "stop"            — any intermediate POI (coffee shop, restaurant, store, pharmacy, etc.)
                         Put all place semantics in `payload`: label, query, brand, category_hint, original_text.
                         Set name=null, brand=null, constraints=null at the top level.
   - "destination"     — the final destination. Put the place name in `name`.
   - "charging_station"— an EV charging stop. Payload and brand are optional.
   - "restaurant"      — legacy alias for "stop"; still accepted but prefer "stop" for new outputs.
4. For multi-stop queries, emit one task per stop in route order. Each gets a sequential order_hint.
5. Map sequence words ("first", "then", "before", "on the way", "stop by", "and then") or Chinese
   equivalents to correct order_hint values.
6. The final destination always gets the highest order_hint.
7. IF the request includes an unsupported intent (restroom, parking, gas station):
   - Exclude the unsupported task from `tasks`.
   - Set `parse_status` to "partial_success".
   - Add `{{"unsupported_intent": true, "notes": "..."}}` to `meta`.
8. Output format must perfectly match this structure:

Example Input 1 (single stop):
I want to go to East Midlands Airport, but stop by a Starbucks on the way.

Example Output 1:
{{
  "raw_query": "I want to go to East Midlands Airport, but stop by a Starbucks on the way.",
  "tasks": [
    {{
      "id": "task_1",
      "type": "stop",
      "name": null,
      "brand": null,
      "constraints": null,
      "order_hint": 1,
      "payload": {{
        "label": "Starbucks",
        "query": "Starbucks",
        "brand": "Starbucks",
        "category_hint": "cafe",
        "original_text": "Starbucks"
      }}
    }},
    {{
      "id": "task_2",
      "type": "destination",
      "name": "East Midlands Airport",
      "brand": null,
      "constraints": null,
      "order_hint": 2,
      "payload": null
    }}
  ],
  "meta": {{"parser_version": "v1.2"}},
  "parse_status": "success"
}}

Example Input 2 (multi-stop):
Take me to East Midlands Airport, but stop by a Starbucks and a Tesco on the way.

Example Output 2:
{{
  "raw_query": "Take me to East Midlands Airport, but stop by a Starbucks and a Tesco on the way.",
  "tasks": [
    {{
      "id": "task_1",
      "type": "stop",
      "name": null,
      "brand": null,
      "constraints": null,
      "order_hint": 1,
      "payload": {{
        "label": "Starbucks",
        "query": "Starbucks",
        "brand": "Starbucks",
        "category_hint": "cafe",
        "original_text": "Starbucks"
      }}
    }},
    {{
      "id": "task_2",
      "type": "stop",
      "name": null,
      "brand": null,
      "constraints": null,
      "order_hint": 2,
      "payload": {{
        "label": "Tesco",
        "query": "Tesco supermarket",
        "brand": "Tesco",
        "category_hint": "supermarket",
        "original_text": "Tesco"
      }}
    }},
    {{
      "id": "task_3",
      "type": "destination",
      "name": "East Midlands Airport",
      "brand": null,
      "constraints": null,
      "order_hint": 3,
      "payload": null
    }}
  ],
  "meta": {{"parser_version": "v1.2"}},
  "parse_status": "success"
}}

Example Input 3 (Unsupported intent):
Find a clean restroom before heading to a highly rated Italian restaurant.

Example Output 3:
{{
  "raw_query": "Find a clean restroom before heading to a highly rated Italian restaurant.",
  "tasks": [
    {{
      "id": "task_1",
      "type": "stop",
      "name": null,
      "brand": null,
      "constraints": null,
      "order_hint": 1,
      "payload": {{
        "label": "Italian restaurant",
        "query": "highly rated Italian restaurant",
        "brand": null,
        "category_hint": "restaurant",
        "original_text": "highly rated Italian restaurant"
      }}
    }}
  ],
  "meta": {{
    "parser_version": "v1.2",
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
        supported_types = {"stop", "restaurant", "destination", "charging_station"}
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
