"""
ActionIntent — explicit route operation layer for Step B1/B1.2.

Translates a SemanticIntentResult into a small set of inspectable RouteActions.
This layer sits between semantic intent classification and pre-route orchestration,
making the system's intermediate reasoning explicit and auditable.

Design boundaries:
  - Deterministic: no LLM calls, no I/O
  - Additive: does not replace semantic_intent or pre_route_filter
  - Minimal: exactly the action set needed for B1 — no speculative additions
  - Translucent: all fields are optional; downstream modules fill in what is missing
"""

import re
from typing import Optional

from pydantic import BaseModel

from app.services.itinerary_editor import EditIntent, parse_edit_intent
from app.services.semantic_intent import SemanticIntentMode, SemanticIntentResult


_ALONG_ROUTE_RE = re.compile(
    r"\b(?:on|along)\s+the\s+way\b|路上|顺路",
    re.IGNORECASE,
)

_LEADING_VERB_RE = re.compile(
    r"^(?:and\s+)?(?:find|get|give|recommend|suggest)(?:\s+me)?\s+",
    re.IGNORECASE,
)

_EN_TRAILING_ALONG_ROUTE_RE = re.compile(
    r"\s+(?:on|along)\s+the\s+way\b[\s.!?]*$",
    re.IGNORECASE,
)

_ZH_LEADING_ALONG_ROUTE_RE = re.compile(
    r"^\s*(?:路上|顺路)\s*(?:找|去|到)?\s*(?:个|家|一下)?",
    re.IGNORECASE,
)


def _has_along_route_marker(query: str) -> bool:
    return bool(_ALONG_ROUTE_RE.search(query))


def _normalise_contextual_stop_query(raw: str) -> Optional[str]:
    text = raw.strip(" ,，。.!?")
    text = _LEADING_VERB_RE.sub("", text)
    text = _EN_TRAILING_ALONG_ROUTE_RE.sub("", text)
    text = _ZH_LEADING_ALONG_ROUTE_RE.sub("", text)
    text = text.strip(" ,，。.!?")

    lowered = text.lower()
    if lowered.startswith(("a ", "an ", "the ")):
        text = text.split(" ", 1)[1]
        lowered = text.lower()
    if lowered.startswith("somewhere for "):
        text = text[len("somewhere for "):]
        lowered = text.lower()
    elif lowered.startswith("a place to "):
        text = text[len("a place to "):]
        lowered = text.lower()
    elif lowered.startswith("a place for "):
        text = text[len("a place for "):]
        lowered = text.lower()
    elif lowered.startswith("something to "):
        text = text[len("something to "):]
        lowered = text.lower()

    category_map = {
        "eat": "eat",
        "food": "eat",
        "drink": "drink",
        "coffee": "coffee",
        "bubble tea": "bubble tea",
        "吃饭的地方": "eat",
        "吃的地方": "eat",
        "餐厅": "eat",
        "饭店": "eat",
        "咖啡店": "coffee",
        "奶茶店": "bubble tea",
        "星巴克": "星巴克",
    }
    return category_map.get(lowered, text or None)


def _derive_append_stop_query(
    semantic_intent: SemanticIntentResult,
    query: str,
) -> Optional[str]:
    if semantic_intent.search_text:
        normalized = _normalise_contextual_stop_query(semantic_intent.search_text)
        return normalized or semantic_intent.search_text
    if semantic_intent.mode == SemanticIntentMode.BROAD_NEED and semantic_intent.category:
        return semantic_intent.category
    if _has_along_route_marker(query):
        return _normalise_contextual_stop_query(query)
    return None


# ── Action type constants ─────────────────────────────────────────────────────

class ActionType:
    """Tightly bounded set of route operations for Step B1.

    Intentionally small.  Adding a new action type here requires a matching
    handler in pre_route_service.py and a verified test case.
    """
    SET_DESTINATION      = "set_destination"      # establish or replace the final destination
    APPEND_STOP          = "append_stop"           # insert a stop along the current route
    REPLACE_STOP         = "replace_stop"          # swap an existing stop for another
    CLARIFY_MISSING_SLOT = "clarify_missing_slot"  # domain known; subtype slot not yet filled
    RESOLVE_CANDIDATE    = "resolve_candidate"     # in-progress POI selection — leaf state
    UNKNOWN              = "unknown"               # cannot classify; fall through to parser


# ── Action schema ─────────────────────────────────────────────────────────────

class RouteAction(BaseModel):
    """Minimal structured representation of the user's intended route operation.

    Fields are set only when directly derivable from deterministic rules at this
    stage.  Downstream modules (parser, editor, pre_route_filter) fill the rest.

    All Optional fields default to None; consumers must check before using.
    """
    action_type: str                              # one of ActionType constants

    # set_destination
    destination_query: Optional[str] = None       # name/query if pre-extractable

    # append_stop
    stop_query: Optional[str] = None              # stop name if extractable (along-route)
    constraints: Optional[dict] = None            # e.g. {"along_route": True}

    # replace_stop
    target_query: Optional[str] = None            # existing stop to swap out
    replacement_query: Optional[str] = None       # new stop to insert

    # clarify_missing_slot
    domain: Optional[str] = None                  # "food" | "drink" | "clothes" | "shopping"
    missing_slot: Optional[str] = None            # always "type" in B1

    # meta — downstream can use these as routing hints
    requires_candidate_selection: bool = False    # True when a branch/location must be picked
    requires_clarification: bool = False          # True when a narrowing question must be asked


# ── Classifier ───────────────────────────────────────────────────────────────

def classify_route_action(
    semantic_intent: SemanticIntentResult,
    query: str,
    *,
    is_continuation: bool = False,
    has_existing_tasks: bool = False,
) -> RouteAction:
    """Translate a SemanticIntentResult into an explicit RouteAction.

    Deterministic — no LLM calls.  Uses only the pre-computed semantic intent
    result and lightweight regex-based edit intent parsing.

    Args:
        semantic_intent: Result of classify_semantic_intent().
        query:           Raw user query string (for edit operand extraction).
        is_continuation: True when the frontend flagged this as an additive turn.

    Returns:
        RouteAction with action_type and whatever fields are directly derivable.
    """
    mode = semantic_intent.mode

    # ── Candidate resolution ──────────────────────────────────────────────────
    # User is selecting from a previously surfaced candidate list — leaf state,
    # no further classification needed.
    if mode == SemanticIntentMode.CANDIDATE_RESOLUTION:
        return RouteAction(action_type=ActionType.RESOLVE_CANDIDATE)

    # ── Continuation / along-route append ─────────────────────────────────────
    # Existing route context is a first-class signal here: with an active itinerary,
    # an along-route request should append a stop even without explicit "and/then".
    contextual_append = has_existing_tasks and _has_along_route_marker(query)
    if is_continuation or semantic_intent.along_route_append or contextual_append:
        return RouteAction(
            action_type=ActionType.APPEND_STOP,
            stop_query=_derive_append_stop_query(semantic_intent, query),
            constraints={"along_route": True},
        )

    # ── Edit / replace existing stop ─────────────────────────────────────────
    # Utterance matched an edit-intent pattern (insert_before, replace, remove).
    # Extract operands AND sub-operation here so downstream can dispatch without
    # re-parsing the query.  Sub-operation is stored in constraints["edit_op"].
    if mode == SemanticIntentMode.EDIT:
        target: Optional[str] = None
        replacement: Optional[str] = None
        edit_op: Optional[str] = None
        try:
            parsed_op, target, replacement = parse_edit_intent(query)
            if parsed_op != EditIntent.UNKNOWN:
                edit_op = parsed_op          # "replace" | "insert_before" | "remove"
            else:
                target = None
                replacement = None
        except Exception:
            pass  # operand extraction is best-effort; executor falls back to apply_edit
        return RouteAction(
            action_type=ActionType.REPLACE_STOP,
            target_query=target,
            replacement_query=replacement,
            # edit_op lets the executor dispatch to the right low-level function
            # without re-calling parse_edit_intent a second time.
            constraints={"edit_op": edit_op} if edit_op else None,
        )

    # ── Broad need → clarification required ───────────────────────────────────
    # The utterance names a domain (food / drink / clothes / shopping) but does
    # not give enough specificity to form a POI search query.
    if mode == SemanticIntentMode.BROAD_NEED:
        return RouteAction(
            action_type=ActionType.CLARIFY_MISSING_SLOT,
            domain=semantic_intent.category,   # e.g. "food", "drink", "shopping"
            missing_slot="type",               # in B1 the missing slot is always the subtype
            requires_candidate_selection=semantic_intent.delegation,
            requires_clarification=not semantic_intent.delegation,
        )

    # ── Direct destination (unique named place) ───────────────────────────────
    # Airport, castle, cathedral, etc. — high-confidence single-result venues.
    # No candidate selection needed; parser determines the exact destination name.
    if mode == SemanticIntentMode.DIRECT_DESTINATION:
        return RouteAction(action_type=ActionType.SET_DESTINATION)

    # ── Specific search (branded / non-unique destination or stop) ────────────
    # The utterance has a routing verb but references a non-unique place.
    # Two sub-cases:
    #   along_route_append (handled above via short-circuit), OR
    #   full destination like "Take me to McDonald's" where the parser will
    #   produce a destination task but candidate selection is still needed.
    if mode == SemanticIntentMode.SPECIFIC_SEARCH:
        if semantic_intent.search_text:
            # Explicit along-route text ("Starbucks on the way") — stop, needs selection
            return RouteAction(
                action_type=ActionType.APPEND_STOP,
                stop_query=semantic_intent.search_text,
                constraints={"along_route": True},
                requires_candidate_selection=True,
            )
        # Branded / non-unique destination ("Take me to McDonald's")
        return RouteAction(
            action_type=ActionType.SET_DESTINATION,
            requires_candidate_selection=True,
        )

    # ── Fallback ──────────────────────────────────────────────────────────────
    return RouteAction(action_type=ActionType.UNKNOWN)
