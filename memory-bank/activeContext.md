# Active Context

## Current focus

**Local Co-Pilot LLM path green (2026-07-21):** OpenRouter credits funded; model pin `anthropic/claude-haiku-4.5`. Session `stream.php` smoke (admin, pid 2) → progress → clinical → done. User confirmed UI Send works.

**Earlier same day:** patient schedule picker popup + QA hardening shipped locally (not yet on DO).

**DO still behind local:** overlay rsync (picker + schedule + QA), `OPENROUTER_MODEL=anthropic/claude-haiku-4.5` + key/credits on `/opt/openemr/.env`, sidecar recreate, optional same-day appt seed, browser-smoke on https://142.93.255.212/.

Next: **DO redeploy/smoke**; then **PRD 04** real chart services behind tool_proxy.

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
- Under pressure: keep UC-1 → UC-2; thin UC-3 first; vertical trust slice before wide skeleton
- Live DO > local for demo truth
- Escalation: auth/PHI/verify-bypass/chart writes/DO data loss/stack-lock changes — see decision guide

## Deferred (explicit in ARCHITECTURE.md)

Exact tool schemas · auto-brief · pre-ask caching · multi-worker scale · interaction APIs · SMART runtime · FHIR dual path · production hardening · full eval catalog (categories reserved)

## Deferred debt (shortcuts)

- **Stub chart facts until PRD 04:** tool_proxy returns fixture locators (not live PHP services / DB).
- **Compose image build locally:** Docker Hub / `docker-credential-desktop` can hang; host `uvicorn` + pytest used for PRD 03 verification. DO/local should rebuild `copilot-sidecar` once pull works; set `OPENROUTER_API_KEY` on host.
- **DO overlay bind-mounts (not fork-built image):** Co-Pilot PHP lives under `/opt/openemr/overlay/` mounted into stock `openemr/openemr:latest`; survives recreate. Full fork image still deferred.
- **OPENROUTER_API_KEY missing on DO** — sidecar up but route/draft will fail until key is set in `/opt/openemr/.env`.
- Per-turn tool tickets (using correlation bind file store for MVP).
- Durable disclosure DB (JSONL file stub under `sites/default/documents/`).
- Citation popups deferred (PRD 06).
- Dosing refusal now keyword-gated (`dose|dosing|dosage|titrate|how much|mg/kg`) — non-dosing meds turns ship facts without refusal; research-backed dosing still PRD 05.
- No rate limiting on `stream.php` (OpenRouter cost exposure) — production hardening, out of MVP scope.
- **Dev compose still defaults** `COPILOT_INTERNAL_SECRET` to weak local value (production compose now requires env); rotate before public demo.
- Entry-script / JS / SidecarClient automated tests still thin (verify/ACL/transcript covered in units).
- **Picker:** recurring appts not expanded; provider-only schedule (no facility fallback); local demo rows `CoPilot Demo%` need re-seed after day roll / rebuild / DO.

## QA hardening pass (2026-07-21, post-review)

- Gateway timeout default 45→**120s** (stream.php + both compose files) — must cover route+draft (30s LLM budget each); `set_time_limit(0)` in stream.php (php.ini max_execution_time=60 would kill slow turns).
- stream.php fails closed on `userId <= 0` (broken session) before binding.
- Sidecar: dosing refusal only for dosing-like messages (not all `meds` routes); verify dedupes claims by locator; refuse node caps message at 4000 chars (mirrors gateway); `/ready` false when `OPENROUTER_API_KEY` missing.
- JS client: system bubble when stream ends without done/error (was silent); 5s pid poll (skipped while streaming) syncs gate + shows patient-changed notice; removed dup JSDoc.
- FileCorrelationBindStore sweeps expired bind files on every put.
- Removed no-op `use Throwable;` in stream.php/tool_proxy.php (emitted PHP warning).
- Tests updated+added: sidecar pytest 53 pass; ClinicalCopilot isolated PHPUnit 51 pass (2 env skips). DO redeploy needed to pick these up (overlay bind-mounts + sidecar rebuild).

## Remaining / next

1. Buy OpenRouter credits (account has $0) → recreate sidecar local + DO (`OPENROUTER_MODEL=anthropic/claude-haiku-4.5`) → browser-smoke Send; **rsync overlay** (picker + schedule API + QA fixes), seed DO same-day appts for admin
2. PRD 04 chart services behind tool_proxy; then 05–07
3. LangSmith + eval/narrative as thin follow-on

## Out of scope right now

- Production credential rotation, DB TLS, MFA, ATNA, chart write-back
- Concurrent multi-physician load testing as a demo requirement
