# PRD 07 — Observability Stubs (LangSmith + `/health`/`/ready` + Disclosure Join)

**Roadmap step:** `ARCHITECTURE.md` §7 item 7  
**Goal:** Wire **redacted LangSmith traces** on the sidecar (env-gated), keep soft **`/health` + `/ready`**, **fail closed** on the agent path when unready, and join **verification outcomes** into the app disclosure JSONL via the same **`correlation_id`**.  
**Non-goal:** LangSmith dashboard polish, wired alerts/paging, load tests (10/50 users), Bruno/Postman collections as a deliverable, durable disclosure DB, gateway `/ready` preflight, physician observability UI, multi-worker, checkpointer, eval catalog, conflict UX, citation changes (PRD 06 done).

---

## 1. Problem Statement and Context

### What

Ship the interview **observability spine** on top of existing health/correlation/disclosure seams:

1. **LangSmith** tracing on the LangGraph sidecar when keys are set — **redacted by default** (hide inputs/outputs); run metadata includes `correlation_id` only (no `pid` / message / note bodies).
2. Confirm **`GET /health`** (alive) and soft **`GET /ready`** (gateway + OpenRouter hard; LangSmith **soft**; never FDA).
3. When `ready=false`, **refuse `/v1/chat`** immediately with SSE `error` (no graph / LLM / clinical).
4. After verify runs, sidecar **POSTs** a thin `verify` event to a secret-gated PHP endpoint that appends `DisclosureLog` (`pass` + short `reason`).
5. Document Graph ≠ Smith + alert-definition stubs for Early rubric optics (markdown only).

### Background

PRDs 01–06 deliver tab → session-proxy → LangGraph → chart + research → verify → hybrid SSE with citations. Correlation IDs and a JSONL disclosure stub exist since PRD 02; `/health` + soft `/ready` since PRD 03. **LangSmith is not wired.** Verification pass/fail is not in the app disclosure log (only Python stdout). Early gate and interview need a defendable join story without building ops theater.

**Mental model (teach explicitly):**

| Piece | Role |
| --- | --- |
| **LangGraph** | Agent workflow (nodes: refuse→route→tools→draft→verify→emit) |
| **LangSmith** | Redacted traces of that workflow (latency, node order, errors) |
| **Disclosure JSONL** | App-owned audit: who asked / which tools / verify outcome — keyed by `correlation_id` |

### Related Work

| Doc / code | Role |
| --- | --- |
| `ARCHITECTURE.md` §4.7, §6, §7 item 7 | Health/ready; observability plan |
| `docs/ai-decision-guide.md` §4, §8, §11 (PRD 07), §12 | Stubs OK; fail-closed; no dashboard polish |
| `docs/directions.md` Engineering Requirements | Rubric pressure — stub-document dashboards/alerts/load |
| `docs/PRDs/02-session-proxy-gateway.md` | Correlation mint; `DisclosureLog`; `tool_proxy` secret |
| `docs/PRDs/03-langgraph-sidecar.md` | Soft `/ready`; Compose-on-`/health` pitfall |
| `docs/PRDs/05-research-tools.md` **H10** | `/ready` must not probe FDA/DailyMed |
| `docs/PRDs/06-citations-hybrid-sse.md` | SSE contract stable — **do not** teach gateway to parse it for verify |
| `sidecar/app/main.py` | `/health`, `/ready`, `/v1/chat` |
| `sidecar/app/stream.py` | `graph.stream` — metadata hook |
| `src/ClinicalCopilot/Logging/DisclosureLog.php` | JSONL allowlist / forbid list |
| `interface/ask_copilot/tool_proxy.php` | Pattern for secret-gated internal PHP |

**Depends on:** PRDs 01–06 coded locally (PRD 06 manual smoke / DO redeploy may still be pending — do not block 07 on DO).  
**Unblocks:** Early observability narrative; interview join walkthrough.

---

## 2. Technical Context

### Relevant Files/Modules

| Path | Change |
| --- | --- |
| `sidecar/requirements.txt` | Pin `langsmith` (already transitive via langgraph — pin for determinism) |
| `sidecar/app/stream.py` | Pass RunnableConfig metadata (`correlation_id`); optional tags |
| `sidecar/app/main.py` | Ready gate before chat; soft `langsmith` field on `/ready` |
| `sidecar/app/errors.py` | New code `sidecar_unready` + short message |
| `sidecar/app/settings.py` (or equiv) | LangSmith / hide-I/O env reads if not already via os.environ |
| `sidecar/app/gateway_client.py` or new thin client | POST verify disclosure callback |
| `sidecar/app/nodes/verify.py` | After verify, fire-and-forget disclosure callback (best-effort) |
| `interface/ask_copilot/disclosure.php` (new) **or** extend small service | Secret + bind-aware append of `verify` event |
| `src/ClinicalCopilot/Logging/DisclosureLog.php` | Allow `verify` via existing fields (`pass`, `reason`) — extend allowlist only if needed |
| `src/ClinicalCopilot/Gateway/CopilotStreamError.php` | Map `sidecar_unready` if gateway ever surfaces it; sidecar SSE message is primary |
| `docker/development-easy/docker-compose.yml` | Sidecar env for LangSmith (empty defaults OK) |
| `docker/production/docker-compose.yml` | Same |
| `sidecar/tests/test_health.py` | Soft langsmith field; H10 retained; unready chat |
| New sidecar + PHPUnit isolated tests | Redaction/env; verify disclosure write; callback auth |
| `docs/` short alert stubs (e.g. in this PRD §10 or `sidecar/README.md`) | Three alert definitions — markdown only |

### Similar Implementations

- **`tool_proxy.php`** — `$ignoreAuth`, `X-Copilot-Internal-Secret`, `X-Correlation-Id`, bind store, `DisclosureLog`.
- **Soft `/ready`** — always HTTP 200 + `{ready: bool, …}` (`test_health.py`).
- **SSE errors** — `sse_error_payload(code, correlation_id=…)` in `errors.py`; UI shows `data.message`.
- **Research logging H13** — log outcomes/ids, never full bodies — same spirit for Smith + disclosure.

### Architecture Notes

- Browser never talks to sidecar or LangSmith.
- Compose healthcheck must stay on **`/health` only** (never `/ready`) — OpenRouter blips must not restart the sidecar.
- Disclosure file path remains `$OE_SITE_DIR/documents/copilot_disclosure.log`.
- Gateway SSE remains **byte pass-through** — do not parse `clinical`/`citation` to infer verify.

### Database/API Context

**No schema migrations.**

**Disclosure events (production inventory after this PRD):**

| Event | Writer | Fields |
| --- | --- | --- |
| `ask_start` | `stream.php` | `correlation_id`, `user_id`, `pid` |
| `ask_error` | `stream.php` | + `reason` (code) |
| `tool_proxy` | `ToolProxyService` | + `pass`, `reason`, `tool?` |
| **`verify`** (**new**) | disclosure endpoint via sidecar callback | + `pass` (bool), `reason` (short code) |

**Forbidden in DisclosureLog (unchanged):** `message`, `note`, `body`, `text`, `chart`, `payload`.

**SSE (unchanged names):** success path still `progress*` → `clinical` → `citation` → `done`.  
New error code when unready at chat start:

```json
{"message":"Co-Pilot is temporarily unavailable. Try again.","code":"sidecar_unready","correlation_id":"…"}
```

---

## 3. Design Decisions (Pre-Made)

| Decision | Choice |
| --- | --- |
| LangSmith keys on DO | **Optional** (like `OPENFDA_API_KEY`) — chat works without them |
| Tracing off / no key | **Silent disable** — do not fail clinical path |
| Redaction | **`LANGSMITH_HIDE_INPUTS=true` + `LANGSMITH_HIDE_OUTPUTS=true`** whenever tracing is on |
| Metadata | `correlation_id` (+ optional `route` / counts later); **no `pid`**, no message |
| LLM nesting | **Optional** `wrap_openai` only under same hide policy; structure-only graph traces OK for MVP |
| `/ready` HTTP | Keep **soft 200** + `ready` boolean |
| Hard ready deps | Gateway tool URL reachable **and** OpenRouter key **and** OpenRouter reachable |
| LangSmith in `/ready` | **Soft** field (`configured` / `reachable`); never alone flips `ready=false` |
| FDA in `/ready` | **Forbidden** (retain PRD 05 H10) |
| Fail-closed | **Sidecar** at `/v1/chat` start — if `ready=false`, SSE `sidecar_unready` immediately; no graph |
| Gateway `/ready` preflight | **Out of scope** (later polish) |
| Compose healthcheck | **`/health` only** — never switch to `/ready` |
| Verify disclosure writer | **Sidecar → secret-gated PHP callback** → `DisclosureLog` |
| Verify event name | `verify` (not `verify_stub`) |
| Callback failure | **Best-effort** — do not fail the physician clinical turn if JSONL write fails |
| Early optics | Screenshot/link + **alert-defs markdown**; no Bruno requirement |
| Dashboard / load tests | **Stub-document as debt** — do not implement |

### Product locks (builder-confirmed 2026-07-22)

1. Optional LangSmith keys; interview join when enabled.  
2. Sidecar→PHP `verify` callback (app owns JSONL).  
3. Sidecar-authoritative fail-closed; no gateway preflight.  
4. Alert stub markdown + Smith screenshot — not wired ops.  
5. No `pid` in LangSmith metadata.

### Hard invariants

| # | Invariant | Enforcement |
| --- | --- | --- |
| H1 | `/health` = process alive only (no dependency probes) | `GET /health` → `200` + `ok` |
| H2 | Hard `/ready` deps = gateway + OpenRouter configured+reachable; research APIs never probed | `check_readiness` + PRD 05 H10 tests |
| H3 | LangSmith is **soft** on `/ready` — missing/unreachable Smith does not set `ready=false` | JSON field + tests |
| H4 | When tracing enabled, each graph run metadata includes `correlation_id` matching gateway mint | `stream.py` config; unit test with mock/env |
| H5 | Trace payloads must not contain note bodies, full message text, tool fact excerpts, or clinical text | Hide inputs/outputs env **required** when tracing on; document + test policy |
| H6 | App disclosure JSONL remains required; LangSmith does **not** replace it | Keep `ask_start` / `tool_proxy`; add `verify` |
| H7 | Disclosure lines require `correlation_id` + `event`; forbidden keys stay stripped | Existing `DisclosureLog` |
| H8 | After verify node runs, one `verify` disclosure line (`pass` + short `reason`) for that `correlation_id` | Callback + PHPUnit/sidecar test |
| H9 | When `ready=false`, `/v1/chat` emits SSE `sidecar_unready` and does **not** run the graph / LLM / clinical | Integration test |
| H10 | Compose/deploy healthcheck stays on `/health` — never `/ready` | Compose files unchanged in that respect; PRD checklist |
| H11 | Tracing off (no keys) must not break chat; disclosure still works | Manual + test with env cleared |
| H12 | No new physician-facing observability UI in OpenEMR | PRD non-goal |
| H13 | Verify callback requires internal secret; reject unauthorized; never accept browser cookies as auth | Mirror `tool_proxy` |

---

## 4. Implementation Guidance

### Step-by-Step Plan

1. **Pin `langsmith`** in `sidecar/requirements.txt`. Document env vars in `sidecar/README.md` + compose.
2. **Compose env** (dev + production) for sidecar — empty defaults OK:

```text
LANGSMITH_TRACING=${LANGSMITH_TRACING:-false}
LANGSMITH_API_KEY=${LANGSMITH_API_KEY:-}
LANGSMITH_PROJECT=${LANGSMITH_PROJECT:-openemr-copilot-demo}
LANGSMITH_HIDE_INPUTS=true
LANGSMITH_HIDE_OUTPUTS=true
```

   Prefer `LANGSMITH_*` names (legacy `LANGCHAIN_TRACING_V2` may work — teach one set).

3. **`stream.py`:** When invoking `graph.stream`, pass config metadata:

```python
config = {
    "metadata": {"correlation_id": correlation_id},
    "tags": ["clinical-copilot"],
}
for update in graph.stream(initial, config=config, stream_mode="updates"):
    ...
```

4. **Redaction policy:** If `LANGSMITH_TRACING` is true (or equivalent), **force** hide inputs/outputs in process env at startup (do not rely on humans remembering). Do **not** put `pid` / message in metadata.
5. **Optional:** `langsmith.wrappers.wrap_openai` on the OpenRouter client in `llm.py` **only if** hide I/O is on — otherwise skip for MVP.
6. **`/ready`:** Add soft `langsmith: {configured, reachable?}` probe when tracing/key present; keep hard `ready` formula unchanged (gateway + OpenRouter). Never probe FDA.
7. **Fail-closed:** At start of `/v1/chat` (after secret check), call `check_readiness`; if not ready, return `StreamingResponse` that yields a single `error` SSE with `sidecar_unready` (or yield then close) — **no** `progress`/`clinical`. Reuse gateway correlation id from body/header.
8. **Disclosure endpoint** — new `interface/ask_copilot/disclosure.php` (preferred over overloading `tool_proxy`):
   - `$ignoreAuth = true`; secret header; correlation header/body.
   - Body: `{ "event": "verify", "correlation_id", "pass": bool, "reason": "<code>" }`.
   - Optional: confirm bind exists for correlation id (same store as tool_proxy) — **recommended**.
   - `DisclosureLog->write(...)`; return `{ok: true}`.
9. **Sidecar callback** after `verify_node` (or once from stream when verify results are known):
   - POST to `COPILOT_GATEWAY_DISCLOSURE_URL` (new) or derive from tool URL base + `disclosure.php`.
   - Headers: secret + correlation id.
   - `reason` allowlist examples: `ok`, `claims_dropped`, `all_refused`, `empty_verified`.
   - Timeouts short; log failures; **do not** set graph `error` on callback failure.
10. **Error copy:** `sidecar_unready` → `Co-Pilot is temporarily unavailable. Try again.` (no OpenRouter/LangSmith names).
11. **Alert stubs:** Add a short markdown subsection (this PRD §10 or README) defining three alerts (p95 latency, error rate, tool failure) + on-call response — **not wired**.
12. **Tests** per §7; update Memory Bank after ship.

### Key Functions/Methods

| Symbol | Role |
| --- | --- |
| `check_readiness` | Extend with soft langsmith; keep hard formula |
| `iter_chat_events` / chat entry | Ready gate before `build_graph` |
| `verify_node` or post-verify hook | Trigger disclosure callback |
| `DisclosureLog::write` | Persist `verify` |
| New PHP disclosure handler | Auth + write |
| `sse_error_payload("sidecar_unready")` | Fail-closed UI |

### Data Flow

```
Browser → stream.php (mint correlation_id, ask_start)
       → sidecar /v1/chat
            → if !ready → SSE error sidecar_unready → stop
            → graph.stream(metadata.correlation_id) ╌╌ redacted LangSmith
            → tools → tool_proxy (tool_proxy disclosure lines)
            → verify → POST disclosure.php {event:verify, pass, reason}
            → clinical → citation → done
```

Interview join: grep disclosure JSONL for `correlation_id` ↔ open LangSmith run with same metadata.

### Complex Logic Breakdown

**Ready vs tracing:**

| Condition | `ready` | Tracing | Chat |
| --- | --- | --- | --- |
| OpenRouter missing/unreachable or gateway down | `false` | n/a | `sidecar_unready` |
| OpenRouter+gateway OK, Smith off/missing | `true` | off | Normal |
| OpenRouter+gateway OK, Smith on but Smith API down | `true` | best-effort | Normal (soft field shows unreachable) |

**`verify.pass` heuristic (explicit):**

- `pass: true` when ≥1 verified claim **or** intentional allowlisted refusal-only answer that completed emit without graph `error` — prefer: `pass: true` iff `len(verified_claims) > 0`; `pass: false` with `reason: empty_verified` / `claims_dropped` / `all_refused` otherwise.
- Do **not** set `pass: true` merely because SSE will emit `done`.

---

## 5. Edge Cases and Error Handling

| Case | Behavior |
| --- | --- |
| No LangSmith keys | Chat + disclosure OK; `/ready.langsmith.configured=false` |
| Tracing on, hide env missing | **Force hide** at startup or refuse to enable tracing (prefer force hide) |
| Unready at chat start | SSE `sidecar_unready`; no graph; no clinical |
| Ready flips mid-turn | MVP: ignore (gate at start only) |
| Disclosure callback 401/5xx/timeout | Log; continue clinical path |
| Bad secret on disclosure.php | 401; no write |
| Missing correlation_id on callback | 400; no write |
| Bind missing for correlation | 403 (recommended); no write |
| Verify never ran (early refuse / unready) | No `verify` line (or skip) — do not invent `pass:true` |
| OpenRouter 4xx still “reachable” | Existing quirk; do not expand; key-empty already fails ready |
| Physician sees error | Short non-technical message only |

### Error Messages

| Code | Message |
| --- | --- |
| `sidecar_unready` | `Co-Pilot is temporarily unavailable. Try again.` |
| Existing `llm_*` / gateway codes | Unchanged |

### Validation

- Disclosure `reason`: non-empty short string; no claim/clinical text.
- `pass`: boolean only.
- Callback body must not include forbidden DisclosureLog keys.

---

## 6. Likely Pitfalls to Avoid

1. Enabling LangSmith **without** hide inputs/outputs — `GraphState` is a PHI firehose.  
2. `wrap_openai` without hide — prompts embed tool JSON / notes.  
3. Putting `pid` or message text in Smith metadata.  
4. Switching Compose healthcheck to `/ready` (restart / unhealthy churn).  
5. Hard-failing `ready` when LangSmith is down.  
6. Probing FDA/DailyMed from `/ready`.  
7. Gateway SSE parsing to infer verify (fragile under PRD 06 contract).  
8. Dual writers for `verify` (gateway + sidecar).  
9. Inferring verify success from SSE `done`.  
10. Failing clinical turn when disclosure callback fails.  
11. Logging claim/clinical text in `reason`.  
12. Physician-facing jargon (OpenRouter, LangSmith, `tool_proxy`, HTTP codes) in unready copy.  
13. Requiring Smith keys for local/DO chat.  
14. Building dashboards, wired alerts, or fake 50-user load reports.  
15. New OpenEMR observability UI.  
16. Replacing disclosure log with LangSmith.  
17. Publicly exposing sidecar or disclosure.php without secret.  
18. Event name drift (`verify_stub` / test-only `disclosure`).  
19. Assuming graph traces alone show token cost without wrap (OK for MVP — defend structure + join).  
20. Blocking this PRD on DO redeploy / PRD 06 manual smoke.

---

## 7. Testing Requirements

### Unit / isolated

| Area | Cases |
| --- | --- |
| `DisclosureLog` | `verify` event with `pass`/`reason`; forbidden keys stripped |
| PHP disclosure endpoint | 401 bad secret; 403 bind miss; 200 writes JSONL line |
| Sidecar ready | Soft langsmith field; H10 no FDA; hard formula unchanged |
| Sidecar chat unready | Mock `ready=false` → one `error` SSE `sidecar_unready`; graph not invoked |
| Tracing metadata | With tracing mocked/env, config includes `correlation_id` |
| Hide policy | Startup or helper forces hide when tracing on |

### Integration (sidecar pytest)

- Happy path still `progress` → `clinical` → `citation` → `done` with ready mocks.  
- Verify callback invoked once with expected payload (httpx mock).  
- Callback failure does not flip graph to error.

### Manual

| Setup | Action | Expect |
| --- | --- | --- |
| Keys off | Brief ask | Chat works; no Smith requirement |
| Keys on + hide | Brief ask | LangSmith run: nodes/latency; I/O hidden; metadata `correlation_id` |
| Same turn | Grep `copilot_disclosure.log` | `ask_start` + `tool_proxy`* + `verify` same id |
| Unset OpenRouter key / block gateway | Ask | `sidecar_unready`; no clinical |
| Compose | `docker inspect` healthcheck | Still `/health` |

**Test data:** Existing Synthea patients; no new clinical seeds.

---

## 8. Acceptance Criteria

- [ ] H1–H13 hold in code + tests where applicable.  
- [ ] LangSmith env-gated; hide inputs/outputs when tracing on; `correlation_id` in run metadata.  
- [ ] No `pid` / message / note bodies / tool fact text in LangSmith payloads.  
- [ ] `/health` + soft `/ready` documented; soft `langsmith` field; FDA never probed.  
- [ ] `ready=false` → SSE `sidecar_unready`; no clinical.  
- [ ] Compose healthcheck remains `/health`.  
- [ ] Disclosure JSONL gains `verify` lines via secret-gated callback.  
- [ ] Tracing off does not break chat.  
- [ ] Alert definitions stubbed in markdown (3 alerts).  
- [ ] No dashboard UI, load-test suite, or Bruno deliverable required.  
- [ ] Interview talk track documented: Graph ≠ Smith; app owns disclosure join.

**Performance:** One short disclosure POST per turn; no extra LLM calls.  
**Security:** Secret on internal PHP; redaction mandatory when tracing; demo keys optional.

---

## 9. Dependencies and Considerations

| Item | Notes |
| --- | --- |
| External | LangSmith cloud (optional); OpenRouter (existing hard dep) |
| DB | None |
| Config | `LANGSMITH_*`, `LANGSMITH_HIDE_*`; optional `COPILOT_GATEWAY_DISCLOSURE_URL` |
| Breaking | Unready now fails fast instead of later `llm_*` / timeout — intentional |
| Deploy | Sidecar rebuild + overlay PHP for `disclosure.php`; batch DO with PRD 06 OK |
| Rubric debt | Dashboards / wired alerts / 10–50 user load / baselines — document, don’t fake |

---

## 10. Project Notes

- Mid-level builder: **contrast Graph vs Smith** in the PRD/demo script — do not assume fluency.  
- Interview line: “Same `correlation_id` joins the app disclosure log to a redacted LangSmith run; the EHR boundary audit is not outsourced to the tracer.”  
- Early optics: one screenshot of a redacted run + this join; alert stubs below.  
- Deferred debt after ship: gateway `/ready` preflight; durable disclosure DB; tighten OpenRouter 4xx reachability; optional `wrap_openai` if not done; wired alerts.

### Alert definition stubs (not wired)

| Alert | Meaning | On-call response (demo) |
| --- | --- | --- |
| p95 latency > threshold | Physician waits too long | Check OpenRouter/gateway; reduce brief tool work; note single-worker limit |
| Error rate > threshold | Elevated SSE `error` | Check `/ready`, keys, disclosure/tool_proxy logs by `correlation_id` |
| Tool failure rate > threshold | Chart proxy / bind failures | Check secret, bind TTL, pid mismatch lines in disclosure JSONL |

### Decisions locked (this PRD)

1. Optional LangSmith keys; silent disable when absent.  
2. Hide inputs/outputs required when tracing on.  
3. Soft LangSmith on `/ready`; hard deps = gateway reachable + OpenRouter **key configured** (`openrouter.reachable` / LangSmith are soft). `/v1/chat` caches readiness (~30s TTL); `/ready` always fresh.  
4. Sidecar fail-closed with `sidecar_unready`; Compose stays on `/health`.  
5. Sidecar→PHP `verify` disclosure callback; best-effort.  
6. No `pid` in Smith metadata; no dashboard/load-test implementation.

### Assumptions

- PRD 06 SSE contract remains `clinical` → `citation` → `done`.  
- File JSONL disclosure remains acceptable through Early.  
- Demo data only; treat LangSmith as BAA-covered / no-training posture like OpenRouter.

---

## 11. References

- `ARCHITECTURE.md` §4.7, §6, §7 item 7  
- `docs/ai-decision-guide.md` §4, §8, §11–12, §14  
- `docs/directions.md` Observability + Engineering Requirements  
- `docs/PRDs/02-session-proxy-gateway.md` … `06-citations-hybrid-sse.md`  
- `memory-bank/activeContext.md` (update after implementation)

No `./attachments/` folder.
