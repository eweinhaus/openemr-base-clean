# Active Context

## Current focus

**`ARCHITECTURE.md` locked**; **Synthea done** (local + DO). **`docs/ai-decision-guide.md`** written (local, untracked) — use for ambiguity, shortcuts, cut order, escalation. Next: implement roadmap via **one PRD per steps 1–7** (`/generate-prd` → `/create-plan-ethan` → `/execute-plan-ethan`). Goal: working interview MVP on **live DO**; discuss unfinished complexity verbally.

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
- OpenRouter **Haiku everywhere** (MVP); temp near zero for factual turns
- LangSmith redacted + app correlation IDs + disclosure log

### Research (UC-3)

- **openFDA primary**, DailyMed fallback
- Drug/condition terms only; no PHI
- Dosing/interactions only from retrieved sources; else chart facts + explicit refuse
- Label conflicts → surface both; never silently pick a winner

### Verification / streaming / state

- Structured claim→source; **cite-or-silence** on primary clinical path (no skim-able warning as verify substitute)
- Demo softening (decision guide): separate hard-labeled **`unverified`** block OK if needed; prefer refuse when unsure; never mix into verified prose
- **Hybrid SSE:** progress early; clinical after verify
- **Open-tab transcript** until closed (resend/session-held); no pre-ask cache / durable checkpointer for MVP
- Patient switch: no silent pid continue

### UX (locked)

- First-class **Ask Co-Pilot** tab; empty chat start; citation hyperlinks → in-pane popup; concise; omit > guess

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

_None yet — add here when faking non-spine work for demo speed._

## Remaining / next

1. PRD + implement roadmap steps 1–7 per `ARCHITECTURE.md` + `docs/ai-decision-guide.md`
2. Smoke on DO after runtime waves; LangSmith + eval/narrative as thin follow-on

## Out of scope right now

- Production credential rotation, DB TLS, MFA, ATNA, chart write-back
- Concurrent multi-physician load testing as a demo requirement
