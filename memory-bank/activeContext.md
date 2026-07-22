# Active Context

## Current focus

**PRD 04 chart tools shipped locally (2026-07-21):** Real PHP chart readers behind `tool_proxy` (`patient_context` · `labs` · `meds` · `notes`); stubs removed. Sidecar brief gathers all four in parallel with partial-domain failure + empty/unavailable assembly. Isolated PHPUnit ClinicalCopilot **123** + sidecar pytest **70** green. Local DB smoke pid **6** (labs/meds rich) + pid **8** (allergies).

**DO:** Previously green on stub path (2026-07-22 UTC sync). Needs **overlay + sidecar redeploy** to pick up PRD 04 (Chart PHP + renamed tools) — batch with interview prep; not a merge gate.

Next: **PRD 05** research (openFDA → DailyMed) **or** DO redeploy smoke on rich patient before interview.

## PRD 04 decisions (locked — implemented)

- **Tools:** `patient_context` · `labs` · `meds` · `notes` (no `*_stub`).
- **Routes:** `brief` → all four parallel (`max_workers` 4); `labs`/`meds` → single tool.
- **Fail-closed vs empty vs throw:** auth/bind unchanged. `facts: []` = success. One tool 5xx → partial answer + allowlisted unavailable line; all tools fail or auth → whole-turn error.
- **Empty/unavailable copy:** sidecar `assemble_clinical` (no fake locators). Meds prefer `data.meta` `{active_med_count, allergy_count}`.
- **Domain ownership:** context = last encounter + active problems only; labs/meds/notes own their domains.
- **Active Rx:** `active=1` + open-ended `end_date`; missing RxNorm → uncertain wording.
- **Notes:** `form_clinical_notes` only; Synthea empty OK.
- **Impl:** `src/ClinicalCopilot/Chart/` Schedule-style (injectable loaders, **not** BaseService); `ChartToolDispatcher` → `ToolProxyService`; sidecar `tool_domain_errors`.
- **Out of 04:** research, citation UI, LangSmith, TTL cache, note seed, FHIR-primary.

## Builder context (for how to teach / decide with this user)

- Mid-level SWE; some small LLM agent + tool-calling experience, **not confident** yet.
- **Stronger:** general eng; OpenRouter “I’ve seen it”; Docker = containers exist.
- **Weak / new:** LangGraph **vs** LangSmith; SSE/streaming; OAuth/SMART; FHIR; OpenEMR internals; Compose beyond single-container intuition.
- Build process: PRD-per-roadmap-step, then plan/execute skills — mental models live in PRDs/plans, not long chat lectures.
- Success bar: (1) defend architecture in interview, (2) ship a clean **generally working** demo — not production, not especially complex.
- When explaining stack: contrast confusable pairs (Graph vs Smith, gateway vs sidecar, FHIR vs SMART).
- **Ambiguity:** follow [`docs/ai-decision-guide.md`](../docs/ai-decision-guide.md) (sits under ARCHITECTURE as how-to-choose).

## Decisions that stuck

### Infra / deploy

- Host EHR on **DO NYC droplet + Docker Compose**
- Stage 2 = official `openemr/openemr`; fork-built image when agent lands
- Droplet **2 GB / $12**; demo **`admin`/`pass`**; self-signed HTTPS; document DB TLS/MFA/encryption gaps
- URL: https://142.93.255.212/
- **Sidecar:** same host, **single** LangGraph worker; honest one-physician concurrency

### Product / persona / jobs (codified in USERS.md)

- **Persona:** clinic / primary care physician only (~30–90s between rooms)
- **UC-1 / UC-2 / UC-3** as in USERS.md; chart read-only; decision support only
- Twin files: `USERS.md` (canonical) + `USER.md`
- Interview demo > Gauntlet rubric completeness

### Auth / data / compliance

- **Session-proxy gateway** (browser never sends cookies to sidecar); SMART later
- Tool-layer **pid** checks, fail closed; **patient picker** if unbound
- Chart: **PHP services via gateway** (FHIR primary = phase 2 talk track)
- Synthea ~5–10 patients local + DO; no invented RxNorm; optional free-text med for missing-RxNorm demo
- Separate PHI-disclosure + verification log; redacted LangSmith; OpenRouter BAA/no-training posture; demo data only

### Agent stack

- Hybrid OpenEMR gateway + LangGraph sidecar
- OpenRouter **Haiku everywhere** (MVP); pin **`anthropic/claude-haiku-4.5`** (retired `claude-3.5-haiku` → 404); temp near zero for factual turns
- `llm_http_error` = OpenRouter HTTP status (404 bad slug, 402 no credits, etc.) — not “missing key” (`llm_not_configured`)
- LangSmith redacted + app correlation IDs + disclosure log

### Research (UC-3)

- **openFDA primary**, DailyMed fallback
- Drug/condition terms only; no PHI
- Dosing/interactions only from retrieved sources; else chart facts + explicit refuse
- Label conflicts → surface both; never silently pick a winner

### Verification / streaming / state

- Structured claim→source; **cite-or-silence** on primary clinical path (no skim-able warning as verify substitute)
- Verify emits **tool fact text** for matching locators (never model prose); refusals allowlisted (`no_research` canonical)
- Demo softening (decision guide): separate hard-labeled **`unverified`** block OK if needed; prefer refuse when unsure; never mix into verified prose
- **Hybrid SSE:** progress early; clinical after verify
- **Open-tab transcript** until closed (resend/session-held); sanitized role/text only; no pre-ask cache / durable checkpointer for MVP
- Patient switch: no silent pid continue
- Ask Co-Pilot ACL: `patients/demo` on index + stream; tool_proxy re-checks bind **pid + user_id**

### UX (locked)

- First-class **Ask Co-Pilot** tab; empty chat start; citation hyperlinks → in-pane popup; concise; omit > guess
- Unbound → **blocking schedule picker popup** (not a warning bar); provider-only today schedule; explicit click to bind; Change patient clears thread after confirm

### Demo / agent decision policy (2026-07-21)

- North star: interview MVP on DO; extensible seams; few happy-path bugs; **not** production
- Engineering guesses OK; clinical claims must be verified+cited, labeled unverified, or refused
- Shortcuts/fakes OK if noted as Memory Bank debt; **do not** fake roadmap spine steps 1–7
- Under pressure: keep UC-1 → UC-2; label-backed UC-3 if easy; else thin UC-3; vertical trust slice before wide skeleton
- **Keep shipping spine locally;** batch DO deploy/flakiness fixes before interview (DO still final talk-track truth)
- Escalation: auth/PHI/verify-bypass/chart writes/DO data loss/stack-lock changes **or** ~90s physician-story changes — see decision guide

### Physician UX defaults (2026-07-21, decision guide §6)

- **~90s budget:** design rich brief for post-cache speed; accept uncached latency now
- **Partial tool failure:** ship verified domains + `… unavailable — try again.` (never invent filler; never whole-turn fail if anything verified)
- **Empty domains:** explicit one-liners (`No allergies on file.` etc.) — omit ≠ “none checked”
- **Citations:** link **every** verified claim; popup for details; conflicts = short chat + both linkable
- **Progress:** clinical-ish (`Pulling labs…`) — no toolchain jargon
- **UC-3:** one label-backed dosing/interaction nice if PRD 05 makes it easy

## Deferred (explicit in ARCHITECTURE.md)

Exact tool schemas · auto-brief · pre-ask caching · multi-worker scale · interaction APIs · SMART runtime · FHIR dual path · production hardening · full eval catalog (categories reserved)

## Deferred debt (shortcuts)

- **Brief four-tool bundle not cached yet** (planned TTL ~30–60s); first brief may be slow under 120s gateway budget.
- **Synthea notes empty:** `form_clinical_notes` unused by CCDA import — honest empty domain; optional seed later for interview script.
- **Draft parse under rich tools:** watch `draft_parse_failed` after four-tool gather; truncate oldest labs before draft if needed.
- **Optional fhir_uuid** on ChartFact supported but loaders do not populate yet (PRD 06 citations).
- **Compose image build locally:** Docker Hub / `docker-credential-desktop` can hang; host `uvicorn` + pytest used historically. DO/local should rebuild `copilot-sidecar` on deploy.
- **DO overlay bind-mounts (not fork-built image):** Co-Pilot PHP under `/opt/openemr/overlay/`; needs sync for PRD 04 Chart/.
- **DO schedule:** `CoPilot Demo%` appts need re-seed after day roll / rebuild.
- Per-turn tool tickets (using correlation bind file store for MVP).
- Durable disclosure DB (JSONL file stub under `sites/default/documents/`).
- Citation popups deferred (PRD 06).
- Dosing refusal now keyword-gated (`dose|dosing|dosage|titrate|how much|mg/kg`) — research-backed dosing still PRD 05.
- No rate limiting on `stream.php` (OpenRouter cost exposure) — production hardening, out of MVP scope.
- **Dev compose still defaults** `COPILOT_INTERNAL_SECRET` to weak local value (production compose now requires env); rotate before public demo.
- Entry-script / JS / SidecarClient automated tests still thin (verify/ACL/transcript/Chart covered in units).
- **Picker:** recurring appts not expanded; provider-only schedule (no facility fallback).

## Remaining / next

1. DO redeploy overlay (Chart + ToolProxy) + sidecar recreate; smoke pid with labs/meds
2. PRD 05 research tools (openFDA → DailyMed)
3. PRD 06–07 citations / LangSmith thin follow-on

## Out of scope right now

- Production credential rotation, DB TLS, MFA, ATNA, chart write-back
- Concurrent multi-physician load testing as a demo requirement
