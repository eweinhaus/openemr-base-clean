"""Sidecar research helpers: dosing detect, scrub, resolve, extract, constants."""

from __future__ import annotations

from .client import LabelFetchResult, fetch_label
from .constants import (
    DAILYMED_BASE_URL,
    DAILYMED_DOSAGE_LOINC,
    DECISION_SUPPORT_DISCLAIMER,
    DOSAGE_SECTION_ID_SUFFIX,
    DOSING_REFUSAL_TEXT,
    HTTP_DEADLINE_SECONDS,
    HTTP_MAX_RESPONSE_BYTES,
    NOT_ON_LIST_TEMPLATE,
    OPENFDA_LABEL_URL,
    PRESCRIBING_RECOMMENDATION_SCOPE,
    RESEARCH_PROGRESS_MESSAGE,
    RESEARCH_TABLES,
    RESEARCH_TOOL_NAME,
    SCRUB_MAX_LENGTH,
    TABLE_DAILYMED,
    TABLE_OPENFDA,
    TEXT_MAX_CHARS,
    UNCERTAIN_RXNORM_SUFFIX,
    format_not_on_list,
)
from .dosing import is_dosing_like, is_prescribing_recommendation_like
from .extract import (
    build_research_tool_result,
    extract_dailymed_facts,
    extract_openfda_facts,
)
from .resolve import (
    DrugQuery,
    ResolveResult,
    ResolveStatus,
    reconcile_on_chart_after_hit,
    resolve_drug_query,
)
from .scrub import scrub_query_term

__all__ = [
    "DAILYMED_BASE_URL",
    "DAILYMED_DOSAGE_LOINC",
    "DECISION_SUPPORT_DISCLAIMER",
    "DOSAGE_SECTION_ID_SUFFIX",
    "DOSING_REFUSAL_TEXT",
    "DrugQuery",
    "HTTP_DEADLINE_SECONDS",
    "HTTP_MAX_RESPONSE_BYTES",
    "LabelFetchResult",
    "NOT_ON_LIST_TEMPLATE",
    "OPENFDA_LABEL_URL",
    "PRESCRIBING_RECOMMENDATION_SCOPE",
    "RESEARCH_PROGRESS_MESSAGE",
    "RESEARCH_TABLES",
    "RESEARCH_TOOL_NAME",
    "ResolveResult",
    "ResolveStatus",
    "SCRUB_MAX_LENGTH",
    "TABLE_DAILYMED",
    "TABLE_OPENFDA",
    "TEXT_MAX_CHARS",
    "UNCERTAIN_RXNORM_SUFFIX",
    "build_research_tool_result",
    "extract_dailymed_facts",
    "extract_openfda_facts",
    "fetch_label",
    "format_not_on_list",
    "is_dosing_like",
    "is_prescribing_recommendation_like",
    "reconcile_on_chart_after_hit",
    "resolve_drug_query",
    "scrub_query_term",
]
