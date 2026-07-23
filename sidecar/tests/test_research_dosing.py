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


# --- PRD 11 switch/replace intent --------------------------------------------


def test_switch_question_flags_dosing_and_prescribing() -> None:
    message = (
        "Would it be reasonable to replace simvastatin 20 mg with "
        "atorvastatin 40 mg orally once daily?"
    )
    assert is_dosing_like(message) is True
    assert is_prescribing_recommendation_like(message) is True


def test_replace_and_switch_phrasing_flags_both() -> None:
    assert is_dosing_like("replace simvastatin with atorvastatin") is True
    assert is_prescribing_recommendation_like("replace simvastatin with atorvastatin") is True
    assert is_dosing_like("switch to atorvastatin") is True
    assert is_prescribing_recommendation_like("switch to atorvastatin") is True


def test_meds_list_and_on_chart_membership_stay_false() -> None:
    assert is_dosing_like("what meds is the patient on?") is False
    assert is_prescribing_recommendation_like("what meds is the patient on?") is False
    assert is_dosing_like("is he taking simvastatin?") is False
    assert is_prescribing_recommendation_like("is he taking simvastatin?") is False


def test_typical_dose_stays_dosing_not_prescribing() -> None:
    assert is_dosing_like("typical adult dose of simvastatin") is True
    assert is_prescribing_recommendation_like("typical adult dose of simvastatin") is False


def test_reasonable_without_med_verb_is_not_prescribing() -> None:
    message = "Would it be reasonable to monitor creatinine?"
    assert is_dosing_like(message) is False
    assert is_prescribing_recommendation_like(message) is False
