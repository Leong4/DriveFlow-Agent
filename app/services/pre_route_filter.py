"""
Pre-route filter: classify parsed tasks before graph building begins.

Three decision outcomes:
  "clarification_needed"       – intent too broad; ask one narrowing question
  "candidate_selection_needed" – specific enough to search; surface options for user
  "ready_for_routing"          – no stop tasks need attention; proceed normally

Rules are deterministic and inspectable — no LLM calls.
"""

import re
from typing import Optional
from pydantic import BaseModel
from app.models.task import Task


# ── Generic terms that cannot map to a specific POI ──────────────────────────
# A stop task whose query/label/original_text matches one of these (with no brand)
# is considered too vague to route — user must narrow down first.
_VAGUE_TERMS: frozenset = frozenset({
    # English — food
    "food", "eat", "eating", "restaurant", "dining", "meal",
    "lunch", "dinner", "breakfast",
    # English — drink
    "drink", "drinks", "cafe", "cafeteria",
    # English — clothes
    "clothes", "clothing", "fashion",
    # English — shopping (generic)
    "shopping", "shop", "store", "retail",
    "gift", "gift shop", "present", "souvenir",  # vague gift purchase
    # English — services
    "pharmacy", "medicine", "drug store", "chemist",
    # Parser fallback
    "point of interest",
    # Chinese — food
    "吃", "吃饭", "吃东西", "餐厅", "饭店",
    # Chinese — drink
    "喝", "喝东西", "咖啡", "奶茶", "茶",
    # Chinese — shopping
    "购物", "买东西", "买衣服", "衣服",
    "礼物", "礼品", "纪念品",
    # Chinese — services
    "药店", "药房",
})

# ── Delegation patterns — user is happy for the system to choose ──────────────
_DELEGATION_RE = re.compile(
    r"\banything\b"
    r"|\bwhatever\b"
    r"|\banywhere\b"
    r"|\bsomewhere\b"
    r"|\bjust find\b"
    r"|\bjust.*?something\b"
    r"|\brecommend\b"
    r"|\bsuggest\b"
    r"|\bis fine\b"
    r"|\bworks for me\b"
    r"|\bwill do\b"
    r"|\bany\b.{0,20}\bway\b"
    r"|\bsomething.*?on the way\b"
    r"|随便|什么都行|帮我找|推荐|建议",
    re.IGNORECASE | re.DOTALL,
)

# ── Unique / high-confidence venue words ─────────────────────────────────────
# If a stop task's query contains one of these as a whole word (and has no brand),
# it is treated as a specific named place that maps to a single dominant result,
# so the pre-route filter lets it pass through to normal routing.
#
# Deliberately narrow: only types that are truly singular in a geographic area.
# Do NOT include: museum, hospital, university, hotel, theatre — those can have
# many branches in a city and should still surface candidates.
_UNIQUE_PLACE_RE = re.compile(
    r"\b(?:"
    r"airport|airfield|terminal"
    r"|castle|castles"
    r"|cathedral|cathedrals"
    r"|abbey|abbeys"
    r"|palace|palaces"
    r"|parliament"
    r")\b"
    r"|机场|城堡|大教堂|宫殿|议会",
    re.IGNORECASE,
)

# ── One narrowing question per vague term ─────────────────────────────────────
_CLARIFICATION_MAP: dict = {
    "food":             "What type of food are you looking for?",
    "eat":              "What type of food are you looking for?",
    "eating":           "What type of food are you looking for?",
    "restaurant":       "What type of cuisine? (e.g. fast food, Chinese, Italian)",
    "dining":           "What type of cuisine? (e.g. fast food, Chinese, Italian)",
    "meal":             "What type of food are you looking for?",
    "lunch":            "Any specific cuisine or restaurant in mind?",
    "dinner":           "Any specific cuisine or restaurant in mind?",
    "breakfast":        "Any specific café or restaurant in mind?",
    "drink":            "Coffee, bubble tea, or something else?",
    "drinks":           "Coffee, bubble tea, or something else?",
    "cafe":             "Any specific brand? (e.g. Starbucks, Costa, Caffe Nero)",
    "cafeteria":        "Any specific brand? (e.g. Starbucks, Costa, Caffe Nero)",
    "clothes":          "Brand store or a shopping centre?",
    "clothing":         "Brand store or a shopping centre?",
    "fashion":          "Any specific brand or a general shopping centre?",
    "shopping":         "What type of shop are you looking for?",
    "shop":             "What type of shop are you looking for?",
    "store":            "What type of store are you looking for?",
    "retail":           "What type of shop are you looking for?",
    "pharmacy":         "Any preferred pharmacy? (e.g. Boots, Lloyds)",
    "medicine":         "Any preferred pharmacy? (e.g. Boots, Lloyds)",
    "drug store":       "Any preferred pharmacy? (e.g. Boots, Lloyds)",
    "chemist":          "Any preferred pharmacy? (e.g. Boots, Lloyds)",
    "gift":             "What type of gift are you looking for? (e.g. clothing, books, electronics)",
    "gift shop":        "What type of gift are you looking for? (e.g. clothing, books, electronics)",
    "present":          "What type of gift are you looking for? (e.g. clothing, books, electronics)",
    "souvenir":         "Any specific type of souvenir? (e.g. local crafts, clothing, food)",
    "point of interest":"What are you specifically looking for?",
    # Chinese
    "吃":     "您想吃什么类型的食物？",
    "吃饭":   "您想吃什么类型的食物？",
    "吃东西": "您想吃什么类型的食物？",
    "餐厅":   "您偏好哪种菜系？（如中餐、西餐、快餐）",
    "饭店":   "您偏好哪种菜系？（如中餐、西餐、快餐）",
    "喝":     "想喝咖啡还是奶茶？",
    "喝东西": "想喝咖啡还是奶茶？",
    "咖啡":   "有偏好的咖啡品牌吗？（如星巴克）",
    "奶茶":   "有偏好的奶茶品牌吗？",
    "茶":     "想去咖啡馆还是奶茶店？",
    "购物":   "想去哪类商店？",
    "买东西": "想买什么类型的东西？",
    "买衣服": "有偏好的品牌，或者去购物中心？",
    "衣服":   "有偏好的品牌，或者去购物中心？",
    "药店":   "有偏好的药店品牌吗？",
    "药房":   "有偏好的药店品牌吗？",
    "礼物":   "您想买什么类型的礼物？（如服装、书籍、电子产品）",
    "礼品":   "您想买什么类型的礼品？（如服装、书籍、电子产品）",
    "纪念品": "您想要什么类型的纪念品？（如工艺品、服装、食品）",
}

_DEFAULT_CLARIFICATION = "Could you be more specific about what you're looking for?"

# ── Domain classification for follow-up interpreter ───────────────────────────
_DOMAIN_MAP: dict = {
    "food": {"eat", "eating", "meal", "lunch", "dinner", "breakfast", "restaurant", "dining",
             "吃", "吃饭", "吃东西", "餐厅", "饭店"},
    "drink": {"drink", "drinks", "cafe", "cafeteria",
              "喝", "喝东西", "咖啡", "奶茶", "茶"},
    "clothes": {"clothes", "clothing", "fashion", "买衣服", "衣服"},
    "shopping": {"shopping", "shop", "store", "retail", "gift", "gift shop", "present", "souvenir",
                 "购物", "买东西", "礼物", "礼品", "纪念品"},
    "pharmacy": {"pharmacy", "medicine", "drug store", "chemist", "药店", "药房"},
}


# ── Public result type ────────────────────────────────────────────────────────

class PreRouteDecision(BaseModel):
    """Result of the pre-route classification step.

    status values:
      "clarification_needed"       – return question to user, do not build route yet
      "candidate_selection_needed" – fetch and surface POI candidates for user choice
      "ready_for_routing"          – proceed to graph building as normal
    """
    status: str
    question: Optional[str] = None        # narrowing question (clarification_needed)
    trigger_task_id: Optional[str] = None # task.id that triggered this decision
    candidate_query: Optional[str] = None # search text for candidate POI lookup
    is_delegation: bool = False           # user explicitly delegated the choice
    clarification_domain: Optional[str] = None  # semantic domain for follow-up interpreter


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_delegation(query: str) -> bool:
    """Return True if the query delegates POI choice to the system."""
    return bool(_DELEGATION_RE.search(query))


def _stop_terms(task: Task) -> tuple:
    """Extract (label, query, original_text) from task payload, all lowercased."""
    p = task.payload or {}
    return (
        (p.get("label") or "").lower().strip(),
        (p.get("query") or "").lower().strip(),
        (p.get("original_text") or "").lower().strip(),
    )


def _is_vague_stop(task: Task) -> bool:
    """True if the stop has no brand and only a generic category term."""
    if task.type not in {"stop", "restaurant"}:
        return False
    p = task.payload or {}
    # A brand at any level makes it specific enough to search
    if p.get("brand") or task.brand:
        return False
    label, query, original = _stop_terms(task)
    return any(t in _VAGUE_TERMS for t in (label, query, original) if t)


def _get_clarification_question(task: Task) -> str:
    """Return the single narrowing question for a vague stop task."""
    label, query, original = _stop_terms(task)
    # Prefer the original user text as the lookup key
    for term in (original, label, query):
        if term in _CLARIFICATION_MAP:
            return _CLARIFICATION_MAP[term]
    return _DEFAULT_CLARIFICATION


def _get_clarification_domain(task: Task) -> str:
    """Return the semantic domain string for the follow-up interpreter."""
    label, query, original = _stop_terms(task)
    for term in (original, label, query):
        for domain, terms in _DOMAIN_MAP.items():
            if term in terms:
                return domain
    return "generic"


def _get_candidate_query(task: Task) -> str:
    """Return the best search string for a stop task."""
    p = task.payload or {}
    return (
        p.get("query")
        or p.get("brand")
        or p.get("label")
        or task.brand
        or task.name
        or "nearby point of interest"
    )


def _is_unique_named_place(task: Task) -> bool:
    """True if the stop query references a clearly singular venue.

    Singular venues (airports, castles, cathedrals …) produce a dominant
    single Google result and do not need candidate selection.
    A brand overrides this check — branded chains are never unique-singular.
    """
    if task.type not in {"stop", "restaurant"}:
        return False
    p = task.payload or {}
    # Any brand means it is a chain → multiple locations → not unique
    if p.get("brand") or task.brand:
        return False
    label, query, original = _stop_terms(task)
    combined = f"{label} {query} {original}"
    return bool(_UNIQUE_PLACE_RE.search(combined))


# ── Public API ────────────────────────────────────────────────────────────────

def classify_tasks(tasks: list, raw_query: str) -> PreRouteDecision:
    """
    Classify parsed tasks and return the pre-route action.

    Decision hierarchy per stop task (in order):
      1. Vague + no delegation  → clarification_needed (ask one question)
      2. Vague + delegation     → candidate_selection_needed (recommend options)
      3. Unique named place     → skip (continue to next task; treat as ready)
      4. Brand / chain / specific category → candidate_selection_needed (user picks)

    Destination and charging_station tasks are transparent to this filter.
    Only the first stop task that triggers action is acted upon; subsequent
    stop tasks in the same query are deferred to future turns.

    Args:
        tasks:     List of Task objects from intent_parser.
        raw_query: Original user query string (delegation detection).

    Returns:
        PreRouteDecision with status and supporting metadata.
    """
    delegation = _is_delegation(raw_query)

    for task in tasks:
        if task.type not in {"stop", "restaurant"}:
            continue

        if _is_vague_stop(task):
            if delegation:
                # User delegated: surface recommendations, skip the question
                return PreRouteDecision(
                    status="candidate_selection_needed",
                    trigger_task_id=task.id,
                    candidate_query=_get_candidate_query(task),
                    is_delegation=True,
                )
            # Broad intent: ask exactly one narrowing question
            return PreRouteDecision(
                status="clarification_needed",
                question=_get_clarification_question(task),
                trigger_task_id=task.id,
                clarification_domain=_get_clarification_domain(task),
            )

        if _is_unique_named_place(task):
            # High-confidence singular venue — no intervention needed.
            # Continue checking remaining tasks rather than returning immediately.
            continue

        # Brand chain or specific-category stop (e.g. "fried chicken", "Starbucks"):
        # likely has multiple nearby candidates → surface them for user selection.
        return PreRouteDecision(
            status="candidate_selection_needed",
            trigger_task_id=task.id,
            candidate_query=_get_candidate_query(task),
            is_delegation=delegation,
        )

    # All tasks either non-stop or unique-named → proceed directly.
    return PreRouteDecision(status="ready_for_routing")
