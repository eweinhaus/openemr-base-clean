# Active Context

## Current focus

**Local demo QA + setup (2026-07-23):** Panther §0–§8 smoke **43/43 pass**
(`tmp/qa-smoke-last-run.txt`); sidecar pytest **165/165** with
`COPILOT_INTERNAL_SECRET=test-secret`. Fixes: citation registry +
`textContent` dialog body in `ask_copilot.js` (U1-5); uncertain-RxNorm
assembly line in `claims.py` (U3-4/F-2); pytest secret reads env. Prior
static audit + setup scripts unchanged.

**Prior — Success-criteria remediation (2026-07-22):** Closed audit gaps from
`docs/success-criteria-audit.md` — allergy contradiction at verify, meds route
+ `patient_context`, citation `retrieved_at`/`fhir_uuid`, `/ready`→503,
`wrap_openai` + usage logs, Bruno collection, eval catalog+results (164 pytest),
cost analysis, k6 scaffold, ARCHITECTURE conflict wording aligned to deferred
MVP. External still open: **demo video (A7)** and **social post (A10)**. Load
baseline numbers (L2) need a real k6 run to fill.

**DO redeploy (2026-07-23 UX pass):** uncommitted local overlay shipped to
https://142.93.255.212/ — patient display names (`PatientDisplayName`,
`patient.inc.php` mount), friendly dates (`ClinicalDisplayDate`), numbered
citations + typing indicator + readable source popup + patient header
(`patient.php`), picker DOB/next-patient UX. DB: Synthea name cleanup +
today's `CoPilot Demo` appts (pids 6/2; pid 8 absent on DO). Module active;
`/ready` true; OpenRouter set; mounts OK incl. `library/patient.inc.php`.

**Prior DO redeploy (2026-07-23):** commit `d08ea03` — sidecar rebuild,
mounts OK, `/ready` 200, OpenRouter set, module re-enabled.

**Next:** Public §12 browser smoke on DO; commit + push UX pass; demo video (A7).

## PRD 07 decisions (locked — implemented)

Canonical: `docs/PRDs/07-observability-langsmith.md` (H1–H13).

- **LangSmith:** Optional keys; silent disable; force hide I/O when tracing on; metadata `correlation_id` only (no `pid`/message); OpenRouter client via `wrap_openai` + usage logs.
- **`/ready`:** Soft `langsmith` + soft `openrouter.reachable`; hard deps = gateway reachable + OpenRouter **key**; never FDA; Compose healthcheck stays on `/health`. `/v1/chat` uses ~30s readiness cache; `/ready` always fresh.
- **Fail-closed:** Sidecar `/v1/chat` gates on ready → SSE `sidecar_unready` (no graph).
- **Internal endpoints:** `tool_proxy.php` / `disclosure.php` reject public `REMOTE_ADDR` via `InternalEndpointGuard` (loopback/RFC1918; escape `COPILOT_INTERNAL_ENDPOINTS_PUBLIC=1`).
- **Disclosure join:** Sidecar → `disclosure.php` → `VerifyDisclosureService` → JSONL `event=verify` (`pass` + short `reason`); best-effort.
- **Pass heuristic:** `pass:true` iff ≥1 verified claim; else `claims_dropped` / `all_refused` / `empty_verified`.
- **Alerts:** Markdown stubs only (README + PRD §10) — not wired.
- **Interview line:** Same `correlation_id` joins disclosure JSONL ↔ redacted LangSmith; app owns EHR audit.

## PRD 06 decisions (locked — implemented)

Canonical: `docs/PRDs/06-citations-hybrid-sse.md` (H1–H13).

- **Link affordance:** Claim text plain + trailing **Source** control (not whole-claim underline).
- **Layout:** Newline between claim segments; assembly/refusal/disclaimer/empty **unlinked**.
- **Clinical SSE:** `{ text, segments[] }` — `kind: claim|assembly`; claims carry `citation_id` (`c1…n`).
- **Citation SSE:** One batch `{ citations: [...] }` **after** `clinical`, before `done` (always emit, even if empty).
- **Client:** Buffer until clinical+citation (~2.5s timeout / `done` → plain `text`); DOM-only (`textContent` / createElement); no `innerHTML`/markdown.
- **Popup:** Picker-style `#acp-cite` dialog; `{ source_type, title, retrieved_at?, excerpt, locator (+ fhir_uuid?) }`; mutual exclusion with picker; focus returns to Source.
- **Research Open label:** Allowlisted `https` only (`dailymed.nlm.nih.gov`, `api.fda.gov`) → `target=_blank` + `noopener noreferrer`.
- **Builders:** `build_clinical_payload` + `build_citation_records` in `sidecar/app/claims.py`; emit/stream wire state `clinical_segments` / `citations`.
- **Progress:** `Pulling chart…` / `Pulling labs…` / `Checking medications…`; keep `Looking up label information…`; drop `Routing…` / `Fetching chart…`.
- **Gateway:** Pass-through only — citations built in sidecar from verified claims.
- **Non-goals still out:** conflict UX, unverified UI, historical transcript re-hydrate.

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
- **`fhir_uuid` / `retrieved_at` on citations** — populated when present (chart UUID + research stamp); UI renders both.
- **Historical transcript citation re-hydrate** — MVP OK to show plain prior turns.
- **Compose image build locally** can hang on Docker Hub creds; host uvicorn/pytest historically.
- **DO overlay:** PRD 07 on droplet (`517f95a`) — disclosure + Gateway + sidecar observability.
- **DO/local schedule:** re-seed with `scripts/copilot/setup-local-demo.sh --seed-only` after day roll (or DO packaged `seed_local_demo.sql`).
- Per-turn tool tickets; durable disclosure DB (file stub OK through PRD 07); gateway `/ready` preflight deferred; wired alerts remain markdown (ops = LangSmith + JSONL).
- **Chart meds facts omit RxCUI digits when present** (only uncertain suffix when missing) — research queries by scrubbed name; acceptable for MVP.
- No rate limiting on `stream.php`.
- **Dev compose** weak default `COPILOT_INTERNAL_SECRET`.
- **Picker:** non-recurring today only; provider-scoped.
- **Manual PRD 06 Ask Co-Pilot click-path** — SSE citation batch verified on DO; Source popup click-path optional.
- **Manual PRD 05 UI smoke** — optional pid 2/amoxicillin.
- **Allergy contradiction** at verify (meds research vs allergy list) — shipped; conditions via meds+`patient_context`.
- **Success-criteria remediation** not yet redeployed to DO (code local).
- **Local demo manual smoke (§12)** — not run after setup-script landing; static audit only.
- **L2 load baseline numbers** — k6 script present; fill after run.
- **A7 demo video / A10 social** — external placeholders in README.

## Remaining / next

1. Manual local demo script (`docs/local-demo-success-criteria.md` §12) + §9 pytest/PHPUnit
2. Redeploy remediation + `scripts/copilot/` seeds to DO
3. Optional Ask Co-Pilot Source popup click-path smoke on DO
4. Optional fuller PRD 05 UI smoke; demo video + interview narrative polish
5. Optional enable LangSmith keys on DO for redacted-trace screenshot

## Out of scope right now

- Production credential rotation, DB TLS, MFA, WAF, chart write-back
- Concurrent multi-physician load testing as a demo requirement
- Label conflict surface in MVP demo
- LangSmith dashboard polish / wired alerts / Bruno load-test deliverables
