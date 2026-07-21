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
- [x] **PRD 01** Ask Co-Pilot tab + module + stub SSE client (`interface/ask_copilot/`, `oe-module-ask-copilot`)
- [x] **PRD 02** session-proxy gateway spine (local): `SessionGateway`, bind store, `DisclosureLog`, `SidecarClient`, `tool_proxy.php`, stub sidecar, Compose wiring; isolated tests green (44 ClinicalCopilot)
- [x] **PRD 03** LangGraph sidecar spine (local): FastAPI + StateGraph (refuse→route→tools→draft→verify→emit), claim schema + code verify, hybrid SSE, OpenRouter Haiku route/draft, enriched stub tools, `/health`+soft `/ready`; sidecar pytest 40 green; ToolProxyService isolated 12 green

## Remaining (MVP → Early)

- [ ] PRD 04–07 (real chart tools → research → citations/SSE polish → LangSmith stubs)
- [ ] Deploy/smoke gateway + LangGraph sidecar on DO (Compose rebuild + `OPENROUTER_API_KEY`)
- [ ] LangSmith + correlation IDs end-to-end, eval suite (thin OK for interview)
- [ ] Demo video + cost analysis (submission) — interview narrative prioritized

## Known issues

- Public site: demo credentials, no DB TLS, self-signed HTTPS — intentional Gauntlet demo posture
- OpenEMR ACL not patient-panel scoped — co-pilot tool layer must enforce pid
- Twig autoescape off — manual escape on co-pilot UI
- Med decision-support is high-stakes — cited decision support only; no dosing without retrieved source
- Droplet `importRandomPatients … false` only stores CCDA documents (known script caveat: non-dev mode broken) — use `--isDev=true` for real patient rows
- Missing-RxNorm demo seeds: local Susan Underwood (pid 2, Lisinopril); DO Vincenzo126 Kemmer137 (pid 6, Turmeric free-text)
- Single-worker 2 GB host will not support meaningful concurrent load (accepted for interview demo)
- Planning docs (`docs/ai-decision-guide.md`, `docs/directions.md`, `.cursor/`, `memory-bank/`, etc.) may still be local untracked until committed
- Docker Hub pull / `docker-credential-desktop` can hang locally — blocked Compose build of `copilot-sidecar`; host Python stub used for PRD 02 smoke

## Schedule reminder (from directions)

| Gate | Focus |
| --- | --- |
| Architecture Defense | planning — `ARCHITECTURE.md` ready |
| MVP (Tue 11:59 CT) | audit, users, agent plan, deployed app + AI interview |
| Early (Thu) | working agent, eval, observability, demo video |
| Final (Sun noon CT) | production-ready, costs, social post |
