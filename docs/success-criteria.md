# Clinical Co-Pilot — Technical Success Criteria

**Purpose:** QA acceptance checklist for calling the work **completed**.  
**Derived from:** [`docs/directions.md`](./directions.md), [`ARCHITECTURE.md`](../ARCHITECTURE.md).  
**Independent of implementation:** criteria are plan/requirement-based, not a code audit.

---

## A. Submission & hard gates

| ID | Criterion |
| --- | --- |
| A1 | Public deployment URL works; OpenEMR loads with sample/demo patients. |
| A2 | For early/final: Co-Pilot agent works on that same public stack (not only local). |
| A3 | Repo includes setup guide, architecture overview, and deployed link. |
| A4 | `AUDIT.md` exists with a ~500-word front summary of key findings (security, performance, architecture, data quality, compliance). |
| A5 | User doc exists (`USERS.md` / `USER.md` per directions) with a narrow target user, workflow, and use cases; each use case answers why an agent (not a dashboard/list). |
| A6 | `ARCHITECTURE.md` exists with ~500-word summary of key decisions/tradeoffs and traces capabilities to those use cases. |
| A7 | Demo video (3–5 min) shows working product and key decisions. |
| A8 | Eval dataset + results are present and defensible. |
| A9 | AI cost analysis covers actual dev spend and projected cost at 100 / 1K / 10K / 100K users, including architectural changes at each scale (not tokens × users only). |
| A10 | Final only: social post on X or LinkedIn describing the project, showing the agent, tagging @GauntletAI. |

---

## B. Product surface & UX (physician 30–90s budget)

| ID | Criterion |
| --- | --- |
| B1 | First-class **Ask Co-Pilot** tab exists in the same iframe-tab shell pattern as Calendar/Messages. |
| B2 | Chat starts empty (no auto-filled wall of text on open). |
| B3 | Interface is multi-turn conversational (follow-ups deepen the same thread). |
| B4 | Answers default to concise, visit-relevant content suitable for a ~30–90s window. |
| B5 | Every clinical claim shown in the UI is cited; citation is a hyperlink. |
| B6 | Citation click opens an **in-pane** source popup with at least: `source_type`, title, `retrieved_at`, locator, excerpt. |
| B7 | Chart remains **read-only** (no write-back / prescribing actions). |
| B8 | Meds framing is decision support only (no autonomous prescribing). |
| B9 | Prefer omit / “not on file” / “research unavailable” over unsupported plausible statements. |
| B10 | Progress messaging is clinical-ish and non-clinical (e.g. “Pulling labs…”) — not raw internal stack dumps. |

---

## C. Use cases (must work end-to-end)

### UC-1 — Pre-visit brief

| ID | Criterion |
| --- | --- |
| C1.1 | Agent can synthesize why-here, conditions, last visit, selective notes, and high-signal structured pointers. |
| C1.2 | Brief facts verify to chart locators; structured data preferred over free-text notes when both exist (MVP: prompt preference + cite-or-silence — no silent invent from notes). |
| --- | --- |
| C1.3 | Incomplete/sparse chart yields honest gaps, not invented history. |

### UC-2 — Labs Q&A

| ID | Criterion |
| --- | --- |
| C2.1 | Agent answers recent labs / abnormals with chart locators for value, date, and abnormal flags. |
| C2.2 | Ambiguous lab names are handled without inventing a specific result (MVP: cite-or-silence + research form ambiguity → miss; no invented numeric result). |
| C2.3 | Follow-up lab questions reuse the bound patient and cited result path. |

### UC-3 — Med decision-support

| ID | Criterion |
| --- | --- |
| C3.1 | Combines chart meds / allergies / conditions with openFDA (DailyMed fallback). |
| C3.2 | Outbound research queries contain **drug/condition terms only** — no PHI. |
| C3.3 | Dosing / interaction / label-backed claims appear only when backed by a retrieved source (URL/title/section). |
| C3.4 | If research misses: return cited chart facts + explicit refusal of dosing/interactions (no model-memory dosing). |
| C3.5 | MVP: openFDA→DailyMed is **fallback-only** (never invent a dose). Dual-source conflict surface is deferred post-MVP — docs must not claim conflicts are surfaced until implemented. |
| C3.6 | Missing RxNorm → uncertain drug identity; no invented codes; no dosing research until identity is clear. |
| C3.7 | Allergy contradictions are flagged / rejected per domain rules. |
| C3.8 | Off-chart named drug questions are allowed with honest “not on list” / chart-vs-research framing where applicable. |

### Multi-turn & patient binding

| ID | Criterion |
| --- | --- |
| C4.1 | Typical flow (brief + 1–2 follow-ups) maintains context while the Co-Pilot tab stays open. |
| C4.2 | Closing the tab ends the held transcript (no expectation of durable cross-session chat DB for MVP). |
| C4.3 | Patient switch does **not** silently continue prior `pid` context; thread rebinds or resets. |
| C4.4 | No patient selected → patient-picker gate before any chart work. |

---

## D. Authorization & trust boundaries

| ID | Criterion |
| --- | --- |
| D1 | Browser talks **only** to OpenEMR (no direct browser→sidecar cookies/credentials). |
| D2 | Gateway validates existing OpenEMR session before agent work. |
| D3 | Gateway binds patient `pid`; client- or model-supplied patient ids are ignored. |
| D4 | Sidecar is called with internal credential / service secret; sidecar never sees browser cookies. |
| D5 | Every chart tool call re-checks allowed `pid` and **fails closed** on mismatch/spoof. |
| D6 | Unbound or wrong-pid attempts refuse before chart tools run. |
| D7 | Multi-role panel ACL (nurse/resident) is explicitly out of MVP — system does not claim it. |
| D8 | SMART on FHIR is documented as later, not required as MVP runtime. |

---

## E. Topology & integration contracts

| ID | Criterion |
| --- | --- |
| E1 | Hybrid topology is live: UI → session-proxy gateway → LangGraph sidecar → tools/LLM/verify. |
| E2 | Chart reads go gateway → PHP services in `/src` (services-first); sidecar does not hit MariaDB directly. |
| E3 | Sidecar does not use a second long-lived OpenEMR chart credential for chart reads in MVP. |
| E4 | Citations always include table+pk; FHIR UUID included when available. |
| E5 | Strict schemas exist for tool inputs/outputs (Pydantic/Zod or equivalent) as the contract source of truth. |
| E6 | Runnable API collection (Postman/Bruno/etc.) covers core agent endpoints so graders can run workflows without reading source. |
| E7 | LLM is OpenRouter with Haiku pinned for MVP factual turns; temperature near zero for factual work. |
| E8 | Stronger models are never used as a substitute for verification. |

---

## F. Verification system (cite-or-silence)

| ID | Criterion |
| --- | --- |
| F1 | Every agent response that reaches the user passes through a verification layer. |
| F2 | Model emits structured claim/source pairs; unverified claims are dropped (not shown with a skim-able warning). |
| F3 | Chart claims require a resolvable locator (table+pk and/or FHIR id; note id+span as applicable). |
| F4 | Research claims require retrieved locator (URL/title/section). |
| F5 | Domain constraints enforced at verify: allergy contradiction; missing RxNorm uncertainty; no invented staging/severity from a single lab; research-backed claims only with sources. |
| F6 | Limitations of verification are documented and honest. |
| F7 | App retains a disclosure / verification log keyed by correlation ID (pass/fail). |

---

## G. Streaming (hybrid SSE)

| ID | Criterion |
| --- | --- |
| G1 | Transport is gateway `POST` → SSE into the Co-Pilot iframe. |
| G2 | `progress` events stream immediately / during tools and contain non-clinical status only. |
| G3 | `clinical` events stream only after verify clears content. |
| G4 | `citation` payloads accompany clinical content for popups. |
| G5 | Terminal `done` / `error` events end the stream predictably. |
| G6 | No unverified clinical tokens appear on screen. |

---

## H. Failure modes & graceful degradation

| ID | Criterion |
| --- | --- |
| H1 | Chart tool failure surfaces a transparent, predictable error (no silent empty “success”). |
| H2 | Incomplete patient record → gaps stated; no fabrication to fill blanks. |
| H3 | Unexpected model output is caught by verify / error path rather than shown as fact. |
| H4 | Research timeout/miss → chart-only answer + explicit dosing/interaction refusal. |
| H5 | Research optional degradation is allowed without claiming full med-label certainty. |
| H6 | System does not crash the EHR shell when the agent fails. |

---

## I. Observability

| ID | Criterion |
| --- | --- |
| I1 | Every agent invocation gets a unique correlation ID at the gateway. |
| I2 | Correlation ID appears across gateway ↔ sidecar ↔ tool ↔ LLM hops and in related logs so a full trace can be rebuilt from logs alone. |
| I3 | LangSmith (or equivalent) is wired and used: graph steps, order of work, step latency, tool failures, tokens/cost. |
| I4 | LangSmith traces are **redacted** (no note bodies / identifiers as free PHI dump). |
| I5 | From observability alone you can answer: what ran and in what order; how long each step took; which tools failed and why; tokens and cost. |
| I6 | Dashboard (MVP): LangSmith UI (when keys set) + disclosure JSONL covers request/error/latency (Smith), tool_proxy lines, and verify pass/fail (`event=verify`); retries N/A (`max_retries=0`). Purpose-built Grafana optional later. |
| I7 | At least three alerts defined and documented: p95 latency threshold, error-rate threshold, tool-failure-rate threshold — each with meaning and on-call response. (Wiring to a paging backend may remain documented debt if definitions + response are present.) |

---

## J. Health / readiness

| ID | Criterion |
| --- | --- |
| J1 | Separate `/health` endpoint: process alive. |
| J2 | Separate `/ready` endpoint: checks meaningful dependencies (OpenEMR gateway path + OpenRouter at minimum). |
| J3 | `/ready` does not unconditionally return 200 when dependencies are down. |
| J4 | Research dependency may be optional/degraded in readiness per architecture — but that behavior is intentional and documented. |

---

## K. Evaluation suite

| ID | Criterion |
| --- | --- |
| K1 | Eval suite exists with intentional pass/fail definitions (not ad hoc demos). |
| K2 | Cases cover more than happy paths: empty/sparse chart; cross-pid / unbound; missing RxNorm; research miss / label conflict; ambiguous lab name. |
| K3 | Happy paths covered: UC-1 brief; UC-2 creatinine (or equivalent concrete lab); UC-3 label-backed question. |
| K4 | Every eval case documents the failure mode it guards (boundary, invariant, or regression risk). |
| K5 | Invariant covered: claims must cite a source (or be omitted). |
| K6 | Authorization edge: attempts to extract data for unauthorized/wrong patient fail closed. |
| K7 | Results of running the suite are recorded for submission/interview. |

---

## L. Performance, load, and cost honesty

| ID | Criterion |
| --- | --- |
| L1 | Design target is seconds-scale usefulness for a between-rooms physician, with explicit tradeoffs when completeness is deferred. |
| L2 | Baseline CPU, memory, latency, and throughput profiles are captured under load scenarios and included in submission. |
| L3 | Load/stress tests at ≥10 and ≥50 concurrent users against the deployed agent; record p50/p95/p99 and error rate at each level. |
| L4 | Architecture’s honest single-worker / 2 GB limit is documented; demo does not claim multi-physician HA it cannot support. |
| L5 | Cost analysis includes projected spend and what must change architecturally at each user tier. |

---

## M. HIPAA / PHI posture (demo-constrained)

| ID | Criterion |
| --- | --- |
| M1 | Only demo data is used. |
| M2 | Treat LLM path as BAA / no-training posture in docs and ops narrative. |
| M3 | Payloads minimized; research path carries no PHI. |
| M4 | Observability redacts sensitive clinical content. |
| M5 | Disclosure/verification logging exists for what was shown and whether it verified. |
| M6 | Architecture docs demonstrate understanding of storage, transmission, logging, and access constraints (not acronym-only). |
| M7 | Co-Pilot UI manually escapes output appropriately given OpenEMR Twig `autoescape` off (XSS safety for agent-rendered content). |

---

## N. Known non-goals (completion = does not falsely claim these)

| ID | Criterion |
| --- | --- |
| N1 | No multi-role panel ACL shipped as done. |
| N2 | No SMART runtime required for MVP “done.” |
| N3 | No FHIR dual-path as primary chart access for MVP. |
| N4 | No pre-ask caching / multi-worker HA required for MVP “done.” |
| N5 | No full clinical interaction engine / separate interaction API required. |
| N6 | No durable chat DB / LangGraph checkpointer DB required for MVP “done.” |
| N7 | Production hardening (DB TLS, MFA, ATNA, etc.) not required before demo value — but remaining risks are documented. |

---

## O. Interview defensibility

| ID | Criterion |
| --- | --- |
| O1 | Can walk trust boundaries: session-proxy, tool-layer pid, picker, fail-closed. |
| O2 | Can defend verify placement, cite-or-silence, and why unverified-with-warning was rejected. |
| O3 | Can explain tool-fail / missing-record / research-miss behavior with a live or recorded example. |
| O4 | Can explain eval cases that a happy-path demo would miss, and what the suite found. |
| O5 | Can speak phase-2 SMART/FHIR without contradicting MVP services-first path. |
| O6 | Can name the failure mode that worries you most and why (aligned with architecture limitations). |

---

## Definition of “completed” (rollup)

Call the work **completed** when **all of the following are true**:

1. **Gates:** A1–A9 (and A10 at final) are met.
2. **Spine demo:** B1–B10, C (UC-1/2/3 + multi-turn), D, E1–E4, F, G, H pass on the deployed environment with demo patients.
3. **Engineering floor from directions:** E5–E6, I, J, K, L2–L3 are met (even if scale story is “honest single-worker”).
4. **Safety posture:** M and N are satisfied (including what you explicitly do *not* claim).
5. **Defendable:** O can be answered without contradicting the running system.

If any of **cite-or-silence (F)**, **pid fail-closed (D)**, **hybrid SSE no unverified clinical (G)**, or **PHI-free research (C3.2 / M3)** fail, the product is **not** complete regardless of demo polish.
