"""
DriveFlow Agent — Week2 Integration Demo

Runs the full pipeline in one script:
  query → /parse → /graph/build → /planner/next → /state/update

Usage:
  1. Start the server:  uvicorn app.main:app --reload
  2. Run this script:   python3 -m scripts.run_week2_demo
"""

import httpx
import json
import sys

BASE = "http://127.0.0.1:8000"


def pretty(label: str, data: dict):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main():
    client = httpx.Client(timeout=30.0)
    query = "我电量低，先去充电，再去机场"

    # ── Step 1: Parse ──
    print(f"\n📝 Query: {query}")
    resp = client.post(f"{BASE}/parse", json={"query": query})
    if resp.status_code != 200:
        print(f"❌ /parse failed: {resp.text}")
        sys.exit(1)
    parse_result = resp.json()
    pretty("Step 1 — /parse → IntentParseResult", parse_result)
    tasks = parse_result["tasks"]

    # ── Step 2: Build Graph ──
    resp = client.post(f"{BASE}/graph/build", json={"tasks": tasks})
    if resp.status_code != 200:
        print(f"❌ /graph/build failed: {resp.text}")
        sys.exit(1)
    graph = resp.json()
    pretty("Step 2 — /graph/build → TaskGraph", graph)

    # ── Step 3: Init State + Plan ──
    all_ids = [node["task_id"] for node in graph["nodes"]]
    state = {
        "current_task_id": None,
        "completed_task_ids": [],
        "remaining_task_ids": all_ids,
        "status": "idle",
        "clarification_needed": False,
    }

    resp = client.post(f"{BASE}/planner/next", json={"graph": graph, "state": state})
    if resp.status_code != 200:
        print(f"❌ /planner/next failed: {resp.text}")
        sys.exit(1)
    decision = resp.json()
    pretty("Step 3 — /planner/next → PlannerDecisionResult", decision)

    # ── Step 4: Update State (mark_current) ──
    next_id = decision["next_task_id"]
    resp = client.post(f"{BASE}/state/update", json={
        "action": "mark_current",
        "task_id": next_id,
        "state": state,
    })
    if resp.status_code != 200:
        print(f"❌ /state/update failed: {resp.text}")
        sys.exit(1)
    state = resp.json()
    pretty("Step 4 — /state/update (mark_current) → ExecutionState", state)

    # ── Summary ──
    print(f"\n{'='*60}")
    print("  ✅ Week2 Full Pipeline Demo Complete")
    print(f"{'='*60}")
    print(f"  Query:        {query}")
    print(f"  Tasks parsed: {len(tasks)}")
    print(f"  Graph nodes:  {len(graph['nodes'])}")
    print(f"  Next task:    {decision['next_task_id']} ({decision['next_task_type']})")
    print(f"  State status: {state['status']}")
    print()


if __name__ == "__main__":
    main()
