# PRD 10 — Conversational Synthesis (All Routes) + Collapsed Sources

**Roadmap step:** Post–PRD 08 enhancement to UC-1 / UC-2 / UC-3 answer shape  
**Goal:** Every job route (`brief`, `labs`, `meds`) returns a **labeled narrative paragraph** first, with **verified claim lines collapsed by default** below for audit — without weakening cite-or-silence verify or PRD 06 citations.  
**Non-goal:** New SSE event types, relaxing verify, narrative-only turns (drop sources), synthesizing on zero verified claims, labs/meds TTL cache, feature flags, transcript DB.

---

## 1. Problem Statement and Context

### What

PRD 08 added post-verify narrative synthesis for **`route=brief` only**. Follow-up turns (`labs`, `meds`) still emit a flat stack of database-shaped verified claim lines with no conversational framing. The brief also shows all Source controls expanded, which clutters the primary read path.

This PRD:

1. **Generalizes synthesis** to `brief`, `labs`, and `meds` when `verified_claims ≥ 1`.
2. **Collapses verified claim segments** in Ask Co-Pilot UI (default **collapsed**), with a toggle to expand and use Source popups.
3. Keeps **assembly lines** (empty, unavailable, disclaimer, refusals, not-on-list) **always visible** outside the collapse.

### Background

- **Persona / jobs** (`USER.md`, `docs/ai-decision-guide.md` §2): clinic PCP, ~30–90s between rooms; UC-1 brief, UC-2 labs Q&A, UC-3 med decision-support.
- **Trust model** (`ARCHITECTURE.md` §4.4): cite-or-silence on verified path; unverified synthesis is **hard-labeled**, never Source-linked.
- **PRD 08** established the two-layer pattern (summary + claims); this PRD extends it to all routes and changes **presentation** (collapsed audit).
- **Latency:** +1 Haiku per eligible turn (~1–2s) is accepted; PRD 09 prefetch cache still applies to **brief only**.

### Related Work

| Doc | Role |
| --- | --- |
| `docs/PRDs/08-brief-narrative-synthesis.md` | Baseline synthesize node, guard, `kind:summary` |
| `docs/PRDs/06-citations-hybrid-sse.md` | Segments, Source controls, SSE order |
| `docs/PRDs/04-chart-tools.md` | Route tool fan-in |
| `docs/PRDs/05-research-tools.md` | Meds research, assembly lines (disclaimer, not-on-list) |
| `docs/PRDs/09-brief-prefetch-cache.md` | Cache stores post-emit payload; brief shape must stay compatible |
| `docs/ai-decision-guide.md` | **Update §6** — narrative on all routes + collapsed audit UI |

**Depends on:** PRDs 03–08 (landed). **Parallel-safe with:** PRD 09 (rename state field carefully if 09 lands first).

### Project Notes (planning session 2026-07-23)

- User locked: **conversational everywhere**, **default collapsed sources**, latency OK on every turn.
- Interview demo: read summary first; expand sources when auditing trust.
- No separate feature flag — one answer shape for all routes.

---

## 2. Technical Context

### Relevant Files/Modules

| Path | Change |
| --- | --- |
| `sidecar/app/graph.py` | `_after_verify`: synthesize for `brief` \| `labs` \| `meds` when verified > 0 |
| `sidecar/app/nodes/synthesize.py` | Route dispatch, labels, shared guard; rename output field |
| `sidecar/app/llm.py` | Route-specific synthesize prompts + `LABS_DRAFT_ADDENDUM`, `MEDS_DRAFT_ADDENDUM` |
| `sidecar/app/nodes/draft.py` | Already passes `route`; no structural change |
| `sidecar/app/state.py` | Rename `brief_summary` → `turn_summary` |
| `sidecar/app/nodes/emit.py` | Pass `turn_summary` to payload builder |
| `sidecar/app/claims.py` | Rename param `brief_summary` → `turn_summary` in `build_clinical_payload` |
| `sidecar/app/progress.py` | Add `PROGRESS_SUMMARIZING = "Summarizing…"`; emit from synthesize node |
| `interface/ask_copilot/assets/ask_copilot.js` | Collapsible claims region in `renderAssistantTurn` |
| `interface/ask_copilot/assets/ask_copilot.css` | Toggle + collapsed panel styling |
| `interface/ask_copilot/index.php` | Optional localized strings for toggle |
| `sidecar/tests/test_synthesize.py` | Labs/meds routes, labels, guard fallbacks |
| `sidecar/tests/test_chat_integration.py` | SSE `kind:summary` on labs/meds |
| `sidecar/tests/test_citations_assemble.py` | Param rename |
| `tests/js/ask-copilot-citations.test.js` | Collapse default, toggle, Source when expanded |
| `docs/ai-decision-guide.md` | §6 answer density update |
| `memory-bank/activeContext.md` | Document shape decision |

### Similar Implementations

- **PRD 08** — `synthesize_node`, `diagnose_guard_summary`, `build_domain_context_for_synthesis`.
- **PRD 06** — `renderAssistantTurn`, `attachSourceControl`, `#acp-cite` dialog.
- **Modal show/hide** in `ask_copilot.js` (`d-none` on picker/cite) — pattern for collapse toggle (not `<details>` required).

### Architecture Notes

- **Cite-or-silence unchanged:** verify replaces draft text with tool fact strings; synthesis never becomes a verified claim.
- **Hybrid SSE unchanged:** `progress*` → `clinical` `{text, segments}` → `citation` → `done`; clinical only after verify + synthesize complete.
- **Collapse is UI-only:** SSE segment list unchanged; transcript plain-text join still includes all segment text.
- **Assembly stays code-only:** `claims.py` `_assembly_lines` — never LLM-authored disclaimer / not-on-list / unavailable copy.
- **Single worker / 2 GB** — no new infra.

### Database/API Context

**No schema migrations.** No gateway PHP changes (byte pass-through SSE).

Segment order (unchanged backend):

```
summary → claim* → assembly*
```

UI render order:

```
summary (visible) → [collapsed: claim* + Source] → assembly* (visible)
```

---

## 3. Design Decisions (Pre-Made)

### Approach

**Generalize PRD 08 post-verify synthesize + frontend collapse of claim segments.**

| Decision | Choice | Rationale |
| --- | --- | --- |
| Routes | `brief`, `labs`, `meds` | Maps to UC-1/2/3 |
| Synthesize gate | `verified_claims.length > 0`, no `error` | Zero claims → assembly only; no duplicate empty copy |
| Graph | Same node `synthesize`; route dispatch inside | One guard, one edge |
| State field | `turn_summary` (rename from `brief_summary`) | Not brief-only anymore |
| Labels | Route-specific fixed prefix + `\n\n` + paragraph | Hard-label unverified (§6) |
| Voice | Third-person clinical, terse | Consistent with brief |
| Length (prompt) | brief ~80–120 words; labs/meds ~40–80 words | Scannable follow-ups |
| Guard | Reuse `diagnose_guard_summary` (novel numerics + length >1200) | PRD 08 date-aware grounding; **no** English vocabulary hard gate |
| Guard fail | Omit summary; claims-only (collapsed); no SSE `error` if claims exist | PRD 08 fallback |
| Collapse default | **Collapsed** on first paint | Conversational first read |
| Inside collapse | `kind:claim` + Source buttons only | Audit preserved |
| Outside collapse | `kind:summary` + all `kind:assembly` | Safety/disclaimer visible |
| Toggle copy | `Show verified sources (N)` / `Hide sources` | N = claim segment count |
| Progress | Append `Summarizing…` via `progress_messages` before Haiku call | Clinical-ish (§6) |
| PRD 09 cache | Unchanged scope (brief prefetch only); cached payload already has `clinical_segments` | No labs/meds cache |
| Feature flag | None | One shape |

### Route-specific labels

| Route | Prefix (include in `turn_summary` string) |
| --- | --- |
| `brief` | `Chart summary — verify sources below.` |
| `labs` | `Lab summary — verify sources below.` |
| `meds` | `Medication summary — verify sources below.` |

### Route-specific synthesize prompts (summary)

**Brief** — reuse PRD 08 `SYNTHESIZE_BRIEF_*`: open on visit reason; allergies/abnormals when verified; narrate gaps from domain flags; ~80–120 words.

**Labs** — new prompt: direct answer to user question; abnormal values first; use only verified lab fact texts; no med/allergy narrative; ~40–80 words; JSON `{"summary":"..."}` only.

**Meds** — new prompt:

- **List mode** (non-dosing): prose list of active meds; mention verified allergies/conditions if present.
- **Dosing mode**: may paraphrase verified chart + research dose facts; do not invent dosing; ~40–80 words.
- Never replace assembly disclaimer / `no_research` / not-on-list lines.

### Draft addenda (cheaper claim selection)

Append to `DRAFT_SYSTEM_PROMPT` when route matches:

**`LABS_DRAFT_ADDENDUM`:** Select lab results relevant to the question; prefer most recent; include abnormal wording when in fact text.

**`MEDS_DRAFT_ADDENDUM`:** For lists include active Rx and allergies; for dosing include research_label locators when present; never claim off-chart drugs as patient Rx.

### Patterns/Libraries

- Reuse `llm.py` `_chat_completion()`, OpenRouter Haiku `anthropic/claude-haiku-4.5`, temp `0.0`.
- LangGraph: `_after_verify` conditional unchanged shape, expanded condition.
- DOM: `textContent` / `createElement` only (PRD 06 H6); collapse via `hidden` or `d-none` + `aria-expanded` on `<button type="button">`.

### Code Organization

```
sidecar/app/nodes/synthesize.py   # synthesize_node(), guard, route labels
sidecar/app/llm.py                # SYNTHESIZE_* prompts, synthesize_turn_raw()
sidecar/app/progress.py           # PROGRESS_SUMMARIZING
interface/ask_copilot/assets/     # collapse UI
```

---

## 4. Implementation Guidance

### Step-by-Step Plan

1. **Rename state** — `brief_summary` → `turn_summary` in `GraphState`, `synthesize_node`, `emit_node`, `build_clinical_payload`, tests. Update PRD 09 `brief_cache.py` if present on branch.
2. **Graph** — Change `_after_verify`:
   ```python
   if state.get("route") in ("brief", "labs", "meds") and state.get("verified_claims"):
       return "synthesize"
   return "emit"
   ```
3. **synthesize_node** — Remove `route != "brief"` early return. Dispatch:
   - `label = ROUTE_SUMMARY_LABELS[route]`
   - `raw = synthesize_turn_raw(route, message, verified_facts, domain_context, transcript)`
   - Parse JSON; guard; set `turn_summary = f"{label}\n\n{summary}"`
4. **llm.py** — Add `ROUTE_SUMMARY_LABELS`, `SYNTHESIZE_LABS_SYSTEM_PROMPT`, `SYNTHESIZE_MEDS_SYSTEM_PROMPT`; refactor brief into `synthesize_turn_raw()`.
5. **Draft addenda** — `LABS_DRAFT_ADDENDUM`, `MEDS_DRAFT_ADDENDUM` in `draft_claims_raw` (mirror `BRIEF_DRAFT_ADDENDUM`).
6. **Progress** — At start of synthesize_node (after gates): `return {"progress_messages": [PROGRESS_SUMMARIZING]}` merged via reducer, or append before LLM call in same node return dict.
7. **emit** — Pass `turn_summary=state.get("turn_summary")`.
8. **UI — `renderAssistantTurn`** — Refactor loop:
   - Render `summary` segments immediately.
   - Collect consecutive `claim` segments into a container:
     - Button: `Show verified sources (N)` with `aria-expanded="false"`.
     - Panel: `hidden` by default; claim rows + Source inside.
   - Render `assembly` segments after collapsed block (always visible).
9. **CSS** — Toggle button spacing; collapsed panel left border or indent; preserve summary bottom border.
10. **Strings** — Add to `index.php` / JS config: `showVerifiedSources`, `hideSources` (with `{count}` placeholder or string concat).
11. **Docs** — Update `docs/ai-decision-guide.md` §6; memory bank.

### Key Functions/Methods

| Function | Location | Purpose |
| --- | --- | --- |
| `_after_verify(state)` | `graph.py` | Route gate for synthesize |
| `synthesize_node(state)` | `synthesize.py` | All-route synthesis |
| `synthesize_turn_raw(route, ...)` | `llm.py` | Route-specific Haiku call |
| `diagnose_guard_summary(text, verified_texts)` | `synthesize.py` | Shared anti-hallucination guard |
| `build_domain_context_for_synthesis(...)` | `synthesize.py` | Empty/unavailable flags (reuse) |
| `build_clinical_payload(..., turn_summary=None)` | `claims.py` | Segment builder |
| `renderAssistantTurn(segments, map)` | `ask_copilot.js` | Summary + collapse + assembly |

### Data Flow

```
route → tools → draft (+ route addendum) → verify (fact text)
  → synthesize (Summarizing… progress → Haiku on verified texts + domain flags)
  → guard → turn_summary | None
  → emit → segments [summary?, claims*, assembly*] + citations
  → stream.py → SSE
  → ask_copilot.js: summary visible; claims collapsed; assembly visible
```

### Complex Logic: guard (unchanged algorithm, all routes)

Reuse PRD 08 `diagnose_guard_summary`:

1. **Hard fail:** novel numeric values not grounded in verified texts; length > 1200.
2. **Date-aware grounding:** day/month/year components from verified ISO or spelled-out dates allowed in any zero-padded form.
3. **Vocabulary:** `novel_tokens` logged only — **not** a hard fail.
4. On fail: log diagnostics in message body (uvicorn ignores `logger.extra`).

Labs/meds are number-heavy — date-aware numeric grounding is critical; do **not** reintroduce closed English allowlist.

### UI collapse pseudo-code

```javascript
// Inside renderAssistantTurn — after summary segments collected:
var claims = []; // claim segments from segs
if (claims.length > 0) {
  var toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'ask-copilot-sources-toggle';
  toggle.setAttribute('aria-expanded', 'false');
  toggle.textContent = 'Show verified sources (' + claims.length + ')';
  var panel = document.createElement('div');
  panel.className = 'ask-copilot-sources-panel';
  panel.hidden = true;
  // append each claim line + attachSourceControl inside panel
  toggle.addEventListener('click', function () {
    var open = panel.hidden;
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    toggle.textContent = open ? 'Hide sources' : 'Show verified sources (' + claims.length + ')';
  });
  bubble.appendChild(toggle);
  bubble.appendChild(panel);
}
// then render assembly segments
```

---

## 5. Edge Cases and Error Handling

| Scenario | Behavior |
| --- | --- |
| `route=labs` or `meds`, verified > 0 | Synthesize with route label + prompt |
| Zero verified claims | Skip synthesize; `EMPTY_CLINICAL` + assembly lines only |
| Synthesize LLM error | Omit summary; collapsed claims-only; no SSE `error` if claims exist |
| Guard fails | Same as LLM error |
| Partial tool failure | Summary may note gaps via domain flags; unavailable copy stays **assembly** |
| Empty domain | Assembly emits `No … on file.`; summary may mention gap; do not duplicate in both if awkward |
| Meds dosing + research hit | Narrative may paraphrase verified research dose; disclaimer stays assembly |
| Meds dosing + `no_research` | Refusal + disclaimer assembly; narrative must not invent dose |
| Off-chart drug | Not-on-list assembly line; narrative must not imply on-chart |
| Uncertain RxNorm + dosing | Uncertain suffix assembly; no research HTTP |
| Unbound pid | Refuse before route; unchanged |
| Single claim | Still show collapse toggle `(1)` — consistent UX |
| Source click while collapsed | Panel must be expandable; focus return to Source after cite dialog |

### Error Messages

No new SSE error codes. Guard/LLM failures are silent fallbacks (claims-only).

---

## 6. Likely Pitfalls to Avoid

| Pitfall | Why it hurts | Prevention |
| --- | --- | --- |
| Hiding disclaimer/refusal/empty inside collapse | Physician misses UC-3 safety framing | Assembly **outside** collapse only |
| Dropping Source buttons | Violates §6 “link every verified claim” | All claims in panel retain Source |
| Synthesizing with zero verified claims | Duplicates or invents empty copy | Hard gate in `_after_verify` + node |
| Streaming summary before verify | Breaks trust model | Synthesize after verify only |
| English vocabulary guard | Rich turns silently lose summary (PRD 08 lesson) | Numeric + length hard fail only |
| LLM-authored assembly | Unallowlisted failure copy | Keep `_assembly_lines` in `claims.py` |
| Breaking Source popup when collapsed | Audit path broken | Jest: expand → click Source → dialog |
| `brief_summary` rename breaks PRD 09 cache | Prefetch replay wrong | Grep + update cache read/write; payload uses `clinical_segments` |
| Stripping claims from transcript join | Loses audit on tab resend | UI collapse only; SSE/text unchanged |
| Narrative dosing without verified fact | Wrong medicine | Guard numerics; dosing only from verified texts |

### Performance

+1 Haiku per eligible turn. No retry on guard fail. Accept ~1–2s incremental latency.

### Security

Synthesize input = verified fact texts + domain flags only — not raw user PHI beyond what's already in-memory post-tools. Research outbound rules unchanged (PRD 05).

---

## 7. Testing Requirements

### Unit Tests (`sidecar/tests/test_synthesize.py`)

- `synthesize_node` runs for `route=labs` and `route=meds` with mocked Haiku.
- Route labels: labs/meds prefixes correct.
- `synthesize_node` skips when `route=labs` and zero verified (unchanged gate).
- Guard fail on labs numeric hallucination omits `turn_summary`.
- Brief regression: still uses chart summary label.

### Assembly Tests (`test_citations_assemble.py`)

- `turn_summary` param prepends `kind:summary` before claims.
- Segment order: summary → claims → assembly.

### Integration (`test_chat_integration.py`)

- Labs happy path: first segment `kind:summary` with `Lab summary —`.
- Meds list path: `Medication summary —`.
- Meds dosing path: summary + research claims + disclaimer assembly segment present.
- Labs route previously asserted **no** summary — **update** those tests.

### Jest (`tests/js/ask-copilot-citations.test.js`)

- Default: claim segments not visible (`panel.hidden === true`).
- Toggle expands; Source button present and opens citation registry entry.
- Summary + assembly visible without expanding.
- Brief turn uses same collapse behavior.

### Manual Testing

| # | Steps | Expected |
| --- | --- | --- |
| M1 | pid 6, auto-brief | Chart summary visible; sources collapsed; expand shows Sources |
| M2 | “What medications do they take?” | Medication summary; med rows collapsed |
| M3 | “What is creatinine?” (pid 6) | Lab summary; lab rows collapsed |
| M4 | pid 6 simvastatin dosing | Summary + disclaimer visible without expand |
| M5 | Guard fail (optional dev mock) | No summary; collapsed claims only |

### Test Data

- Local pid **6** — rich brief, labs, meds (Synthea).
- pid **2** — uncertain RxNorm Lisinopril (no dosing research).

---

## 8. Acceptance Criteria

### Functional

- [ ] `_after_verify` routes `brief`, `labs`, `meds` with verified > 0 through `synthesize`.
- [ ] Each route uses correct summary label prefix in `turn_summary`.
- [ ] Guard fail / LLM error → no summary segment; claims still emit with citations.
- [ ] Assembly lines (disclaimer, empty, unavailable, refusals) always render **outside** collapse.
- [ ] UI defaults to **collapsed** claims; toggle shows/hides all claim rows + Source controls.
- [ ] Source popup works when expanded; focus returns to Source button.
- [ ] `Summarizing…` appears in progress before clinical SSE.
- [ ] Plain-text clinical `text` still joins summary + all claims + assembly (transcript path).

### User-Facing

- Physician reads a conversational paragraph first on brief, labs, and meds turns.
- One click reveals all verified sources for audit.
- UC-3 disclaimer visible without expanding sources.

### Performance

- Incremental synthesize latency ~1–2s p95 acceptable; no guard retry loop.

### Security / Trust

- No clinical SSE before verify completes.
- Every verified claim has a Source control when expanded.
- No new PHI sent to research APIs.

### Invariants (H1–H12)

| ID | Invariant |
| --- | --- |
| H1 | Synthesize only after verify, only when verified > 0 |
| H2 | Summary segment has no `citation_id` |
| H3 | Claim `citation_id` values still pair with citation batch |
| H4 | Assembly never inside collapse |
| H5 | Guard fail → no summary segment |
| H6 | DOM-only rendering (`textContent`) |
| H7 | SSE order unchanged |
| H8 | Route-specific labels exactly as table §3 |
| H9 | Zero verified → no synthesize |
| H10 | Meds disclaimer assembly unchanged |
| H11 | PRD 09 brief cache replay still valid |
| H12 | Collapse is UI-only; SSE schema unchanged |

---

## 9. Dependencies and Considerations

### External Services

- OpenRouter Haiku (existing); +1 call per eligible turn.

### Database / Gateway

- None.

### Configuration

- No new env vars.

### Breaking Changes

- **Product shape:** labs/meds answers change from list-first to narrative-first (intentional).
- **State rename:** `brief_summary` → `turn_summary` — update all sidecar references on branch.
- **Tests:** assertions that labs/meds have no summary must flip.

### PRD 09 Coordination

If `brief_cache.py` stores graph state fields by name, rename alongside emit output. Cached replay serves `clinical_segments` — ensure cached brief segments still include `kind:summary` + claims; UI collapse applies on replay identically.

### Migration

- Deploy sidecar + overlay JS together; no data migration.

---

## 10. Project Notes from Ticket

### Assumptions

- User accepts +1 Haiku latency on all eligible turns.
- Collapsed default is acceptable for interview demo (expand for trust moment).
- No PRD 10 feature flag — ship one shape.

### Out of Scope

- Narrative on refuse/error paths.
- Synthesizing assembly copy.
- Labs/meds prefetch cache.
- Changing verify or citation SSE contract.

---

## 11. Attachments and References

- Planning conversation: conversational all routes + collapsed sources (2026-07-23).
- Pitfalls list: see §6 and session notes in `memory-bank/activeContext.md` after implementation.
- No Jira ticket; no `./attachments/` folder for this PRD.

---

## Checklist (implementation)

- [ ] Sidecar: graph + synthesize + llm prompts + draft addenda + progress
- [ ] Sidecar: rename `turn_summary`; pytest green
- [ ] UI: collapse in `renderAssistantTurn` + CSS + strings
- [ ] Jest: collapse + Source interaction
- [ ] Update `docs/ai-decision-guide.md` §6
- [ ] Update memory bank
- [ ] Manual M1–M5 on local pid 6
