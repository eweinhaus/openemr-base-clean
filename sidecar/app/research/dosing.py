"""Shared dosing-intent detector for tools and verify (PRD 05 H17)."""

from __future__ import annotations

import re

_DOSING_LIKE = re.compile(
    r"\b("
    r"dose|dosing|dosage|titrat(?:e|ion)|"
    r"how\s+much|how\s+many\s+mg|"
    r"mg\s*/?\s*kg|"
    r"adult\s+dose|typical\s+dose|starting\s+dose|usual\s+dose|"
    r"what\s+(?:is\s+)?(?:the\s+)?dose"
    r")\b",
    re.IGNORECASE,
)


def is_dosing_like(message: str) -> bool:
    """Return True when ``message`` asks about dosing / titration intent."""
    return _DOSING_LIKE.search(message) is not None
