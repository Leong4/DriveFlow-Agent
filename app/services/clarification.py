import re
from typing import Optional
from app.models.graph import ExecutionState
from app.tools.schemas import ToolResult
from app.services.state_manager import StateManager

# Minimum number of POI candidates to trigger clarification
_CLARIFICATION_THRESHOLD = 2

_sm = StateManager()


def _is_chinese_query(query: str) -> bool:
    """Return True if the query contains any CJK Unified Ideographs."""
    return bool(re.search(r"[\u4e00-\u9fff]", query))


def needs_clarification(tool_result: ToolResult) -> bool:
    """Return True if the tool result contains ambiguity that requires user clarification."""
    if tool_result.status != "success":
        return False
    candidates = tool_result.data.get("candidates", [])
    return len(candidates) >= _CLARIFICATION_THRESHOLD


def build_clarification_prompt(tool_result: ToolResult, query: str = "") -> Optional[str]:
    """Generate a human-readable clarification question from multi-candidate POI results.

    Returns None if clarification is not needed.
    Language is inferred from the original query.
    """
    candidates = tool_result.data.get("candidates", [])
    if len(candidates) < _CLARIFICATION_THRESHOLD:
        return None

    use_zh = _is_chinese_query(query)
    n = len(candidates)

    if use_zh:
        header = f"我找到了 {n} 个候选地点，请确认你想去哪一个："
    else:
        header = f"I found {n} options. Which one would you like?"

    lines = [header]
    for idx, c in enumerate(candidates, start=1):
        name = c.get("name", "Unknown")
        address = c.get("address", "")
        lines.append(f"  {idx}. {name} — {address}" if address else f"  {idx}. {name}")

    return "\n".join(lines)


def handle_clarification_if_needed(
    state: ExecutionState,
    tool_result: ToolResult,
    query: str = "",
) -> tuple[ExecutionState, Optional[str]]:
    """Check if clarification is needed and return updated state + prompt.

    If clarification is NOT needed, returns the original state and None.
    If clarification IS needed, sets clarification_needed=True on the state
    and returns a readable clarification prompt string in the query's language.
    """
    if not needs_clarification(tool_result):
        return state, None

    prompt = build_clarification_prompt(tool_result, query)
    updated_state = _sm.mark_clarification_needed(state)
    return updated_state, prompt
