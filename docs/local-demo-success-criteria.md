# Local Demo Success Criteria — Clinical Co-Pilot

**Purpose:** Checklist for QA to confirm the implementation satisfies the AgentForge case study (`docs/directions.md`), the locked plan (`ARCHITECTURE.md`), and the demo bar in `docs/ai-decision-guide.md` — **on a local dev stack**, before treating the build as interview-ready.

**Audience:** QA / builder running manual smoke + automated regressions.  
**Scope:** Local OpenEMR at `http://localhost:8300/` with Docker Compose (`docker/development-easy`). Public DigitalOcean deploy, demo video, and social post are **separate** gates (noted at the end).

**How to use:** Work top to bottom. Mark each item **Pass / Fail / N/A**. A local demo is **green** when every item in §0–§9 passes (§10 is informational only).

---

## 0. Prerequisites (environment)

| # | Criterion | How to verify | Pass when |
| --- | --- | --- | --- |
| P-1 | OpenEMR stack runs | `cd docker/development-easy && docker compose up --detach --wait` | App loads at http://localhost:8300/ |
| P-2 | Login works | Log in as `admin` / `pass` | Main tabs shell loads |
| P-3 | Sidecar is up | `docker compose ps` shows `copilot-sidecar` healthy; or `curl -s http://127.0.0.1:8080/health` (loopback port in dev compose) | `{"status":"ok"}` (or equivalent) |
| P-4 | OpenRouter configured | `OPENROUTER_API_KEY` set in compose env for sidecar | `/ready` returns HTTP **200** with `"ready": true` (not 503) |
| P-5 | Model pin is current | `OPENROUTER_MODEL=anthropic/claude-haiku-4.5` | Live Send does **not** SSE-error with `llm_http_error` / 404 |
| P-6 | Internal secret aligned | Same `COPILOT_INTERNAL_SECRET` on OpenEMR + sidecar | Chart tools succeed (not 401 on `tool_proxy.php`) |
| P-7 | Synthea demo patients | `openemr-cmd import-random-patients` (≈5–10 patients) | Rich chart data exists (see §11 patient table) |
| P-8 | Ask Co-Pilot module enabled | Menu shows **Ask Co-Pilot** tab | Tab opens without 404 — run `scripts/copilot/setup-local-demo.sh` after stack up (also runs from `start-openemr` skill unless `COPILOT_SKIP_SETUP=1`) |

---

## 1. Spine — must be real (not faked)

Per `docs/ai-decision-guide.md` §4, these seven seams must exist as working code — stubs/theater do **not** satisfy the demo.

| # | Criterion | How to verify | Pass when |
| --- | --- | --- | --- |
| S-1 | Ask Co-Pilot UI | Open tab; unbound vs bound states | Empty chat chrome; patient gate when unbound |
| S-2 | Session-proxy gateway | Send via `stream.php` (browser or Bruno) | Request carries correlation ID; sidecar called with bound `pid` from session — **not** client-supplied pid |
| S-3 | LangGraph sidecar graph | Successful turn on bound patient | SSE shows route→tools→verify path (progress then clinical) |
| S-4 | Chart tools via PHP services | Brief on pid 6 | Clinical text reflects **that patient's** chart (labs/meds/conditions), not hard-coded fixture names |
| S-5 | Research path **or** honest refuse | Dosing ask on pid 6 (`simvastatin`) | Label-backed dose **or** cited chart + explicit `no_research` — never model-memory dosing |
| S-6 | Citation + hybrid stream | Any verified turn | Event order: `progress*` → `clinical` `{text, segments}` → `citation` `{citations}` → `done` |
| S-7 | Observability minimum | After one turn | Correlation ID in disclosure JSONL; `/health` + `/ready` respond; verify event logged |

---

## 2. Auth & access control

Maps to `docs/directions.md` (Authorization) and `ARCHITECTURE.md` §4.1 / §4.9.

| # | Criterion | How to verify | Pass when |
| --- | --- | --- | --- |
| A-1 | Unbound patient gate | Open Ask Co-Pilot with no session `pid` | Blocking schedule picker over dimmed chat; composer disabled until patient selected |
| A-2 | No chart work unbound | Send message before selecting patient | Refusal / `unbound_patient` — **no** chart facts, **no** LLM burn for clinical synthesis |
| A-3 | Session pid binding | Select patient via picker; send | Gateway binds session `pid`; chart tools use that pid |
| A-4 | Client pid ignored | Tamper request body with wrong `pid` (if exposed) | Bound session pid wins; tool layer refuses cross-patient facts |
| A-5 | Internal endpoints gated | Call `tool_proxy.php` / `disclosure.php` from public IP without secret | **401** wrong secret; **403** forbidden from non-private `REMOTE_ADDR` |
| A-6 | Sidecar secret | POST `/v1/chat` without / with wrong `X-Copilot-Internal-Secret` | **401** unauthorized |
| A-7 | Browser never hits sidecar directly | Network tab during normal UI Send | Only OpenEMR `stream.php` — no browser cookies to sidecar |
| A-8 | Change patient | Bind patient A, send, then **Change patient** with non-empty transcript | Confirm dialog; thread clears; new pid required before chart work |

---

## 3. UC-1 — Pre-visit brief (core demo job)

Maps to `USERS.md` UC-1; `docs/ai-decision-guide.md` §5–§6 (rich gather, empty domains, partial failure).

| # | Criterion | How to verify | Pass when |
| --- | --- | --- | --- |
| U1-1 | Happy path brief | Bind **pid 6**; ask “Brief me” / “Why are they here?” | Short structured answer (bullets preferred over wall of text) |
| U1-2 | Multi-tool gather | Watch progress during brief | Clinical-ish progress for chart domains (e.g. `Pulling chart…`, `Pulling labs…`, `Checking medications…`) — **not** toolchain jargon |
| U1-3 | Domain coverage | Read brief content | Includes available: visit reason / conditions / last visit pointer / meds / labs signal / notes — as chart permits |
| U1-4 | Citations on facts | Inspect clinical segments | ≥ **2 verified claims** each with trailing **Source** control |
| U1-5 | Source popup | Click **Source** on a chart claim | In-pane dialog: `source_type`, title/locator, excerpt; stays in chat pane |
| U1-6 | Empty domains honest | Patient with sparse data (or domain truly empty) | Explicit one-liners (e.g. `No recent notes on file.`) — **not** silent omission of safety domains |
| U1-7 | Partial tool failure | Simulate one tool 5xx (or use test patient if scripted) | Verified domains still shown + `… unavailable — try again.` for failed domain — **not** whole-turn failure |
| U1-8 | Multi-turn follow-up | After brief, ask “Go deeper on last visit” | Same thread; same pid; no silent patient switch |
| U1-9 | No invented history | Demographics-only or empty chart patient | States gaps; does **not** invent conditions/meds/labs |
| U1-10 | Latency acceptable for demo | Time the uncached brief | Completes without `draft_parse_failed` or timeout on pid 6; progress carries the wait |

**Do not use local pid 2 (Susan Underwood) for UC-1/labs smoke** — she has no lab rows. Use **pid 6** for rich brief.

---

## 4. UC-2 — Recent labs Q&A

Maps to `USERS.md` UC-2.

| # | Criterion | How to verify | Pass when |
| --- | --- | --- | --- |
| U2-1 | Creatinine / abnormals | pid 6: “What’s their creatinine?” or “Any abnormal labs?” | Value + date + **Source** citation tied to lab result locator |
| U2-2 | Standalone labs route | Same patient, labs-only question | Progress includes `Pulling labs…`; answer is direct, not full brief dump |
| U2-3 | No recent labs | Patient without lab rows | `No recent labs on file.` (or equivalent) — not fabricated values |
| U2-4 | Descriptive only | Creatinine answer | Reports value/date/range when on file; does **not** invent CKD staging without chart support |
| U2-5 | Follow-up in thread | “Compare to prior creatinine” (if data exists) | Uses same conversation context; still pid-bound |

---

## 5. UC-3 — Medication decision-support

Maps to `USERS.md` UC-3; `ARCHITECTURE.md` §4.3; PRD 05 locks.

| # | Criterion | How to verify | Pass when |
| --- | --- | --- | --- |
| U3-1 | Label-backed dosing (happy) | pid 6: “What is a typical adult dose for simvastatin?” | Retrieved label dose in clinical text; research **Source** citation; **no** `no_research` refusal |
| U3-2 | Chart facts cited | Same turn | Active meds / allergies / conditions from chart appear with chart **Source** links when present |
| U3-3 | Decision-support disclaimer | Med / dosing turn | Short disclaimer once (physician responsible; not a prescription) |
| U3-4 | Uncertain RxNorm — no HTTP | pid 2 (Lisinopril, empty RxNorm): dosing ask | States uncertain identity; **zero** openFDA/DailyMed calls; refuses unsupported dosing |
| U3-5 | Research miss | Ask dosing for drug with no label hit (or offline stub) | Cited chart facts + explicit refuse of unsupported dosing — partial win OK |
| U3-6 | Off-chart named drug | Ask about drug **not** on active list (e.g. amoxicillin) if resolvable | Research allowed; assembly includes **not on active medication list** line |
| U3-7 | Med list without dosing | “What meds are they on?” | Lists cited chart meds; **no** `no_research` unless ask was dosing-like |
| U3-8 | Allergy contradiction | Patient with relevant allergy + conflicting med research (pid 8 or seeded case) | Contradiction surfaced or conflicting claims dropped; no silent unsafe recommendation |
| U3-9 | No PHI in research | Inspect sidecar logs / network during research | Outbound queries = drug/condition terms only — no patient name/MRN/note text |
| U3-10 | Brief/labs routes skip research | UC-1 brief or UC-2 labs question | No `Looking up label information…` unless route is `meds` + dosing-like |

**Note:** Label **conflict UX** (openFDA vs DailyMed both shown) is **deferred for MVP** — fallback-only is acceptable. Do **not** fail local demo for missing conflict UI.

---

## 6. Verification & trust

Maps to `docs/directions.md` (Verification System) and `ARCHITECTURE.md` §4.4.

| # | Criterion | How to verify | Pass when |
| --- | --- | --- | --- |
| V-1 | Cite-or-silence | Review any clinical turn | Every sentence presented as verified fact has a resolvable source; unverified claims omitted or hard-labeled — **not** mixed into verified block |
| V-2 | No unverified clinical stream | Watch SSE during turn | No clinical tokens before verify completes |
| V-3 | Hallucination drop | Automated: `E-HALLUC` in eval catalog | Invented locators dropped from clinical output |
| V-4 | Tool fact text wins | Compare claim to tool JSON | Shipped prose matches tool fact text when locator matches — model does not override with friendlier wrong numbers |
| V-5 | `source_type` preserved | Citation popup for research vs chart vs note | Types remain distinct (`chart` / `note` / `research`) |
| V-6 | Dosing gate | Non-dosing med question | No dosing claims without retrieved label |
| V-7 | Verify disclosure | Read `documents/copilot_disclosure.log` after turn | `event=verify` line with same `correlation_id`; `pass` + reason (`ok`, `claims_dropped`, etc.) |

---

## 7. Streaming & physician UX

Maps to `docs/ai-decision-guide.md` §6 and PRD 06.

| # | Criterion | How to verify | Pass when |
| --- | --- | --- | --- |
| X-1 | Hybrid SSE contract | DevTools → Network → `stream.php` | Success path: `progress*` → `clinical` → `citation` → `done` |
| X-2 | Progress copy clinical-ish | Read progress events | Uses `Pulling labs…` family — not `ROUTE=`, HTTP codes, tool names |
| X-3 | Citation batch always | Even empty verify edge case | `citation` event emitted before `done` (may be `[]`) |
| X-4 | Client buffers safely | Fast stream | UI waits for clinical + citation before painting linked claims (~2.5s timeout fallback to plain text OK) |
| X-5 | XSS safety | Inspect DOM rendering | User/assistant text via `textContent` / `createElement` — no raw `innerHTML` for chat |
| X-6 | Research “Open” link | Research citation with DailyMed/FDA URL | Allowlisted `https` only; `target=_blank` + `noopener noreferrer` |
| X-7 | Concise default | UC-1 brief | Scannable under ~90s **reading** time; depth via follow-up |
| X-8 | Error surfaces | Stop sidecar or remove API key | Non-technical error (`sidecar_unready` / generic) — not stack trace in chat |

---

## 8. Failure modes (intentional demo stories)

Per `docs/ai-decision-guide.md` §10 — at least the **required** scenarios should be demonstrable locally.

| # | Scenario | Steps | Pass when |
| --- | --- | --- | --- |
| F-1 | **Unbound patient** | Open tab without pid; try to chat | Picker / refuse — auth story clear |
| F-2 | **Missing RxNorm** | pid 2 + dosing ask | Uncertain identity; no invented code; no research HTTP |
| F-3 | **Research miss / refuse dosing** | Dosing ask with no label hit | Cited chart + explicit refuse — verify story clear |
| F-4 | Partial domain unavailable (optional) | One chart tool fails | Partial answer + unavailable line |
| F-5 | Sidecar not ready (optional) | Unset `OPENROUTER_API_KEY`; send | Immediate SSE error; no fake clinical text |

---

## 9. Automated regression gate

Run before signing off local demo. Records should match [`docs/eval/results.md`](./eval/results.md).

| # | Criterion | Command | Pass when |
| --- | --- | --- | --- |
| T-1 | Sidecar pytest suite | `pip install -r sidecar/requirements.txt pytest && export COPILOT_INTERNAL_SECRET=test-secret && pytest sidecar/tests/ -q` | All tests pass (target: **164+** cases) |
| T-2 | Eval catalog coverage | Cross-check [`docs/eval/catalog.md`](./eval/catalog.md) case IDs | E-UNBOUND, E-EMPTY, E-RXNORM, E-MISS, E-HALLUC, E-UC1–3, E-CITE, E-XPID, E-ALLERGY covered by pytest |
| T-3 | PHP isolated tests (Clinical Co-Pilot) | `openemr-cmd unit-test --filter ClinicalCopilot` (or project equivalent) | Green for gateway/chart/disclosure modules |
| T-4 | Bruno collection import | Open `docs/api/bruno/` in Bruno | Requests run against local env with session cookie + secret |
| T-5 | Health / ready | Bruno or curl: `/health`, `/ready` | `/health` always OK; `/ready` **503** when deps down, **200** when gateway + key OK |
| T-6 | Internal tool proxy | Bruno `internal/tool_proxy` with secret + bind | Returns chart JSON for allowed pid; 401/403 on bad auth |

---

## 10. Observability minimum (local)

Not a blocker for “works locally,” but required for Early/Final submission narrative.

| # | Criterion | How to verify | Pass when |
| --- | --- | --- | --- |
| O-1 | Correlation ID join | One turn end-to-end | Same ID in disclosure JSONL (`ask_start`, `tool_proxy`, `verify`) |
| O-2 | LangSmith optional | Set `LANGSMITH_TRACING=true` + key | Traces appear with redacted I/O; chat still works if unset |
| O-3 | Token usage logged | Sidecar logs on LLM turn | Prompt/completion totals logged (for cost story) |
| O-4 | Alert definitions documented | Read `sidecar/README.md` § Alerts | Three alerts defined (p95 latency, error rate, tool failure) — wiring to pager **not** required locally |

---

## 11. Reference patients (local MariaDB)

Use these consistently so QA results are reproducible.

| pid | Patient (typical) | Use for |
| --- | --- | --- |
| **6** | Rich Synthea (labs + RxNorm meds, e.g. simvastatin `312961`) | UC-1 brief, UC-2 creatinine, UC-3 dosing happy path |
| **8** | Allergies + coded Rx | UC-3 allergy / med list; **not** missing-RxNorm demo |
| **2** | Susan Underwood — Lisinopril **empty RxNorm** | UC-3 uncertain identity / no research HTTP only |
| **2** | — | **Avoid** for labs/brief richness (no lab rows) |

Seed missing-RxNorm and demo appointments: `scripts/copilot/setup-local-demo.sh --seed-only` (re-run after calendar day roll). Full local bootstrap: `scripts/copilot/setup-local-demo.sh` after Synthea import.

---

## 12. Recommended local demo script (≈15–20 min)

Ordered walkthrough that hits the interview line in `docs/ai-decision-guide.md` §16:

1. Log in → open **Ask Co-Pilot** → confirm empty chat + unbound gate (**F-1**).
2. Select **pid 6** from schedule picker → ask **“Brief me.”** → confirm progress, ≥2 **Source** links (**U1-1–U1-5**).
3. Follow-up: **“What’s their creatinine?”** (**U2-1**).
4. **“What is a typical adult dose for simvastatin?”** → label-backed dose + chart citations (**U3-1–U3-3**).
5. **Change patient** → **pid 2** → dosing ask on lisinopril → uncertain / no HTTP (**F-2**, **U3-4**).
6. Optional: off-chart drug ask → not-on-list line (**U3-6**).
7. Run **§9 automated gate**; spot-check disclosure log for last `correlation_id` (**V-7**, **O-1**).

---

## 13. Explicitly out of scope for *local* pass/fail

These remain important for submission but **do not** block marking §0–§9 green locally:

| Item | Where tracked |
| --- | --- |
| Public DO deploy smoke | https://142.93.255.212/ — batch before interview |
| Demo video (3–5 min) | README TODO |
| Social post (Final) | External |
| k6 load baselines (10 / 50 VU) | [`docs/load-tests/README.md`](./load-tests/README.md) — fill after run |
| LangSmith dashboard polish / wired paging | PRD 07 deferred |
| Label conflict dual-source UI | Deferred MVP |
| SMART on FHIR runtime | Phase 2 |
| Production HIPAA hardening (DB TLS, MFA) | Documented gaps in `AUDIT.md` |

---

## 14. Local demo sign-off

| Field | Value |
| --- | --- |
| Date | |
| Tester | |
| Git commit | |
| OpenEMR URL | http://localhost:8300/ |
| Sidecar `/ready` | ☐ 200 ready ☐ 503 not ready |
| pytest (`sidecar/tests/`) | ☐ Pass ☐ Fail — count: |
| Manual script (§12) | ☐ Pass ☐ Fail |
| Blocking failures | |
| Notes | |

**Sign-off rule:** All §0–§9 criteria **Pass** (or documented N/A with human approval) **and** §12 manual script completes without clinical trust violations (invented facts, uncited claims, silent cross-patient access, or dosing without label).

---

## Traceability

| Source | What this checklist enforces |
| --- | --- |
| `docs/directions.md` | Agentic chat, verification, observability, eval, correlation ID, health/ready, failure modes |
| `ARCHITECTURE.md` | Hybrid topology, session-proxy, tool-layer pid, cite-or-silence, hybrid SSE, UC-1/2/3, research fail-closed |
| `docs/ai-decision-guide.md` | Interview MVP bar, spine steps 1–7, physician UX, intentional failures, UC cut order, no silent clinical guessing |
| `USERS.md` | PCP persona, UC-1/2/3 jobs and edge cases |
| PRDs 01–07 | Concrete acceptance for tab, gateway, sidecar, chart tools, research, citations, observability |
