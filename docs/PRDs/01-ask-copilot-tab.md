# PRD 01 — Ask Co-Pilot Tab (Step 1)

**Roadmap step:** `ARCHITECTURE.md` §7 item 1  
**Goal:** Ship a **working** Co-Pilot tab: empty chat, patient gate, stub SSE round-trip.  
**Non-goal:** Real LLM, chart tools, verification, LangGraph, LangSmith.

---

## 1. Problem Statement and Context

### What

Build the first vertical slice of Clinical Co-Pilot inside OpenEMR:

1. A first-class **Ask Co-Pilot** top-level menu tab (same iframe-tab shell as Calendar / Messages).
2. An empty chat UI in that iframe.
3. A **patient picker gate** when no session `pid` is bound.
4. A **stub SSE endpoint** that echoes the user’s message (progress → reply → done) so the chrome is demoable end-to-end.

### Background

Physicians need a multi-turn agent in the EHR shell (~30–90s between rooms). Step 1 proves the **UI + session + stream seam** before gateway/sidecar work (PRDs 02–07).

### Related Work

| Doc | Role |
| --- | --- |
| `ARCHITECTURE.md` | Locked topology, hybrid SSE contract, open-tab state |
| `USERS.md` / `USER.md` | UC-1/2/3; this PRD is chrome only |
| `docs/ai-decision-guide.md` | Simplicity-first; stubs OK for unfinished spine pieces |
| `memory-bank/activeContext.md` | Current focus / deferred debt |

Depends on: running OpenEMR (local and/or DO), logged-in session.  
Unblocks: PRD 02 (real gateway) behind the same SSE contract.

---

## 2. Technical Context

### Relevant Files/Modules

| Path | Why |
| --- | --- |
| `interface/main/tabs/main.php` | Post-login shell; Knockout tabs; CSRF globals |
| `interface/main/tabs/js/tabs_view_model.js` | `navigateTab`, `menuActionClick`, `requirement` gating |
| `interface/main/tabs/menu/menus/standard.json` | Reference shape for menu items (**do not edit**) |
| `src/Menu/MainMenuRole.php` | Dispatches `MenuEvent::MENU_UPDATE` |
| `src/Menu/MenuEvent.php` | Event constants |
| `interface/modules/custom_modules/oe-module-faxsms/openemr.bootstrap.php` | Canonical pattern for injecting a menu item via `MenuEvent` |
| `interface/main/messages/messages.php` | Simple iframe page: `globals.php` + `Header::setupHeader` |
| `library/ajax/set_pt.php` | Sets / reads session `pid` (CSRF required) |
| `interface/main/finder/dynamic_finder.php` | Existing patient Finder (reuse for picker) |
| `interface/main/tabs/js/user_data_view_model.js` | `viewPtFinder` (search → Finder tab) |

### Similar Implementations

- **Menu injection:** faxsms / dorn / weno / prior-auth modules — `addListener(MenuEvent::MENU_UPDATE, …)` and push a `stdClass` menu item (`requirement: 0`, `target`, `url`, `acl_req`).
- **Tab page:** Messages — thin PHP entry under `interface/`, themed via `Header::setupHeader`.
- **Patient selection:** Finder tab sets global session `pid`; attendant bar reflects it. Co-Pilot reuses that model.

### Architecture Notes

- Browser talks only to OpenEMR (never to a future sidecar).
- Tab must open with **no patient** (`requirement: 0`); picker gates chart work later.
- Transcript = **in-memory for the open iframe** until tab closed/refreshed (no DB).
- Twig/`autoescape` is **off** in OpenEMR — **escape all rendered chat text manually**.
- Hybrid SSE event names are locked for later steps; the stub must use the same names.

### Database/API Context

- **No schema changes.**
- Stub stream API (OpenEMR-only):

```
POST /interface/ask_copilot/stream.php
Content-Type: application/x-www-form-urlencoded (or multipart)
Body: csrf_token_form=<csrf>&message=<text>
Response: text/event-stream
```

Event contract (client must parse these; step 2 keeps the names):

| Event | When | `data` JSON |
| --- | --- | --- |
| `progress` | Immediately | `{ "message": "…" }` (non-clinical) |
| `clinical` | After “fake verify” delay | `{ "text": "…" }` — stub echo only; **not** real clinical claims |
| `done` | Always on success | `{ "correlation_id": "…" }` |
| `error` | On failure | `{ "message": "…" }` (generic; no exception internals) |

Do **not** invent a separate `reply` event name — keep the architecture names so the JS client survives PRD 02.

---

## 3. Design Decisions (Pre-Made)

### Approach

| Decision | Choice |
| --- | --- |
| Menu registration | **Event-driven** via a **minimal custom module** bootstrap that listens to `MenuEvent::MENU_UPDATE` and injects one top-level item. Do **not** edit `standard.json`. |
| Listener / domain code | Listener helper in `/src` (`OpenEMR\ClinicalCopilot\…`); module bootstrap only registers the listener. |
| Iframe page | `interface/ask_copilot/index.php` (legacy entry, same as Messages). |
| Stub stream | `interface/ask_copilot/stream.php` — session + CSRF + echo SSE; no LLM. |
| Patient model | **Reuse global session `pid`**. Picker opens Finder; selection uses existing OpenEMR flow (`setpid`). |
| Unbound UX | Gate banner + “Select patient” → open Finder tab; on return/send, re-read `pid` via `top.getSessionValue('pid')`. |
| Chat state | In-memory JS array in the iframe; wipe on refresh/close. |
| Assets | `Header::setupHeader` + small inline or one JS/CSS under `interface/ask_copilot/`. Bootstrap 4.6 / existing theme only. |

### Rationale

- Event injection works for **all** `main_menu_role` values, not only `standard`, and matches the “clean OpenEMR extension” interview story without a core JSON edit.
- Legacy `interface/ask_copilot/` URL matches how every existing top-level tab loads — no new router for one page.
- Global `pid` avoids reimplementing patient search; Finder already sets session correctly.
- Stub SSE makes step 1 a **working product** (send → stream → see reply), not dead chrome.

### Patterns/Libraries

- PHP: `declare(strict_types=1)` on new `/src` files; `CsrfUtils`; `SessionWrapperFactory`; `Header`; `text()` / `attr()` / `js_escape()` / `xlj()`.
- JS: vanilla or light jQuery already on the page; **no** new SPA framework. Prefer `fetch` + manual SSE parse (`ReadableStream`) **or** `EventSource` only if POST+CSRF can be satisfied (if EventSource GET is awkward with CSRF, use `fetch` streaming — **prefer fetch POST**).
- Menu item shape: same fields as Calendar/Messages (`label`, `menu_id`, `target`, `url`, `children`, `requirement`, `acl_req`).

### Code Organization

```
src/ClinicalCopilot/
  Menu/AskCopilotMenuSubscriber.php   # or Listener; builds menu stdClass + handles MenuEvent
interface/modules/custom_modules/oe-module-ask-copilot/
  openemr.bootstrap.php               # addListener only; enable module in Modules UI (or install script note)
  moduleConfig.php / info if required by module installer conventions
interface/ask_copilot/
  index.php                           # chat chrome
  stream.php                          # stub SSE
  assets/ask_copilot.js               # optional
  assets/ask_copilot.css              # optional, minimal
```

Module must be **installable/activatable** like other custom modules so `openemr.bootstrap.php` runs. Document one-time enable step in this PRD §9.

**Locked IDs (avoid collisions):**

| Field | Value |
| --- | --- |
| `menu_id` | `acp0` |
| `target` (iframe name) | `acp` |
| `label` | `Ask Co-Pilot` (via `xlt`) |
| `url` | `/interface/ask_copilot/index.php` |
| `requirement` | `0` |
| `acl_req` | `["patients", "demo"]` (same class of access as Finder; physician demo user has this) |

---

## 4. Implementation Guidance

### Step-by-Step Plan

1. **Scaffold module + `/src` listener**  
   - Implement `AskCopilotMenuSubscriber` (or listener method) that prepends/inserts the menu item near other top-level clinical tabs (after Messages is fine).  
   - In `openemr.bootstrap.php`: `$eventDispatcher->addListener(MenuEvent::MENU_UPDATE, …)`.  
   - Enable the module; hard-refresh login; confirm **Ask Co-Pilot** appears and opens an iframe named `acp`.

2. **Build `index.php` chrome**  
   - `require_once` `globals.php` (path relative like Messages).  
   - `Header::setupHeader` with minimal needs.  
   - Emit CSRF into JS (`CsrfUtils::collectCsrfToken`).  
   - Layout: header (“Ask Co-Pilot”), optional bound-patient line, message list, textarea, Send, progress line.  
   - Start with **empty** transcript (no auto-brief).

3. **Patient gate**  
   - On load (and before Send): `const pid = await top.getSessionValue('pid')` (parse JSON/string carefully — `set_pt.php` echoes `js_escape`’d value).  
   - If missing/`0`: show gate; disable Send; button calls `top.navigateTab(top.webroot_url + '/interface/main/finder/dynamic_finder.php', 'fin', () => top.activateTabByName('fin', true))`.  
   - After user selects a patient in Finder, they click Ask Co-Pilot tab again; re-check pid and enable chat.  
   - **Do not** accept pid from query string or form fields for authorization.

4. **Stub `stream.php`**  
   - Validate login/session; `CsrfUtils::checkCsrfInput` (same style as `set_pt.php`).  
   - Read message; reject empty.  
   - Mint `correlation_id` (e.g. `bin2hex(random_bytes(8))`).  
   - `session_write_close()` **immediately after** reading session (pid, user) so the UI does not freeze.  
   - Headers: `Content-Type: text/event-stream`, `Cache-Control: no-cache`, disable buffering if needed (`X-Accel-Buffering: no`, `@ini_set('output_buffering','off')`, flush).  
   - Emit `progress` → short sleep (~200–500ms) → `clinical` with escaped echo text like `Stub: I received: …` (plus pid if bound, for demo honesty) → `done`.  
   - On error: emit `error` + end.

5. **Wire Send in JS**  
   - Disable Send while streaming; append user bubble; open fetch stream; append progress text; append assistant bubble from `clinical`; re-enable on `done`/`error`.  
   - Escape all inserted text (`textContent` or a small `escapeHtml` — never `innerHTML` with raw model/user text).

6. **Smoke on local, then DO** when behavior is right (per decision guide: DO is interview source of truth).

### Key Functions/Methods

| Piece | Responsibility |
| --- | --- |
| `AskCopilotMenuSubscriber::onMenuUpdate` | Insert menu `stdClass`; return event |
| `index.php` | Render shell; bootstrap JS config (`webroot`, csrf, urls) |
| `stream.php` | AuthZ session, CSRF, SSE stub |
| `ask_copilot.js`: `readPid()`, `showGate()`, `sendMessage()`, `consumeSse()` | Client flow |

### Data Flow

```
Physician clicks Ask Co-Pilot
  → menuActionClick → navigateTab(.../ask_copilot/index.php, "acp")
  → iframe loads index.php (session cookie)

Unbound: gate → Finder → setpid in session → return to acp → readPid OK

Send:
  index.js → POST stream.php (csrf + message)
           → stream.php reads session pid/user, closes session write
           → SSE progress → clinical(echo) → done
           → UI appends bubbles (escaped)
```

### Complex Logic Breakdown

**SSE over POST:** browsers’ `EventSource` is GET-only. Use `fetch` + `response.body.getReader()`, split on `\n\n`, parse `event:` / `data:` lines. Keep a small parser; do not pull a large SSE library.

**`getSessionValue('pid')` return shape:** `set_pt.php` prints `text(js_escape($current))` — treat as a JSON-encoded scalar string/number after parse. Normalize to integer; treat `0` / `""` / `null` as unbound.

**Pid at send-time:** Always re-read session pid when Send is clicked. If unbound, refuse client-side (gate). Stub may include pid in echo for debugging; real authZ comes in PRD 02/04.

### Code Examples

Menu item (mirror faxsms):

```php
$item = new \stdClass();
$item->requirement = 0;
$item->target = 'acp';
$item->menu_id = 'acp0';
$item->label = xlt('Ask Co-Pilot');
$item->url = '/interface/ask_copilot/index.php';
$item->children = [];
$item->acl_req = ['patients', 'demo'];
// array_unshift($menu, $item) or insert after Messages (menu_id msg0)
```

SSE frame:

```text
event: progress
data: {"message":"Working…"}

event: clinical
data: {"text":"Stub: I received: hello"}

event: done
data: {"correlation_id":"a1b2c3d4e5f60718"}
```

---

## 5. Edge Cases and Error Handling

### Edge Cases

| Case | Handling |
| --- | --- |
| No `pid` | Gate UI; Send disabled; Finder CTA |
| `pid` becomes 0 mid-session | Next Send re-checks; show gate (no live watcher required in step 1) |
| Empty message | Client block; server 400 + `error` event if reached |
| Double Send / Enter spam | Disable Send until `done`/`error` |
| Tab refresh | Transcript cleared; empty chat OK |
| Tab hidden then shown | Iframe kept alive; transcript preserved (Knockout hide) |
| CSRF missing/invalid | Fail request; show generic error in UI |
| Session timeout mid-stream | Surface `error`; user re-login |
| User lacks `patients/demo` ACL | Menu item hidden by menu restrictor — expected |
| Module not activated | Tab missing — document enable step |
| `target` collision | Must use `acp` only |

### Error Scenarios

- Stream PHP exception → log server-side; emit generic `error` (“Something went wrong. Try again.”); never `$e->getMessage()` to browser.
- Network failure → catch in JS; show error bubble; re-enable Send.
- Non-SSE response (HTML login page) → detect non-event-stream / parse failure → error UI.

### Validation Requirements

- Message: non-empty after trim; max length (e.g. 4000 chars) server-side.
- CSRF required on `stream.php`.
- Authenticated OpenEMR session required.

### Error Messages (user-facing)

- Unbound: “Select a patient before chatting.”
- Empty: “Enter a message.”
- Stream fail: “Something went wrong. Try again.”
- Stub watermark in reply text is OK (e.g. prefix `Stub:`) so demos don’t look like real clinical advice.

---

## 6. Likely Pitfalls to Avoid

### Common Mistakes

- Editing `standard.json` instead of `MenuEvent` (breaks custom menu roles; merge pain).
- Reusing `target` `msg` / `cal` / `pat` / `fin` (hijacks existing tabs).
- Setting `requirement` to `1` (tab greyed until patient selected — wrong UX).
- Trusting `?pid=` on the Co-Pilot URL for anything security-related.
- `innerHTML = llmOrUserText` with autoescape off → XSS.
- Holding the PHP session open for the whole SSE duration → frozen shell.

### Gotchas

- Custom menus: event injection still runs after JSON load — good — but **module must be active**.
- `getSessionValue` needs `restoreSession()` (already inside helper).
- Output buffering may coalesce SSE; flush explicitly.
- Self-signed HTTPS on DO: use same origin; don’t hardcode `http://`.

### Performance Concerns

- Stub only: keep sleep short; don’t load heavy assets on `index.php`.
- No polling loops for pid in step 1 (check on load + Send only).

### Security Considerations

- Escape every user/stub string in the DOM.
- CSRF on stream.
- No secrets in client JS.
- Stub must not call OpenRouter or log full PHI beyond normal request logs.

### Integration Issues

- Attendant bar shows global patient — selecting in Finder changes whole app context (accepted).
- Live pid-change while a thread is open is **deferred**; document as known limitation (send-time re-check only).

---

## 7. Testing Requirements

### Test Scenarios

1. Module enabled → Ask Co-Pilot visible to `admin`.
2. Click tab → iframe loads empty chat.
3. No patient → gate; Send disabled.
4. Select Synthea patient in Finder → return → Send enabled; optional “Patient #N” label.
5. Send “hello” → progress then stub clinical echo → done; Send re-enabled.
6. Refresh Co-Pilot tab → transcript empty.
7. Invalid CSRF → error path, no crash.

### Unit Tests

- Menu subscriber returns menu containing `menu_id === 'acp0'` and `target === 'acp'` (isolated/unit if easy; otherwise skip and rely on manual — don’t block demo).

### Integration Tests

- Optional thin test that `stream.php` rejects missing CSRF (if harness already boots session). Prefer manual for step 1 if costly.

### Manual Testing

- Local `http://localhost:8300/` and DO `https://142.93.255.212/` after deploy.
- Confirm no JS console errors on send.
- Confirm other tabs (Calendar, Messages) still work.

### Test Data

- Any Synthea patient already imported; unbound session (clear patient) for gate test.

---

## 8. Acceptance Criteria

### Functional Requirements

- [ ] Ask Co-Pilot appears as a top-level tab without editing `standard.json`.
- [ ] Tab opens with empty chat when a patient may or may not be selected (`requirement: 0`).
- [ ] Unbound session shows picker gate; bound session allows Send.
- [ ] Send completes a stub SSE round-trip (`progress` → `clinical` → `done`).
- [ ] Transcript is in-memory only; refresh clears it.
- [ ] CSRF validated on stream endpoint.
- [ ] All chat text rendered safely (no raw HTML injection).

### User-Facing Behavior

- Physician can open Ask Co-Pilot like Messages, pick a patient via Finder if needed, type a message, and see a streamed stub reply within ~1s.

### Performance Requirements

- Stub TTFB progress event &lt; 1s on local; full stub turn &lt; 2s typical. No formal load test in step 1.

### Security Requirements

- Session required; CSRF required; no client-supplied pid trusted for auth; no exception details to UI.

---

## 9. Dependencies and Considerations

### External Services

- None for step 1 (no OpenRouter, no sidecar).

### Database Changes

- None.

### Configuration

- Enable custom module `oe-module-ask-copilot` (Modules admin UI) on local and DO after deploy.
- No new env vars required for step 1.

### Breaking Changes

- None expected. New menu item only.

### Migration Steps

1. Deploy code.
2. Activate module.
3. Hard refresh browser / re-login.
4. Smoke Send with a Synthea patient.

---

## 10. Project Notes from Ticket

### Important Notes

- Optimize for **working MVP**; polish and live pid-watchers are later.
- Stub clinical text must remain obviously non-authoritative (`Stub:` prefix).
- Preserve SSE event names for PRD 02.
- After merge: note deferred debt in Memory Bank — live pid-change reset, citation popups, real gateway, session-lock discipline hardening beyond `session_write_close`.

### Assumptions

- Demo user `admin` / `pass` has `patients`/`demo` ACL.
- Finder selection continues to call `setpid` as today.
- Knockout keeps the `acp` iframe mounted when switching tabs (current shell behavior).

### Deferred (explicitly out of this PRD)

- Real gateway / LangGraph / OpenRouter / verify / research / citations popup / disclosure log / LangSmith / `/health`/`/ready` / durable chat storage / auto-brief / caching.

---

## 11. Attachments and References

- No Jira attachments folder for this PRD.
- Canonical plan: `ARCHITECTURE.md`
- Decision shortcuts: `docs/ai-decision-guide.md`
- Diagrams: `docs/architecture-overview.md`
- Prior discussion context: Memory Bank + this file under `docs/PRDs/`
