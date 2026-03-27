import asyncio
from app.api.demo import run_demo, DemoRequest
import json

async def main():
    req = DemoRequest(query="我想去白云山，路上先找一家麦当劳")
    try:
        resp = await run_demo(req)
        print("SUCCESS")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
