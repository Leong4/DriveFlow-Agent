"""
ActionIntent — explicit route operation layer (B1/B2).

Translates a SemanticIntentResult into a small set of inspectable RouteActions.
This layer sits between semantic intent classification and pre-route orchestration,
making the system's intermediate reasoning explicit and auditable.

Design boundaries:
  - Deterministic: no LLM calls, no I/O
  - Additive: does not replace semantic_intent or pre_route_filter
  - Minimal: exactly the action set needed for current scope — no speculative additions
  - Translucent: all fields are optional; downstream modules fill in what is missing

Category normalisation pipeline (B2/Phase 3):
  normalize_poi_category()          ← single entry point / LLM replacement boundary
    ├─ try_llm_normalize_poi_category()  ← LLM-assisted (Phase 2); None on any failure
    ├─ _canonicalize_llm_category()      ← strict canonical enforcement (Phase 3)
    │    rejects LLM output not in _CANONICAL_CATEGORIES → falls back to rules
    └─ _rule_normalize_poi_category()    ← rule-based fallback
         ├─ _detect_special_context()   ← idiom detection ("something for a friend")
         ├─ _strip_intent_frame()       ← remove leading verb frame ("I want", "find me", …)
         └─ _lookup_category_vocab()    ← canonical vocab lookup on the residual text
"""

import re
from typing import Optional

from pydantic import BaseModel

from app.services.category_normalizer import (
    CategoryNormalizationContext,
    try_llm_normalize_poi_category,
)
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


def _build_category_normalization_context(
    semantic_intent: SemanticIntentResult,
    query: str,
    *,
    has_existing_tasks: bool,
    is_continuation: bool,
) -> CategoryNormalizationContext:
    """Build the narrow advisory context allowed for Phase 5."""
    along_route = semantic_intent.along_route_append or _has_along_route_marker(query)
    append_like = has_existing_tasks and (is_continuation or along_route)
    return CategoryNormalizationContext(
        has_existing_route=has_existing_tasks,
        append_like=append_like,
        along_route=along_route,
    )


# ── Action type constants ─────────────────────────────────────────────────────

class ActionType:
    """Tightly bounded set of route operations for Step B1/B2.

    Intentionally small.  Adding a new action type here requires a matching
    handler in pre_route_service.py and a verified test case.
    """
    SET_DESTINATION      = "set_destination"      # establish or replace the final destination
    APPEND_STOP          = "append_stop"           # insert a stop along the current route
    REPLACE_STOP         = "replace_stop"          # swap an existing stop for another
    CLARIFY_MISSING_SLOT = "clarify_missing_slot"  # domain known; subtype slot not yet filled
    RESOLVE_CANDIDATE    = "resolve_candidate"     # in-progress POI selection — leaf state
    SEARCH_POI_CATEGORY  = "search_poi_category"  # B2: normalised category want (pharmacy/haircut/gift…)
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

    # B2: normalised POI category for search_poi_category actions
    # (e.g. "pharmacy", "hair salon", "gift shop")
    category: Optional[str] = None

    # meta — downstream can use these as routing hints
    requires_candidate_selection: bool = False    # True when a branch/location must be picked
    requires_clarification: bool = False          # True when a narrowing question must be asked


# ── B2: POI category normalisation ───────────────────────────────────────────
#
# Maps surface-form category keywords to canonical search strings.
# Deliberately small and explicit: new categories require one new entry here,
# not a new regex pattern.  Multi-word phrases are checked before single-word.
#
# Canonical values are recognised by pre_route_filter._VAGUE_TERMS (triggers
# clarification) or fall through to candidate_selection_needed.

_CATEGORY_VOCAB: dict[str, str] = {
    # food & drink
    "food": "restaurant",       "meal": "restaurant",
    "restaurant": "restaurant", "diner": "restaurant",
    "lunch": "restaurant",      "dinner": "restaurant",
    "breakfast": "cafe",        "eat": "restaurant",
    "coffee": "coffee shop",    "cafe": "coffee shop",
    "cafeteria": "coffee shop", "bubble tea": "bubble tea shop",
    "drink": "cafe",            "drinks": "cafe",
    # health
    "pharmacy": "pharmacy",     "chemist": "pharmacy",
    "drugstore": "pharmacy",    "drug store": "pharmacy",
    "medicine": "pharmacy",     "drugs": "pharmacy",
    # personal care
    "haircut": "hair salon",    "hairdresser": "hair salon",
    "barber": "barber shop",    "hair": "hair salon",
    "salon": "hair salon",      "nail": "nail salon",
    "nails": "nail salon",
    # shopping / gifts
    "gift": "gift shop",        "gifts": "gift shop",
    "present": "gift shop",     "presents": "gift shop",
    "souvenir": "souvenir shop","souvenirs": "souvenir shop",
    "clothes": "clothing store","clothing": "clothing store",
    "shopping": "shopping centre",
    "shopping centre": "shopping centre",
    "shopping mall": "shopping mall",
    "mall": "shopping mall",
    # multi-word category self-references (needed so _lookup_category_vocab can
    # return the canonical string when the residual text IS the category phrase,
    # e.g. "hair salon" residual after stripping a verb frame)
    "hair salon": "hair salon",         "gift shop": "gift shop",
    "souvenir shop": "souvenir shop",   "coffee shop": "coffee shop",
    "clothing store": "clothing store", "barber shop": "barber shop",
    "nail salon": "nail salon",
    # fuel / services
    "petrol": "petrol station", "fuel": "petrol station",
    "gas": "gas station",       "car wash": "car wash",
    "parking": "car park",      "atm": "ATM",
    "cash": "ATM",              "bank": "bank",
    # grocery
    "supermarket": "supermarket",
    "grocery": "supermarket",   "groceries": "supermarket",
    # hospitality
    "hotel": "hotel",           "accommodation": "hotel",
    # Chinese basics (BROAD_NEED covers most Chinese; these are extra safety)
    "药店": "pharmacy",         "药房": "pharmacy",
    "礼物": "gift shop",        "礼品": "gift shop",
    "纪念品": "souvenir shop",  "理发": "hair salon",
    "理发店": "hair salon",     "超市": "supermarket",
}

# Multi-word entries that must be matched before single-word fallback.
_MULTI_WORD_CATEGORIES: list[str] = [
    "bubble tea", "drug store", "car wash",
    "hair salon", "gift shop",  "souvenir shop",
    "coffee shop", "clothing store", "shopping centre", "shopping mall",
]

# Verb frame: "I want / I need / I'd like / I'm looking for ..."
# Strips the leading intent verb so the remainder is the category noun.
_WANT_FRAME_RE = re.compile(
    r"^(?:(?:and|also|then)\s+)?"
    r"(?:i\s+)?"
    r"(?:"
        r"want(?:\s+to\s+(?:buy|get|find|have))?"
        r"|need(?:\s+to\s+(?:buy|get|find|have))?"
        r"|'d\s+like"
        r"|would\s+like"
        r"|'m\s+looking\s+for"
        r"|am\s+looking\s+for"
    r")\s+"
    r"(?:(?:a|an|some|to\s+(?:buy|get|find|have))\s+)?",
    re.IGNORECASE,
)

# Verb frame: "find / get / show / recommend / go to / take me to ..."
_FIND_FRAME_RE = re.compile(
    r"^(?:(?:and|also|then)\s+)?"
    r"(?:"
        r"(?:find|get|show|recommend|suggest)(?:\s+me)?"
        r"|(?:take|drive|navigate)\s+me\s+to"
        r"|(?:go|head|drive|navigate)\s+to"
        r"|stop\s+at"
    r")\s+"
    r"(?:a|an|the|some|me\s+)?",
    re.IGNORECASE,
)

# Context pattern: "something for a friend/family" → gift shop
_GIFT_CONTEXT_RE = re.compile(
    r"\b(?:something|anything|a\s+gift|presents?|souvenirs?)\s+"
    r"(?:for|to\s+give(?:\s+to)?)\s+"
    r"(?:a\s+)?(?:friend|family|someone|my|the|him|her|them)\b",
    re.IGNORECASE,
)


def _strip_intent_frame(text: str) -> str:
    """Remove a leading intent verb frame and return the residual category noun.

    Handles two frame families:
      - Want frame: "I want", "I need", "I'd like", "I'm looking for", …
      - Find frame: "find me", "get me", "go to", "take me to", …

    # ── LLM replacement note ──────────────────────────────────────────────────
    # An LLM-backed normalize_poi_category would infer the category from the
    # full utterance and skip this step entirely.
    # ─────────────────────────────────────────────────────────────────────────
    """
    stripped = text.strip()
    for frame_re in (_WANT_FRAME_RE, _FIND_FRAME_RE):
        candidate = frame_re.sub("", stripped, count=1)
        if candidate != stripped:
            return candidate.strip(" ,.:!?")
    return stripped.strip(" ,.:!?")


def _detect_special_context(text: str) -> Optional[str]:
    """Return a category for narrow idioms not reducible to a single keyword.

    Currently supported:
      - "something/anything for a friend/family" → "gift shop"

    # ── LLM replacement note ──────────────────────────────────────────────────
    # An LLM-backed normalize_poi_category would resolve these implicitly.
    # ─────────────────────────────────────────────────────────────────────────
    """
    if _GIFT_CONTEXT_RE.search(text):
        return "gift shop"
    return None


def _lookup_category_vocab(text: str) -> Optional[str]:
    """Look up stripped text in the category vocabulary.

    Match priority: multi-word phrase → first single word → exact full text.

    # ── LLM replacement note ──────────────────────────────────────────────────
    # An LLM-backed normalize_poi_category would replace this lookup entirely.
    # ─────────────────────────────────────────────────────────────────────────
    """
    lower = text.lower().rstrip(" .!?,")
    if not lower:
        return None

    # Multi-word entries must be checked before single-word to avoid partial matches
    for phrase in _MULTI_WORD_CATEGORIES:
        if lower == phrase or lower.startswith(phrase + " ") or lower.startswith(phrase + "."):
            return _CATEGORY_VOCAB[phrase]

    # First-word match covers trailing noise ("haircut please", "pharmacy nearby", …)
    first_word = lower.split()[0] if lower.split() else ""
    if first_word in _CATEGORY_VOCAB:
        return _CATEGORY_VOCAB[first_word]

    return _CATEGORY_VOCAB.get(lower)


def _rule_normalize_poi_category(query: str) -> Optional[str]:
    """Rule-based category normalization pipeline (Phase 1).

    Used as the fallback when LLM normalization is unavailable or unconfident.
    Three steps in order:
      1. _detect_special_context — idioms not reducible to one keyword
      2. _strip_intent_frame      — remove outer request verb frame
      3. _lookup_category_vocab   — canonical vocab lookup on the residual
    """
    result = _detect_special_context(query)
    if result:
        return result
    residual = _strip_intent_frame(query)
    return _lookup_category_vocab(residual)


# ── Phase 3: canonical category enforcement ───────────────────────────────────
#
# Exactly the set of strings that _CATEGORY_VOCAB produces.  Any LLM output
# that cannot be mapped into this set is rejected (→ None) so the rule-based
# fallback pipeline takes over.  Add new entries here only when _CATEGORY_VOCAB
# is updated to produce them.

_CANONICAL_CATEGORIES: frozenset[str] = frozenset({
    # food & drink
    "restaurant", "cafe", "coffee shop", "bubble tea shop",
    # health
    "pharmacy",
    # personal care
    "hair salon", "barber shop", "nail salon",
    # shopping / gifts
    "gift shop", "souvenir shop", "clothing store",
    "shopping centre", "shopping mall",
    # fuel / services
    "petrol station", "gas station", "car wash", "car park", "ATM", "bank",
    # grocery / hospitality
    "supermarket", "hotel",
})

# LLM-specific surface variants not in _CATEGORY_VOCAB but mappable to a canonical.
# Keep this list small and explicit — it is NOT a free-text alias expansion.
_LLM_ALIAS_MAP: dict[str, str] = {
    "café":            "coffee shop",
    "coffee bar":      "coffee shop",
    "beauty salon":    "hair salon",
    "chemists":        "pharmacy",
    "grocery shop":    "supermarket",
    "grocery store":   "supermarket",
    "gas station":     "gas station",
    "petrol station":  "petrol station",
    "car park":        "car park",
    "atm":             "ATM",
}


def _canonicalize_llm_category(raw: str) -> Optional[str]:
    """Map an LLM-produced category string to a stable canonical value.

    Phase 3: strict canonicalization — only strings that map into
    _CANONICAL_CATEGORIES are accepted.  Anything else returns None so that
    normalize_poi_category falls back to the rule-based pipeline.

    Lookup order:
      1. _lookup_category_vocab — covers all _CATEGORY_VOCAB surface forms
      2. _LLM_ALIAS_MAP         — covers LLM-specific variants not in vocab
      3. None                   — unknown string; trigger rule fallback
    """
    if not raw:
        return None
    lower = raw.strip().lower()

    result = _lookup_category_vocab(lower)
    if result and result in _CANONICAL_CATEGORIES:
        return result

    aliased = _LLM_ALIAS_MAP.get(lower)
    if aliased and aliased in _CANONICAL_CATEGORIES:
        return aliased

    # Unknown category — reject and let rule pipeline decide
    return None


async def normalize_poi_category(
    query: str,
    *,
    context: Optional[CategoryNormalizationContext] = None,
) -> Optional[str]:
    """Normalize a raw user query to a canonical POI category string.

    Single entry point and LLM replacement boundary (Phase 2).

    Pipeline:
      1. try_llm_normalize_poi_category — LLM-assisted normalization (Phase 2)
         Returns None on any failure, missing credentials, or low confidence.
      2. _canonicalize_llm_category     — strict canonical enforcement (Phase 3)
         Rejects LLM output not in _CANONICAL_CATEGORIES → returns None → fallback.
      3. _rule_normalize_poi_category   — Phase 1 rule-based fallback

    Returns the canonical category (e.g. "pharmacy", "hair salon", "gift shop")
    or None if the query does not express a recognisable POI category want.

    # ── Replacement boundary ──────────────────────────────────────────────────
    # To migrate to a full function-calling normalizer, replace this function's
    # body.  No other file needs to change.
    # ─────────────────────────────────────────────────────────────────────────
    """
    # Phase 2: LLM-assisted normalization (graceful fallback on any failure)
    llm_raw = await try_llm_normalize_poi_category(query, context=context)
    if llm_raw is not None:
        return _canonicalize_llm_category(llm_raw)

    # Phase 1 fallback: deterministic rule-based pipeline
    return _rule_normalize_poi_category(query)


# ── Classifier ───────────────────────────────────────────────────────────────

async def classify_route_action(
    semantic_intent: SemanticIntentResult,
    query: str,
    *,
    is_continuation: bool = False,
    has_existing_tasks: bool = False,
) -> RouteAction:
    """Translate a SemanticIntentResult into an explicit RouteAction.

    All action classification is deterministic except for category normalization
    (SPECIFIC_SEARCH / UNKNOWN paths), which may call the LLM via normalize_poi_category.
    Every other branch — candidate resolution, edit, append, set_destination — is
    fully rule-based and never touches the LLM.

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
    # Airport, castle, cathedral, etc. — high-confidence named venues.
    # Confirmation is still required before route commitment so the user can
    # verify the system resolved the correct location.
    if mode == SemanticIntentMode.DIRECT_DESTINATION:
        return RouteAction(action_type=ActionType.SET_DESTINATION, requires_candidate_selection=True)

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
        # B2: before assuming SET_DESTINATION, try to extract a category.
        # "Find a pharmacy" should become search_poi_category, not set_destination.
        # "Find McDonald's" → category extractor returns None → falls through to SET_DESTINATION.
        category_context = _build_category_normalization_context(
            semantic_intent,
            query,
            has_existing_tasks=has_existing_tasks,
            is_continuation=is_continuation,
        )
        category = await normalize_poi_category(query, context=category_context)
        if category:
            return RouteAction(
                action_type=ActionType.SEARCH_POI_CATEGORY,
                category=category,
                stop_query=category,
                constraints={"append_to_existing": True} if has_existing_tasks else None,
                requires_candidate_selection=semantic_intent.delegation,
                requires_clarification=not semantic_intent.delegation,
            )
        # Branded / non-unique destination ("Take me to McDonald's")
        return RouteAction(
            action_type=ActionType.SET_DESTINATION,
            requires_candidate_selection=True,
        )

    # ── Fallback ──────────────────────────────────────────────────────────────
    # B2: before giving up, try vocabulary-based category extraction.
    # Catches UNKNOWN-mode queries like "I need a pharmacy", "I want a haircut",
    # "Get me a souvenir" that have no routing verb but express a clear category want.
    category_context = _build_category_normalization_context(
        semantic_intent,
        query,
        has_existing_tasks=has_existing_tasks,
        is_continuation=is_continuation,
    )
    category = await normalize_poi_category(query, context=category_context)
    if category:
        return RouteAction(
            action_type=ActionType.SEARCH_POI_CATEGORY,
            category=category,
            stop_query=category,
            constraints={"append_to_existing": True} if has_existing_tasks else None,
            requires_candidate_selection=semantic_intent.delegation,
            requires_clarification=not semantic_intent.delegation,
        )
    return RouteAction(action_type=ActionType.UNKNOWN)
