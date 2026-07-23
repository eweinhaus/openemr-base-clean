# PRD 08 — Brief Narrative Synthesis (UC-1 Conversational Summary)

**Roadmap step:** Post–PRD 06 enhancement to UC-1 pre-visit brief  
**Goal:** Replace the list-shaped brief (newline-stacked verified fact lines) with a **professional clinical narrative summary** plus **always-visible cited source lines**, without weakening cite-or-silence verify.  
**Non-goal:** Narrative on `labs`/`meds` routes, relaxing verify, inline span-level citations, feature flags, brief TTL cache, transcript DB, new SSE event types.

---

## 1. Problem Statement and Context

### What

Today, `route=brief` gathers four chart tools, Haiku drafts claim locators, verify replaces model text with **verbatim tool fact strings**, and emit joins them with `\n`. The physician sees a stack of database-shaped lines (`Active problem: …`, `Last visit …`, lab rows) — not a pre-visit handoff.

This PRD adds a **`synthesize` graph node** (brief only, after verify) that produces a short **unverified narrative paragraph** anchored on visit reason, while **verified claims + Source buttons** remain below for audit.

### Background

- **UC-1 job** (`USER.md`): synthesis across EHR fragments — “why here,” what changed, safety signals — in seconds before a visit.
- **Locked trust model** (`ARCHITECTURE.md` §4.4, `docs/ai-decision-guide.md` §6): cite-or-silence on verified path; unverified synthesis must be **hard-labeled** with **no Source links**.
- **Current cost/latency** (`docs/cost-analysis.md`): ~2 Haiku calls/turn (route + draft); tool fan-in dominates uncached brief. A 3rd Haiku call on verified facts only adds ~1–2s — acceptable for demo.

### Related Work

| Doc | Role |
| --- | --- |
| `docs/PRDs/03-langgraph-sidecar.md` | Graph spine; draft → verify → emit |
| `docs/PRDs/04-chart-tools.md` | Brief four-tool fan-in; domain ownership |
| `docs/PRDs/06-citations-hybrid-sse.md` | Segment kinds, Source controls, SSE order |
| `docs/ai-decision-guide.md` | Physician UX; **update §6** with UC-1 narrative exception |
| `USER.md` UC-1 | Product job definition |
| `docs/copilot-concepts-guide.md` | Verify + cite-or-silence explainer |

**Depends on:** PRDs 03–06 (landed). **Does not block:** PRD 07 observability.

### Project Notes (planning session 2026-07-23)

- Voice: **“Patient presents for…”** — professional clinical tone.
- Brief-me opens on **visit reason / last encounter** when present.
- Empty/sparse charts: **narrate gaps** honestly + existing domain empty lines.
- Follow-ups: **`labs`/`meds` stay structured**; shape matches route.
- Demo smoke patient: **local pid 6** (rich brief; not pid 2 for labs).
- No feature flag — narrative is the new default for `route=brief`.

---

## 2. Technical Context

### Relevant Files/Modules

| Path | Change |
| --- | --- |
| `sidecar/app/graph.py` | Insert `synthesize` between `verify` and `emit` |
| `sidecar/app/nodes/synthesize.py` | **New** — brief synthesis node + guard |
| `sidecar/app/llm.py` | `SYNTHESIZE_SYSTEM_PROMPT`, `synthesize_brief_raw()`, brief draft addendum |
| `sidecar/app/nodes/draft.py` | Pass `route` into draft helper (brief prompt variant) |
| `sidecar/app/claims.py` | `build_clinical_payload()` accepts optional `brief_summary` |
| `sidecar/app/nodes/emit.py` | Pass `brief_summary` from state into payload builder |
| `sidecar/app/state.py` | Add `brief_summary: Optional[str]` |
| `interface/ask_copilot/assets/ask_copilot.js` | Render `kind: "summary"` segments |
| `interface/ask_copilot/assets/ask_copilot.css` | Summary block styling |
| `sidecar/tests/test_synthesize.py` | **New** unit tests |
| `sidecar/tests/test_citations_assemble.py` | Summary segment ordering |
| `sidecar/tests/test_chat_integration.py` | Brief SSE shape regression |
| `memory-bank/activeContext.md` | Document shape decision |
| `docs/ai-decision-guide.md` | UC-1 narrative exception under §6 |

### Similar Implementations

- **Draft node** (`sidecar/app/nodes/draft.py`) — Haiku call pattern via `llm.py`.
- **Emit + assemble** (`sidecar/app/claims.py` `build_clinical_payload`) — segment list builder.
- **PRD 06 assembly lines** — unlinked `kind: "assembly"` segments (summary follows same “no Source” rule).

### Architecture Notes

- **Cite-or-silence unchanged:** verify still ships tool fact text for claims; synthesis never becomes a verified claim.
- **Hybrid SSE unchanged:** `progress*` → `clinical` → `citation` → `done`; no clinical tokens before verify+synthesize complete.
- **Browser transcript:** flat `text` from clinical payload (summary + claims + assembly) resend via existing JS join path.
- **Single worker / 2 GB** — no new infra.

### Database/API Context

**No schema migrations.** No gateway PHP changes required (pass-through SSE). Segment schema extends PRD 06:

```json
{
  "text": "Chart summary — verify sources below.\n\nPatient presents for…\nLast visit…",
  "segments": [
    { "kind": "summary", "text": "Chart summary — verify sources below.\n\nPatient presents for…" },
    { "kind": "claim", "text": "Last visit 2024-03-01 — follow-up", "citation_id": "c1" },
    { "kind": "assembly", "text": "No recent notes on file." }
  ]
}
```

---

## 3. Design Decisions (Pre-Made)

### Approach

**Post-verify `synthesize` node + two-layer UI** (labeled narrative, then cited fact lines).

| Decision | Choice | Rationale |
| --- | --- | --- |
| Graph placement | `verify → synthesize → emit` (brief only) | Synthesis input = verified facts only; cite-or-silence intact |
| LLM calls | +1 Haiku on brief (~3 total with route+draft) | Natural prose; ~1–2s incremental latency |
| Segment kind | `kind: "summary"` | Extends PRD 06 H2; distinct from `assembly` |
| Summary label | Fixed prefix: `Chart summary — verify sources below.` | Hard-label per ai-decision-guide §6 citations |
| Voice | “Patient presents for…” | Professional; user-locked |
| Opening | Visit reason / last encounter first | UC-1 “why here” |
| Length | Soft ~80–150 words in prompt | Scannable; no hard truncate/re-prompt |
| Claim selection | Brief draft addendum: ~5–10 high-signal locators | Prioritize visit, conditions, allergies, abnormals, ≤1 note |
| Allergies | Must appear in narrative when verified | Safer clinically |
| Guard | Heuristic token check → omit summary on failure | No LLM retry (latency); fall back to list-only |
| Partial failure | Unavailable lines = allowlisted assembly only | No model-authored failure copy |
| Scope | `brief` route only | Labs/meds unchanged |
| Feature flag | None | Simpler; one brief shape |

### Patterns/Libraries

- Reuse `llm.py` `_chat_completion()` + OpenRouter Haiku (`anthropic/claude-haiku-4.5`), temp `0.0`.
- LangGraph conditional edge: `_after_verify` → `synthesize` if `route=="brief"` and verified claims > 0, else `emit`.
- DOM rendering: `textContent` only (PRD 06 H6).

### Code Organization

```
sidecar/app/nodes/synthesize.py   # synthesize_node(), guard helper
sidecar/app/llm.py                # prompts + synthesize_brief_raw()
sidecar/app/claims.py             # build_clinical_payload(..., brief_summary=...)
```

---

## 4. Implementation Guidance

### Step-by-Step Plan

1. **State** — Add `brief_summary: Optional[str]` to `GraphState`.
2. **LLM prompts** (`llm.py`):
   - `BRIEF_DRAFT_ADDENDUM` appended when `route=="brief"`: prioritize visit reason, 5–10 facts, allergies/abnormals, no chart dump.
   - `SYNTHESIZE_SYSTEM_PROMPT`: JSON `{"summary":"..."}` only; professional clinical voice; open with visit reason; include verified allergies/abnormals; narrate gaps from provided domain flags; no new clinical facts; ~80–150 words.
   - `synthesize_brief_raw(message, verified_facts, domain_context, transcript)` — input is **verified fact texts + domain status**, not full tool JSON.
3. **`synthesize_node`** (`nodes/synthesize.py`):
   - Skip if `route != "brief"`, `error` set, or `len(verified_claims)==0`.
   - Build `verified_facts: list[{text, source_type}]` from verified claims.
   - Build `domain_context` from existing assembly helpers / tool meta: empty-domain flags, `tool_domain_errors` keys — **not** raw fact payloads.
   - Call `synthesize_brief_raw`; parse JSON; run `guard_summary(summary, verified_facts)`.
   - On guard fail or `LlmError`: log warning, leave `brief_summary` unset (emit falls back to list-only).
   - On success: set `brief_summary` to `SUMMARY_LABEL + "\n\n" + summary`.
4. **Graph** (`graph.py`):
   ```python
   AfterVerify = Literal["synthesize", "emit"]
   def _after_verify(state): ...
   graph.add_node("synthesize", synthesize_node)
   graph.add_conditional_edges("verify", _after_verify, {"synthesize": "synthesize", "emit": "emit"})
   graph.add_edge("synthesize", "emit")
   ```
5. **`build_clinical_payload`** — If `brief_summary` truthy, prepend `{kind:"summary", text: brief_summary}` **before** claim segments. Update flat `text` to join summary + claims + assembly.
6. **`emit_node`** — Read `state.get("brief_summary")`, pass to builder.
7. **Frontend** — In `renderAssistantTurn`, if `seg.kind === "summary"`, add class `ask-copilot-segment-summary`; never attach Source. CSS: slightly distinct typography/spacing.
8. **Docs** — Update `ai-decision-guide.md` §6 Answer density: UC-1 brief uses labeled narrative + cited lines (exception to “prefer bullets”). Update `memory-bank/activeContext.md`.

### Key Functions/Methods

| Function | Location | Purpose |
| --- | --- | --- |
| `synthesize_node(state) -> dict` | `nodes/synthesize.py` | Brief narrative generation |
| `guard_summary(text, verified_texts) -> bool` | `nodes/synthesize.py` or `claims.py` | Heuristic anti-hallucination |
| `synthesize_brief_raw(...)` | `llm.py` | Haiku call |
| `build_domain_context_for_synthesis(...)` | `claims.py` or `synthesize.py` | Empty/unavailable flags for gap narration |
| `build_clinical_payload(..., brief_summary=None)` | `claims.py` | Segment ordering |

### Data Flow

```
tools → draft (brief addendum) → verify (fact text)
  → synthesize (Haiku on verified texts + domain flags)
  → guard → brief_summary | None
  → emit → segments [summary?, claims*, assembly*] + citations
  → stream.py → SSE clinical + citation
  → ask_copilot.js render
```

### Complex Logic: `guard_summary`

**Purpose:** Drop summary if it likely introduces facts not in verified texts.

**Algorithm (deterministic, no retry):**

1. Normalize verified texts to lowercase union string `V`.
2. Extract candidate clinical tokens from summary:
   - Decimal numbers (`\d+\.?\d*`) — e.g. lab values, dates as numbers.
   - Words ≥4 chars not in a small stopword list (the, and, patient, presents, for, with, chart, summary, verify, sources, below, file, none, recent, active).
3. For each numeric token in summary, require it appears in `V` (substring match).
4. For each candidate drug/clinical token (optional enhancement): if token appears in summary but not in `V`, fail guard.
5. If summary length > 1200 chars, fail guard (runaway output).

On fail: log `correlation_id`, omit `brief_summary`, emit claims-only (current behavior).

### Draft Prompt Addendum (brief only)

Append to user prompt or system prompt when `route=="brief"`:

> Select approximately 5–10 highest-signal facts for a pre-visit brief. Prioritize: (1) last visit / encounter reason, (2) active conditions, (3) allergies if present, (4) abnormal or recent labs over normals, (5) at most one recent note. Use locators from tool results only.

---

## 5. Edge Cases and Error Handling

| Scenario | Behavior |
| --- | --- |
| `route=labs` or `meds` | Skip synthesize; unchanged output |
| Zero verified claims | Skip synthesize; `EMPTY_CLINICAL` + domain assembly lines |
| Synthesize LLM error | Omit summary; claims-only; no SSE `error` if claims exist |
| Guard fails | Same as LLM error |
| Partial tool failure | Summary may note gaps using domain flags; **unavailable copy stays assembly lines** at bottom (allowlisted) |
| Empty chart domains | Summary narrates gaps; assembly still emits `No … on file.` per domain |
| All tools fail | Existing graph error path; no synthesis |
| Unbound pid | Refuse before route; unchanged |
| Synthesis mentions allergy but no allergy claim verified | Guard should not block (prose OK); **allergy must also appear as verified claim line** if allergy facts exist — draft addendum enforces selection |

### Error Messages

No new physician-facing error codes. Synthesis failure is silent degradation to list-only.

---

## 6. Likely Pitfalls to Avoid

1. **Model-authored clinical values in summary without cited lines below** — never paraphrase labs/meds/allergies as new facts; guard + prompt forbid.
2. **Source buttons on summary** — violates PRD 06 H2/H5 and hard-label rule.
3. **Relaxing cite-or-silence** — do not use model `claim.text` at verify.
4. **LLM-written unavailable/empty strings** — assembly allowlist only.
5. **Streaming summary before verify** — synthesize runs after verify; clinical SSE unchanged.
6. **Sending full tool JSON to synthesize** — token bloat + wider PHI surface; verified texts + flags only.
7. **Synthesis retry loops** — one attempt; fallback only.
8. **Breaking flat `text` / transcript** — summary must be first in joined `text` for resend.
9. **Orphan citation_ids in summary** — summary segment has no `citation_id`.
10. **`innerHTML` for summary** — `textContent` only.
11. **Changing labs/meds output** — gate on `route=="brief"` everywhere.
12. **Draft selecting 20+ claims** — without addendum, UI reverts to chart dump.
13. **Forgetting disclosure/verify metrics** — verify outcome unchanged; synthesis doesn't affect pass heuristic.

---

## 7. Testing Requirements

### Unit Tests (`sidecar/tests/test_synthesize.py`)

- `guard_summary` passes when summary only uses verified numbers/terms.
- `guard_summary` fails when summary introduces novel numeric value.
- `synthesize_node` skips when `route=labs`.
- `synthesize_node` skips when zero verified claims.
- `synthesize_node` sets `brief_summary` on mocked Haiku success.
- `synthesize_node` omits summary on guard fail / `LlmError`.

### Assembly Tests (`test_citations_assemble.py`)

- With `brief_summary`: first segment `kind:summary`, no `citation_id`.
- Claim segments still `c1…cN`; assembly last.
- Flat `text` starts with summary label.

### Integration (`test_chat_integration.py`)

- Mock brief path: clinical SSE includes summary + ≥2 claim segments with Sources.
- Labs route mock: no summary segment (regression).

### Manual Testing

| Step | Action | Expected |
| --- | --- | --- |
| M1 | Local pid **6**, “Brief me.” | Summary opens with visit reason; cited lines below; Sources work |
| M2 | “What’s creatinine?” (labs route) | No summary block; lab values + Sources |
| M3 | Patient with empty notes | Summary mentions gap; `No recent notes on file.` assembly line |
| M4 | Force notes tool error (if feasible) | Partial brief; `Notes unavailable — try again.` at bottom |
| M5 | Follow-up after brief | Transcript includes summary text; coherent reply |

---

## 8. Acceptance Criteria

### Functional

- [ ] `route=brief` with ≥1 verified claim emits `kind:summary` segment with fixed label prefix.
- [ ] Summary uses professional “Patient presents for…” voice and leads with visit reason when encounter fact verified.
- [ ] All verified claims appear as `kind:claim` lines with Source controls (PRD 06 H1).
- [ ] Summary segment never has `citation_id` or Source button.
- [ ] `route=labs` and `route=meds` unchanged (no summary segment).
- [ ] Guard failure degrades to pre-PRD-08 list output without SSE error.
- [ ] Partial tool failure still shows allowlisted unavailable assembly lines.
- [ ] Flat clinical `text` includes summary for transcript resend.

### User-Facing

- Physician reads a short professional paragraph first, then audits facts via Source.
- Allergies visible in narrative when on chart and selected by draft.

### Performance

- Brief turn adds ≤~3s p95 vs pre-change (acceptable on uncached path); no second synthesize retry.

### Security

- No new PHI to research/FDA; synthesize input is already-in-memory verified chart strings.
- XSS: summary rendered via `textContent`.

---

## 9. Dependencies and Considerations

### External Services

- OpenRouter Haiku (existing); +1 call per successful brief turn.

### Configuration

- No new required env vars. Reuse `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `COPILOT_LLM_TIMEOUT_SECONDS`.

### Breaking Changes

- **Brief UX shape changes** — list-only brief replaced by narrative + list. Labs/meds unaffected.
- PRD 06 segment contract extended with `kind: "summary"` (backward compatible: old clients ignore unknown kind or show as plain text).

### Migration

- None. Deploy sidecar + refreshed JS/CSS together.

---

## 10. Hard Invariants

| # | Invariant | Enforcement |
| --- | --- | --- |
| H1 | `kind:summary` never carries `citation_id` | emit + JS |
| H2 | Verify unchanged — claim text = tool fact text | existing tests |
| H3 | Synthesize runs only after verify, only `route=brief`, only if verified > 0 | graph conditional |
| H4 | No clinical SSE before synthesize completes (when run) | stream.py unchanged order |
| H5 | Guard fail → no summary segment | synthesize_node |
| H6 | Unavailable/empty copy = allowlisted assembly only | no LLM failure strings |
| H7 | Citation batch still pairs 1:1 with claim segments | existing H3 |

---

## 11. Attachments and References

- Planning conversation: conversational brief architecture (2026-07-23).
- Code anchors: `sidecar/app/claims.py` `verify_claims()`, `build_clinical_payload()`; `sidecar/app/graph.py`; `interface/ask_copilot/assets/ask_copilot.js` `renderAssistantTurn()`.
- No Jira ticket attachments for this work.

---

## 12. Acceptance Checklist (PR)

- [ ] Graph: verify → synthesize → emit for brief
- [ ] LLM prompts + guard + tests
- [ ] UI summary segment + CSS
- [ ] `ai-decision-guide.md` + `memory-bank/activeContext.md` updated
- [ ] Manual M1–M3 on pid 6
- [ ] `sidecar` pytest green; no PHP changes required
