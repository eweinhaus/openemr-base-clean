# PRD 11 — Intent Detection Extensions (Answer More Question Types)

**Roadmap step:** Post–PRD 10 enhancement to UC-2 / UC-3 follow-up turns  
**Goal:** Widen **deterministic** intent detection so common physician phrasings (med switches, implicit dosing, reasonableness asks) trigger the **existing** pipeline correctly — research, verify refusals, prescribing scope, and synthesis — without new graph nodes, a central intent module, or a second LLM call.  
**Non-goal:** New routes (`notes`, `conditions`), dual-drug research HTTP, interaction APIs, relaxing cite-or-silence, research on `brief`/`labs`, transcript DB, feature flags, UI collapse changes, auto-brief synonym expansion (PRD 09).

---

## 1. Problem Statement and Context

### What

Physicians ask follow-ups in natural language. Today two shared regex detectors in `sidecar/app/research/dosing.py` gate much of UC-3 behavior:

- `is_dosing_like` — research HTTP, `no_research` refusal, uncertain-RxNorm assembly
- `is_prescribing_recommendation_like` — chart fallback when draft verify is empty, decision-support disclaimer, prescribing scope line

**Observed failure (pid 6, local/DO):**

> “Would it be reasonable to replace simvastatin 20 mg with atorvastatin 40 mg orally once daily?”

| Step | Current | User sees |
| --- | --- | --- |
| Intent | Both flags **false** | No FDA lookup; no prescribing scope |
| Verify | ~5 chart facts verified | “Show verified sources (5)” (collapsed) |
| Synthesize | Haiku echoes **40** → guard `novel_numeric` | No `kind:summary` (or failure line if PRD 11 Tier 2b deployed) |
| Assembly | No disclaimer/scope for this phrasing | Apparent “no answer” |

Simple asks work (“What meds?”, “Is he on atorvastatin?”) because they stay inside chart lookup + grounded synthesis.

### Background

- **UC-3** (`USERS.md`): medication decision-support — chart + retrieved labels; physician decides.
- **Trust model** (`ARCHITECTURE.md` §4.4): cite-or-silence; dosing only from retrieved sources; no autonomous prescribing.
- **PRD 05 H17**: one module (`dosing.py`) shared by tools + verify — extend regex here only.
- **PRD 10**: verified claims collapsed by default; **visible** copy must come from `kind:summary` or **always-visible** `kind:assembly` lines.

### Related Work

| Doc | Role |
| --- | --- |
| `docs/PRDs/05-research-tools.md` | Research gates, H1–H17 invariants, resolve order |
| `docs/PRDs/08-brief-narrative-synthesis.md` | Synthesis guard (`novel_numeric`) |
| `docs/PRDs/10-conversational-synthesis-all-routes.md` | Collapsed sources UI |
| `docs/copilot-concepts-guide.md` | UC-3 decision tree |
| `memory-bank/activeContext.md` | Prescribing UX + guard fix history |

**Depends on:** PRDs 05–10 (landed). **Partial overlap:** guard-fail visible assembly (`synthesis_failure_line`) — see §3.

### Project Notes (planning session 2026-07-23)

- Builder goal: **more answerable question shapes** with **minimal diff** (~3–4 files + tests).
- Interview demo: statin switch is a credible UC-3 story when label + chart + scope lines appear.
- Do **not** refactor into `sidecar/app/intent/` in this PRD.

---

## 2. Technical Context

### Relevant Files/Modules

| Path | Change |
| --- | --- |
| `sidecar/app/research/dosing.py` | **Tier 1** — extend `_DOSING_LIKE`, `_PRESCRIBING_RECOMMENDATION_LIKE` |
| `sidecar/app/research/resolve.py` | **Tier 3** — switch target capture; reorder resolve candidates |
| `sidecar/app/llm.py` | **Tier 2** — `SYNTHESIZE_MEDS_SYSTEM_PROMPT`, `MEDS_DRAFT_ADDENDUM`; optional `ROUTE_SYSTEM_PROMPT` clause |
| `sidecar/app/nodes/synthesize.py` | **Tier 2b** — already sets `synthesis_failure_line` on guard/parse/LLM fail |
| `sidecar/app/claims.py` | **Tier 2b** — prepends `synthesis_failure_line` to assembly when no summary |
| `sidecar/app/nodes/emit.py` | **Tier 2b** — passes `synthesis_failure_line` (no change if landed) |
| `sidecar/app/state.py` | **Tier 2b** — `synthesis_failure_line` field (no change if landed) |
| `sidecar/tests/test_research_dosing.py` | Tier 1 table tests |
| `sidecar/tests/test_research_resolve.py` | Tier 3 switch target tests |
| `sidecar/tests/test_tools_node.py` | Research HTTP uses target drug term |
| `sidecar/tests/test_verify.py` | H1 refusal + prescribing fallback on switch phrasing |
| `sidecar/tests/test_synthesize.py` | Guard + failure line payload |
| `sidecar/tests/test_citations_assemble.py` | Assembly order: failure line → claims → disclaimer |

**No changes:** `graph.py`, PHP gateway, `tool_proxy`, Ask Co-Pilot JS (assembly already renders outside collapse).

### Similar Implementations

- **PRD 05 H17 dosing regex** — same file, same call sites.
- **`_DOSE_OF_CAPTURE`** in `resolve.py` — pattern for off-chart named drug; mirror for switch target.
- **`fallback_verified_claims_for_prescribing`** — verify injects chart Rx when prescribing-like + zero verified.
- **`format_synthesis_failure_line`** — guard-fail visible assembly (Tier 2b).

### Architecture Notes

- **Single source of truth:** all new intent patterns live in `dosing.py` only (H17).
- **Resolve order matters:** chart substring match currently wins → researches **simvastatin** on switch questions unless target capture runs **first**.
- **Cite-or-silence unchanged:** verify still ships tool fact text; synthesis never becomes a verified claim.
- **Hybrid SSE unchanged:** progress → clinical `{text,segments}` → citation → done.
- **Research:** still one HTTP chain per turn (openFDA → DailyMed); no dual-fetch conflict UX (H12).

### Database/API Context

No schema migrations. Outbound research still uses scrubbed `DrugQuery` only (H3). FDA/DailyMed contracts unchanged from PRD 05.

---

## 3. Design Decisions (Pre-Made)

### Approach

**Three tiers, one PR — implement in order 1 → 3 → 2 prompts.**

| Tier | Scope | Rationale |
| --- | --- | --- |
| **1** | Widen regex in `dosing.py` | Unblocks research gate, H1 `no_research`, prescribing fallback, assembly disclaimer/scope with ~30 lines |
| **3** | Switch target in `resolve.py` | Tier 1 alone researches **wrong drug** (chart match simvastatin); target = proposed agent |
| **2** | Meds LLM prompts + confirm Tier 2b | Reduces `novel_numeric` guard fails; visible copy when guard still fails |

**Tier 2b (guard-fail assembly):** If `synthesis_failure_line` is already in tree, **verify tests only** — do not re-implement.

### Tier 1 — Regex extensions (`dosing.py`)

**Extend `_DOSING_LIKE`** — append to existing alternation (case-insensitive):

```text
replace(?:\s+\S+){0,8}?\s+with|
switch(?:ing)?(?:\s+from)?|
substitut(?:e|ing|ion)|
convert(?:ing)?(?:\s+to)?|
equivalent\s+(?:to|dose)
```

**Optional narrow booster** inside `is_dosing_like` (second check, not in main regex):

```python
if re.search(r"\b(replace|switch|substitut)\b", message, re.I) and re.search(
    r"\b\d+\s*mg\b", message, re.I
):
    return True
```

**Extend `_PRESCRIBING_RECOMMENDATION_LIKE`:**

```text
replace(?:\s+\S+){0,8}?\s+with|
switch(?:ing)?(?:\s+(?:from|to))?|
substitut(?:e|ing|ion)|
(?:is|would)\s+it\s+(?:be\s+)?reasonable\s+(?:to\s+)?(?:replace|switch|substitut|change|add|start|prescrib)
```

**Do not** add bare `\breasonable\b` without a med verb — false positives on non-switch turns.

### Tier 3 — Switch resolve (`resolve.py`)

**Decision: research the TARGET drug** (token after `with` / `to`).

New capture (message only — H16):

```python
_SWITCH_TARGET_CAPTURE = re.compile(
    r"(?:replace|switch(?:ing)?(?:\s+from)?|substitut(?:e|ing))\s+"
    r"(?:\S+\s+){0,8}?"
    r"(?:with|to)\s+"
    r"([A-Za-z][A-Za-z0-9\-/ ]{1,40})",
    re.IGNORECASE,
)
```

Strip strength/form via existing `_display_name_from_fact_text()`.

**New `resolve_drug_query` order:**

1. Not dosing-like → `None`
2. **Switch target capture** → scrub → `OK` (`on_chart` if target also matches active Rx text, else `False`)
3. Chart Rx substring match (longest display name in message) — existing
4. `_DOSE_OF_CAPTURE` — existing
5. Else → `NONE`

### Tier 2 — Prompt tweaks (`llm.py`)

Add to **`SYNTHESIZE_MEDS_SYSTEM_PROMPT`** (switch/replace block):

- Summarize verified **current** Rx from chart facts and verified **research** facts for the **proposed** drug only.
- Do **not** state whether the switch is appropriate.
- Do **not** repeat dose numbers from the user question unless identical substring appears in verified fact text.
- Do not duplicate disclaimer / not-on-list / refusal copy (assembly handles those).

Add to **`MEDS_DRAFT_ADDENDUM`:**

- Switch/replace: include `research_label` locators for **target** drug when tool facts exist; never claim target as `prescriptions` chart Rx.

**Optional:** `ROUTE_SYSTEM_PROMPT` — one clause: `meds = medications, dosing, switches, or replacements`.

### Code Organization

All regex in `dosing.py`. Switch capture + resolve reorder in `resolve.py` only. No new packages.

---

## 4. Implementation Guidance

### Step-by-Step Plan

1. **Tier 1:** Extend regex in `dosing.py`; add table tests in `test_research_dosing.py` (positive switch/replace/reasonable; negative meds list).
2. **Tier 3:** Add `_capture_switch_target_term()`; reorder `resolve_drug_query()`; tests in `test_research_resolve.py` (simvastatin on chart + atorvastatin in message → `query.term == "atorvastatin"`, `on_chart=False`).
3. **Integration:** Extend `test_tools_node.py` — switch message triggers mock fetch with **atorvastatin** term.
4. **Verify/assembly:** Extend `test_verify.py` / `test_citations_assemble.py` — switch message gets disclaimer + scope; research hit skips `no_research`; miss appends `no_research`.
5. **Tier 2 prompts:** Update `llm.py` meds synthesize + draft addenda.
6. **Tier 2b verify:** Run synthesize/assembly tests; ensure failure line visible when guard fails with verified claims.
7. **Manual smoke:** pid 6 switch question; pid 6 meds list (regression); pid 2 uncertain Rx if switch names uncertain drug.

### Key Functions

| Function | File | Action |
| --- | --- | --- |
| `is_dosing_like` | `dosing.py` | Wider regex + optional mg booster |
| `is_prescribing_recommendation_like` | `dosing.py` | Wider regex |
| `_capture_switch_target_term` | `resolve.py` | **New** |
| `resolve_drug_query` | `resolve.py` | Reorder candidates |
| `format_synthesis_failure_line` | `synthesize.py` | Confirm mapped copy for `novel_numeric` |
| `build_clinical_payload` | `claims.py` | Confirm failure line prepended to assembly |

### Data Flow (switch question, pid 6)

```
meds route
  → tools: meds + patient_context
  → is_dosing_like True (Tier 1)
  → resolve: target atorvastatin (Tier 3) → openFDA/DailyMed
  → draft: chart simvastatin locators + research atorvastatin locators
  → verify: verified chart + research facts; no_research only if research miss
  → is_prescribing_recommendation_like True → disclaimer + scope in assembly
  → synthesize: paraphrase without user-only 40 (Tier 2) → turn_summary OR synthesis_failure_line
  → emit: summary → collapsed claims → visible assembly (disclaimer, scope, not-on-list, failure?)
```

### Call-Site Behavior When Flags Widen

| Call site | When dosing-like | When prescribing-like |
| --- | --- | --- |
| `tools.py:_maybe_append_research` | HTTP if resolve OK | — |
| `verify.py` | `no_research` if no verified research dosing | Fallback Rx if **zero** verified after draft |
| `claims.py:_assembly_lines` | Disclaimer if research or no_research | Disclaimer + `PRESCRIBING_RECOMMENDATION_SCOPE` |
| `claims.py:_uncertain_rxnorm_lines` | Resolve BLOCKED → uncertain line | — |

**Both flags true on typical switch question** — expect research + scope + possible not-on-list + summary or failure line.

---

## 5. Edge Cases and Error Handling

| Case | Required behavior |
| --- | --- |
| Switch + research hit on target | Verified research dosing; **no** `no_research` (H1); not-on-list if `on_chart=false` (H5) |
| Switch + research miss | Chart facts + `no_research` + disclaimer + scope; SSE `done` (H8) |
| Switch + target on chart (brand/generic reconcile) | H15 may flip `on_chart=true`; skip not-on-list |
| Switch + uncertain RxNorm on **matched chart row** | H4: no HTTP if resolve picks blocked chart drug; capture target first avoids wrong block |
| Meds list “what is he taking?” | Flags false; no research; no prescribing scope |
| “Would it be reasonable to monitor creatinine?” | Must **not** match prescribing regex (no med verb) |
| Guard rejects summary (`novel_numeric`) | `synthesis_failure_line` visible; claims still collapsed |
| Draft verify produces claims | Prescribing **fallback skipped** (only when `not verified`) |
| `brief` / `labs` routes | Research not invoked (H11) |
| Unbound patient | Existing refuse node |

**Error messages (allowlisted, assembly only):**

- Existing: `DECISION_SUPPORT_DISCLAIMER`, `PRESCRIBING_RECOMMENDATION_SCOPE`, `DOSING_REFUSAL`, not-on-list template
- Existing: `format_synthesis_failure_line("novel_numeric")` → physician-facing “couldn’t answer safely…” copy

---

## 6. Likely Pitfalls to Avoid

| Pitfall | Mitigation |
| --- | --- |
| **Tier 1 without Tier 3** | Researches simvastatin instead of atorvastatin — always ship resolve reorder with dosing regex |
| **False positive `reasonable`** | Require med verb (`replace`, `switch`, …) in prescribing regex |
| **Verify/assembly parity drift** | Only edit `dosing.py`; never duplicate regex in tools/verify/claims |
| **Guard numeric trap** | User-stated **40 mg** fails unless in verified facts — prompt + target research both required |
| **Collapsed UI looks empty** | Rely on visible assembly (disclaimer, scope, failure line); do not require UI change |
| **Prescribing fallback misunderstanding** | Fallback runs only when draft yields **zero** verified — switch with good draft won’t inject extra Rx |
| **H16 violation** | Switch capture from message only — never parse allergy/`lists` for drug names |
| **Relaxing guard** | Do **not** allow user-message numerics in guard — fix prompts/research instead |
| **Dual disclaimer stack** | Switch may show scope + disclaimer + not-on-list + failure — acceptable for MVP |
| **DO not redeployed** | Redeploy sidecar after merge; Tier 2b useless on droplet until rebuilt |
| **Prefetch cache** | Brief-only (PRD 09) — no interaction |
| **Regex `replace` in non-med context** | Low risk in Co-Pilot; clinical phrasing dominates |

---

## 7. Testing Requirements

### Unit Tests

**`test_research_dosing.py`**

| Case | `is_dosing_like` | `is_prescribing_*` |
| --- | --- | --- |
| `Would it be reasonable to replace simvastatin 20 mg with atorvastatin 40 mg…` | True | True |
| `replace X with Y` / `switch to atorvastatin` | True | True |
| `what meds is the patient on?` | False | False |
| `is he taking simvastatin?` | False | False |
| `typical adult dose of simvastatin` | True | False |

**`test_research_resolve.py`**

- `test_switch_resolves_target_not_source` — chart simvastatin + message replace with atorvastatin → term `atorvastatin`, `on_chart=False`.

**`test_tools_node.py`**

- Switch message → research client called with scrubbed **atorvastatin** (mock).

**`test_verify.py`**

- Switch + mock research hit → no `no_research`.
- Switch + no research facts → `no_research` present.
- Switch + empty draft verify → fallback chart Rx injected.

**`test_synthesize.py` / `test_citations_assemble.py`**

- Guard fail with verified claims → `synthesis_failure_line` first in assembly segments.
- Prescribing switch → disclaimer + scope in assembly texts.

### Integration (optional)

`test_chat_integration.py` — meds route mock: switch message SSE includes visible assembly (summary or failure line), not claims-only silence.

### Manual Testing (M1–M4)

| # | Steps | Pass |
| --- | --- | --- |
| M1 | pid 6 — switch simvastatin → atorvastatin 40 mg question | Visible summary **or** failure line; collapsed sources; disclaimer + scope; not-on-list for atorvastatin; research citation if HTTP OK |
| M2 | pid 6 — “What medications is he currently taking?” | Unchanged — summary + sources; no FDA progress |
| M3 | pid 6 — “typical dose of simvastatin” | Label-backed research claim; summary |
| M4 | pid 6 — “Is he currently taking atorvastatin?” | Summary answers from chart; no inappropriate scope line |

### Test Data

- Local pid **6** — simvastatin RxNorm `312961`, rich chart.
- pid **2** — uncertain RxNorm (Lisinopril) for blocked-path regression if message matches uncertain row.

---

## 8. Acceptance Criteria

### Functional

- [ ] Switch/replace/reasonable-to-change-med phrasings set **`is_dosing_like`** and **`is_prescribing_recommendation_like`** per test table.
- [ ] `resolve_drug_query` returns **target** drug for `replace X with Y` when both names appear; does not prefer chart source drug when switch capture matches.
- [ ] Switch question on pid 6 triggers **at most one** research chain for **atorvastatin** (mock or live FDA).
- [ ] Assembly includes **`DECISION_SUPPORT_DISCLAIMER`** and **`PRESCRIBING_RECOMMENDATION_SCOPE`** on switch questions.
- [ ] When target off-chart and research hits, **not-on-list** line present (H5).
- [ ] When synthesis guard fails but verified claims exist, **`synthesis_failure_line`** appears as visible assembly (outside collapsed panel).
- [ ] Meds list and on-chart membership questions **unchanged** (no false-positive research or scope).

### User-Facing

- Physician never sees a **blank** assistant bubble on switch questions when verified claims exist.
- Physician sees either a **short narrative** (chart + label facts, no “yes switch”) **or** explicit “couldn’t answer safely” line plus sources.
- Source controls remain on verified claims only; assembly unlinked.

### Performance / Security

- No extra LLM call; no second research HTTP per turn.
- Outbound research still scrubbed `DrugQuery` only (H3).
- No change to session-proxy or pid fail-closed behavior.

---

## 9. Dependencies and Considerations

| Topic | Notes |
| --- | --- |
| **External services** | openFDA → DailyMed unchanged; optional `OPENFDA_API_KEY` |
| **Database** | None |
| **Configuration** | None new |
| **Breaking changes** | Wider regex may add disclaimer/scope to turns that previously had neither — intentional |
| **Deploy** | Rebuild `copilot-sidecar` on DO after merge |
| **PRD 09 prefetch** | Unaffected (brief-only) |
| **PRD 10 UI** | No JS change required |

---

## 10. Project Notes from Ticket

- **Source:** Conversation / planning session 2026-07-23 — “answer more question types without major code changes.”
- **Assumption:** Single research HTTP per turn is sufficient for interview demo (no simvastatin + atorvastatin dual fetch).
- **Assumption:** Labs/brief intent extensions (abnormal-only, analyte aliases) are **follow-up PR** — out of scope here unless time remains after Tier 1–3 land.
- **Assumption:** `synthesis_failure_line` path may already exist locally — confirm via pytest before re-implementing.

---

## 11. Attachments and References

- **Primary code:** `sidecar/app/research/dosing.py`, `resolve.py`, `llm.py`
- **Concepts:** `docs/copilot-concepts-guide.md` §4 (UC-3 fork)
- **Invariants:** `docs/PRDs/05-research-tools.md` §3 Hard invariants H1–H17
- **No Jira attachments** — requirements captured from chat + codebase audit.

---

## Appendix — Out of Scope (explicit)

- Central `intent/` module or second Haiku intent call
- `is_auto_brief_message` synonym expansion
- Research on `brief` / `labs`
- Dual-drug label fetch / statin equivalence math
- Interaction APIs
- Weakening `diagnose_guard_summary`
- Ask Co-Pilot UI collapse behavior changes
- PHP / gateway changes
