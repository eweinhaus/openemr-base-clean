"""Allowlisted physician-facing SSE progress copy (PRD 06 H13).

Keep strings clinical-ish — no toolchain jargon, no fake % complete.
Research progress stays in ``research.constants`` (unchanged wording).
"""

from __future__ import annotations

from .llm import Route

# Early progress from route (while chart tools run).
PROGRESS_PULLING_CHART = "Pulling chart…"

# Domain progress from tools (one line per turn is enough).
PROGRESS_PULLING_LABS = "Pulling labs…"
PROGRESS_CHECKING_MEDICATIONS = "Checking medications…"
PROGRESS_REVIEWING_NOTES = "Reviewing chart notes…"
PROGRESS_SUMMARIZING = "Summarizing…"


def chart_progress_for_route(route: Route | str) -> str:
    """Return the allowlisted chart-gather progress line for ``route``."""
    if route == "labs":
        return PROGRESS_PULLING_LABS
    if route == "meds":
        return PROGRESS_CHECKING_MEDICATIONS
    return PROGRESS_PULLING_CHART
