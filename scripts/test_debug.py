import asyncio
from dotenv import load_dotenv

load_dotenv()

from app.services.intent_parser import parse_intent

async def main():
    try:
        res = await parse_intent("Find the nearest charging station.")
        print("OK", res)
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
