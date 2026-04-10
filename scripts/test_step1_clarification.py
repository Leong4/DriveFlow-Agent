"""
DriveFlow Agent — Step 1 Verification: Clarification + Candidate Selection

Tests the five required scenarios end-to-end via /demo/run.

  1. "I want to eat"                          → clarification_needed
  2. "fried chicken"                          → candidate_selection_needed
  3. "Take me to McDonald's"                  → candidate_selection_needed
  4. "Find anything to eat on the way"        → candidate_selection_needed (delegation)
  5. "Take me to East Midlands Airport"       → ready_for_routing (unchanged)

Usage:
  1. Start the server:  uvicorn app.main:app --reload
  2. Run this script:   python3 -m scripts.test_step1_clarification
"""

import json
import sys
import httpx

BASE = "http://127.0.0.1:8000"

SCENARIOS = [
    {
        "title":    "1. Broad intent → clarification",
        "payload":  {"query": "I want to eat", "origin": "University of Nottingham"},
        "expect_status": "clarification_needed",
        "expect_candidates": False,
        "expect_question":   True,
        # Must NOT build a route or return stop markers
        "expect_no_route":   True,
    },
    {
        "title":    "2. Specific non-brand (after clarification) → candidates, no premature route",
        "payload":  {"query": "fried chicken", "origin": "University of Nottingham"},
        "expect_status": "candidate_selection_needed",
        "expect_candidates": True,
        "expect_question":   False,
        "expect_no_route":   True,
    },
    {
        "title":    "3. Known brand → candidates, no premature route",
        "payload":  {"query": "Take me to McDonald's", "origin": "University of Nottingham"},
        "expect_status": "candidate_selection_needed",
        "expect_candidates": True,
        "expect_question":   False,
        "expect_no_route":   True,
    },
    {
        "title":    "4. Delegation (anything / whatever) → recommendations, no premature route",
        "payload":  {"query": "Find anything to eat on the way to Nottingham city centre",
                     "origin": "University of Nottingham"},
        "expect_status": "candidate_selection_needed",
        "expect_candidates": True,
        "expect_question":   False,
        "expect_delegation": True,
        "expect_no_route":   True,
    },
    {
        "title":    "5. Destination only → normal routing unchanged",
        "payload":  {"query": "Take me to East Midlands Airport",
                     "origin": "University of Nottingham"},
        "expect_status": "ready_for_routing",
        "expect_candidates": False,
        "expect_question":   False,
        "expect_no_route":   False,   # route SHOULD be built
    },
    {
        "title":    "6. Unique named stop (airport) → ready_for_routing, not candidate selection",
        "payload":  {"query": "Stop at East Midlands Airport then go to Nottingham city centre",
                     "origin": "University of Nottingham"},
        "expect_status": "ready_for_routing",
        "expect_candidates": False,
        "expect_question":   False,
        "expect_no_route":   False,
    },
]


def _pretty(label: str, data: dict):
    print(f"\n{'─' * 60}")
    print(f"  {label}")
    print(f"{'─' * 60}")
    print(json.dumps(data, indent=2, ensure_ascii=False)[:1200])


def run_scenario(client: httpx.Client, s: dict) -> bool:
    print(f"\n{'#' * 60}")
    print(f"  {s['title']}")
    print(f"  Query: {s['payload']['query']!r}")
    print(f"{'#' * 60}")

    resp = client.post(f"{BASE}/demo/run", json=s["payload"])
    if resp.status_code != 200:
        print(f"  ❌ HTTP {resp.status_code}: {resp.text[:300]}")
        return False

    data = resp.json()
    pre_status = data.get("pre_route_status", "")
    question   = data.get("pre_route_question")
    candidates = data.get("pre_route_candidates") or []

    print(f"  pre_route_status : {pre_status!r}")
    print(f"  pre_route_question: {question!r}")
    print(f"  candidates count : {len(candidates)}")
    if candidates:
        for c in candidates:
            print(f"    • {c.get('name')} [{c.get('reason_tag')}] — {c.get('address','')[:60]}")

    # ── Assertions ──────────────────────────────────────────────────────────
    ok = True

    if pre_status != s["expect_status"]:
        print(f"  ❌ FAIL: expected pre_route_status={s['expect_status']!r}, got {pre_status!r}")
        ok = False

    if s["expect_question"] and not question:
        print("  ❌ FAIL: expected a clarification question, got None")
        ok = False

    if not s["expect_question"] and question:
        print(f"  ❌ FAIL: did not expect a question, got {question!r}")
        ok = False

    if s["expect_candidates"] and not candidates:
        print("  ❌ FAIL: expected candidates, got empty list")
        ok = False

    if not s["expect_candidates"] and candidates:
        print(f"  ❌ FAIL: did not expect candidates, got {len(candidates)}")
        ok = False

    if s.get("expect_delegation"):
        if not any(c.get("reason_tag") == "recommended" for c in candidates):
            print("  ❌ FAIL: delegation scenario should have a 'recommended' reason_tag")
            ok = False

    if s.get("expect_no_route"):
        # For blocking pre-route states the map must have no stop markers
        # and state.status must remain "idle" (no route built).
        stops_on_map = data.get("map_data", {}).get("stops", [])
        state_status = data.get("state", {}).get("status", "")
        if stops_on_map:
            print(f"  ❌ FAIL: expect_no_route but map has {len(stops_on_map)} stop(s)")
            ok = False
        if state_status not in {"idle"}:
            print(f"  ❌ FAIL: expect_no_route but state.status={state_status!r} (expected 'idle')")
            ok = False
        if data.get("planner_result") is not None:
            print("  ❌ FAIL: expect_no_route but planner_result is populated")
            ok = False

    if s["expect_status"] == "ready_for_routing":
        state_status = data.get("state", {}).get("status", "")
        if state_status not in {"running", "completed", "idle"}:
            print(f"  ❌ FAIL: normal routing should proceed; got state.status={state_status!r}")
            ok = False

    if ok:
        print("  ✅ PASS")

    return ok


def main():
    client = httpx.Client(timeout=30.0)
    results = []
    for s in SCENARIOS:
        try:
            results.append(run_scenario(client, s))
        except Exception as exc:
            print(f"  ❌ Exception: {exc}")
            results.append(False)

    passed = sum(results)
    total  = len(results)
    print(f"\n{'=' * 60}")
    print(f"  Step 1 Tests: {passed}/{total} passed")
    print(f"{'=' * 60}\n")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
