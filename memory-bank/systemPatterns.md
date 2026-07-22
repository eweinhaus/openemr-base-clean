# System Patterns

## OpenEMR layers

| Path | Role |
| --- | --- |
| `/src` | PSR-4 `OpenEMR\` — services, REST/FHIR, events, Twig helpers |
| `/library` | Legacy procedural — avoid for new agent code |
| `/interface` | Web UI controllers |
| `/templates` | Twig (modern) + Smarty (legacy) |

OpenEMR-side co-pilot code in `/src` only. Prefer `BaseService` when it fits; Co-Pilot facades that need isolated PHPUnit (Schedule, Chart) may use injectable loaders **without** extending `BaseService` (DB bootstrap breaks isolated tests). MVP chart path = **PHP services**, not raw SQL. FHIR/SMART = phase 2.

## OpenEMR UI shell (for first-class pages)

- Post-login shell: `interface/main/tabs/main.php` — navbar + **iframe tabs**
- Menu: `interface/main/tabs/menu/menus/standard.json` — **do not edit** for Co-Pilot
- **Ask Co-Pilot:** custom module `oe-module-ask-copilot` → `AskCopilotMenuSubscriber` (`menu_id=acp0`, `target=acp`, `requirement=0`); chrome at `interface/ask_copilot/`; stream via session-proxy `stream.php`
- **Patient gate (popup):** unbound → non-dismissible dialog over dimmed chat (composer disabled). Loads provider-scoped today schedule from `schedule.php` (GET + CSRF; session `authUserID` only). UI: Next card (`next_pid`) → remaining appts → Search all patients (Finder). Select via `top.RTop` → `demographics.php?set_pid=` then fast-poll session pid. Bound: header **Change patient** (confirm if transcript non-empty). Never auto-bind.
- Schedule service: `src/ClinicalCopilot/Schedule/` — terminal statuses `x ? ! > $ %` excluded; next = earliest start ≥ now−15m in configured timezone. Non-recurring `pc_eventDate = today` only (MVP).
- Chat JS: prefer `top.getSessionValue('pid')`; fallback `askCopilotConfig.sessionPid` when page is top-level (not under main iframe)

## Ambiguity / tradeoffs

When implementing and docs leave a choice open, follow [`docs/ai-decision-guide.md`](../docs/ai-decision-guide.md): closest to `ARCHITECTURE.md`, clinical safety over cleverness, DO demo truth, record shortcuts as Memory Bank debt. Do not fake roadmap spine steps 1–7.

## Hybrid agent topology (locked)

```
Physician → Ask Co-Pilot tab → session-proxy gateway (session + pid + correlation ID)
                → LangGraph sidecar (single worker) → OpenRouter (Haiku)
                     ├─ Chart tools → gateway → PHP services (re-check pid)
                     ├─ Research tools (openFDA → DailyMed; no PHI)
                     └─ Verify structured claims → hybrid SSE
```

- **LangGraph** = workflow; **LangSmith** = redacted traces — not interchangeable
- App owns correlation IDs + PHI disclosure / verification log
- Browser never sends cookies to sidecar
- OpenRouter model pin: `anthropic/claude-haiku-4.5`. SSE `llm_http_error` = provider HTTP reject (bad slug/credits/etc.); `llm_not_configured` = missing `OPENROUTER_API_KEY`

## Auth reality + co-pilot policy

- GACL is **role/section**, not per-patient
- Session-proxy binds pid; **every chart tool** re-checks pid (fail closed)
- Unbound → patient picker before chart work; ignore client/model-supplied pid
- SMART later; multi-role later
- Twig `autoescape` **off** — escape manually

## Co-Pilot UX patterns (locked)

- Empty chat start; concise; follow-ups for depth; thread until tab closed
- Prefer omit / “not on file” / “research unavailable” over guess
- **Hybrid SSE:** progress early; clinical after verify; then citation batch; **no** unverified clinical text
- **Citations (PRD 06 coded):** trailing **Source** on verified claims only → `#acp-cite` in-pane dialog; assembly unlinked; claim newlines; DOM-only XSS
- Dialog chrome: reuse patient-picker overlay pattern (`role="dialog"` + backdrop) — not Bootstrap modal/popover

## Hybrid SSE contract (PRD 06 coded)

- Success: `progress*` → `clinical` `{text, segments}` → `citation` `{citations}` (always, even `[]`) → `done`
- Error: unchanged (no clinical/citation required)
- Client buffers clinical+citation before paint (timeout/`done` → plain text); gateway is byte pass-through
- Progress: clinical-ish only (`Pulling chart…` / labs / meds; `Looking up label information…`) — no toolchain jargon

## Integration seams

1. **`src/ClinicalCopilot/Chart/`** — `PatientContextService` + Labs/Meds/Notes + `ChartToolDispatcher` (Schedule-style injectable loaders); wired via `ToolProxyService`
2. Ask Co-Pilot tab + gateway SSE endpoint
3. Sidecar chart access **only via gateway** in MVP; brief = four tools in parallel; empty ≠ error; per-tool domain errors → partial assemble
4. Separate PHI-disclosure / verification log
5. Agent **read-only** into the chart

## Clinical data joins (hot paths)

- Labs: `procedure_order` → `procedure_report` → `procedure_result`
- Problems/allergies: `lists` via `type`
- Meds: `prescriptions` (`drug` ± `rxnorm_drugcode`) — missing RxNorm ⇒ uncertain; never invent codes
- Visits: `form_encounter`
- Notes: `form_clinical_notes` selective recent (cap 3, excerpt ≤500); Synthea typically empty
- Active Rx filter: `prescriptions.active=1` AND open-ended `end_date` (past end_date = completed even if active flag set)

## Verification pattern

- Model emits structured claim/source pairs; verify node cite-or-silence
- Chart: table+pk (± FHIR id); notes: id + span; research: `openfda`/`dailymed` + set_id:section (URL/title in excerpt/meta)
- Prefer structured over notes when both exist
- Keep claim `source_type` (`chart`|`note`|`research`) — do not rewrite survivors to `chart`
- Dosing only from retrieved labels; `no_research` only when dosing-like and no verified research fact
- Allergy / contradiction checks; med UX = decision support only
- Label **conflict UX deferred** (MVP does not dual-fetch or surface conflicts)

## Research pattern (PRD 05)

- Sidecar-only (`sidecar/app/research/`) — never via `tool_proxy`
- openFDA primary → DailyMed fallback on miss/timeout/5xx/empty dose; ≤5s; no retries
- Outbound: scrubbed `DrugQuery` / RxCUI digits only — never raw user message or PHI
- `meds` route + dosing-like only (`is_dosing_like` shared by tools + verify); uncertain RxNorm blocks HTTP
- Off-chart named drug allowed if single Rx SPL; assembly not-on-list line required
- Brand↔generic post-hit may reconcile `on_chart=true`
- Miss: cited chart + refuse unsupported dosing (partial turn OK; not SSE `error`)
- Verify keeps `source_type=research`; `no_research` only if dosing-like ∧ no verified research dosing fact
- `/ready` must not probe FDA/DailyMed
- Optional `OPENFDA_API_KEY`; chart facts omit RxCUI when present → query by scrubbed name
- Canonical PRD: `docs/PRDs/05-research-tools.md` (H1–H17 invariants)

## Citations pattern (PRD 06 — implemented)

- `claims.build_clinical_payload` + `build_citation_records`; `emit_node` → state `clinical_text` / `clinical_segments` / `citations`
- SSE success: `progress*` → `clinical` `{text,segments}` → `citation` `{citations}` (always, even `[]`) → `done`
- Emit citations **only** from verified claims; `citation_id` `c1…n` paired to claim segments; assembly unlinked
- UI: buffer clinical+citation; `renderAssistantTurn`; `#acp-cite` dialog; allowlisted Open label (`dailymed.nlm.nih.gov`, `api.fda.gov`)
- Progress allowlist in `sidecar/app/progress.py` (`Pulling chart…` / labs / meds); research keeps `Looking up label information…`
- `fhir_uuid`/`retrieved_at` deferred null; historical transcript re-hydrate deferred
- Canonical PRD: `docs/PRDs/06-citations-hybrid-sse.md` (H1–H13)

## Observability pattern (PRD 07 — implemented thin)

- **LangGraph** = agent workflow; **LangSmith** = optional redacted traces (not interchangeable)
- Env-gated `LANGSMITH_*`; startup forces hide inputs/outputs when tracing on; run metadata = `correlation_id` only (no `pid`/message)
- Soft `/ready.langsmith` + soft `openrouter.reachable`; hard `ready` = gateway reachable + OpenRouter **key**; **never FDA**; Compose healthcheck stays on `/health`
- `/v1/chat` caches readiness (~30s TTL); ops `/ready` always fresh; unready → SSE `sidecar_unready` immediately (no graph/LLM/clinical)
- App owns disclosure JSONL: `ask_start` / `tool_proxy` / **`verify`** via secret-gated `disclosure.php` (`VerifyDisclosureService`); sidecar best-effort POST after verify
- `tool_proxy` / `disclosure` also gated by `InternalEndpointGuard` (private/loopback `REMOTE_ADDR` by default)
- Alert defs stubbed in markdown only — no dashboard polish / wired paging
- Canonical PRD: `docs/PRDs/07-observability-langsmith.md` (H1–H13)

## Deploy pattern

- Single DO NYC droplet, Docker Compose at `/opt/openemr`
- OpenEMR + MariaDB + **one** LangGraph worker; document concurrency limits
- Demo creds / no DB TLS / self-signed HTTPS = documented Gauntlet posture
