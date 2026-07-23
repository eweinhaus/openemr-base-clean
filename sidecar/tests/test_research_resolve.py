"""Unit tests for drug identity resolve (PRD 05 H4 / H15 / H16)."""

from __future__ import annotations

from sidecar.app.research.constants import UNCERTAIN_RXNORM_SUFFIX
from sidecar.app.research.resolve import (
    DrugQuery,
    ResolveStatus,
    reconcile_on_chart_after_hit,
    resolve_drug_query,
)


def test_uncertain_suffix_returns_blocked_without_http() -> None:
    """H4: uncertain RxNorm → blocked. Resolve never calls an HTTP client."""
    message = "What is the typical adult dose of lisinopril?"
    facts = [
        {
            "text": f"Lisinopril 10 mg — daily{UNCERTAIN_RXNORM_SUFFIX}",
            "table": "prescriptions",
            "id": "55",
        }
    ]

    result = resolve_drug_query(message, facts)

    assert result is not None
    assert result.status is ResolveStatus.BLOCKED
    assert result.query is not None
    assert result.query.blocked is True
    assert result.query.on_chart is True
    assert result.query.display_name.lower() == "lisinopril"
    # Document: resolve itself does not call any research client / HTTP.
    # Callers must skip HTTP when status is BLOCKED.


def test_candidate_not_taken_from_allergy_lists_facts() -> None:
    """H16: allergy/lists facts must not supply the drug candidate."""
    message = "What is the dose of penicillin?"
    facts = [
        {
            "text": "Allergy: Penicillin — rash",
            "table": "lists",
            "id": "77",
        },
        {
            "text": "Simvastatin 20 MG Oral Tablet",
            "table": "prescriptions",
            "id": "6",
        },
    ]

    result = resolve_drug_query(message, facts)

    assert result is not None
    assert result.status is ResolveStatus.OK
    assert result.query is not None
    assert result.query.on_chart is False
    assert result.query.blocked is False
    assert result.query.term.lower() == "penicillin"
    assert result.query.rxcui is None


def test_on_chart_with_rxnorm_digits() -> None:
    message = "typical adult dose for simvastatin"
    facts = [
        {
            "text": "Simvastatin 20 MG Oral Tablet (RxNorm 312961)",
            "table": "prescriptions",
            "id": "12",
        }
    ]

    result = resolve_drug_query(message, facts)

    assert result is not None
    assert result.status is ResolveStatus.OK
    assert result.query is not None
    assert result.query.on_chart is True
    assert result.query.blocked is False
    assert result.query.rxcui == "312961"
    assert result.query.term.lower() == "simvastatin"
    assert result.query.matched_fact_id == "12"


def test_off_chart_named_drug_via_dose_of() -> None:
    message = "What is the dose of amoxicillin?"
    facts = [
        {
            "text": "Simvastatin 20 MG Oral Tablet",
            "table": "prescriptions",
            "id": "6",
        }
    ]

    result = resolve_drug_query(message, facts)

    assert result is not None
    assert result.status is ResolveStatus.OK
    assert result.query is not None
    assert result.query.on_chart is False
    assert result.query.blocked is False
    assert result.query.rxcui is None
    assert result.query.term == "amoxicillin"
    assert result.query.display_name.lower() == "amoxicillin"


def test_non_dosing_message_returns_none() -> None:
    result = resolve_drug_query(
        "what meds is the patient on?",
        [{"text": "Simvastatin 20 MG", "table": "prescriptions", "id": "1"}],
    )
    assert result is None


def test_reconcile_brand_label_to_chart_generic() -> None:
    """H15: label brand/generic tokens can flip off-chart → on-chart."""
    # Ask was brand (Zocor); chart lists generic simvastatin; label returns both.
    flipped = reconcile_on_chart_after_hit(
        on_chart=False,
        label_generic_names=["simvastatin"],
        label_brand_names=["Zocor"],
        active_rx_texts=["simvastatin 20 MG Oral Tablet"],
    )
    assert flipped is True

    # Brand token alone matching chart brand-like text.
    brand_hit = reconcile_on_chart_after_hit(
        on_chart=False,
        label_generic_names=[],
        label_brand_names=["Zocor"],
        active_rx_texts=["Zocor 20 mg daily"],
    )
    assert brand_hit is True

    # No overlap → stays off-chart.
    miss = reconcile_on_chart_after_hit(
        on_chart=False,
        label_generic_names=["amoxicillin"],
        label_brand_names=["Amoxil"],
        active_rx_texts=["simvastatin 20 MG Oral Tablet"],
    )
    assert miss is False

    # Already on-chart stays True.
    assert (
        reconcile_on_chart_after_hit(
            on_chart=True,
            label_generic_names=[],
            label_brand_names=[],
            active_rx_texts=[],
        )
        is True
    )


def test_resolve_result_ok_query_is_drug_query() -> None:
    result = resolve_drug_query(
        "starting dose of metformin",
        [{"text": "Metformin 500 mg", "table": "prescriptions", "id": "1"}],
    )
    assert result is not None
    assert result.status is ResolveStatus.OK
    assert isinstance(result.query, DrugQuery)


def test_switch_resolves_target_not_source() -> None:
    """PRD 11: replace X with Y → research target (proposed) drug, not chart source."""
    message = (
        "Would it be reasonable to replace simvastatin 20 mg with "
        "atorvastatin 40 mg orally once daily?"
    )
    facts = [
        {
            "text": "Simvastatin 20 MG Oral Tablet (RxNorm 312961)",
            "table": "prescriptions",
            "id": "12",
        }
    ]

    result = resolve_drug_query(message, facts)

    assert result is not None
    assert result.status is ResolveStatus.OK
    assert result.query is not None
    assert result.query.term.lower() == "atorvastatin"
    assert result.query.on_chart is False
    assert result.query.blocked is False
    assert result.query.rxcui is None


def test_switch_target_on_chart_when_proposed_drug_is_active_rx() -> None:
    message = "replace atorvastatin with simvastatin"
    facts = [
        {
            "text": "Atorvastatin 40 MG Oral Tablet (RxNorm 617312)",
            "table": "prescriptions",
            "id": "20",
        },
        {
            "text": "Simvastatin 20 MG Oral Tablet",
            "table": "prescriptions",
            "id": "12",
        },
    ]

    result = resolve_drug_query(message, facts)

    assert result is not None
    assert result.status is ResolveStatus.OK
    assert result.query is not None
    assert result.query.term.lower() == "simvastatin"
    assert result.query.on_chart is True
