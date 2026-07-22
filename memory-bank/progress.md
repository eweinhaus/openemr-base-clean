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
- [x] **PRD 05 written (2026-07-21):** `docs/PRDs/05-research-tools.md` — locks + H1–H17 invariants; conflict skipped; off-chart + not-on-list.
- [x] **PRD 05 research tools (2026-07-21):** `sidecar/app/research/` (dosing/scrub/resolve/client/extract); tools gate meds-only; verify keeps `source_type=research`; conditional `no_research`; assemble not-on-list + disclaimer; optional `OPENFDA_API_KEY`; sidecar pytest **126**; PHP/`tool_proxy` unchanged.
- [x] **DO redeploy PRD 04+05 (2026-07-21):** overlay Chart + research sidecar rebuild on https://142.93.255.212/; module active; OpenRouter set; bind-seeded pid 6 dosing SSE → progress (incl. label lookup) → clinical label text → done.
- [x] **PRD 06 written (2026-07-22):** `docs/PRDs/06-citations-hybrid-sse.md` — segments + batch `citation` SSE, trailing Source, in-pane popup, H1–H13.
- [x] **PRD 06 citations + hybrid SSE (2026-07-22):** `build_clinical_payload` / `build_citation_records`; emit/stream `clinical`→`citation`→`done`; progress polish; Ask Co-Pilot Source + `#acp-cite` dialog + URL allowlist; sidecar pytest **137**; Jest ask-copilot **31**.
- [x] **DO redeploy PRD 06 (2026-07-22):** commit `58eb115`; overlay+sidecar; module active; OpenRouter set; bind-seeded pid 6 dosing → progress → clinical+segments → research citation → done.
- [x] **PRD 07 written + coded (2026-07-22):** LangSmith env-gated + force hide; soft `/ready.langsmith`; `sidecar_unready` fail-closed; `disclosure.php` + `VerifyDisclosureService`; verify callback; alert stubs in README; sidecar pytest **157**; isolated PHPUnit disclosure **29**.
- [x] **PRD 07 on DO (2026-07-22):** commit `517f95a`; disclosure `verify` join smoked.
- [x] **PRD 4–7 review hardening (2026-07-22):** readiness cache + soft OpenRouter `/models`; `InternalEndpointGuard`; research body cap + `defusedxml`; no model excerpt fallback; research redirects. Sidecar pytest **161**. Commit `8b3f4d8`.
- [x] **DO redeploy review hardening (2026-07-22):** `8b3f4d8` overlay+sidecar; module active; OpenRouter set; pid 6 dosing → progress → clinical → citation → done; disclosure `verify` join confirmed.

## Remaining (MVP → Early)

- [ ] Optional Ask Co-Pilot Source popup click-path smoke on DO
- [ ] Optional fuller PRD 05 UI smoke (pid 2 uncertain no-HTTP; off-chart amoxicillin not-on-list; Ask Co-Pilot tab click-path)
- [ ] Optional LangSmith keys on DO for redacted-trace screenshot
- [ ] Eval suite thin + demo video / cost analysis — interview narrative prioritized

## Known issues

- Public site: demo credentials, no DB TLS, self-signed HTTPS — intentional Gauntlet demo posture
- **DO uses overlay bind-mounts** under `/opt/openemr/overlay/` (not a fork-built OpenEMR image yet)
- **DO/local `CoPilot Demo%` appts** need re-seed after calendar day roll (UTC on droplet)
- OpenEMR ACL not patient-panel scoped — co-pilot tool layer must enforce pid
- Twig autoescape off — manual escape on co-pilot UI
- Med decision-support is high-stakes — cited decision support only; no dosing without retrieved source
- Droplet `importRandomPatients … false` only stores CCDA documents (known script caveat: non-dev mode broken) — use `--isDev=true` for real patient rows
- Missing-RxNorm demo seeds: local Susan Underwood (**pid 2**, Lisinopril); DO Vincenzo126 Kemmer137 (pid 6, Turmeric free-text). **Local pid 8 is allergies + coded Rx — not missing-RxNorm.**
- UC-3 dosing happy-path: local pid **6** simvastatin RxNorm `312961`; DO smoke used off-chart/named **simvastatin** on pid 6 and still returned label-backed dose (not-on-list may apply depending on chart meds)
- **Chart meds facts omit RxCUI when present** — research uses scrubbed display/generic term (MVP OK)
- Label **conflict UX deferred** (MVP fallback-only)
- Single-worker 2 GB host will not support meaningful concurrent load (accepted for interview demo)
- Planning docs may still be local untracked until committed
- Docker Hub pull / `docker-credential-desktop` can hang locally — prefer build sidecar **on the droplet**
- **Synthea `form_clinical_notes` empty** — notes domain honest empty; optional seed deferred
- **Uncached four-tool brief** may be slow; TTL cache deferred; watch `draft_parse_failed` under richer tool JSON
- **DO `OPENFDA_API_KEY` empty** — optional; unauthenticated openFDA worked for smoke
- **PRD 06 on DO** — SSE citation path verified; Ask Co-Pilot Source click-path optional
- **PRD 07 on DO** — soft langsmith field; verify disclosure join smoked; LangSmith API key not required for chat
- Deferred after 07: gateway `/ready` preflight; durable disclosure DB; optional `wrap_openai`; wired alerts

## Schedule reminder (from directions)

| Gate | Focus |
| --- | --- |
| Architecture Defense | planning — `ARCHITECTURE.md` ready |
| MVP (Tue 11:59 CT) | audit, users, agent plan, deployed app + AI interview |
| Early (Thu) | working agent, eval, observability, demo video |
| Final (Sun noon CT) | production-ready, costs, social post |
