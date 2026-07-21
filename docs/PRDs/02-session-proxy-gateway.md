# PRD 02 — Session-Proxy Gateway (Step 2)

**Roadmap step:** `ARCHITECTURE.md` §7 item 2  
**Goal:** Replace the PRD 01 stub stream with a **real session-proxy gateway**: validate OpenEMR session, bind `pid`, mint correlation ID, call an internal sidecar with a shared secret, proxy chart-tool calls with pid re-check (fail closed), SSE to the browser, disclosure/verification log stub.  
**Non-goal:** Real LangGraph agent loop, OpenRouter, `PatientContextService` chart data, verification logic, research tools, LangSmith, citation popups.

---

## 1. Problem Statement and Context

### What

Build the OpenEMR-side **trust boundary** for Clinical Co-Pilot:

1. **Browser → OpenEMR only** — validate login session + CSRF; never send cookies to the sidecar.
2. **Bind patient `pid` from session only** — ignore client- or model-supplied patient ids.
3. **Mint a correlation ID** per user ask; carry it on every hop and log line.
4. **Call a minimal sidecar** over Compose-internal HTTP with `COPILOT_INTERNAL_SECRET`.
5. **Proxy/flush SSE** from sidecar → browser (`progress` → `clinical` → `done` / `error`).
6. **Chart-tool proxy endpoint** that re-checks bound `pid` (fail closed) and returns a stub “not implemented” payload until PRD 04.
7. **Disclosure / verification log stub** (structured JSON lines; no note bodies).

### Background

OpenEMR GACL is role/section, not panel-scoped. The co-pilot must enforce patient binding in the gateway/tool layer. Architecture locks a hybrid topology: thin PHP gateway + LangGraph sidecar. This PRD implements the **gateway spine** with a **stub sidecar** so the hop is real before PRD 03 adds LangGraph.

### Related Work

| Doc | Role |
| --- | --- |
| `ARCHITECTURE.md` §4.1, §4.5, §7 item 2 | Session-proxy, hybrid SSE, roadmap |
| `docs/PRDs/01-ask-copilot-tab.md` | Tab chrome, SSE event names, module layout — **dependency** |
| `docs/ai-decision-guide.md` | Real seams required; stub unfinished graph/tools |
| `docs/architecture-overview.md` | Sequence: browser → gateway → sidecar → SSE |

**Depends on:** PRD 01 (Ask Co-Pilot tab + JS SSE client + CSRF). If 01 is not merged yet, implement 01 first or land both with 02 replacing `stream.php` stub behavior.  
**Unblocks:** PRD 03 (real LangGraph), PRD 04 (chart services behind the same tool proxy).

---

## 2. Technical Context

### Relevant Files/Modules

| Path | Why |
| --- | --- |
| `interface/ask_copilot/stream.php` | PRD 01 stub — **replace** with real gateway entry |
| `interface/ask_copilot/index.php` + assets | Browser client; keep SSE event names |
| `interface/modules/custom_modules/oe-module-ask-copilot/` | Module from PRD 01 |
| `src/Common/Http/HttpClient.php` / Guzzle | Pattern for outbound HTTP (use `GuzzleHttp\Client`; **no** raw `curl_*`) |
| `library/ajax/set_pt.php` | Session `pid` + CSRF pattern |
| `docker/development-easy/docker-compose.yml` | Add sidecar service + env for openemr |
| `tests/PHPStan/Rules/ForbiddenCurlFunctionsRule.php` | Enforces Guzzle over curl |

### Similar Implementations

- **CSRF + session AJAX:** `library/ajax/set_pt.php`
- **Outbound HTTP:** `GuzzleHttp\Client` (see telehealth config verifier, NPI lookup)
- **Custom module bootstrap:** faxsms / PRD 01 ask-copilot module

### Architecture Notes

- Browser never talks to sidecar.
- Sidecar trusts gateway via shared secret only.
- Chart reads (later) go **gateway → PHP services**; this PRD only ships the **pid-checked proxy seam**.
- Hybrid SSE: progress early; clinical only after sidecar emits it (stub sidecar may emit watermarked non-authoritative text).
- Twig/`autoescape` off — escape all UI text (client already from PRD 01).

### Database/API Context

- **No schema migrations.**
- Browser API (same URL as PRD 01):

```
POST /interface/ask_copilot/stream.php
Body: csrf_token_form=<csrf>&message=<text>&transcript=<json-optional>
Response: text/event-stream
```

- Do **not** accept `pid` from the browser body/query. If present, **ignore**.

- Sidecar → gateway chart proxy (internal):

```
POST /interface/ask_copilot/tool_proxy.php
Header: X-Copilot-Internal-Secret: <secret>
Header: X-Correlation-Id: <id>
Content-Type: application/json
Body: { "tool": "patient_context_stub", "args": { } }
```

Optional `args.pid` if sidecar sends one: must equal gateway-bound pid for that correlation/session context or **refuse**. Prefer omitting pid from sidecar args entirely — gateway uses its bound pid.

**SSE events (unchanged names):**

| Event | `data` JSON |
| --- | --- |
| `progress` | `{ "message": "…" }` |
| `clinical` | `{ "text": "…" }` |
| `done` | `{ "correlation_id": "…" }` |
| `error` | `{ "message": "…" }` (generic) |

`citation` is **out of scope** (later PRD).

---

## 3. Design Decisions (Pre-Made)

### Approach

| Decision | Choice |
| --- | --- |
| PRD scope | Gateway shell + real trust seams; **stub sidecar**, not LangGraph |
| Sidecar | Minimal Python (or tiny HTTP) service in Compose; echo SSE; validate secret |
| Stream hop | Gateway opens request to sidecar, **proxies/flushes** SSE bytes to browser |
| Internal auth | Env `COPILOT_INTERNAL_SECRET`; header `X-Copilot-Internal-Secret` both directions |
| Chart proxy | One endpoint; pid re-check; returns stub JSON until PRD 04 |
| Pid source | OpenEMR session only; ignore client/model pid |
| Transcript | Browser resends open-tab transcript JSON each POST (optional array) |
| Patient switch | Compare send-time session pid to client-supplied `bound_pid` (thread’s pid). Mismatch → `error` SSE instructing reset; client clears transcript |
| Disclosure stub | Append JSON lines to a log file under a docker-writable path (e.g. `sites/default/documents/copilot_disclosure.log` or `/var/log/copilot-disclosure.jsonl`) |
| Verification stub | Same log channel with `"event":"verify_stub"` |
| HTTP client | `GuzzleHttp\Client` with stream + timeout |
| Replace stub | No feature flag — `stream.php` becomes the real gateway |

### Rationale

- Decision guide: do not fake spine step 2; stub unfinished step 3/4 work.
- Shared secret is the simplest reversible MVP; per-turn tickets deferred.
- Browser-owned transcript keeps gateway thin (no chat DB).
- File JSONL disclosure avoids schema work while preserving correlation IDs for interview.

### Patterns/Libraries

- PHP: `declare(strict_types=1)` on new `/src` files; `CsrfUtils`; session helpers; Guzzle; PSR-3 logger where useful.
- Python stub: stdlib `http.server` **or** FastAPI/Starlette — pick **FastAPI** only if already planned for PRD 03; otherwise **stdlib or Flask-lite** is fine. Prefer one file `sidecar/stub_app.py` that PRD 03 can replace.
- JS: keep PRD 01 `fetch` + SSE parser; add optional `bound_pid` + `transcript` fields on send.

### Code Organization

```
src/ClinicalCopilot/
  Gateway/SessionGateway.php          # bind session user+pid, mint correlation id
  Gateway/SidecarClient.php           # Guzzle call + SSE proxy helper
  Gateway/ToolProxyService.php        # secret check + pid re-check + stub response
  Logging/DisclosureLog.php           # JSONL append (no note bodies)
interface/ask_copilot/
  stream.php                          # browser entry: CSRF, session_write_close, proxy SSE
  tool_proxy.php                      # sidecar entry: secret, no CSRF
docker/… or repo root:
  sidecar/
    stub_app.py                       # minimal SSE echo
    Dockerfile                        # tiny image
  docker-compose overlay / edit development-easy + DO compose
```

**Env (both openemr + sidecar containers):**

| Variable | Purpose |
| --- | --- |
| `COPILOT_INTERNAL_SECRET` | Shared secret (required in deploy) |
| `COPILOT_SIDECAR_URL` | e.g. `http://copilot-sidecar:8080` (openemr only) |
| `COPILOT_GATEWAY_TIMEOUT_SECONDS` | Default `45` |

Sidecar must **not** publish a host port on DO public interface (Compose internal only).

---

## 4. Implementation Guidance

### Step-by-Step Plan

1. **PRD 01 prerequisite**  
   Confirm Ask Co-Pilot tab, CSRF, SSE client, patient gate exist. If not, finish PRD 01 first.

2. **`SessionGateway` in `/src`**  
   - Require authenticated session.  
   - Read `authUserID` / username and `pid` from session.  
   - Normalize pid: missing/`0` → unbound.  
   - Mint `correlation_id` = `bin2hex(random_bytes(16))`.  
   - Return a small readonly DTO: `{ userId, username, pid, correlationId }`.  
   - **Never** take pid from request body.

3. **`DisclosureLog`**  
   - Method `write(array $fields): void` — JSON-encode one line + newline.  
   - Always include `correlation_id`, `ts`, `event`.  
   - Allowed fields: `user_id`, `pid`, `tool`, `pass`, `reason` (short codes).  
   - **Forbidden:** note text, full message body, full chart payloads.

4. **Replace `stream.php`**  
   - Validate CSRF + login.  
   - Build gateway context; if unbound → SSE `error` (“Select a patient…”) and stop (UI gate should already prevent; server is source of truth).  
   - Optional: if POST `bound_pid` present and ≠ session pid → `error` (patient switched); client resets.  
   - `session_write_close()` **immediately** after reading session.  
   - Log disclosure event `ask_start`.  
   - Call sidecar `POST {COPILOT_SIDECAR_URL}/v1/chat` with JSON:

```json
{
  "correlation_id": "…",
  "user_id": 1,
  "username": "admin",
  "pid": 6,
  "message": "…",
  "transcript": []
}
```

   - Headers: `X-Copilot-Internal-Secret`, `X-Correlation-Id`, `Accept: text/event-stream`.  
   - Proxy response stream to client; flush frequently.  
   - On timeout/connect failure: log + emit generic `error`.  
   - Ensure terminal `done` or `error` always reaches the client.

5. **Stub sidecar**  
   - Verify secret; reject 401 otherwise.  
   - Emit `progress` (“Working…”), short sleep, `clinical` with watermark `Stub sidecar: received … (pid=N)`, `done` with same correlation id.  
   - Optionally call `tool_proxy` once to prove round-trip (then ignore stub result) — **nice-to-have**, not required.

6. **`tool_proxy.php` + `ToolProxyService`**  
   - **No** OpenEMR browser session/CSRF.  
   - Constant-time secret compare.  
   - Resolve bound pid: for MVP, require header `X-Copilot-Bound-Pid` set by… **wait — sidecar must not invent pid.**  
   - **Locked approach:** sidecar echoes the `pid` it received from gateway on the chat request when calling tools; gateway compares that pid to… it has no session on tool_proxy.  
   - **Fix (pre-made):** Tool proxy trusts only: (1) valid secret, (2) JSON body includes `pid` **and** `correlation_id`, (3) gateway looks up **in-memory/apcu/file bind cache** written at `ask_start`: `correlation_id → {pid, user_id, expires}`. Mismatch or missing bind → refuse. TTL ~10 minutes.  
   - Stub tool response: `{ "ok": true, "tool": "patient_context_stub", "data": { "status": "not_implemented" } }` when pid matches.  
   - Log `tool_proxy` pass/fail.

7. **Compose wiring**  
   - Add `copilot-sidecar` service; attach to same network as `openemr`.  
   - Pass `COPILOT_INTERNAL_SECRET` + `COPILOT_SIDECAR_URL` into `openemr`.  
   - Document same vars for `/opt/openemr` on DO.  
   - Do not map sidecar ports to host in production/demo compose.

8. **Smoke**  
   Local then DO: bind Synthea patient → Send → progress → stub clinical → done; confirm disclosure log line; confirm wrong secret on tool_proxy fails; confirm unbound refused.

### Key Functions/Methods

| Piece | Responsibility |
| --- | --- |
| `SessionGateway::fromRequest()` | Session auth + pid bind + correlation id |
| `SidecarClient::streamChat(...)` | Guzzle stream; yields/writes SSE |
| `ToolProxyService::handle(array $body, string $correlationId)` | Bind-cache pid check + stub |
| `DisclosureLog::write(...)` | JSONL |
| `CorrelationBindStore::put/get` | correlation_id → pid (file or APCu) |

### Data Flow

```
Browser POST stream.php (csrf, message, transcript?, bound_pid?)
  → SessionGateway binds pid from session; mint correlation_id
  → session_write_close()
  → CorrelationBindStore.put(correlation_id, pid, user)
  → DisclosureLog ask_start
  → SidecarClient → stub sidecar /v1/chat
       (optional) sidecar → tool_proxy.php (secret + correlation_id + pid)
            → ToolProxyService re-check bind store → stub JSON
  → SSE frames flushed to browser
  → done { correlation_id }
```

### Complex Logic Breakdown

**SSE proxy with Guzzle:** Use `stream => true`, read body stream in chunks, `echo` + `flush()` / `ob_flush()`. Set `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`.

**Bind store without Redis:** Simple file under `sites/default/documents/copilot_binds/` named by correlation id, JSON `{"pid":N,"user_id":N,"exp":…}`, delete on expiry. Good enough for single-worker demo.

**Constant-time secret compare:** `hash_equals((string)$expected, (string)$provided)`.

**Ignore client pid:** Do not read `$_POST['pid']` / JSON `pid` on `stream.php`. Only session.

### Code Examples

SSE headers (PHP):

```php
header('Content-Type: text/event-stream');
header('Cache-Control: no-cache');
header('X-Accel-Buffering: no');
session_write_close();
```

Disclosure line:

```json
{"ts":"2026-07-21T19:00:00Z","event":"ask_start","correlation_id":"…","user_id":1,"pid":6}
```

Tool refuse:

```json
{"ok":false,"error":"pid_mismatch"}
```

---

## 5. Edge Cases and Error Handling

### Edge Cases

| Case | Handling |
| --- | --- |
| Unbound pid | SSE `error`; no sidecar call |
| `bound_pid` ≠ session pid | SSE `error` “Patient changed; start a new chat.”; no sidecar |
| Empty message | 400 / `error` |
| Message too long (>4000) | Reject |
| Sidecar down | Generic `error`; log reason server-side |
| Sidecar slow | Timeout → `error` |
| Invalid CSRF | Fail before stream |
| Session expired | Fail auth; client shows generic error |
| Tool proxy bad secret | 401 JSON; log fail |
| Tool proxy unknown correlation | 403 `bind_missing` |
| Tool proxy pid ≠ bind | 403 `pid_mismatch`; log fail |
| Client sends `pid` in body | Ignored |
| Double Send | Client disables Send (PRD 01); server best-effort OK |
| Transcript huge | Cap entries (e.g. last 20) server-side |

### Error Scenarios

- Guzzle connect/timeout → disclosure `ask_error` + SSE `error`.  
- Malformed sidecar stream → stop + `error`.  
- Bind store write failure → fail closed (do not call sidecar without bind if tools might run).

### Validation Requirements

- CSRF on `stream.php`.  
- Secret on `tool_proxy.php`.  
- Authenticated session on `stream.php`.  
- Pid > 0 for chart path.

### Error Messages (user-facing)

- Unbound: “Select a patient before chatting.”  
- Patient switch: “Patient changed. Clear the chat and try again.”  
- Sidecar/timeout: “Something went wrong. Try again.”  
- Never expose secrets, stack traces, or upstream URLs.

---

## 6. Likely Pitfalls to Avoid

### Common Mistakes

- Trusting body/query/`args.pid` without bind-store re-check.  
- Holding PHP session open during SSE.  
- Using browser CSRF on `tool_proxy.php` (sidecar has no cookie).  
- Publishing sidecar port publicly.  
- Putting secret in JS or SSE.  
- Raw `curl_*` (PHPStan forbidden).  
- Implementing real chart SQL in this PRD.  
- Calling OpenRouter from PHP.  
- Renaming SSE events.  
- Logging full chat/note text in disclosure stub.

### Gotchas

- PHP-FPM/nginx buffering — flush + `X-Accel-Buffering: no`.  
- DO compose must get the same env vars as local.  
- Stub clinical text must stay watermarked (`Stub sidecar:`) so it is not mistaken for verified care.  
- `tool_proxy` has no physician session — bind store is mandatory for pid fail-closed.

### Performance Concerns

- Single sidecar worker — document one-physician limit.  
- Timeout 45s default; don’t leave unlimited.  
- Keep stub sleep short (<500ms).

### Security Considerations

- Fail closed on unbound / mismatch.  
- `hash_equals` for secret.  
- Escape UI text (PRD 01).  
- Minimize PHI in logs.

### Integration Issues

- PRD 01 client must send `bound_pid` (session pid at thread start) for switch detection — small JS update allowed in this PRD.  
- Module must remain enabled.

---

## 7. Testing Requirements

### Test Scenarios

1. Bound patient → Send → `progress` → stub `clinical` → `done` with correlation id.  
2. Unbound → `error`; no sidecar hit (or sidecar not called).  
3. Wrong `COPILOT_INTERNAL_SECRET` on tool_proxy → 401.  
4. Tool proxy with wrong pid vs bind store → refuse + log.  
5. Sidecar stopped → generic `error` in UI.  
6. Disclosure log contains `ask_start` + correlation id (no note body).  
7. Client `pid` in POST ignored; session pid used.

### Unit Tests

- `SessionGateway` ignores request pid (isolated).  
- `ToolProxyService` pass/fail on pid mismatch (isolated with fake bind store).  
- `DisclosureLog` writes one JSON line (temp file).

### Integration Tests

- Optional: HTTP test for tool_proxy secret rejection. Prefer manual if costly.

### Manual Testing

- Local `http://localhost:8300/` and DO `https://142.93.255.212/`.  
- Confirm OpenEMR UI remains responsive during stream (`session_write_close`).

### Test Data

- Any Synthea patient; clear patient for unbound case.

---

## 8. Acceptance Criteria

### Functional Requirements

- [ ] `stream.php` validates session + CSRF, binds pid from session only, mints correlation ID.  
- [ ] Gateway calls Compose-internal sidecar with shared secret; browser never contacts sidecar.  
- [ ] SSE events `progress` → `clinical` → `done` (or `error`) reach the Ask Co-Pilot UI.  
- [ ] `tool_proxy.php` rejects bad secret and pid mismatch (fail closed); stub tool response on success.  
- [ ] Disclosure JSONL stub writes correlation-keyed events without note bodies.  
- [ ] Client/model-supplied patient ids are ignored / cannot override session bind.  
- [ ] Sidecar not exposed on public host port.

### User-Facing Behavior

Physician with a selected patient can send a message and see a streamed stub reply from the sidecar path, with a correlation id on completion. Failures show a generic error.

### Performance Requirements

- Progress event typically &lt; 2s local when sidecar is up.  
- Hard timeout ≤ 60s.

### Security Requirements

- Session + CSRF (browser); secret (sidecar); pid fail-closed on tool proxy; no secrets/exception details to UI.

---

## 9. Dependencies and Considerations

### External Services

- Stub sidecar only (no OpenRouter in this PRD).

### Database Changes

- None.

### Configuration

- `COPILOT_INTERNAL_SECRET` (required)  
- `COPILOT_SIDECAR_URL` (required on openemr)  
- `COPILOT_GATEWAY_TIMEOUT_SECONDS` (optional, default 45)  
- Enable ask-copilot module (PRD 01)  
- Document DO `/opt/openemr` env + compose update

### Breaking Changes

- Replaces PRD 01 echo stub behavior (intentional).

### Migration Steps

1. Deploy code + sidecar image/service.  
2. Set secrets on local and DO.  
3. `docker compose up` (or equivalent on DO).  
4. Smoke Send with Synthea patient.  
5. Record deferred debt in Memory Bank (per-turn tickets, real LangGraph, real chart tools, live pid watcher, durable disclosure DB).

---

## 10. Project Notes from Ticket

### Important Notes

- Spine step 2 must be **real** (session-proxy + pid seam + correlation + disclosure stub). Stub sidecar and stub chart payload are allowed.  
- Interview line: “Browser never sends cookies to the agent; PHP binds patient and re-checks on every chart tool.”  
- Live DO is source of truth after local works.

### Assumptions

- PRD 01 contracts (paths, event names, module) hold.  
- Demo user has normal patient ACL.  
- Single concurrent physician is acceptable.

### Deferred (explicitly out of this PRD)

- LangGraph graph, Haiku/OpenRouter, verify node, research, citations UI, `PatientContextService`, LangSmith, `/health`/`/ready` (thin OK in PRD 07), per-turn tool tickets, durable chat storage.

---

## 11. Attachments and References

- No Jira attachments folder.  
- Canonical: `ARCHITECTURE.md`  
- Decisions: prior chat + `docs/ai-decision-guide.md`  
- Prior PRD: `docs/PRDs/01-ask-copilot-tab.md`  
- Diagrams: `docs/architecture-overview.md`
