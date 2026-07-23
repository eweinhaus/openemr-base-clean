"""Unit tests for shared dosing-intent detection (PRD 05 H17)."""

from __future__ import annotations

from sidecar.app.research import is_dosing_like, is_prescribing_recommendation_like


def test_is_dosing_like_typical_adult_dose() -> None:
    assert is_dosing_like("typical adult dose") is True


def test_is_dosing_like_how_many_mg() -> None:
    assert is_dosing_like("how many mg") is True


def test_is_dosing_like_starting_dose() -> None:
    assert is_dosing_like("starting dose") is True


def test_is_dosing_like_what_is_the_dose() -> None:
    assert is_dosing_like("what is the dose") is True


def test_is_dosing_like_false_for_meds_list_ask() -> None:
    assert is_dosing_like("what meds is the patient on?") is False


def test_is_prescribing_recommendation_like_consider_prescribing() -> None:
    assert (
        is_prescribing_recommendation_like(
            "Are there any new medications I should consider prescribing?"
        )
        is True
    )


def test_is_prescribing_recommendation_like_false_for_current_meds_list() -> None:
    assert (
        is_prescribing_recommendation_like(
            "What medications are they currently taking?"
        )
        is False
    )
