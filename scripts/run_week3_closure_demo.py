"""
DriveFlow Agent — Week3 Closure Demo

Runs two full end-to-end scenarios to prove the system forms a real closed loop:

  Scenario 1: "去景点，路上先找餐厅"         (no car-state)
  Scenario 2: "电量低，先补能再去机场"        (with car-state)

Pipeline per scenario:
  query → /parse → [car-state rules] → /graph/build → /planner/next
  → executor → state update

Usage:
  1. Start the server:  uvicorn app.main:app --reload
  2. Run this script:   python3 -m scripts.run_week3_closure_demo
"""

import json
import httpx
import sys

BASE = "http://127.0.0.1:8000"


def pretty(label: str, data: dict):
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(json.dumps(data, indent=2, ensure_ascii=False))


def run_scenario(client: httpx.Client, title: str, query: str, car_state=None):
    print(f"\n{'#' * 60}")
    print(f"  {title}")
    print(f"  Query: {query}")
    if car_state:
        print(f"  Car State: battery={car_state['battery_level']}%, range={car_state['remaining_range_km']}km")
    print(f"{'#' * 60}")

    # ── Step 1: Parse ──
    resp = client.post(f"{BASE}/parse", json={"query": query})
    if resp.status_code != 200:
        print(f"❌ /parse failed: {resp.text}")
        return
    parse_result = resp.json()
    tasks = parse_result["tasks"]
    pretty("Step 1 — /parse → IntentParseResult", parse_result)

    # ── Step 1.5: Car-state rules (offline, no API call) ──
    if car_state:
        from app.models.context import CarStateContext
        from app.models.task import Task
        from app.services.car_state_rules import maybe_insert_charging_task

        ctx = CarStateContext(**car_state)
        task_objs = [Task(**t) for t in tasks]
        augmented = maybe_insert_charging_task(task_objs, ctx)
        tasks = [t.model_dump() for t in augmented]
        pretty("Step 1.5 — Car-State Rule Augmentation", {"tasks": tasks})

    # ── Step 2: Build Graph ──
    resp = client.post(f"{BASE}/graph/build", json={"tasks": tasks})
    if resp.status_code != 200:
        print(f"❌ /graph/build failed: {resp.text}")
        return
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
        return
    decision = resp.json()
    pretty("Step 3 — /planner/next → PlannerDecisionResult", decision)

    # ── Step 4: Execute via Executor (in-process, not API) ──
    from app.models.graph import TaskGraph as TG
    from app.services.task_planner import PlannerDecisionResult
    from app.services.executor import Executor

    executor = Executor()
    planner_res = PlannerDecisionResult(**decision)
    graph_obj = TG(**graph)
    exec_result = executor.execute(planner_res, graph_obj)
    pretty("Step 4 — Executor → ExecutionResult", exec_result.model_dump())

    # ── Step 5: State update (mark_current + mark_completed) ──
    next_id = decision.get("next_task_id")
    if next_id:
        resp = client.post(f"{BASE}/state/update", json={
            "action": "mark_current",
            "task_id": next_id,
            "state": state,
        })
        if resp.status_code == 200:
            state = resp.json()

        resp = client.post(f"{BASE}/state/update", json={
            "action": "mark_completed",
            "task_id": next_id,
            "state": state,
        })
        if resp.status_code == 200:
            state = resp.json()

        resp = client.post(f"{BASE}/state/update", json={
            "action": "recompute_remaining",
            "task_id": None,
            "state": state,
            "graph": graph,
        })
        if resp.status_code == 200:
            state = resp.json()

    pretty("Step 5 — State after one round", state)

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print(f"  ✅ {title} — CLOSED LOOP COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Tasks parsed:  {len(parse_result['tasks'])}")
    print(f"  Tasks in graph: {len(graph['nodes'])}")
    print(f"  First executed: {exec_result.task_id} ({exec_result.task_type}) → {exec_result.execution_status}")
    print(f"  State status:  {state['status']}")
    print(f"  Completed:     {state['completed_task_ids']}")
    print(f"  Remaining:     {state['remaining_task_ids']}")
    print()


def main():
    client = httpx.Client(timeout=30.0)

    # ── Scenario 1 ──
    run_scenario(
        client,
        title="Scenario 1: Restaurant + Destination (no car-state)",
        query="我想去白云山，路上先找一家麦当劳",
    )

    # ── Scenario 2 ──
    run_scenario(
        client,
        title="Scenario 2: Low Battery → Auto-insert Charging → Airport",
        query="我要去机场",
        car_state={"battery_level": 18, "remaining_range_km": 20},
    )


if __name__ == "__main__":
    main()
