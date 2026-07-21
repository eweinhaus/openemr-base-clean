# System Patterns

## OpenEMR layers

| Path | Role |
| --- | --- |
| `/src` | PSR-4 `OpenEMR\` — services, REST/FHIR, events, Twig helpers |
| `/library` | Legacy procedural — avoid for new agent code |
| `/interface` | Web UI controllers |
| `/templates` | Twig (modern) + Smarty (legacy) |

OpenEMR-side co-pilot code in `/src` only; extend `BaseService`. MVP chart path = **PHP services**, not raw SQL. FHIR/SMART = phase 2.

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

## Auth reality + co-pilot policy

- GACL is **role/section**, not per-patient
- Session-proxy binds pid; **every chart tool** re-checks pid (fail closed)
- Unbound → patient picker before chart work; ignore client/model-supplied pid
- SMART later; multi-role later
- Twig `autoescape` **off** — escape manually

## Co-Pilot UX patterns (locked)

- Empty chat start; concise; follow-ups for depth; thread until tab closed
- Claims → hyperlink → **in-pane** source popup
- Prefer omit / “not on file” / “research unavailable” over guess
- **Hybrid SSE:** progress early; **no** unverified clinical text (no warning-label workaround)

## Integration seams

1. **`PatientContextService`** — UC-1 snapshot; drill-down tools for labs/meds/notes
2. Ask Co-Pilot tab + gateway SSE endpoint
3. Sidecar chart access **only via gateway** in MVP
4. Separate PHI-disclosure / verification log
5. Agent **read-only** into the chart

## Clinical data joins (hot paths)

- Labs: `procedure_order` → `procedure_report` → `procedure_result`
- Problems/allergies: `lists` via `type`
- Meds: `prescriptions` (`drug` ± `rxnorm_drugcode`) — missing RxNorm ⇒ uncertain; never invent codes
- Visits: `form_encounter`
- Notes: selective recent / relevant only

## Verification pattern

- Model emits structured claim/source pairs; verify node cite-or-silence
- Chart: table+pk (± FHIR id); notes: id + span; research: URL/title/section
- Prefer structured over notes when both exist
- Dosing/interactions only from retrieved labels; conflicts surfaced, not auto-resolved
- Allergy / contradiction checks; med UX = decision support only

## Research pattern

- openFDA primary → DailyMed fallback
- Outbound: drug/condition terms only
- Miss: cited chart + refuse unsupported dosing claim (partial turn OK)

## Deploy pattern

- Single DO NYC droplet, Docker Compose at `/opt/openemr`
- OpenEMR + MariaDB + **one** LangGraph worker; document concurrency limits
- Demo creds / no DB TLS / self-signed HTTPS = documented Gauntlet posture
