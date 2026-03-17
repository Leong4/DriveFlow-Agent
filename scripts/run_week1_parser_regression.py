import json
import asyncio
import httpx
from pathlib import Path

import json
import asyncio
import httpx
from pathlib import Path

async def run_suite(client, data_file, title):
    if not data_file.exists():
        print(f"Test data file not found: {data_file}")
        return 0, 0, 0
        
    with open(data_file, "r", encoding="utf-8") as f:
        cases = json.load(f)
        
    url = "http://127.0.0.1:8000/parse"
    print(f"\n=== {title} ===")
    
    success_count = 0
    failed_count = 0
    
    for case in cases:
        case_id = case["id"]
        query = case["query"]
        
        try:
            response = await client.post(url, json={"query": query})
            status = response.status_code
            data = response.json()
            
            parse_status = data.get("parse_status", "unknown")
            if status == 200 and parse_status in ("success", "partial_success"):
                print(f"[{case_id}] SUCCESS | Query: {query}")
                print(f"    -> Status: {status}")
                print(f"    -> Parse Status: {parse_status}")
                print(f"    -> Tasks: {len(data.get('tasks', []))}")
                
                meta = data.get("meta", {})
                if meta and meta.get("unsupported_intent"):
                    print(f"    -> Notes: {meta.get('notes', 'No notes provided')}")
                
                success_count += 1
            else:
                print(f"[{case_id}] FAILED  | Query: {query}")
                print(f"    -> Status: {status}")
                print(f"    -> Error Type: {data.get('error_type', 'unknown')}")
                print(f"    -> Message: {data.get('message', 'No message')}")
                failed_count += 1
                
        except Exception as e:
            print(f"[{case_id}] ERROR   | Query: {query}")
            print(f"    -> Exception: {str(e)}")
            failed_count += 1
            
    return len(cases), success_count, failed_count

async def main():
    print("Starting bilingual regression test...")
    
    zh_file = Path("data/test_queries_week1.json")
    en_file = Path("data/test_queries_week1_en.json")
    
    total_all, success_all, failed_all = 0, 0, 0
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Run Chinese cases
        t_zh, s_zh, f_zh = await run_suite(client, zh_file, "Chinese Cases")
        total_all += t_zh
        success_all += s_zh
        failed_all += f_zh
        
        # Run English cases
        t_en, s_en, f_en = await run_suite(client, en_file, "English Cases")
        total_all += t_en
        success_all += s_en
        failed_all += f_en
            
    print("\n" + "=" * 50)
    print("Regression Test Summary")
    print("=" * 50)
    print(f"TOTAL:   {total_all}")
    print(f"SUCCESS: {success_all}")
    print(f"FAILED:  {failed_all}")

if __name__ == "__main__":
    asyncio.run(main())
