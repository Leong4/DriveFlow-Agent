from typing import Optional
from app.tools.schemas import ToolResult
from app.services.clarification import _is_chinese_query


def _handle_empty_poi(tool_result: ToolResult, zh: bool) -> ToolResult:
    """Return a controlled failure if POI candidates list is empty."""
    candidates = tool_result.data.get("candidates", [])
    if not candidates:
        msg = "未找到匹配的地点，请尝试放宽搜索条件。" if zh else \
              "No matching POI found. Please broaden your search conditions."
        return ToolResult(
            tool_name=tool_result.tool_name,
            status="failed",
            data={"candidates": []},
            message=msg,
        )
    return tool_result


def _is_valid_coordinate(candidate: dict) -> bool:
    """Check whether a single candidate has valid lat/lng values."""
    lat = candidate.get("lat")
    lng = candidate.get("lng")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        return False
    return -90 <= lat <= 90 and -180 <= lng <= 180


def _validate_poi_coordinates(tool_result: ToolResult, zh: bool) -> ToolResult:
    """Filter out candidates with invalid coordinates."""
    candidates = tool_result.data.get("candidates", [])
    valid = [c for c in candidates if _is_valid_coordinate(c)]

    if not valid:
        msg = "返回的候选地点坐标无效，无法继续使用。" if zh else \
              "All returned POI candidates have invalid coordinates."
        return ToolResult(
            tool_name=tool_result.tool_name,
            status="failed",
            data={"candidates": []},
            message=msg,
        )

    if len(valid) < len(candidates):
        removed = len(candidates) - len(valid)
        msg = f"已移除 {removed} 个坐标无效的候选地点。" if zh else \
              f"{removed} candidate(s) removed due to invalid coordinates."
        return ToolResult(
            tool_name=tool_result.tool_name,
            status=tool_result.status,
            data={"candidates": valid},
            message=msg,
        )

    return tool_result


def _handle_route_plan_failure(tool_result: ToolResult, zh: bool) -> ToolResult:
    """Return a controlled failure if route plan result is missing or incomplete."""
    if tool_result.status == "failed":
        fallback = "路线规划失败，请尝试更换目的地或放宽条件。" if zh else \
                   "Route planning failed. Please try a different destination or loosen constraints."
        return ToolResult(
            tool_name=tool_result.tool_name,
            status="failed",
            data={},
            message=tool_result.message or fallback,
        )

    data = tool_result.data
    if "distance_km" not in data or "eta_min" not in data:
        msg = "路线结果不完整，无法继续执行。" if zh else \
              "Route result is incomplete and cannot be used."
        return ToolResult(
            tool_name=tool_result.tool_name,
            status="failed",
            data=data,
            message=msg,
        )

    return tool_result


def apply_guardrails(tool_result: ToolResult, query: str = "") -> ToolResult:
    """Unified guardrail entry point. Dispatches checks based on tool_name.

    Does NOT update state, decide next task, or trigger clarification.
    """
    zh = _is_chinese_query(query)

    if tool_result.tool_name == "poi_search":
        result = _handle_empty_poi(tool_result, zh)
        if result.status == "failed":
            return result
        return _validate_poi_coordinates(result, zh)

    if tool_result.tool_name == "route_plan":
        return _handle_route_plan_failure(tool_result, zh)

    # Unknown tool — pass through without modification
    return tool_result
