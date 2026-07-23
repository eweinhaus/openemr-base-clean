"""Shared dosing-intent detector for tools and verify (PRD 05 H17)."""

from __future__ import annotations

import re

_DOSING_LIKE = re.compile(
    r"\b("
    r"dose|dosing|dosage|titrat(?:e|ion)|"
    r"how\s+much|how\s+many\s+mg|"
    r"mg\s*/?\s*kg|"
    r"adult\s+dose|typical\s+dose|starting\s+dose|usual\s+dose|"
    r"what\s+(?:is\s+)?(?:the\s+)?dose|"
    r"replace(?:\s+\S+){0,8}?\s+with|"
    r"switch(?:ing)?(?:\s+from)?|"
    r"substitut(?:e|ing|ion)|"
    r"convert(?:ing)?(?:\s+to)?|"
    r"equivalent\s+(?:to|dose)"
    r")\b",
    re.IGNORECASE,
)

_PRESCRIBING_RECOMMENDATION_LIKE = re.compile(
    r"\b("
    r"prescrib|recommend(?:ation)?s?|"
    r"consider\s+(?:prescrib|add(?:ing)?|start(?:ing)?|new)|"
    r"new\s+med(?:ication)?s?|add\s+(?:a\s+)?med(?:ication)?s?|"
    r"start\s+(?:a\s+)?med(?:ication)?s?|"
    r"should\s+(?:i|we)\s+(?:prescrib|add|start)|"
    r"(?:any|what)\s+(?:new\s+)?med(?:ication)?s?\s+(?:to|should|can|could)|"
    r"options?\s+(?:for|to)\s+(?:prescrib|add|start|treat)|"
    r"replace(?:\s+\S+){0,8}?\s+with|"
    r"switch(?:ing)?(?:\s+(?:from|to))?|"
    r"substitut(?:e|ing|ion)"
    r")\b|"
    r"(?:is|would)\s+it\s+(?:be\s+)?reasonable\s+(?:to\s+)?"
    r"(?:replace|switch|substitut|change|add|start|prescrib)",
    re.IGNORECASE,
)

_SWITCH_MG_BOOSTER = re.compile(r"\b(replace|switch|substitut)\b", re.IGNORECASE)
_MG_BOOSTER = re.compile(r"\b\d+\s*mg\b", re.IGNORECASE)


def is_dosing_like(message: str) -> bool:
    """Return True when ``message`` asks about dosing / titration intent."""
    if _DOSING_LIKE.search(message) is not None:
        return True
    if _SWITCH_MG_BOOSTER.search(message) and _MG_BOOSTER.search(message):
        return True
    return False


def is_prescribing_recommendation_like(message: str) -> bool:
    """Return True when the user asks to add/prescribe/recommend new medications."""
    return _PRESCRIBING_RECOMMENDATION_LIKE.search(message) is not None
