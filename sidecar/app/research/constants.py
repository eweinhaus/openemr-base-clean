"""Allowlisted research copy, caps, and locator constants (PRD 05)."""

from __future__ import annotations

# --- Allowlisted physician-facing copy ---

DOSING_REFUSAL_TEXT = "No retrieved label source for dosing — I won't guess."

NOT_ON_LIST_TEMPLATE = "{drug} is not on this patient's active medication list."

DECISION_SUPPORT_DISCLAIMER = (
    "Decision support only — physician decides; Co-Pilot does not prescribe "
    "or write the chart."
)

# Exact chart-fact suffix for missing RxNorm (leading space required).
UNCERTAIN_RXNORM_SUFFIX = " (RxNorm not on file — drug identity uncertain)"

# --- Caps / deadlines ---

TEXT_MAX_CHARS = 1500
HTTP_DEADLINE_SECONDS = 5.0
SCRUB_MAX_LENGTH = 64
# Cap raw label/XML bodies before parse (2 GB host; DoS / memory guard).
HTTP_MAX_RESPONSE_BYTES = 2_000_000

# --- External APIs ---

OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"
DAILYMED_BASE_URL = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
DAILYMED_DOSAGE_LOINC = "34068-7"

# --- Tool / locator vocabulary ---

RESEARCH_TOOL_NAME = "research_label"
TABLE_OPENFDA = "openfda"
TABLE_DAILYMED = "dailymed"
RESEARCH_TABLES = frozenset({TABLE_OPENFDA, TABLE_DAILYMED})
DOSAGE_SECTION_ID_SUFFIX = ":dosage_and_administration"

RESEARCH_PROGRESS_MESSAGE = "Looking up label information…"


def format_not_on_list(drug: str) -> str:
    """Format the allowlisted off-chart medication line for ``drug``."""
    return NOT_ON_LIST_TEMPLATE.format(drug=drug)
