"""
SemanticIntent — lightweight utterance framing before structured task generation.

This is intentionally narrow and deterministic. It does not replace the parser.
It only classifies the raw query into a small set of high-level intent modes so
the existing pre-route service can route broad conversational needs more cleanly.
"""

import re
from typing import Optional

from pydantic import BaseModel

from app.services.itinerary_editor import EditIntent, parse_edit_intent


class SemanticIntentMode:
    BROAD_NEED = "broad_need"
    SPECIFIC_SEARCH = "specific_search"
    DIRECT_DESTINATION = "direct_destination"
    EDIT = "edit"
    CANDIDATE_RESOLUTION = "candidate_resolution"
    UNKNOWN = "unknown"


class SemanticIntentResult(BaseModel):
    mode: str
    category: Optional[str] = None
    delegation: bool = False
    search_text: Optional[str] = None
    along_route_append: bool = False


_DELEGATION_RE = re.compile(
    r"\banything\b"
    r"|\bwhatever\b"
    r"|\banywhere\b"
    r"|\bsomewhere\b"
    r"|\bjust find\b"
    r"|\brecommend\b"
    r"|\bsuggest\b"
    r"|\bis fine\b"
    r"|\bworks for me\b"
    r"|\bwill do\b"
    r"|\bsomething.*?on the way\b"
    r"|随便|什么都行|帮我找|推荐|建议",
    re.IGNORECASE | re.DOTALL,
)

_BROAD_NEED_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\bi\s+want\s+to\s+eat(?:\s+something)?\b"
            r"|\bi(?:'m| am)\s+hungry\b"
            r"|\bneed\s+(?:some\s+)?food\b"
            r"|\b(?:find|want)\s+(?:anything|something)\s+to\s+eat\b"
            r"|\b(?:find|get|give)\s+(?:me\s+)?(?:something|anything)\s+to\s+eat\b"
            r"|\b(?:just\s+)?(?:recommend|suggest|give|find)\s+(?:me\s+)?(?:somewhere|some place|a place)\s+(?:for\s+food|to\s+eat)\b"
            r"|\b(?:anywhere|somewhere)\s+(?:for\s+food|to\s+eat)\s+(?:is\s+fine|is\s+okay|works|will\s+do)\b"
            r"|想吃(?:点|些|东西)?|我饿了"
            r"|(?:随便|推荐|给我推荐|帮我找|找个|找一家).{0,8}(?:吃饭的地方|吃的地方|餐厅|饭店)",
            re.IGNORECASE,
        ),
        "eat",
    ),
    (
        re.compile(
            r"\bi\s+want\s+(?:a\s+)?drink\b"
            r"|\bi(?:'m| am)\s+thirsty\b"
            r"|\b(?:find|want)\s+(?:anything|something)\s+to\s+drink\b"
            r"|\b(?:find|get|give)\s+(?:me\s+)?(?:something|anything)\s+to\s+drink\b"
            r"|\b(?:just\s+)?(?:recommend|suggest|give|find)\s+(?:me\s+)?(?:somewhere|some place|a place)\s+(?:for\s+(?:a\s+)?drink|to\s+drink|for\s+coffee)\b"
            r"|\b(?:anywhere|somewhere)\s+(?:for\s+drinks?|to\s+drink)\s+(?:is\s+fine|is\s+okay|works|will\s+do)\b"
            r"|想喝(?:点|些|东西)?|我渴了"
            r"|(?:随便|推荐|给我推荐|帮我找|找个|找一家).{0,8}(?:咖啡店|奶茶店|饮品店|喝的地方)",
            re.IGNORECASE,
        ),
        "drink",
    ),
    (
        re.compile(
            r"\bi\s+want\s+to\s+buy\s+clothes\b"
            r"|\bneed\s+clothes\b"
            r"|想买衣服|买衣服|想买点衣服",
            re.IGNORECASE,
        ),
        "clothes",
    ),
    # Vague shopping / gift intent — specific enough to ask for clarification
    # but too vague to geocode directly (e.g. "buy something for a friend").
    # Does NOT match specific purchases like "buy a Starbucks coffee".
    (
        re.compile(
            r"\bi\s+want\s+to\s+buy\s+something\b"
            r"|\bi\s+(?:want\s+to|need\s+to)\s+(?:buy|get|find)\s+(?:a\s+)?(?:gift|present|souvenir)\b"
            r"|\bi\s+(?:want|need)\s+(?:a\s+)?(?:gift|present|souvenir)\b"
            r"|\bbuy\s+(?:a\s+)?(?:gift|present|souvenir)\b"
            r"|想买点东西|想买个礼物|想买个礼品|买礼物|买礼品",
            re.IGNORECASE,
        ),
        "shopping",
    ),
]

_UNIQUE_DESTINATION_RE = re.compile(
    r"\b(?:airport|airfield|terminal|castle|cathedral|abbey|palace|parliament)\b"
    r"|机场|城堡|大教堂|宫殿|议会",
    re.IGNORECASE,
)

_ROUTING_VERB_RE = re.compile(
    r"\b(?:take me to|go to|drive to|navigate to|head to|stop at|find)\b"
    r"|去|到|带我去|导航到|找",
    re.IGNORECASE,
)

_EN_ALONG_ROUTE_RE = re.compile(
    r"^\s*(?P<term>.+?)\s+(?:on|along)\s+the\s+way\b[\s.!?]*$",
    re.IGNORECASE,
)

_ZH_ALONG_ROUTE_RE = re.compile(
    r"^\s*(?:路上|顺路)\s*(?:去|到|找)?\s*(?:个|家|一下)?\s*(?P<term>.+?)\s*(?:吧|啊|呀|啦)?\s*$",
    re.IGNORECASE,
)

_LEADING_ACTION_RE = re.compile(
    r"^(?:(?:and|then|also)\s+)?(?:find|go|drive|navigate|head|stop|take)\b"
    r"|^(?:去|到|找|带我去|导航到)",
    re.IGNORECASE,
)


def _extract_along_route_append_query(query: str) -> Optional[str]:
    """Return the stop search text for short along-route append utterances."""
    for pattern in (_EN_ALONG_ROUTE_RE, _ZH_ALONG_ROUTE_RE):
        match = pattern.match(query)
        if not match:
            continue
        term = (match.group("term") or "").strip(" ,，。.!?")
        if term and not _LEADING_ACTION_RE.search(term):
            return term
    return None


def classify_semantic_intent(
    query: str,
    *,
    has_existing_tasks: bool = False,
    has_selected_candidate: bool = False,
) -> SemanticIntentResult:
    """Classify the utterance into a tiny set of demo-safe semantic modes."""
    if has_selected_candidate and has_existing_tasks:
        return SemanticIntentResult(mode=SemanticIntentMode.CANDIDATE_RESOLUTION)

    if has_existing_tasks:
        edit_intent, _, _ = parse_edit_intent(query)
        if edit_intent != EditIntent.UNKNOWN:
            return SemanticIntentResult(mode=SemanticIntentMode.EDIT)

        along_route_query = _extract_along_route_append_query(query)
        if along_route_query:
            return SemanticIntentResult(
                mode=SemanticIntentMode.SPECIFIC_SEARCH,
                search_text=along_route_query,
                along_route_append=True,
            )

    delegation = bool(_DELEGATION_RE.search(query))

    for pattern, category in _BROAD_NEED_PATTERNS:
        if pattern.search(query):
            return SemanticIntentResult(
                mode=SemanticIntentMode.BROAD_NEED,
                category=category,
                delegation=delegation,
            )

    if _ROUTING_VERB_RE.search(query):
        if _UNIQUE_DESTINATION_RE.search(query):
            return SemanticIntentResult(mode=SemanticIntentMode.DIRECT_DESTINATION)
        return SemanticIntentResult(
            mode=SemanticIntentMode.SPECIFIC_SEARCH,
            delegation=delegation,
        )

    return SemanticIntentResult(mode=SemanticIntentMode.UNKNOWN, delegation=delegation)
