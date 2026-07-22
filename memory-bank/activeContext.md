# Active Context

## Current focus

**PRD 06 on DO (2026-07-22):** Commit `58eb115` pushed + redeployed to https://142.93.255.212/. Overlay cite UI + sidecar rebuild. Bind-seeded pid **6** dosing SSE → progress (`Pulling chart…` / `Checking medications…` / `Looking up label information…`) → `clinical`+`segments` → `citation` (research `source_type`, DailyMed url) → `done`. Module active; OpenRouter **set**. Login HTTP 200.

**Next:** Optional Ask Co-Pilot click-path UI smoke (Source popup); then PRD 07 (LangSmith thin).

## PRD 06 decisions (locked — implemented)

Canonical: `docs/PRDs/06-citations-hybrid-sse.md` (H1–H13).

- **Link affordance:** Claim text plain + trailing **Source** control (not whole-claim underline).
- **Layout:** Newline between claim segments; assembly/refusal/disclaimer/empty **unlinked**.
- **Clinical SSE:** `{ text, segments[] }` — `kind: claim|assembly`; claims carry `citation_id` (`c1…n`).
- **Citation SSE:** One batch `{ citations: [...] }` **after** `clinical`, before `done` (always emit, even if empty).
- **Client:** Buffer until clinical+citation (~2.5s timeout / `done` → plain `text`); DOM-only (`textContent` / createElement); no `innerHTML`/markdown.
- **Popup:** Picker-style `#acp-cite` dialog; `{ source_type, title, excerpt, locator }`; mutual exclusion with picker; focus returns to Source.
- **Research Open label:** Allowlisted `https` only (`dailymed.nlm.nih.gov`, `api.fda.gov`) → `target=_blank` + `noopener noreferrer`.
- **Builders:** `build_clinical_payload` + `build_citation_records` in `sidecar/app/claims.py`; emit/stream wire state `clinical_segments` / `citations`.
- **Progress:** `Pulling chart…` / `Pulling labs…` / `Checking medications…`; keep `Looking up label information…`; drop `Routing…` / `Fetching chart…`.
- **Gateway:** Pass-through only — citations built in sidecar from verified claims.
- **Non-goals still out:** conflict UX, LangSmith (07), unverified UI, historical transcript re-hydrate, required `fhir_uuid`/`retrieved_at`.

## PRD 07 planning notes (for next PRD write — not started)

Guide defaults (`docs/ai-decision-guide.md` §11): redacted LangSmith traces; correlation ID joins app disclosure log; `/ready` false → fail closed on agent path + short non-technical UI error; **stubs OK** — no LangSmith dashboard polish for interview.

**Already partly present (do not rebuild from scratch):**

- Sidecar `GET /health` (alive) + `GET /ready` (gateway + OpenRouter; **must not** probe FDA — PRD 05 H10).
- Gateway mints **correlation ID**; disclosure log **stub** (JSONL file) from PRD 02.
- SSE `error` codes (`llm_not_configured`, `llm_http_error`, etc.) already surface in UI.

**Likely PRD 07 scope (thin):**

1. Wire **LangSmith** on sidecar (env keys) with **redaction** — no note bodies / identifiers in traces; join on `correlation_id`.
2. Confirm `/health` + `/ready` behavior on DO + local; document fail-closed when unready.
3. Optional: richer disclosure/verification log lines keyed by correlation ID (still file stub OK — durable DB deferred).
4. Interview talk track: LangGraph ≠ LangSmith; app owns disclosure log + correlation IDs.

**Keep out of PRD 07:** citation UI (06 done), conflict UX, multi-worker, durable checkpointer, eval catalog polish, production HA.

**Builder teaching note:** Contrast Graph (workflow) vs Smith (traces) explicitly — weak mental model today.

## PRD 05 decisions (locked — implemented)

- **Happy path:** One label-backed **dosing** answer — local **pid 6 simvastatin** (RxNorm `312961` in DB; chart fact text does **not** embed RxCUI when present — query uses scrubbed generic/brand term).
- **Uncertain identity:** local **pid 2** Lisinopril (empty RxNorm) — **no HTTP**; pid 8 is allergies + coded Rx (not missing-RxNorm).
- **Conflict UX:** **Skipped** for MVP/demo — no dual-fetch compare, no conflict module/tests.
- **Off-chart named drug:** Allowed if name → single Rx SPL; **assembly must** say not on active list (not prompt-only).
- **Placement:** `sidecar/app/research/` only — **never** `tool_proxy`.
- **Verify:** Keep `source_type=research` (no force to `chart`); `no_research` only if dosing-like **and** no verified research dosing fact.
- **DailyMed:** Real fallback after openFDA miss/timeout/5xx/empty dose; ≤5s hard cap; no retries.
- **Gates:** `meds` route only; dosing-like (shared `is_dosing_like`); scrubbed `DrugQuery` only; uncertain RxNorm blocks research; `/ready` does not probe FDA.
- **Optional env:** `OPENFDA_API_KEY` on compose (dev + production).
- **Non-goals:** interaction APIs, option lists, research on brief/labs (citation popups = PRD 06).

## PRD 04 decisions (locked — implemented)

- **Tools:** `patient_context` · `labs` · `meds` · `notes` (no `*_stub`).
- **Routes:** `brief` → all four parallel (`max_workers` 4); `labs`/`meds` → single tool.
- **Fail-closed vs empty vs throw:** auth/bind unchanged. `facts: []` = success. One tool 5xx → partial + unavailable line.
- **Empty/unavailable copy:** sidecar assemble (no fake locators). Meds `data.meta` counts.
- **Domain ownership:** context = last encounter + problems; labs/meds/notes own domains.
- **Active Rx:** `active=1` + open-ended `end_date`; missing RxNorm → uncertain wording.
- **Impl:** `src/ClinicalCopilot/Chart/` Schedule-style; `ChartToolDispatcher` → `ToolProxyService`.

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

### Research (UC-3) — PRD 05 locks (code landed)

- **openFDA primary**, DailyMed **fallback only** (not dual-fetch conflict)
- Drug/condition terms only; scrubbed `DrugQuery` — never raw user message
- Dosing only from retrieved sources; else chart + `no_research`
- **Conflict UX deferred** (ARCHITECTURE still mentions it for later; MVP skips)
- Off-chart named drug OK if single Rx SPL + mandatory not-on-list assembly line
- Brand↔generic post-hit reconcile may flip `on_chart=true`
- Optional `OPENFDA_API_KEY` on DO / compose
- Module: `sidecar/app/research/` — dosing, scrub, resolve, client, extract, constants

### Verification / streaming / state

- Structured claim→source; **cite-or-silence** on primary clinical path
- Verify emits **tool fact text**; keep `source_type` (`research`/`note`/`chart`) — do not force chart
- Refusals allowlisted (`no_research` canonical); dosing refuse **conditional** (dosing-like ∧ no verified research dosing fact)
- **Hybrid SSE (PRD 06 coded):** `progress*` → `clinical` `{text,segments}` → `citation` `{citations}` → `done`; clinical-ish progress
- **Open-tab transcript** until closed; sanitized role/text only (citations display-only; resend stays plain)
- Ask Co-Pilot ACL: `patients/demo`; tool_proxy re-checks bind **pid + user_id**

### UX (locked)

- First-class **Ask Co-Pilot** tab; empty chat start; concise; omit > guess
- Unbound → **blocking schedule picker popup**; Change patient clears thread after confirm
- **Citations (PRD 06 coded):** trailing Source → in-pane popup; allowlisted Open label; claim newlines

### Demo / agent decision policy (2026-07-21)

- North star: interview MVP on DO; extensible seams; few happy-path bugs; **not** production
- Engineering guesses OK; clinical claims must be verified+cited, labeled unverified, or refused
- Shortcuts/fakes OK if noted as Memory Bank debt; **do not** fake roadmap spine steps 1–7
- Under pressure: keep UC-1 → UC-2; label-backed UC-3 if easy; else thin UC-3
- **Keep shipping spine locally;** batch DO deploy before interview
- Escalation: auth/PHI/verify-bypass/chart writes/DO data loss/stack-lock **or** ~90s physician-story — see decision guide

### Physician UX defaults (decision guide §6)

- **~90s budget:** rich brief shape for post-cache; accept uncached latency now
- **Partial tool failure:** verified domains + `… unavailable — try again.`
- **Empty domains:** explicit one-liners
- **Citations:** every verified claim linked (PRD 06); conflict UX deferred
- **Progress:** clinical-ish (`Pulling labs…` / `Looking up label information…`)
- **UC-3:** one label-backed dosing path (PRD 05)

## Deferred (explicit in ARCHITECTURE.md)

Exact tool schemas · auto-brief · pre-ask caching · multi-worker scale · interaction APIs · SMART runtime · FHIR dual path · production hardening · full eval catalog · **label conflict UX** (deferred from PRD 05)

## Deferred debt (shortcuts)

- **Brief four-tool bundle not cached yet** (planned TTL ~30–60s).
- **Synthea notes empty** — honest empty; optional seed later.
- **Draft parse under rich tools:** watch `draft_parse_failed`; truncate oldest labs if needed.
- **`fhir_uuid` / `retrieved_at` on citations** — omitted/null in PRD 06; populate later.
- **Historical transcript citation re-hydrate** — MVP OK to show plain prior turns.
- **Compose image build locally** can hang on Docker Hub creds; host uvicorn/pytest historically.
- **DO overlay:** synced for PRD 06 citations (2026-07-22) — JS/CSS + sidecar.
- **DO schedule:** `CoPilot Demo%` re-seed after day roll.
- Per-turn tool tickets; durable disclosure DB (file stub OK through PRD 07).
- **Chart meds facts omit RxCUI digits when present** (only uncertain suffix when missing) — research queries by scrubbed name; acceptable for MVP.
- No rate limiting on `stream.php`.
- **Dev compose** weak default `COPILOT_INTERNAL_SECRET`.
- **Picker:** non-recurring today only; provider-scoped.
- **Manual PRD 06 Ask Co-Pilot click-path** — SSE citation batch verified on DO; Source popup click-path optional.
- **Manual PRD 05 UI smoke** — optional pid 2/amoxicillin.

## Remaining / next

1. Optional Ask Co-Pilot Source popup click-path smoke on DO
2. Write + implement PRD 07 (LangSmith redacted stubs + health/ready polish)
3. Optional fuller PRD 05 UI smoke; demo video + interview narrative polish

## Out of scope right now

- Production credential rotation, DB TLS, MFA, WAF, chart write-back
- Concurrent multi-physician load testing as a demo requirement
- Label conflict surface in MVP demo
