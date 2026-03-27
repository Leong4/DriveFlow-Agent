"""
DriveFlow Agent — Google Maps Tool Verification Script

Verifies that PoiSearchTool and RoutePlanTool produce real results
via the Google Maps API, using the project's standard ToolInput / ToolResult
contract.

Usage:
    python3 -m scripts.test_google_tools
"""

import json
import sys

from dotenv import load_dotenv

load_dotenv()

from app.tools.schemas import ToolInput
from app.tools.poi_search import PoiSearchTool
from app.tools.route_plan import RoutePlanTool


def pretty(label: str, result):
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
    print()


def main():
    poi_tool = PoiSearchTool()
    route_tool = RoutePlanTool()
    all_passed = True

    # ── Test A: Restaurant POI (brand = McDonalds) ──
    print("\n▶ Test A: Restaurant POI search (brand = McDonalds)")
    result_a = poi_tool.run(ToolInput(
        task_id="task_1",
        task_type="restaurant",
        payload={"brand": "McDonalds"},
    ))
    pretty("Test A — PoiSearchTool (restaurant / McDonalds)", result_a)
    if result_a.status != "success":
        print("  ⚠️  Test A returned non-success (API issue?)")
        all_passed = False

    # ── Test B: Charging Station POI ──
    print("\n▶ Test B: Charging Station POI search")
    result_b = poi_tool.run(ToolInput(
        task_id="task_2",
        task_type="charging_station",
        payload={},
    ))
    pretty("Test B — PoiSearchTool (charging_station)", result_b)
    if result_b.status != "success":
        print("  ⚠️  Test B returned non-success (API issue?)")
        all_passed = False

    # ── Test C: Destination POI (Nottingham Station) ──
    print("\n▶ Test C: Destination POI search (name = Nottingham Station)")
    result_c = poi_tool.run(ToolInput(
        task_id="task_3",
        task_type="destination",
        payload={"name": "Nottingham Station"},
    ))
    pretty("Test C — PoiSearchTool (destination / Nottingham Station)", result_c)
    if result_c.status != "success":
        print("  ⚠️  Test C returned non-success (API issue?)")
        all_passed = False

    # ── Test D: Route Plan (to Nottingham Station) ──
    print("\n▶ Test D: Route plan (University of Nottingham → Nottingham Station)")
    result_d = route_tool.run(ToolInput(
        task_id="task_4",
        task_type="destination",
        payload={"name": "Nottingham Station"},
    ))
    pretty("Test D — RoutePlanTool (→ Nottingham Station)", result_d)
    if result_d.status != "success":
        print("  ⚠️  Test D returned non-success (API issue?)")
        all_passed = False

    # ── Test E: Error handling — missing destination ──
    print("\n▶ Test E: Route plan with missing destination (expect controlled failure)")
    result_e = route_tool.run(ToolInput(
        task_id="task_5",
        task_type="destination",
        payload={},
    ))
    pretty("Test E — RoutePlanTool (missing destination)", result_e)
    if result_e.status != "failed":
        print("  ⚠️  Test E should have returned 'failed'")
        all_passed = False

    # ── Summary ──
    print(f"\n{'#' * 60}")
    if all_passed:
        print("  ✅ ALL TESTS PASSED — tools return real Google Maps data")
    else:
        print("  ⚠️  SOME TESTS HAD ISSUES — check output above")
    print(f"{'#' * 60}\n")


if __name__ == "__main__":
    main()
