import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

from app.services.intent_parser import parse_intent
from app.services.llm_client import LLMClient
from app.services.intent_parser import PARSER_PROMPT

async def main():
    query = "我想去白云山，不过路上先找一家麦当劳"
    print(f"Testing query: {query}")
    print("-" * 50)
    
    # We will test the LLMClient directly first to see raw output
    client = LLMClient()
    messages = [
        {"role": "system", "content": "You are a precise JSON parsing API. You never output conversational text."},
        {"role": "user", "content": PARSER_PROMPT.format(query=query)}
    ]
    raw = await client.chat(messages)
    print("RAW OUTPUT:")
    print(raw)
    print("-" * 50)

    try:
        result = await parse_intent(query)
        print("Success! Parsed Intent Result:")
        print(result.model_dump_json(indent=2))
    except Exception as e:
        print(f"Error testing intent parser: {repr(e)}")

if __name__ == "__main__":
    if not os.getenv("LLM_API_KEY"):
        print("Please set up your .env file copied from .env.example first!")
    else:
        asyncio.run(main())
