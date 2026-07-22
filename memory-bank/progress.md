# Progress

## Done

- [x] OpenEMR running locally with sample/demo login
- [x] Public DigitalOcean deploy (https://142.93.255.212/)
- [x] Fork: `eweinhaus/openemr-base-clean` (`origin` + `upstream`)
- [x] README deploy section + live URL
- [x] SSH / droplet bootstrap (Docker, 2G swap, `/opt/openemr`)
- [x] Product decisions locked (persona, three jobs, hybrid + LangGraph + OpenRouter/Haiku + LangSmith, notes+research stance)
- [x] `AUDIT.md` rewritten (Stage 3 hard gate)
- [x] `USERS.md` / `USER.md` (Stage 4 hard gate) — PCP persona, workflow moment, UC-1/2/3 + why agent
- [x] UX locks (Co-Pilot as first-class tab; empty chat; citation popups; fail-closed honesty; stream; concise)
- [x] `docs/architecture-tech-primer.md` + `docs/architecture-overview.md` + notebooklm pack
- [x] Technical decisions locked (session-proxy, services-first chart, openFDA→DailyMed, structured verify, hybrid SSE, open-tab state, single worker, Haiku, patient picker)
- [x] `ARCHITECTURE.md` (Stage 5 hard gate) — ~500w summary + plan tracing to UC-1/2/3
- [x] Synthea import on local + DO (~6 patients each); clinical richness + FHIR UUIDs verified; missing-RxNorm seed on both
- [x] `docs/ai-decision-guide.md` — ambiguity / shortcuts / cut order / escalation (local, untracked; sits under ARCHITECTURE)
- [x] **PRD 01** Ask Co-Pilot tab + module + SSE client (`interface/ask_copilot/`, `oe-module-ask-copilot`); local smoke re-verified 2026-07-21 (menu, gate, send → clinical echo for pid 2)
- [x] **PRD 02** session-proxy gateway spine (local): `SessionGateway`, bind store, `DisclosureLog`, `SidecarClient`, `tool_proxy.php`, stub sidecar, Compose wiring; isolated tests green
- [x] **PRD 03** LangGraph sidecar spine (local): FastAPI + StateGraph (refuse→route→tools→draft→verify→emit), claim schema + code verify, hybrid SSE, OpenRouter Haiku route/draft, enriched stub tools, `/health`+soft `/ready`; sidecar pytest green
- [x] **PRD 01–03 review hardening (2026-07-21):** verify uses tool fact text + allowlisted refusals; route/network errors → SSE error; ACL on index/stream; transcript sanitize; bind user_id check; production compose requires `COPILOT_INTERNAL_SECRET`
- [x] **DO deploy (2026-07-21):** overlay bind-mounts + `copilot-sidecar` on https://142.93.255.212/; module enabled; health OK.
- [x] **QA static review + fix pass (2026-07-21):** gateway timeout 120s + `set_time_limit(0)`; userId fail-closed; dosing refusal keyword-gated; locator dedupe; sidecar 4000-char cap; `/ready` requires OpenRouter key; JS silent-stream error + 5s pid poll; bind-file sweep; tests green (pytest 53 / PHPUnit 51).
- [x] **Patient schedule picker popup (2026-07-21):** blocking dialog over chat; `schedule.php` + `src/ClinicalCopilot/Schedule/`; Next / today list / Finder; Change patient; Jest 20 + ClinicalCopilot isolated 93 OK; local demo appts seeded.
- [x] **Local OpenRouter Send smoke (2026-07-21):** model pin `anthropic/claude-haiku-4.5` (old `claude-3.5-haiku` → 404); credits funded (was 402); `stream.php` pid 2 → progress → clinical → done; UI confirmed working.
- [x] **DO redeploy (2026-07-21 evening):** packaged overlay+sidecar; model pin on droplet; schedule API 200; unbound → `unbound_patient`; pid 6 Send → progress → `draft_parse_failed` (spine OK; full clinical reply not yet green on DO).
- [x] **DO sync smoke (2026-07-22 UTC):** overlay+sidecar rebuild; timeout 120s; seeded today appts; pid 6 → progress → clinical → done.
- [x] **PRD 04 chart tools (2026-07-21):** `src/ClinicalCopilot/Chart/` + `ChartToolDispatcher` → `ToolProxyService`; stubs removed; sidecar brief×4 parallel + partial/empty assemble; PHPUnit ClinicalCopilot 123 + pytest 70; local DB smoke pid 6/8.

## Remaining (MVP → Early)

- [ ] DO redeploy for PRD 04 (overlay Chart + sidecar tool rename); smoke rich patient
- [ ] PRD 05–07 (research → citations/SSE polish → LangSmith stubs)
- [ ] LangSmith + correlation IDs end-to-end, eval suite (thin OK for interview)
- [ ] Demo video + cost analysis (submission) — interview narrative prioritized

## Known issues

- Public site: demo credentials, no DB TLS, self-signed HTTPS — intentional Gauntlet demo posture
- **DO uses overlay bind-mounts** under `/opt/openemr/overlay/` (not a fork-built OpenEMR image yet)
- **DO needs PRD 04 redeploy** before interview talk-track uses live chart facts (local already real)
- **DO/local `CoPilot Demo%` appts** need re-seed after calendar day roll (UTC on droplet)
- OpenEMR ACL not patient-panel scoped — co-pilot tool layer must enforce pid
- Twig autoescape off — manual escape on co-pilot UI
- Med decision-support is high-stakes — cited decision support only; no dosing without retrieved source
- Droplet `importRandomPatients … false` only stores CCDA documents (known script caveat: non-dev mode broken) — use `--isDev=true` for real patient rows
- Missing-RxNorm demo seeds: local Susan Underwood (pid 2, Lisinopril); DO Vincenzo126 Kemmer137 (pid 6, Turmeric free-text)
- Single-worker 2 GB host will not support meaningful concurrent load (accepted for interview demo)
- Planning docs (`docs/ai-decision-guide.md`, `docs/directions.md`, `.cursor/`, `memory-bank/`, etc.) may still be local untracked until committed
- Docker Hub pull / `docker-credential-desktop` can hang locally — blocked Compose build of `copilot-sidecar`; host Python stub used for PRD 02 smoke
- **Synthea `form_clinical_notes` empty** — notes domain honest empty; optional seed deferred
- **Uncached four-tool brief** may be slow; TTL cache deferred; watch `draft_parse_failed` under richer tool JSON

## Schedule reminder (from directions)

| Gate | Focus |
| --- | --- |
| Architecture Defense | planning — `ARCHITECTURE.md` ready |
| MVP (Tue 11:59 CT) | audit, users, agent plan, deployed app + AI interview |
| Early (Thu) | working agent, eval, observability, demo video |
| Final (Sun noon CT) | production-ready, costs, social post |
