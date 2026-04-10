"""
ClarificationFollowup — LLM-assisted follow-up interpreter.

Narrow bounded role: given a pending clarification context and the user's reply,
decide whether the reply is a follow-up answer and extract a search_query string
suitable for Google Places. Does NOT choose POIs or modify routing.

Fails gracefully: on any error, returns is_followup_answer=False so the normal
parse path handles the query.
"""

import json
import logging
from typing import Optional

from pydantic import BaseModel

from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a query resolver for a navigation assistant. You receive a JSON object with:
- domain: the semantic domain of the original vague request (food | drink | clothes | shopping | pharmacy | generic)
- question_asked: the clarification question that was shown to the user
- original_query: the user's original vague query
- user_reply: the user's follow-up message

Your ONLY job: decide if user_reply answers the clarification question, and if so,
produce a short English search_query string suitable for Google Places API.

Rules:
1. If the reply is a navigation command unrelated to the pending clarification
   (e.g. "Take me to the airport", "Navigate to London"), set is_followup_answer=false.
2. If the reply is an entirely new unrelated request that clearly contradicts the domain
   (e.g. "I want to buy shoes" when domain=food), set is_followup_answer=false.
3. If the reply narrows or answers the clarification question — even partially, in any
   language, or with a brief phrase — set is_followup_answer=true.
4. For domain=shopping: replies like "hiking gear", "outdoor gear", "something for a
   friend", "a gift", "electronics", "books" are valid answers. Map them to a useful
   English Google Places search_query.
5. search_query must be a short, precise English phrase (2-6 words) for Google Places.
   Never include city names or "near me".
6. resolved_subtype is a brief English label of the specific type chosen.
7. delegation=true if the user implies the system should choose
   (e.g. "anything", "whatever", "you pick", "随便", "无所谓").

Output ONLY valid JSON matching this exact schema (no markdown, no extra text):
{
  "is_followup_answer": boolean,
  "resolved_domain": string | null,
  "resolved_subtype": string | null,
  "search_query": string | null,
  "delegation": boolean,
  "next_action_hint": "candidate_selection" | "clarification" | "ready_for_routing"
}

Examples:

Input: {"domain":"food","question_asked":"What type of food are you looking for?","original_query":"I want to eat","user_reply":"汉堡"}
Output: {"is_followup_answer":true,"resolved_domain":"food","resolved_subtype":"burger","search_query":"burger restaurant","delegation":false,"next_action_hint":"candidate_selection"}

Input: {"domain":"clothes","question_asked":"Brand store or a shopping centre?","original_query":"I want to buy clothes","user_reply":"品牌店"}
Output: {"is_followup_answer":true,"resolved_domain":"clothes","resolved_subtype":"brand clothing store","search_query":"brand clothing store","delegation":false,"next_action_hint":"candidate_selection"}

Input: {"domain":"drink","question_asked":"Coffee, bubble tea, or something else?","original_query":"I want a drink","user_reply":"奶茶"}
Output: {"is_followup_answer":true,"resolved_domain":"drink","resolved_subtype":"bubble tea","search_query":"bubble tea shop","delegation":false,"next_action_hint":"candidate_selection"}

Input: {"domain":"drink","question_asked":"Coffee, bubble tea, or something else?","original_query":"I want a drink","user_reply":"coffee"}
Output: {"is_followup_answer":true,"resolved_domain":"drink","resolved_subtype":"coffee","search_query":"coffee shop","delegation":false,"next_action_hint":"candidate_selection"}

Input: {"domain":"food","question_asked":"What type of food are you looking for?","original_query":"I want to eat","user_reply":"anything is fine"}
Output: {"is_followup_answer":true,"resolved_domain":"food","resolved_subtype":null,"search_query":"restaurant","delegation":true,"next_action_hint":"candidate_selection"}

Input: {"domain":"shopping","question_asked":"What are you looking for? (e.g. a gift, outdoor gear, electronics)","original_query":"I want to buy something for a friend","user_reply":"hiking gear"}
Output: {"is_followup_answer":true,"resolved_domain":"shopping","resolved_subtype":"hiking gear","search_query":"outdoor sports store hiking gear","delegation":false,"next_action_hint":"candidate_selection"}

Input: {"domain":"shopping","question_asked":"What type of gift are you looking for?","original_query":"I want to buy a gift","user_reply":"something for my friend"}
Output: {"is_followup_answer":true,"resolved_domain":"shopping","resolved_subtype":"gift","search_query":"gift shop","delegation":false,"next_action_hint":"candidate_selection"}

Input: {"domain":"shopping","question_asked":"What are you looking for?","original_query":"I want to buy something","user_reply":"电子产品"}
Output: {"is_followup_answer":true,"resolved_domain":"shopping","resolved_subtype":"electronics","search_query":"electronics store","delegation":false,"next_action_hint":"candidate_selection"}

Input: {"domain":"shopping","question_asked":"What type of gift are you looking for?","original_query":"I want to buy a gift","user_reply":"anything will do"}
Output: {"is_followup_answer":true,"resolved_domain":"shopping","resolved_subtype":null,"search_query":"gift shop","delegation":true,"next_action_hint":"candidate_selection"}

Input: {"domain":"food","question_asked":"What type of food are you looking for?","original_query":"I want to eat","user_reply":"Navigate to Heathrow Airport"}
Output: {"is_followup_answer":false,"resolved_domain":null,"resolved_subtype":null,"search_query":null,"delegation":false,"next_action_hint":"candidate_selection"}
"""


class ClarificationContext(BaseModel):
    domain: str           # "food" | "drink" | "clothes" | "shopping" | "pharmacy" | "generic"
    question_asked: str   # exact question shown to user
    original_query: str   # the vague query that triggered clarification


class FollowupInterpretation(BaseModel):
    is_followup_answer: bool
    resolved_domain: Optional[str] = None
    resolved_subtype: Optional[str] = None
    search_query: Optional[str] = None
    delegation: bool = False
    next_action_hint: str = "candidate_selection"


async def interpret_clarification_followup(
    user_reply: str,
    context: ClarificationContext,
) -> FollowupInterpretation:
    """
    Ask the LLM whether user_reply answers the pending clarification question.
    On any failure, returns is_followup_answer=False so normal parse takes over.
    """
    try:
        client = LLMClient()
        user_msg = json.dumps({
            "domain": context.domain,
            "question_asked": context.question_asked,
            "original_query": context.original_query,
            "user_reply": user_reply,
        }, ensure_ascii=False)

        raw = await client.chat([
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ])

        # Strip markdown fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            cleaned = parts[1] if len(parts) > 1 else cleaned
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()

        parsed = json.loads(cleaned)
        return FollowupInterpretation(**parsed)

    except Exception as exc:
        logger.warning("clarification_followup LLM failed: %s", exc)
        return FollowupInterpretation(is_followup_answer=False)
