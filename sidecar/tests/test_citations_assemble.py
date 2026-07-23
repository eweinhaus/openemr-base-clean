"""PRD 06 Wave 1: clinical payload segments + citation records from verified claims."""

from __future__ import annotations

from sidecar.app.claims import (
    Claim,
    Locator,
    Refusal,
    assemble_clinical,
    build_citation_records,
    build_clinical_payload,
)
from sidecar.app.research.constants import (
    DECISION_SUPPORT_DISCLAIMER,
    RESEARCH_TOOL_NAME,
    UNCERTAIN_RXNORM_SUFFIX,
    format_not_on_list,
)

DOSING_REFUSAL_TEXT = "No retrieved label source for dosing — I won't guess."
EMPTY_MESSAGE = "Not enough verified chart data to answer from the record."


def _claim(
    text: str,
    *,
    source_type: str = "chart",
    table: str = "procedure_result",
    fact_id: str = "42",
    excerpt: str | None = "CMP — within reference range",
) -> Claim:
    return Claim(
        text=text,
        source_type=source_type,
        locator=Locator(table=table, id=fact_id),
        excerpt=excerpt,
    )


def test_build_clinical_payload_claim_segments_have_citation_ids() -> None:
    verified = [
        _claim("Creatinine 1.4 mg/dL", fact_id="42"),
        _claim(
            "Metformin 500 mg",
            table="prescriptions",
            fact_id="10",
            excerpt="Active Rx — started 2020-01-10",
        ),
    ]

    payload = build_clinical_payload(verified, [])

    assert payload["text"] == "Creatinine 1.4 mg/dL\nMetformin 500 mg"
    assert payload["segments"] == [
        {
            "kind": "claim",
            "text": "Creatinine 1.4 mg/dL",
            "citation_id": "c1",
        },
        {
            "kind": "claim",
            "text": "Metformin 500 mg",
            "citation_id": "c2",
        },
    ]
    for segment in payload["segments"]:
        assert segment["kind"] == "claim"
        assert "citation_id" in segment


def test_assembly_segments_never_have_citation_id() -> None:
    verified = [_claim("Creatinine 1.4 mg/dL")]
    refusals = [Refusal(code="no_research", text=DOSING_REFUSAL_TEXT)]
    tool_results = [
        {
            "ok": True,
            "tool": RESEARCH_TOOL_NAME,
            "data": {
                "facts": [],
                "meta": {
                    "on_chart": False,
                    "query_term": "amoxicillin",
                    "source": "openfda",
                    "set_id": None,
                },
            },
        }
    ]

    payload = build_clinical_payload(
        verified,
        refusals,
        tool_results=tool_results,
        requested_tools=["labs"],
        tool_domain_errors={},
        # labs not in tool_results → no domain line; still disclaimer + not-on-list
    )

    not_on_list = format_not_on_list("amoxicillin")
    claim_segs = [s for s in payload["segments"] if s["kind"] == "claim"]
    assembly_segs = [s for s in payload["segments"] if s["kind"] == "assembly"]

    assert len(claim_segs) == 1
    assert claim_segs[0]["citation_id"] == "c1"
    assert assembly_segs
    for segment in assembly_segs:
        assert "citation_id" not in segment
        assert segment["kind"] == "assembly"

    assembly_texts = [s["text"] for s in assembly_segs]
    assert not_on_list in assembly_texts
    assert DECISION_SUPPORT_DISCLAIMER in assembly_texts
    assert DOSING_REFUSAL_TEXT in assembly_texts


def test_uncertain_rxnorm_assembly_line_for_blocked_dosing() -> None:
    """pid 2 story: uncertain chart Rx → assembly copy before dosing refusal."""
    tool_results = [
        {
            "ok": True,
            "tool": "meds",
            "data": {
                "facts": [
                    {
                        "text": f"Lisinopril 10 mg — daily{UNCERTAIN_RXNORM_SUFFIX}",
                        "table": "prescriptions",
                        "id": "901",
                    }
                ],
                "meta": {"active_med_count": 1, "allergy_count": 0},
            },
        }
    ]
    refusals = [Refusal(code="no_research", text=DOSING_REFUSAL_TEXT)]

    payload = build_clinical_payload(
        [],
        refusals,
        tool_results=tool_results,
        requested_tools=["meds", "patient_context"],
        message="What is a typical adult dose for lisinopril?",
    )

    assembly_texts = [
        s["text"] for s in payload["segments"] if s["kind"] == "assembly"
    ]
    uncertain_line = f"Lisinopril{UNCERTAIN_RXNORM_SUFFIX}"
    assert uncertain_line in assembly_texts
    assert DOSING_REFUSAL_TEXT in assembly_texts
    assert uncertain_line in payload["text"]


def test_zero_verified_empty_clinical_is_assembly_only() -> None:
    payload = build_clinical_payload([], [])

    assert payload["text"] == EMPTY_MESSAGE
    assert payload["segments"] == [
        {"kind": "assembly", "text": EMPTY_MESSAGE},
    ]
    assert "citation_id" not in payload["segments"][0]

    citations = build_citation_records([])
    assert citations == []


def test_zero_verified_domain_empty_lines_are_assembly() -> None:
    payload = build_clinical_payload(
        [],
        [],
        tool_results=[{"ok": True, "tool": "labs", "data": {"facts": []}}],
        tool_domain_errors={},
        requested_tools=["labs"],
    )

    assert payload["segments"] == [
        {"kind": "assembly", "text": "No recent labs on file."},
    ]
    assert "citation_id" not in payload["segments"][0]
    assert build_citation_records([]) == []


def test_citation_batch_length_matches_verified_and_segment_ids() -> None:
    verified = [
        _claim("Creatinine 1.4 mg/dL", fact_id="42"),
        _claim(
            "Metformin 500 mg",
            table="prescriptions",
            fact_id="10",
            excerpt="Active Rx — started 2020-01-10",
        ),
    ]

    payload = build_clinical_payload(verified, [])
    citations = build_citation_records(verified)

    assert len(citations) == len(verified)
    claim_ids = [
        s["citation_id"] for s in payload["segments"] if s["kind"] == "claim"
    ]
    cite_ids = [c["citation_id"] for c in citations]
    assert claim_ids == cite_ids == ["c1", "c2"]


def test_chart_citation_keeps_source_type_and_locator_no_invented_fields() -> None:
    verified = [
        _claim(
            "Creatinine 1.4 mg/dL",
            excerpt="CMP — within reference range",
        )
    ]

    citations = build_citation_records(verified)

    assert len(citations) == 1
    cite = citations[0]
    assert cite["citation_id"] == "c1"
    assert cite["source_type"] == "chart"
    assert cite["excerpt"] == "CMP — within reference range"
    assert cite["title"] == "CMP — within reference range"
    assert cite["locator"] == {
        "table": "procedure_result",
        "id": "42",
        "url": None,
    }
    # Without tool_results, optional fields are omitted (not invented).
    assert "fhir_uuid" not in cite
    assert "retrieved_at" not in cite
    assert "fhir_uuid" not in cite["locator"]
    assert "retrieved_at" not in cite["locator"]


def test_citation_includes_fhir_uuid_and_retrieved_at_when_present() -> None:
    verified = [
        _claim(
            "Creatinine 1.4 mg/dL",
            excerpt="CMP — within reference range",
        )
    ]
    tool_results = [
        {
            "ok": True,
            "tool": "labs",
            "data": {
                "facts": [
                    {
                        "text": "Creatinine 1.4 mg/dL",
                        "table": "procedure_result",
                        "id": "42",
                        "excerpt": "CMP — within reference range",
                        "fhir_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                        "retrieved_at": "2026-07-22T12:00:00Z",
                    }
                ]
            },
        }
    ]

    citations = build_citation_records(verified, tool_results=tool_results)
    cite = citations[0]
    assert cite["retrieved_at"] == "2026-07-22T12:00:00Z"
    assert cite["locator"]["fhir_uuid"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_research_citation_uses_meta_retrieved_at() -> None:
    verified = [
        Claim(
            text="Take 20 mg once daily",
            source_type="research",
            locator=Locator(table="openfda", id="set-1#dosage"),
            excerpt="Simvastatin — https://api.fda.gov/x",
        )
    ]
    tool_results = [
        {
            "ok": True,
            "tool": "research_label",
            "data": {
                "facts": [
                    {
                        "text": "Take 20 mg once daily",
                        "table": "openfda",
                        "id": "set-1#dosage",
                        "excerpt": "Simvastatin — https://api.fda.gov/x",
                    }
                ],
                "meta": {
                    "on_chart": True,
                    "query_term": "simvastatin",
                    "source": "openfda",
                    "set_id": "set-1",
                    "retrieved_at": "2026-07-22T15:30:00Z",
                },
            },
        }
    ]

    citations = build_citation_records(verified, tool_results=tool_results)
    assert citations[0]["retrieved_at"] == "2026-07-22T15:30:00Z"


def test_chart_title_falls_back_to_table_label_when_excerpt_empty() -> None:
    verified = [
        _claim("Creatinine 1.4 mg/dL", excerpt=None),
        _claim(
            "Metformin 500 mg",
            table="prescriptions",
            fact_id="10",
            excerpt="",
        ),
        _claim(
            "Progress note body",
            source_type="note",
            table="form_clinical_notes",
            fact_id="7",
            excerpt=None,
        ),
    ]

    citations = build_citation_records(verified)

    assert citations[0]["title"] == "Lab result"
    assert citations[0]["excerpt"] == ""
    assert citations[0]["locator"]["table"] == "procedure_result"
    assert citations[0]["locator"]["id"] == "42"

    assert citations[1]["title"] == "Active medication"
    assert citations[1]["source_type"] == "chart"

    assert citations[2]["title"] == "Clinical note"
    assert citations[2]["source_type"] == "note"


def test_research_citation_parses_title_and_url_from_excerpt() -> None:
    url = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=abc-set"
    verified = [
        Claim(
            text="Usual adult dose 20 to 40 mg once daily.",
            source_type="research",
            locator=Locator(table="openfda", id="abc-set:dosage_and_administration"),
            excerpt=f"SIMVASTATIN — {url}",
        )
    ]

    citations = build_citation_records(verified)

    assert len(citations) == 1
    cite = citations[0]
    assert cite["source_type"] == "research"
    assert cite["title"] == "SIMVASTATIN"
    assert cite["locator"]["url"] == url
    assert cite["locator"]["table"] == "openfda"
    assert cite["locator"]["id"] == "abc-set:dosage_and_administration"


def test_research_citation_url_from_set_id_meta_when_excerpt_lacks_url() -> None:
    set_id = "abc-set-id-1"
    fact_id = f"{set_id}:dosage_and_administration"
    verified = [
        Claim(
            text="Usual adult dose 20 to 40 mg once daily.",
            source_type="research",
            locator=Locator(table="openfda", id=fact_id),
            excerpt="openFDA label",
        )
    ]
    tool_results = [
        {
            "ok": True,
            "tool": RESEARCH_TOOL_NAME,
            "data": {
                "facts": [
                    {
                        "text": "Usual adult dose 20 to 40 mg once daily.",
                        "table": "openfda",
                        "id": fact_id,
                        "excerpt": "openFDA label",
                    }
                ],
                "meta": {
                    "on_chart": True,
                    "query_term": "simvastatin",
                    "source": "openfda",
                    "set_id": set_id,
                },
            },
        }
    ]

    citations = build_citation_records(verified, tool_results=tool_results)

    assert citations[0]["source_type"] == "research"
    assert citations[0]["title"] == "openFDA label"
    assert (
        citations[0]["locator"]["url"]
        == f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"
    )


def test_assemble_clinical_matches_payload_text() -> None:
    verified = [
        _claim("Creatinine 1.4 mg/dL"),
        _claim(
            "Metformin 500 mg",
            table="prescriptions",
            fact_id="10",
            excerpt="Active Rx",
        ),
    ]
    refusals = [Refusal(code="no_research", text=DOSING_REFUSAL_TEXT)]

    text = assemble_clinical(verified, refusals)
    payload = build_clinical_payload(verified, refusals)

    assert text == payload["text"]
    assert "\n" in text
    claim_pos = text.index("Creatinine 1.4 mg/dL")
    metformin_pos = text.index("Metformin 500 mg")
    disclaimer_pos = text.index(DECISION_SUPPORT_DISCLAIMER)
    refusal_pos = text.index(DOSING_REFUSAL_TEXT)
    assert claim_pos < metformin_pos < disclaimer_pos < refusal_pos
