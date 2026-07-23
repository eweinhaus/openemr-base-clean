# Clinical Co-Pilot — Eval catalog (A8 / K)

**Purpose:** Defensible failure-mode catalog for cite-or-silence, auth, research, and UC paths.  
**Method:** Cases map **1:1** to existing `sidecar/tests/` pytest regressions (mocked LLM + gateway). This is not a separate live-clinical harness — it is the regression suite lifted into grader-readable IDs.  
**Stack assumptions:** hybrid OpenEMR gateway + LangGraph sidecar; OpenRouter Haiku `anthropic/claude-haiku-4.5`; openFDA→DailyMed fallback-only; hybrid SSE after verify.

## How to run

From repo root (host Python 3.11+ recommended):

```bash
pip install -r sidecar/requirements.txt pytest
export COPILOT_INTERNAL_SECRET=test-secret
pytest sidecar/tests/ -q
```

Record the summary in [`results.md`](./results.md).

## Case table

| Case ID | Failure mode | Expected behavior | Source test(s) |
| --- | --- | --- | --- |
| **E-UNBOUND** | Unbound / missing `pid` | Refuse with unbound clinical text; **no** LLM route/draft and **no** gateway chart tools | `test_chat_integration.py::test_missing_pid_refuses_without_llm_or_gateway`, `test_auth.py::test_chat_refuses_unbound_pid_without_placeholder_clinical` |
| **E-EMPTY** | Empty chart facts (`facts: []`) | Tool success (not graph error); assemble empty / “not on file” lines — **do not invent** values | `test_tools_node.py::test_empty_facts_is_success_not_error`, assemble empty paths in `test_verify.py` |
| **E-RXNORM** | Missing / uncertain RxNorm on active Rx | Block research resolve; **zero** openFDA/DailyMed HTTP | `test_tools_node.py::test_meds_dosing_blocked_uncertain_skips_fetch`, `test_research_resolve.py::test_uncertain_suffix_returns_blocked_without_http` |
| **E-MISS** | Research miss on dosing-like ask | Canonical `no_research` refusal; chart facts may still verify; **no** model-memory dosing | `test_verify.py` dosing refusal assemble, `test_chat_integration.py::test_dosing_question_includes_dosing_refusal` |
| **E-AMBIG** | Ambiguous IR/ER (or multi-form) label | Extract miss → no invented dose facts | `test_research_extract.py::test_ambiguous_forms_flag_miss`, `test_mixed_ir_er_names_without_hint_miss` |
| **E-HALLUC** | Hallucinated / unmatched locator | Claim **dropped** (or text replaced only when locator matches a tool fact) | `test_verify.py::test_invented_locator_dropped`, `test_chat_integration.py::test_invented_locator_dropped_from_clinical` |
| **E-UC1** | Chart summary / domain tool unavailable (partial) | Honest **unavailable** assembly line; no fake locators | `test_verify.py::test_assemble_chart_summary_unavailable`, `test_assemble_unavailable_notes_line` |
| **E-UC2** | Labs creatinine path | Verified lab claim text + citation pairing on happy path | `test_chat_integration.py::test_happy_path_labs_progress_clinical_done` |
| **E-UC3** | Label-backed dosing (research hit) | Research claim in clinical; **no** `no_research` refusal | `test_chat_integration.py::test_dosing_research_hit_omits_refusal`, `test_verify.py` research keep paths |
| **E-CITE** | Claims must cite / segment ids | Claim segments carry `citation_id`; citation batch length matches verified claims; assembly/refusal unlinked | `test_citations_assemble.py` (esp. `test_build_clinical_payload_claim_segments_have_citation_ids`, `test_citation_batch_length_matches_verified_and_segment_ids`) |
| **E-XPID** | Unauthorized / wrong internal secret | Fail-closed **401** | `test_auth.py::test_chat_rejects_missing_secret`, `test_chat_rejects_wrong_secret` |
| **E-ALLERGY** | Allergy contradiction vs dosing/med research | `allergy_contradiction` refusal; conflicting research (and matching Rx) claims dropped at verify | New verify guard: `sidecar/app/claims.py::apply_allergy_contradiction` wired in `nodes/verify.py` — add/keep a dedicated pytest under `test_verify.py` when extending coverage |
| **E-CONFLICT** | openFDA vs DailyMed label conflict | **DEFERRED MVP** — fallback-only single source; no dual-fetch compare / conflict UI | N/A (by design; see ARCHITECTURE / PRD 05) |

## Notes for graders

- **Cite-or-silence:** clinical SSE only after verify; progress events are non-clinical.
- **PHI-free research:** outbound queries are drug/condition terms only (scrubbed `DrugQuery`).
- **E-CONFLICT** is an intentional non-goal for interview MVP — documenting it here prevents overclaiming.
