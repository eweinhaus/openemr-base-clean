"""Scrub outbound research query terms — drug tokens only, never PHI."""

from __future__ import annotations

import re

from .constants import SCRUB_MAX_LENGTH

# Allowed drug-term shape after trim (max SCRUB_MAX_LENGTH chars).
_ALLOWED_TERM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 \-/]{0,63}$")

# Long digit runs look like record numbers when mixed with name-like tokens.
_LONG_DIGIT_RUN = re.compile(r"\d{5,}")
_PERSON_NAMEISH = re.compile(r"[A-Za-z]{2,}\s+[A-Za-z]{2,}")


def scrub_query_term(raw: str) -> str | None:
    """Return a cleaned drug query term, or None if ``raw`` is not usable.

    Rejects empty/oversized input, characters outside the allowlist (``@``,
    commas, etc.), and MRN-like long digit runs mixed with person-name patterns.
    """
    term = raw.strip()
    if not term or len(term) > SCRUB_MAX_LENGTH:
        return None
    if not _ALLOWED_TERM.fullmatch(term):
        return None
    if _LONG_DIGIT_RUN.search(term) and _PERSON_NAMEISH.search(term):
        return None
    return term
