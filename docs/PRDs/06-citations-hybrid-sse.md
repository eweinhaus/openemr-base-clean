# PRD 06 — Citations + Hybrid SSE Polish

**Roadmap step:** `ARCHITECTURE.md` §7 item 6  
**Goal:** Wire **verified claims → clickable Source controls → in-pane citation popup**, and polish hybrid SSE so progress stays clinical-ish while clinical text is never shown pre-verify.  
**Non-goal:** Conflict UX, LangSmith / dashboard polish (PRD 07), FHIR-primary citations, required `fhir_uuid` / `retrieved_at`, unlabeled unverified clinical text, markdown/`innerHTML` rendering, new physician surfaces, chart writes, TTL cache, durable chat DB.

---

## 1. Problem Statement and Context

### What

Ship the interview **trust UI** on top of the existing verify path:

1. Sidecar emits structured **`clinical`** (`text` + `segments`) and one batch **`citation`** event from **verified claims only**.
2. Ask Co-Pilot JS waits for `clinical` + `citation`, then renders claim lines with a trailing **Source** control; assembly/refusal/disclaimer lines stay plain.
3. Click Source → **in-pane dialog** (picker-style overlay) with locator + excerpt (+ research title/URL when available).
4. Research popup may offer an allowlisted **https** “Open label” link (`target=_blank`, `rel=noopener noreferrer`).
5. Polish progress strings to clinical-ish domain copy (drop toolchain jargon).

### Background

PRDs 01–05 deliver tab → gateway → LangGraph → chart + research → cite-or-silence verify → hybrid SSE (`progress` → plain `clinical` → `done`). Claims already carry `source_type` + `locator` + `excerpt`, but the UI shows a flat string with **no audit path**. Architecture and `docs/ai-decision-guide.md` lock “link every verified claim” and reject streaming unverified clinical prose.

### Related Work

| Doc / code | Role |
| --- | --- |
| `ARCHITECTURE.md` §4.4–4.5, §7 item 6 | Popup sketch; hybrid SSE events |
| `docs/ai-decision-guide.md` §6, §8, §10–12 | Citation policy; PRD 06 defaults; anti-patterns |
| `docs/PRDs/01-ask-copilot-tab.md` | SSE names; `textContent`-only XSS rule |
| `docs/PRDs/03-langgraph-sidecar.md` | Claim schema; `citation` deferred here |
| `docs/PRDs/04-chart-tools.md` | Assembly lines ≠ claims (no fake locators) |
| `docs/PRDs/05-research-tools.md` | Research facts / excerpt URL; conflict **still** deferred |
| `interface/ask_copilot/assets/ask_copilot.js` | SSE client; picker dialog pattern |
| `sidecar/app/claims.py` / `stream.py` / `nodes/emit.py` | Assemble + emit — must extend |

**Depends on:** PRDs 01–05 (local + DO smoke OK). **Unblocks:** interview trust demo; PRD 07 observability polish.

---

## 2. Technical Context

### Relevant Files/Modules

| Path | Change |
| --- | --- |
| `sidecar/app/claims.py` | `assemble_clinical` → also build `segments` + citation payloads from verified claims |
| `sidecar/app/stream.py` | Emit `clinical` with `text`+`segments`; then one `citation` batch; then `done` |
| `sidecar/app/nodes/tools.py` / `route.py` | Progress string polish (clinical-ish) |
| `sidecar/app/research/extract.py` (optional small) | Prefer structured title/url helpers if parsing excerpt is fragile — **do not** expand FDA scope |
| `interface/ask_copilot/index.php` | Citation dialog + backdrop markup (sibling to picker) |
| `interface/ask_copilot/assets/ask_copilot.js` | `citation` handler; buffered render; Source controls; popup |
| `interface/ask_copilot/assets/ask_copilot.css` | Cite dialog + Source control styles (OpenEMR-familiar) |
| `tests/js/ask-copilot-*.test.js` | New Jest cases (mirror picker tests) |
| `sidecar/tests/test_verify.py` / chat integration | Segments + citation emit; assembly unmarked |
| PHP gateway / `SidecarClient` | **Pass-through only** — do not invent citations |

### Similar Implementations

- **Patient picker overlay** — custom `role="dialog"` + backdrop + Escape/focus trap (`ask_copilot.js` / `index.php`). **Reuse this chrome**, not Bootstrap `.modal` / popover.
- **XSS-safe DOM** — `createElement` + `textContent` everywhere in Ask Co-Pilot (no `innerHTML`).
- **Verify → assemble** — `emit_node` + `assemble_clinical` already separate claim texts from assembly copy.

### Architecture Notes

- Browser never talks to sidecar; gateway proxies SSE bytes.
- Clinical text **only after verify**. Progress may stream during tools.
- Twig `autoescape` off — client must escape via DOM APIs.
- Transcript remains plain role/text for resend; citation markup is **display-only**.

### Database/API Context

**No schema migrations. No new env vars.**

**SSE contract (extend; keep names):**

| Event | When | `data` |
| --- | --- | --- |
| `progress` | During route/tools | `{ "message": "<clinical-ish>" }` |
| `clinical` | After verify/emit | `{ "text": "<flat>", "segments": [ ... ] }` |
| `citation` | Immediately after `clinical` | `{ "citations": [ ... ] }` **one batch** |
| `done` | Success end | `{ "correlation_id": "…" }` |
| `error` | Failure | `{ "message": "…", "code"?: "…", … }` (unchanged) |

Order: `progress*` → `clinical` → `citation` → `done`  
On graph/SSE `error`: no clinical/citation requirement (existing error path).

---

## 3. Design Decisions (Pre-Made)

| Decision | Choice |
| --- | --- |
| Link density | **Every** verified claim |
| Link affordance | Claim text **plain** + trailing **Source** control (`btn btn-link btn-sm`) |
| Claim layout | **Newline** between claim segments; assembly/refusal/disclaimer lines plain (still unlinked) |
| Clinical encoding | `segments[]` — **not** `[[c:1]]` markers / markdown |
| Citation transport | **One** `citation` batch event after `clinical` |
| Paint timing | Client **buffers** until both `clinical` + `citation` arrive (or timeout → plain `text`) |
| Popup chrome | Clone picker overlay (`#acp-cite` / backdrop); stay in iframe |
| Popup fields | `source_type`, `title`, `excerpt`, `locator.table`, `locator.id`, optional `locator.url` |
| `fhir_uuid` / `retrieved_at` | **Omit or null** — deferred debt; do not display as if populated |
| Research Open label | Allowlisted `https` only → new tab; show URL text always |
| URL allowlist | `dailymed.nlm.nih.gov`, `api.fda.gov` (and `www.` variants if needed) |
| Unverified block | **Out of scope** unless blocked; prefer omit/refuse |
| Conflict UX | **Still forbidden** (PRD 05 lock) |
| Progress | Clinical-ish domain strings; no % complete; no tool/HTTP jargon |
| Gateway | Byte proxy only |

### Product locks (builder-confirmed 2026-07-22)

1. **1B** — trailing Source control (not whole-claim underline).  
2. **2A** — allowlisted external Open label link.  
3. **3B** — one claim per line (newlines between claim segments).

### Hard invariants

| # | Invariant | Enforcement |
| --- | --- | --- |
| H1 | Only `kind: "claim"` segments may carry `citation_id` | Assemble from `verified_claims` only |
| H2 | Assembly / disclaimer / not-on-list / refusal / empty-domain / `EMPTY_CLINICAL` never get Source | `kind: "assembly"` (or equivalent) without `citation_id` |
| H3 | Every `citation_id` on a segment exists in the `citation` batch | Emit-time pairing; test |
| H4 | No citation payload invented in PHP or browser | Sidecar-only construction from verified claims + tool facts |
| H5 | Popup never implies backing for unlabeled/unverified text | No unverified path in this PRD |
| H6 | XSS: no `innerHTML` / markdown HTML for clinical or popup body | DOM APIs + `textContent` |
| H7 | External `href` only after `https:` + host allowlist | JS URL guard |
| H8 | Hybrid order: no `clinical` before verify; `citation` after `clinical` before `done` | `stream.py` |
| H9 | Flat `text` remains valid fallback / transcript content | Assemble still builds joined plain string (claims newline-separated) |
| H10 | Research citations keep `source_type: "research"` | Pass through claim field |
| H11 | Citation dialog and patient picker mutually exclusive | JS: close one when opening the other |
| H12 | Focus returns to the Source control that opened the dialog | JS on close |
| H13 | Progress strings physician-facing | Allowlist / constants in tools/route nodes |

### Patterns / code organization

- Prefer small helpers: `build_clinical_payload(verified, …)` next to `assemble_clinical`; `build_citation_payloads(verified, tool_results)`.
- Derive research `title` / `url` from fact `excerpt` (`"{title} — {url}"`) and/or `set_id` via existing DailyMed URL builder — **do not** require new FDA fields.
- Chart `title`: short human label from excerpt first line or table-friendly label (e.g. `Lab result`, `Active medication`) — never invent clinical values.
- Empty excerpt → popup still shows `source_type` + `table` + `id` fallback line: `Chart locator: {table} #{id}` (or research equivalent).

### Layout (UI)

```
interface/ask_copilot/
  index.php              # + #acp-cite-backdrop, #acp-cite dialog
  assets/ask_copilot.js  # buffered SSE render + cite dialog
  assets/ask_copilot.css # cite dialog / Source control
```

Sidecar changes stay under `sidecar/app/` (claims, stream, progress constants).

---

## 4. Implementation Guidance

### Step-by-step

1. **Sidecar assemble**  
   - Refactor `assemble_clinical` (or add sibling) to return:
     - `text`: claims joined with `\n`, then assembly blocks (space or newline — prefer `\n` before assembly block for scanability).  
     - `segments`: ordered list — each verified claim → `{kind:"claim", text, citation_id}`; each assembly/refusal/disclaimer/domain line → `{kind:"assembly", text}`.  
   - Assign `citation_id` = `c1`…`cN` in verified order.

2. **Citation payloads**  
   For each verified claim, build:
   ```json
   {
     "citation_id": "c1",
     "source_type": "chart",
     "title": "…",
     "excerpt": "…",
     "locator": { "table": "procedure_result", "id": "42", "url": null }
   }
   ```
   Research: set `locator.url` when derivable; `title` from excerpt/meta.

3. **`stream.py`**  
   ```
   yield ("clinical", { "text": ..., "segments": [...] })
   yield ("citation", { "citations": [...] })  # empty array OK if zero claims
   yield ("done", { "correlation_id": ... })
   ```
   Always emit `citation` after successful `clinical` (even if `citations: []`) so the client unblocks.

4. **Progress polish**  
   Replace `Routing…` / bare `Fetching chart…` with allowlisted clinical-ish strings, e.g.:
   - brief fan-in: `Pulling chart…` then optional per-domain if easy (`Pulling labs…`, `Checking medications…`, `Reviewing chart notes…`) — **one at a time is enough**  
   - meds chart: `Checking medications…`  
   - research HTTP: keep `Looking up label information…`  
   Exact wording may vary if still clinical-ish.

5. **UI markup**  
   Add cite backdrop + dialog (title, body region, Close). Reuse picker z-index / `d-none` pattern.

6. **JS SSE**  
   - Handle `citation`.  
   - Buffer: on `clinical` store payload; on `citation` store map; when both present → `renderAssistantTurn`.  
   - Timeout (~2–3s after `clinical` without `citation`, or on `done`): render flat `text` without Source.  
   - `renderAssistantTurn`: for each segment — claim → text node + Source button (`data-cite-id`); assembly → text node; separate claim lines with `\n` / block elements (`div` per segment OK).  
   - Source click → fill dialog via `textContent` / createElement; open dialog; trap focus lightly (copy picker).  
   - Open label: only if `locator.url` passes allowlist.

7. **Tests + smoke**  
   Update assemble order tests for newlines; add citation emit tests; Jest for render + popup + URL guard.

### Key functions (suggested)

| Name | Where | Role |
| --- | --- | --- |
| `build_clinical_payload(...)` | `claims.py` | `text` + `segments` |
| `build_citation_records(...)` | `claims.py` | batch list |
| `iter_chat_events` | `stream.py` | emit order |
| `renderAssistantTurn` | `ask_copilot.js` | DOM bubble |
| `openCitation` / `closeCitation` | `ask_copilot.js` | dialog |
| `isAllowlistedHttpsUrl(url)` | `ask_copilot.js` | URL guard |

### Data flow

```
verify → verified_claims
      → build_clinical_payload + build_citation_records
      → SSE clinical → SSE citation → done
      → JS buffer → DOM (plain + Source)
      → Source click → in-pane popup (± Open label)
```

### Complex logic

**Buffering:** Do not call `appendBubble(text)` for clinical anymore. Keep a per-send `pendingClinical` / `pendingCitations`. Render once. If `error` arrives, clear pending and show error.

**Title/url derivation (research):** Prefer split excerpt on `" — "` when right side looks like `https://…`; else build DailyMed URL from `set_id` in tool meta when locator table is `openfda`/`dailymed`.

**Zero claims:** Still emit `clinical` (assembly/empty message) + `citation: {citations:[]}`; no Source controls.

---

## 5. Edge Cases and Error Handling

| Case | Behavior |
| --- | --- |
| Zero verified claims | Plain assembly/empty text; empty citations array; no Source |
| Duplicate locator in draft | Verify already dedupes — one citation |
| `citation` missing | Timeout / `done` → render flat `text`; no hang |
| `citation_id` orphan on segment | Do not render Source for that segment (log/dev assert in tests) |
| Empty excerpt | Fallback locator line in popup |
| Research without URL | Show excerpt/title only; hide Open label |
| Non-allowlisted URL | Never set `href`; show as text or omit link |
| Picker open | Close cite first / refuse opening cite over gate as needed — picker wins when unbound |
| Patient switch mid-stream | Existing error/reset path; clear pending cite state |
| Prior transcript turns | Plain text only on resend; historical bubbles need not re-hydrate citations (MVP OK) |
| Partial tool failure | Verified claims still linked; unavailable assembly line unlinked |
| Off-chart not-on-list | Unlinked assembly; research claim (if any) linked separately |

**Validation:** Sidecar only cites verified claims; JS must not invent locators from prose.

**User-facing errors:** Unchanged generic stream fail copy; citation failures degrade to plain text (not a scary error).

---

## 6. Likely Pitfalls to Avoid

- Linking disclaimer / refuse / empty / not-on-list (“looks cited”).  
- `innerHTML` or markdown-to-HTML for “easy” links.  
- Painting clinical before citations (flash) or waiting forever (hang).  
- Bootstrap modal/popover (iframe clip + dual focus systems).  
- Inventing `fhir_uuid` / `retrieved_at` display values.  
- Reopening conflict UX “while we’re in citations.”  
- Putting HTML into transcript resend payload.  
- Toolchain progress (`Routing…`, `tool_proxy`, HTTP status).  
- Skipping Source on verified claims to “reduce clutter.”  
- Client-side guessing of chart rows from claim text.  
- Breaking gateway flush / SSE framing when payloads grow (keep excerpts capped as today).

**Security:** XSS via claim/excerpt strings; open redirects via `href`; never send cookies to DailyMed (browser navigates user-initiated only).

**Integration:** Old JS that only reads `data.text` still works via flat `text`; new JS requires `segments` for Source — always send both.

---

## 7. Testing Requirements

### Unit (sidecar)

- Assemble: claim segments have `citation_id`; assembly segments do not.  
- Citation batch length == verified claim count; ids match.  
- Research citation includes derivable url/title when excerpt has DailyMed URL.  
- Empty verified → `citations: []` still emitted after clinical.  
- Progress allowlist / expected strings for brief/meds/research paths (spot-check).

### Unit (Jest)

- `renderAssistantTurn` creates Source only for claim segments.  
- Source opens dialog with locator + excerpt via `textContent`.  
- URL guard rejects `javascript:`, `http:`, evil hosts; accepts DailyMed https.  
- Buffer: clinical-only then timeout → plain text; clinical+citation → linked.  
- Escape/Close restores focus to Source button.

### Integration

- Chat smoke (mocked tools): `progress` → `clinical` (with segments) → `citation` → `done`.  
- Dosing happy path: ≥1 research citation with `source_type: research`.

### Manual

| Bind | Ask | Expect |
| --- | --- | --- |
| Synthea pid with labs/meds (e.g. local **6**) | Pre-visit brief / “summarize this patient” | ≥**2** Source controls; popup shows chart locator + excerpt |
| pid **6** | typical adult dose simvastatin | Research Source + Open label (allowlisted); not-on-list (if any) **unlinked** |
| pid **2** | dosing lisinopril | Chart/uncertain + refuse unlinked; no fake research Source |
| Any | Send | Progress clinical-ish before clinical; Send re-enables on done |

**Test data:** Existing Synthea patients; no new seeds required for citations.

---

## 8. Acceptance Criteria

- [ ] H1–H13 hold in code + tests where applicable.  
- [ ] SSE order on success: `progress*` → `clinical` `{text,segments}` → `citation` `{citations}` → `done`.  
- [ ] Every verified claim has a trailing **Source** control; assembly lines do not.  
- [ ] Source opens **in-pane** popup with `source_type`, locator, excerpt (title when available).  
- [ ] Research Open label works only for allowlisted https; `noopener noreferrer`.  
- [ ] Claim segments render **one per line**; no whole-bubble `innerHTML`.  
- [ ] Missing citation batch degrades to plain text (no infinite wait).  
- [ ] Progress copy is clinical-ish on happy paths (no toolchain jargon).  
- [ ] UC-1 manual: ≥2 linked citations on a Synthea patient.  
- [ ] UC-3 manual: ≥1 research citation popup when label-backed dosing succeeds.  
- [ ] No conflict feature; no LangSmith work; `fhir_uuid` not required.  
- [ ] PHP does not construct citation payloads.

**Performance:** Citation JSON small (reuse existing excerpt caps); no extra LLM calls.  
**Security:** DOM-only render; URL allowlist; session-proxy unchanged.

---

## 9. Dependencies and Considerations

| Item | Notes |
| --- | --- |
| External | User-initiated DailyMed/openFDA pages only (no new server egress for 06) |
| DB | None |
| Config | None new |
| Breaking | Clients that assume clinical `data` is only `{text}` still work; Prefer updating Ask Co-Pilot JS in same PR |
| Deploy | Sidecar rebuild + overlay JS/CSS/PHP on DO when demoing; batch OK per decision guide |

---

## 10. Project Notes

- Mid-level builder: this PRD is **presentation + contract**, not a new verifier — do not weaken cite-or-silence.  
- Interview line: “Every on-screen clinical claim is one click from its chart or label locator.”  
- Deferred debt to record in Memory Bank after ship: `fhir_uuid` population, `retrieved_at`, historical transcript citation re-hydrate, conflict link pairs.  
- Do not thin link density for aesthetics (escalation topic).

### Decisions locked (this PRD)

1. Trailing **Source** control (not full-text link).  
2. Allowlisted external Open label.  
3. Newline-separated claim segments.  
4. `segments` + batch `citation` event; client buffers both.  
5. Picker-style in-pane dialog; DOM-only XSS posture.  
6. `fhir_uuid` / `retrieved_at` / conflict / unverified UI / LangSmith out of scope.

---

## 11. References

- `ARCHITECTURE.md` §4.4–4.5 / §7 item 6  
- `docs/ai-decision-guide.md` §6, §8, §10–12  
- `docs/PRDs/01-ask-copilot-tab.md` … `05-research-tools.md`  
- `memory-bank/activeContext.md` (update after implementation)

No `./attachments/` folder.
