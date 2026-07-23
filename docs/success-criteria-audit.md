# Clinical Co-Pilot — Success Criteria Audit (Failures & Partials)

**Audited against:** [`docs/success-criteria.md`](./success-criteria.md) (criteria A–O).
**Method:** direct code review of the sidecar (LangGraph), the PHP gateway/services, and the
Ask Co-Pilot UI — not doc claims. Live URL (https://142.93.255.212/) confirmed responding (HTTP 302 → login).
**Date:** 2026-07-22.

## Remediation status (same day)

Most engineering-floor and clinical-domain gaps below were closed in-repo after this audit.
**Still external / ops:** A7 demo video URL, A10 social post, L2 baseline numbers after a real
k6 run on the droplet, DO redeploy of the remediation commit. See `docs/eval/results.md`,
`docs/cost-analysis.md`, `docs/api/`, `docs/load-tests/`.

---

This document lists **only** criteria that are **NOT MET** or **PARTIALLY MET** *as of the
original audit pass*. Everything else in A–O passes. Each entry gives: the criterion, what the
code actually does, the evidence (file:line), and what an agent must change to close the gap.

> **Spine status (the non-negotiables in the completion rollup):** pid fail-closed (D),
> cite-or-silence verify (F1–F4), hybrid SSE with no unverified clinical tokens (G), and
> PHI-free research (C3.2 / M3) **all pass in code**. The gaps below are the engineering-floor
> deliverables plus two clinical domain-constraint gaps.

---

## ❌ NOT MET

### A7 — Demo video (3–5 min)
- **State:** No reference anywhere in the repo (README/ARCHITECTURE/AUDIT/USER/USERS).
- **Fix:** Produce the video (external deliverable) and link it from README.md.

### A8 — Eval dataset + results present and defensible
- **State:** No eval dataset and no recorded results exist. `sidecar/tests/` is a **pytest
  regression suite** (mocked LLM + gateway), not a curated clinical eval dataset with pass/fail
  cases and recorded outcomes.
- **Fix:** Build an eval dataset (cases + expected behavior) and record a run. See K1–K7 below —
  A8 is the submission-gate view of the same gap. Many boundary behaviors already exist as unit
  tests and can be lifted into an eval catalog.

### A9 / L5 — AI cost analysis
- **State:** Completely absent. No actual dev spend figures; no projected cost at 100 / 1K / 10K /
  100K users; no per-tier architectural-change analysis. Only incidental mentions ("$12/mo droplet",
  "Haiku = speed/cost").
- **Fix:** Write a cost analysis doc: actual dev spend + per-tier projections **and** what must
  change architecturally at each tier (this is explicitly *not* tokens × users). Tie to the
  honest single-worker / 2 GB limit already documented in `ARCHITECTURE.md §4.7 / §8`.

### A10 — Social post (final only)
- **State:** Not present.
- **Fix:** Post on X/LinkedIn describing the project, showing the agent, tagging @GauntletAI (final submission only).

### C3.5 — openFDA vs DailyMed conflict surfaced (never silently resolved)
- **State (code):** `sidecar/app/research/client.py` does **openFDA-first → DailyMed-fallback**
  returning a **single source**. There is **no cross-source comparison** and no conflict surface.
  This matches the deliberate "conflict UX deferred for MVP" decision.
- **⚠️ Doc contradiction:** `ARCHITECTURE.md:20` states *"Label conflicts are surfaced as conflicts,
  never silently resolved."* — which the code does **not** do. `ARCHITECTURE.md:76` repeats
  "conflicts surfaced". This is a doc-vs-code contradiction (interview risk for O2/O6).
- **Fix (choose one):**
  1. **Re-scope the docs** to say conflict surfacing is deferred (align with
     `memory-bank/` decision "Conflict UX skipped for MVP"), **or**
  2. Implement a dual-fetch compare in `research/client.py` + a conflict claim/segment in
     `claims.py` and a conflict UI in the popup.
  - Recommended for now: option 1 (docs) — it removes an overclaim without new clinical risk.

### C3.7 / F5 (allergy) — Allergy contradiction flagged/rejected
- **State:** No code anywhere checks a med/dose claim against a patient allergy. Allergies are
  **display-only** facts. The only allergy-related logic is H16 (never *derive a drug query
  candidate* from allergy/`lists` facts — `sidecar/app/research/resolve.py:218` matches only the
  `prescriptions` table) and empty-allergy copy (`sidecar/app/claims.py:501,508-514`). Nothing
  flags "you asked to dose X but the patient is allergic to X."
- **Fix:** Add an allergy-contradiction guard **at verify** (`sidecar/app/nodes/verify.py` /
  `sidecar/app/claims.py`): when a dosing/med claim's drug matches an allergy fact in that turn's
  tool facts, reject/flag the claim. Requires the `meds` route to also carry allergy facts
  (it already pulls allergies — see C3.1). Update `docs/PRDs/05` invariants and success-criteria
  wording once implemented.

### E6 — Runnable API collection (Postman/Bruno/etc.)
- **State:** None exists for the agent endpoints (`stream.php`, sidecar `/v1/chat`,
  `tool_proxy.php`, `disclosure.php`). Only the stock OpenEMR `swagger/openemr-api.yaml` (unrelated).
  Graders cannot exercise the agent without reading source. **This is in the completion rollup's
  required floor (`success-criteria.md:253`).**
- **Fix:** Export a Bruno/Postman collection covering: gateway `POST stream.php` (SSE),
  `schedule.php` (GET + CSRF), `tool_proxy.php` (internal-secret), `disclosure.php`
  (internal-secret), and sidecar `/health` `/ready` `/v1/chat`. Note the auth each requires
  (session+CSRF for browser-facing; `X-Copilot-Internal-Secret` for internal).

### I3 / I5 — Tokens & cost + tool-failure visibility in observability
- **State:** LangGraph passes `metadata.correlation_id` + tags to `graph.stream`
  (`sidecar/app/stream.py:17-22,82`) giving **steps / order / step-latency** via native LangSmith
  auto-instrumentation. **But:**
  - `sidecar/app/llm.py:168-224` uses a plain `OpenAI` client — **no `wrap_openai` / `traceable`**
    (grep: 0 matches) — so **tokens & cost are never captured anywhere**. This directly fails the
    directions' "how many tokens, at what cost" requirement.
  - Tracing is **default-off** (`LANGSMITH_TRACING=false`, `docker-compose.yml:222`).
  - Tool failures are swallowed inside the node (return an `error` dict, don't raise) so with I/O
    hidden they aren't visible as failures in LangSmith — only in local logs + disclosure JSONL.
- **Fix:** Wrap the OpenRouter client with `langsmith.wrappers.wrap_openai` (or log
  `usage`/`cost` from the OpenRouter response into the disclosure JSONL / a metrics sink) so
  tokens+cost are answerable. Consider surfacing tool-failure as a traced error span.

### I6 — Dashboard (request count, error rate, p50/p95, tool calls, retries, verify pass/fail)
- **State:** No purpose-built dashboard (no Prometheus/Grafana/`/metrics`). Only LangSmith's
  default UI + hand-grepping the disclosure JSONL. Retry counts are meaningless — `llm.py:179`
  sets `max_retries=0` and there is no retry logic. PRD 07 §5 lists this as a non-goal;
  `sidecar/README.md:150` says "not wired".
- **Fix:** Either build a minimal dashboard over the disclosure JSONL / LangSmith metrics, or
  explicitly document (in ARCHITECTURE + success-criteria) that the "dashboard" is the LangSmith
  default UI + JSONL and accept the partial. Verify pass/fail *is* derivable from disclosure
  `event=verify` `pass` field (`VerifyDisclosureService.php`).

### I7 — Alerts wired (nuance: defined but NOT wired)
- **State:** Three alerts (p95 latency, error rate, tool-failure rate) are **defined and
  documented** with meaning + on-call response (`sidecar/README.md:150-156`,
  `docs/PRDs/07-observability-langsmith.md:380-386`), but they are **markdown stubs — not wired**
  to any alerting backend.
- **Fix:** Wire to a backend (LangSmith alerts / a simple threshold checker), or keep as
  documented debt. The *definition* half of the criterion is met; the *wired* half is not.

### K7 — Eval results recorded for submission
- **State:** No recorded suite run anywhere (this doc's predecessor `success-criteria-audit.md`
  was 0 bytes). See A8.
- **Fix:** Record a run of the eval suite once it exists.

### L2 — Baseline CPU / memory / latency / throughput under load
- **State:** Not captured. Only qualitative RAM-pressure notes in
  `docs/architecture-tech-primer.md §12`.
- **Fix:** Capture baseline infra metrics under the L3 load scenarios and include in submission.

### L3 — Load/stress tests at ≥10 and ≥50 concurrent users
- **State:** No load-test scripts or results (no locust/k6/jmeter; no p50/p95/p99 or error-rate
  data). `architecture-tech-primer.md:274` lists these as future work.
- **Fix:** Add a load-test script (k6/locust) targeting the deployed agent at ≥10 and ≥50
  concurrent; record p50/p95/p99 + error rate at each level. Expect the honest single-worker
  limit to show — that's fine, but record it.

---

## ⚠️ PARTIALLY MET

### F5 — Domain constraints enforced at verify (2 of 4)
- **✅ Missing RxNorm → uncertainty:** real. `MedsChartService.php:212-214` appends
  "(RxNorm not on file — drug identity uncertain)"; `resolve.py:223-224` detects it →
  `ResolveStatus.BLOCKED` → no HTTP (`tools.py:123-125`) → `DOSING_REFUSAL` at verify.
- **✅ Research-backed-only dosing:** real. Dosing-like turns without a verified research locator
  get `DOSING_REFUSAL` (`verify.py:26-36,83-87`; `_has_verified_research_dosing`).
- **❌ Allergy contradiction:** not implemented (see C3.7 above).
- **⚠️ No invented staging/severity from a single lab:** only **structurally** prevented — verify
  replaces claim text with the raw source-fact text (`claims.py:145-155`), so the model can't inject
  a computed stage/severity, but there is **no targeted rule** (grep: zero staging/severity matches).
- **Fix:** Implement allergy contradiction; optionally add an explicit single-lab staging guard.

### B6 — Citation popup fields (missing `retrieved_at`)
- **State:** Popup renders `source_type`, `title`, `excerpt`, and `locator` (table/id + Open-label
  URL), but **`retrieved_at` is never rendered** — the sidecar deliberately omits the key
  (`sidecar/app/claims.py:250,262`) and a test asserts its absence
  (`sidecar/tests/test_citations_assemble.py:188-190`). Criterion explicitly requires `retrieved_at`.
- **Fix:** Populate `retrieved_at` when building citation records in `claims.py:build_citation_records`
  (set at fetch time in the research client / tool facts), render it in the `#acp-cite` popup JS,
  and update the assemble test.

### E4 — Citations include FHIR UUID when available (dead path)
- **State:** `table`+`pk` are **always** present (`claims.py:262-270`; `ChartFact.php:37-50`) — good.
  But the FHIR-UUID path is **inert**: every `new ChartFact(...)` call omits `fhirUuid`
  (`LabsChartService.php:165`, `PatientContextService.php:168,193`, `MedsChartService.php:222,247`,
  `NotesChartService.php:141`), and `claims.py:build_citation_records` (244-273) builds
  `locator: {table, id, url}` with **no `fhir_uuid` key** — so even a fact carrying one would be dropped.
- **Fix:** Populate `fhirUuid` in the chart services where a FHIR UUID exists, and add a `fhir_uuid`
  key to the locator in `build_citation_records` (emit only when present).

### C3.1 — Meds route combines meds / allergies / **conditions**
- **State:** The `meds` route (`sidecar/app/nodes/tools.py:47`) pulls **meds + allergies** but
  **not** the problem/condition list, so "combines meds/allergies/conditions" is incomplete.
- **Fix:** Add the conditions/problems fact source to the `meds` route (the `PatientContextService`
  / problems path already exists for UC-1). This also unblocks a proper allergy/condition-aware
  contradiction check (C3.7).

### C1.2 — Structured data preferred over free-text notes when both exist
- **State:** Invention is structurally blocked by cite-or-silence, but the **preference** of
  structured over notes is left to the LLM prompt (`nodes/draft.py`) with no dedicated logic.
- **Fix:** Either add explicit ranking (drop/deprioritize note claims when a structured fact covers
  the same datum) or document it as prompt-only behavior.

### C2.2 — Ambiguous lab names handled without inventing a specific result
- **State:** Same shape as C1.2 — no specific result can be invented (cite-or-silence), but
  disambiguation itself is prompt-driven with no dedicated code.
- **Fix:** Optional — add a disambiguation branch, or document as prompt-only + covered by
  cite-or-silence.

### J3 — `/ready` does not unconditionally return 200 when deps down
- **State:** The `ready` **boolean** correctly flips false when gateway/OpenRouter are down
  (`main.py:188` `ready = gateway.reachable AND openrouter_api_key`), **but the endpoint always
  returns HTTP 200** (`main.py` returns `JSONResponse(body)`; intentional "soft 200" per PRD 07 H1).
  An orchestrator keying off HTTP status alone would be misled; the chat gate correctly reads the
  boolean (`main.py:283-292`).
- **Fix:** Return HTTP 503 when `ready:false` (keep the JSON body), or explicitly document that
  consumers must read the `ready` boolean not the status code.

### K1–K4 — Eval suite is a regression suite, not an eval deliverable
- **State:** Boundary/invariant behaviors **are** exercised as unit/integration tests:
  unbound pid (`test_chat_integration.py:491`), empty facts (`test_tools_node.py:197`),
  uncertain/missing RxNorm (`test_tools_node.py:322`), research miss (`test_verify.py:541`),
  ambiguous forms (`test_research_extract.py:117`), hallucinated-locator drop (`test_verify.py:48`),
  UC-2 creatinine (`test_chat_integration.py:111/204`), UC-3 label-backed (`test_verify.py:489`),
  UC-1 chart summary (`test_verify.py:445`). **But** they are pytest regression tests, not a curated
  eval dataset with a per-case "failure mode guarded" catalog and recorded results.
  - **K5 (claims must cite) and K6 (cross-pid/unauthorized fail closed) are MET as tested.**
  - **Label-conflict** eval case is largely absent (conflict UX deferred — see C3.5).
- **Fix:** Promote these into a documented eval catalog (case → guarded failure mode → expected
  result), add the missing conflict + allergy cases, and record a run (K7/A8).

---

## Caveats on items scored MET (worth watching)

- **A2 — Agent works on public stack:** live site responds (HTTP 302), and the agent path was
  smoked on DO per Memory Bank — **but the latest review-hardening pass (InternalEndpointGuard,
  defusedxml, readiness cache) is NOT yet redeployed to DO** (`memory-bank/activeContext.md`).
  Redeploy before relying on A2.
- **B5 — Citation is a hyperlink:** the clinical citation control is a `<button class="btn-link">`,
  not a literal `<a>`; the true anchor ("Open label") is inside the popup. Functionally a link.
- **B4 — Concise answers:** conciseness is *structural* (verified-claim segments + 1500-char
  research cap); there's no explicit brevity instruction or `max_tokens` cap in the draft prompt.

---

## Priority order (recommended)

**Fast, high-value (docs/small code):**
1. C3.5 — reconcile `ARCHITECTURE.md:20,76` conflict-surfacing wording with reality (or implement). *(clinical honesty / interview)*
2. B6 — render `retrieved_at` in the citation popup + populate it.
3. C3.7 / F5 — add allergy-contradiction guard at verify (needs C3.1 conditions/allergy in meds route).

**Engineering-floor deliverables (required by rollup):**
4. E6 — runnable API collection (Bruno/Postman).
5. A8 / K7 — eval dataset + recorded results (lift from existing unit tests).
6. A9 / L5 — cost analysis with per-tier architecture changes.
7. L2 / L3 — load tests (≥10/≥50) + baseline profiles.
8. I3 / I5 — capture tokens & cost (`wrap_openai` or log OpenRouter usage).

**Lower urgency / documentable:**
9. I6 — dashboard (or document LangSmith-UI-as-dashboard).
10. I7 — wire the three defined alerts (or keep as documented debt).
11. J3 — return 503 on `ready:false` (or document boolean-not-status).
12. E4 — populate `fhir_uuid` in citations when available.
13. A7 / A10 — demo video (all subs) + social post (final).
