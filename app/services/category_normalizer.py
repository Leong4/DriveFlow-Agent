"""
CategoryNormalizer — LLM-assisted POI category normalization.

Narrow scope: given a raw user query, decide if it expresses a category-of-place
want, and if so, return the raw (un-canonicalized) category string.

Role:
  - Only identifies categories; does NOT choose route action types
  - Returns None on any failure so the caller always has a safe fallback
  - Used exclusively as a backing implementation for normalize_poi_category()
    in action_intent.py — do not call from anywhere else

Fallback contract:
  A None return means "I don't know / I failed"; the caller must fall back to the
  rule-based pipeline.  This function must never raise.

Structured-output contract (Phase 4):
  The LLM call uses response_format={"type": "json_object"} so the provider
  guarantees a single valid JSON object in its response — no markdown fences,
  no surrounding prose.  The result is validated with Pydantic model_validate
  (schema enforcement).  Any deviation — invalid JSON, schema mismatch, missing
  field — triggers the fallback exactly as before.
"""

import json
import logging
import os
from typing import Optional

from pydantic import BaseModel

from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────
# Tightly constrained to a single task: is-category? and if so, which?
# Deliberately excludes route action types, POI selection, and ordering logic.

_SYSTEM_PROMPT = """\
You are a category classifier for a navigation assistant.

Your ONLY task: decide if the user's message is asking to stop at a type or category
of place, and if so, return the canonical category name.

The user is in a car. They may phrase category requests in many ways.
You may also receive a tiny advisory route-context object with:
  - has_existing_route
  - append_like
  - along_route
This context is advisory only. It may help interpret whether a message is about a
category-like stop request, but you must NOT infer or output route actions from it.

Category request examples with their canonical category values:
  "I need a pharmacy"                  → pharmacy
  "I want a haircut"                   → hair salon
  "Get me a souvenir"                  → souvenir shop
  "Find something for a friend"        → gift shop
  "I'm looking for a coffee shop"      → coffee shop
  "I need a drug store"                → pharmacy
  "Find me somewhere to eat"           → restaurant
  "I need petrol"                      → petrol station
  "Find me a barber"                   → barber shop
  "I need to do some grocery shopping" → supermarket
  "I want to buy some clothes"         → clothing store
  "Find me a bank"                     → bank

NOT category requests — return is_category_request=false:
  "Take me to East Midlands Airport"   (specific named destination)
  "Take me to McDonald's"              (specific brand/chain)
  "Find a Starbucks"                   (specific brand/chain)
  "Find a Starbucks on the way"        (specific brand with route context)
  "Replace Starbucks with Costa"       (route edit command)
  "Go home"                            (navigation command)
  "Navigate to London"                 (navigation command)
  "Take me to the Trafford Centre"     (specific named venue)

Output ONLY valid JSON matching this exact schema (no markdown, no extra text):
{
  "is_category_request": boolean,
  "category": string | null,
  "confidence": number,
  "needs_clarification": boolean
}

Rules:
1. category must be a short English phrase (1-4 words), all lowercase.
2. confidence is a float from 0.0 to 1.0.
3. needs_clarification=true when the category is broad enough that a follow-up
   question would help narrow it (e.g. "restaurant" without a cuisine type).
4. If is_category_request=false, set category=null.
5. Never include city names, street addresses, or "near me" in category.
6. Do not output route action types such as set_destination or append_stop.
7. Route context is advisory only; do not decide append, replace, remove, or set_destination.
"""

# ── LLM output schema ─────────────────────────────────────────────────────────

class LLMCategoryResult(BaseModel):
    is_category_request: bool
    category: Optional[str] = None
    confidence: float = 0.0
    needs_clarification: bool = False


class CategoryNormalizationContext(BaseModel):
    """Tiny advisory route-context object for Phase 5 category normalization."""

    has_existing_route: bool = False
    append_like: bool = False
    along_route: bool = False


# Minimum confidence for an LLM result to be trusted over the rule pipeline.
_CONFIDENCE_THRESHOLD = 0.7


# ── LLM call ─────────────────────────────────────────────────────────────────

async def try_llm_normalize_poi_category(
    query: str,
    *,
    context: Optional[CategoryNormalizationContext] = None,
) -> Optional[str]:
    """Ask the LLM if this query is a category request and return the raw category string.

    Returns the LLM-provided category string (lowercase, not yet canonicalized) on
    success, or None if:
      - LLM credentials are not configured (silent skip, no log noise)
      - the LLM call fails for any reason
      - is_category_request=False
      - confidence < _CONFIDENCE_THRESHOLD
      - category is empty or missing

    The caller (normalize_poi_category in action_intent.py) is responsible for:
      1. Canonicalizing the returned string via _lookup_category_vocab
      2. Falling back to the rule-based pipeline when this returns None
    """
    # Skip silently when LLM is not configured — avoids log noise in rule-only deployments
    if not (os.getenv("LLM_API_KEY") and os.getenv("LLM_BASE_URL") and os.getenv("LLM_MODEL")):
        return None

    try:
        client = LLMClient()
        # Phase 4: response_format=json_object instructs the provider to return
        # a single valid JSON object — no markdown fences, no surrounding prose.
        # Falls back to rule pipeline on any failure (including providers that
        # don't support this flag; they raise an HTTP error caught below).
        advisory_context = context or CategoryNormalizationContext()
        raw = await client.chat(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "User query:\n"
                        f"{query}\n\n"
                        "Advisory route context (do not infer route actions from this):\n"
                        f"{advisory_context.model_dump_json()}"
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )

        # json_object mode guarantees valid JSON — no fence stripping needed.
        # json.loads is the single parsing boundary; Pydantic validates the schema.
        parsed = json.loads(raw)
        result = LLMCategoryResult.model_validate(parsed)

        if (
            not result.is_category_request
            or not result.category
            or result.confidence < _CONFIDENCE_THRESHOLD
        ):
            return None

        return result.category.strip().lower()

    except Exception as exc:
        logger.warning("category_normalizer LLM call failed: %s", exc)
        return None
