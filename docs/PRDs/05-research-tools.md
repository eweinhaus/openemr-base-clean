# PRD 05 — Research Tools (openFDA → DailyMed) + UC-3 Dosing Path

**Roadmap step:** `ARCHITECTURE.md` §7 item 5  
**Goal:** Sidecar-only label research (openFDA → DailyMed) so UC-3 dosing can return **one verified label-backed** claim when a source is retrieved; otherwise cited chart + canonical **`no_research`**.  
**Non-goal:** Conflict UX (no dual-fetch, no fixture conflict, **no conflict module**), citation popups (PRD 06), LangSmith (PRD 07), interaction APIs, option lists, ReAct, chart writes, research on `brief`/`labs`, TTL cache.

---

## 1. Problem Statement and Context

### What

1. Add `sidecar/app/research/` — openFDA primary, DailyMed fallback, facts in `{text, table, id, excerpt}` merged into `tool_results`.
2. On route **`meds` only**, when **dosing-like**, resolve drug identity; if clear, query with **scrubbed drug terms only** (never raw user message / PHI).
3. Fix verify: **keep** `source_type: "research"` when locator ∈ fact_map; **never** rewrite research/note → `"chart"`.
4. Fix `no_research`: append **only** if dosing-like **and** zero verified research dosing facts (`table` ∈ `{openfda,dailymed}`).
5. Off-chart named drug → single Rx SPL still researches; assembly **must** say not on active list (code-enforced, not prompt-only).
6. Smoke: pid **6** simvastatin happy path; pid **2** missing-RxNorm no-HTTP refuse.

### Background

PRDs 01–04: tab → gateway → LangGraph → real chart tools → verify → SSE. Research claims are hard-dropped today; dosing keywords always refuse. Interview needs one label-backed dosing hit + honest miss/uncertain paths.

**Product locks:**

| Topic | Lock |
| --- | --- |
| Happy path | One **dosing** answer (not options / “safe to add”) |
| Conflict | **Forbidden** in this PRD — no code, types, SSE, or tests for conflict |
| Off-chart named drug | Allow if single Rx SPL; **mandatory** not-on-list assembly line |
| DailyMed | Fallback after openFDA miss/timeout/5xx/empty dose section only |
| Placement | Sidecar only — **never** `tool_proxy` / PHP |
| Demo | pid **6** + **simvastatin** RxNorm `312961` |
| Uncertain identity | pid **2** Lisinopril empty RxNorm — **block HTTP** |

### Related Work

| Doc / code | Role |
| --- | --- |
| `ARCHITECTURE.md` §4.3 / §7.5 | Research locks |
| `docs/ai-decision-guide.md` §6–11 | UX / PRD 05 menu |
| `docs/PRDs/03-*.md` / `04-*.md` | Claims, meds facts, RxNorm suffix |
| `sidecar/app/claims.py` | Drops research today — must change |
| `sidecar/app/nodes/verify.py` | Unconditional dosing refuse — must change |
| `sidecar/app/nodes/tools.py` | Chart-only gather — add gated research |
| `USERS.md` UC-3 | Chart + research; refuse without source |

**Depends on:** PRD 04 (local done). **Unblocks:** PRD 06 research citations.

---

## 2. Technical Context

| Path | Change |
| --- | --- |
| **New** `sidecar/app/research/` | client, resolve, scrub, extract, dosing detect, constants |
| `sidecar/app/claims.py` | Keep research/`note` source_type; assembly not-on-list + disclaimer |
| `sidecar/app/nodes/verify.py` | Conditional `no_research` only |
| `sidecar/app/nodes/tools.py` | `if route == "meds":` gated research; **never** on brief/labs |
| `sidecar/app/llm.py` | Draft: no invent URLs; off-chart ≠ patient’s Rx |
| `sidecar/app/main.py` `/ready` | **Do not** probe openFDA/DailyMed |
| Compose / DO env | Optional `OPENFDA_API_KEY` |
| PHP / `tool_proxy` | **No research changes** |

**APIs (no DB migrations):**

- openFDA: `https://api.fda.gov/drug/label.json` (`sort=effective_time:desc`, `limit=1`, optional `api_key`)
- DailyMed: `…/spls.json` then `…/spls/{setid}.xml` (dosage LOINC **`34068-7`**)

---

## 3. Design Decisions (Pre-Made)

| Decision | Choice |
| --- | --- |
| Fact shape | `{text,table,id,excerpt}` under `tool: "research_label"` |
| Locators | `table`: `openfda`\|`dailymed`; `id`: `{set_id}:dosage_and_administration` |
| Query order | RxCUI/NDC from chart → else scrubbed generic → brand last; **RxCUI 404 ⇒ always try generic** |
| SPL accept | Exactly one usable **HUMAN PRESCRIPTION DRUG** hit with non-empty `dosage_and_administration`; else **miss** |
| Ambiguity | If filtered candidates imply multiple release forms (IR vs ER) with no form hint in message/chart → **miss** (do not pick newest alone) |
| Truncation | `text` ≤ **1500** chars; never put full SPL in tool_results or logs |
| HTTP | ≤1 openFDA attempt + ≤1 DailyMed attempt; **zero retries**; total deadline **5s**; exceptions → miss (no `state.error`) |
| Progress | `Looking up label information…` only when HTTP will run |
| Disclaimer | Allowlisted once if research facts **or** dosing refuse |
| Conflict | **Do not implement** |

### Hard invariants (must hold — maps prior hazard list)

| # | Invariant | Enforcement |
| --- | --- | --- |
| H1 | Verified research dosing ⇒ **no** `no_research` | `verify_node` checks verified research locators before append |
| H2 | Surviving claims keep original `source_type` (`research`/`note`/`chart`) | `verify_claims` must not force `"chart"` |
| H3 | Outbound URL/body built only from `scrub_query_term` / RxCUI digits — **never** `state["message"]` | `client.py` accepts `DrugQuery` only; unit test |
| H4 | Chart fact with `RxNorm not on file — drug identity uncertain` ⇒ **no HTTP** | `resolve` returns `None` / `blocked` |
| H5 | `meta.on_chart is False` ⇒ assembly always emits not-on-list (hit **or** miss) | `assemble_clinical` reads meta; not prompt-dependent |
| H6 | Off-chart drug never appears as a `prescriptions` chart claim | Draft prompt + verify (no fake prescription locator) |
| H7 | Ambiguous / OTC-only / empty dose section ⇒ miss | `extract` returns no facts |
| H8 | Research failure never sets graph `error` | `tools_node` catches; empty research facts only |
| H9 | No HTTP retries on 429/5xx | Single attempt per source |
| H10 | `/ready` ignores research | Explicit comment + no call |
| H11 | Research only if `route == "meds"` | Early return in tools; test brief never calls research |
| H12 | No conflict feature surface | No `conflict` types, dual simultaneous fetch for compare, or conflict copy |
| H13 | Logs: correlation_id + outcome + set_id only — not message, not full label | Logger policy in client |
| H14 | Smoke patients: happy **pid 6 / simvastatin**; uncertain **pid 2** — not pid 8 for missing RxNorm | Manual + notes |
| H15 | Brand↔generic: after label hit, if returned generic/brand matches any active Rx text ⇒ treat **`on_chart=true`** | Post-hit reconcile in resolve/tools |
| H16 | Drug candidate extracted from **user message** only — never from allergy/`lists` facts | `resolve.py` |
| H17 | Shared dosing detector used by tools + verify (one module) | Expand regex (below) |

### Patterns

- Deterministic resolve/extract — no LLM “pick an SPL.”
- Prefer stdlib `urllib` unless `httpx` already depended.
- PHI scrub: `^[A-Za-z0-9][A-Za-z0-9 \-/]{0,63}$` after trim; reject `@`, commas of names, long digit runs as MRN-like when mixed with person-name patterns; RxCUI = digits only.

### Layout

```
sidecar/app/research/
  __init__.py
  dosing.py       # is_dosing_like — single source of truth
  scrub.py
  resolve.py      # DrugQuery + on_chart + blocked
  client.py       # openFDA → DailyMed, deadlines, no retries
  extract.py      # SPL → facts or miss
  constants.py    # caps, URLs, uncertain suffix string, allowlisted copy
```

---

## 4. Implementation Guidance

### Step-by-Step

1. Add `research/` with mocked HTTP unit tests first (hit, 404 miss, timeout miss, OTC miss, truncate).
2. Implement `is_dosing_like` + `resolve_drug_query` + scrub (table-driven tests).
3. Gate in `tools_node`: **only** `route == "meds"` and dosing-like and not blocked → progress + fetch + append `research_label`; never raise to `error`.
4. Post-hit: reconcile brand/generic → may flip `on_chart` True (H15).
5. Fix `verify_claims` (H1/H2) and `verify_node` conditional refuse (H1).
6. Extend `assemble_clinical` for not-on-list (H5) + disclaimer.
7. Tighten `DRAFT_SYSTEM_PROMPT` (off-chart honesty; no invented research locators/URLs).
8. Confirm `/ready` unchanged re: FDA (H10).
9. Update pytest; delete expectations that research is always dropped.
10. Manual smoke pid 6 / pid 2 / off-chart amoxicillin / non-dosing meds list.

### Dosing detection (`is_dosing_like`)

Use **one** regex (case-insensitive), shared by tools + verify:

```text
\b(
  dose|dosing|dosage|titrat(?:e|ion)|
  how\s+much|how\s+many\s+mg|
  mg\s*/?\s*kg|
  adult\s+dose|typical\s+dose|starting\s+dose|usual\s+dose|
  what\s+(?:is\s+)?(?:the\s+)?dose
)\b
```

If dosing-like but resolve returns None → no HTTP → `no_research` after verify.

### Resolve algorithm (order matters)

1. If not dosing-like → no research.
2. From **message only**, find candidate:
   - Prefer: active Rx **display name** (strip strength/form tokens like `MG`, `Oral`, `Tablet`, `ER`, `HCl`) that appears as a substring in the message.
   - Else: capture after `(?:dose|dosing|dosage)\s+(?:of|for)\s+([A-Za-z][A-Za-z0-9\-/ ]{1,40})`.
   - Else: none → blocked/None.
3. Never take candidate from allergy/`lists` facts (H16).
4. If matched chart fact contains exact suffix  
   ` (RxNorm not on file — drug identity uncertain)` → **blocked** (H4).
5. If chart match with RxNorm digits → `on_chart=true`, prefer rxcui query then generic fallback on miss/404 (H3/H7).
6. If no chart match → `on_chart=false`, scrubbed generic/brand query only.
7. After successful label: if any `openfda.generic_name` / `brand_name` token matches an active Rx text substring → set `on_chart=true` (H15) and **skip** not-on-list line.

### Accept / miss rules for a label payload

**Accept** only if all true:

- `product_type` includes `HUMAN PRESCRIPTION DRUG` (or DailyMed equivalent Rx)
- Non-empty dosage section after truncate
- Not obviously multi-form ambiguous given message/chart (if message/chart say `ER`/`XR`/`SA`, prefer that form; if neither specifies and results are mixed IR/ER family → miss)

**Miss** (no facts, no graph error): openFDA 404/400/429/5xx/timeout; empty dose; OTC-only; ambiguity; DailyMed list/XML/parse failure after openFDA miss.

### Data flow

```
meds → chart meds
    → dosing? → resolve (message + meds facts)
    → blocked/None? → skip HTTP
    → else progress + openFDA → else DailyMed (≤5s, no retries)
    → append research_label {facts, meta:{on_chart, query_term, source, set_id}}
→ draft → verify (keep research source_type; tool text wins)
→ refuse only if dosing && no verified research dosing fact
→ assemble: claims → not-on-list if meta.on_chart==false → disclaimer? → refusal?
→ clinical → done
```

### Code sketch — verify

```python
for claim in draft.claims:
    if claim.source_type not in ("chart", "note", "research"):
        continue
    fact = fact_map.get((claim.locator.table, claim.locator.id))
    if not fact:
        continue
    verified.append(Claim(
        text=fact["text"],
        source_type=claim.source_type,  # H2: never force "chart"
        locator=claim.locator,
        excerpt=fact.get("excerpt") or claim.excerpt,
    ))
# H1: append DOSING_REFUSAL only if dosing_like and no verified
# claim with source_type=="research" and table in {"openfda","dailymed"}
```

### Allowlisted physician copy

- Refuse: `No retrieved label source for dosing — I won't guess.`
- Off-chart: `{Drug} is not on this patient's active medication list.`
- Disclaimer: `Decision support only — physician decides; Co-Pilot does not prescribe or write the chart.`

---

## 5. Edge Cases and Error Handling

| Case | Required behavior |
| --- | --- |
| Dosing + research hit | Label fact in clinical; **no** `no_research` (H1) |
| Dosing + any research HTTP/parse miss | Chart + `no_research`; SSE **`done`**; `error` unset (H8) |
| Matched uncertain RxNorm | **No HTTP**; chart suffix + `no_research` (H4) |
| Off-chart + hit/miss | Not-on-list line always (H5); never as patient’s Rx (H6) |
| Brand ask / generic on chart (Zocor↔simvastatin) | Post-hit reconcile → on_chart (H15) |
| Allergy drug name in chart, not in dosing ask | Must not become query (H16) |
| Non-dosing “what meds?” | No research progress; no refuse |
| `brief` / `labs` | Research function not invoked (H11) |
| Ambiguous IR/ER / OTC-only | Miss → refuse if dosing |
| Invented research locator | Dropped |
| 429 | Miss; **no retry** (H9) |
| Unbound | Existing refuse node; no tools/research |
| Conflict scenarios | **Not handled / not coded** (H12) |

**Validation / logging:** scrub before every HTTP; log `correlation_id`, `outcome`, `source`, `set_id` only (H13).

---

## 6. Likely Pitfalls to Avoid

Implementers must treat §3 **Hard invariants** as blockers. Especially:

- Leaving keyword-unconditional `no_research` after a hit (H1).
- Rewriting `source_type` to `chart` (H2).
- Passing `message` into URL builders (H3).
- Relying on the LLM alone for not-on-list honesty (H5 — assembly required).
- Adding “helpful” conflict comparison code (H12).
- Probing FDA from `/ready` (H10).
- Using pid 2 for happy-path dosing or pid 8 for missing-RxNorm (H14).

---

## 7. Testing Requirements

### Unit (required)

| Test | Guards |
| --- | --- |
| scrub rejects raw-message-like / empty / oversized; accepts `simvastatin` | H3 |
| resolve: uncertain suffix → blocked, **mock client not called** | H4 |
| resolve: candidate not taken from allergy facts | H16 |
| resolve/post-hit: brand label reconciles to chart generic → `on_chart=true` | H15 |
| client: 404/timeout/429 → miss; **assert single HTTP call** (no retry) | H8/H9 |
| client: never receives a `message=` kwarg / full prompt | H3 |
| extract: OTC-only → no facts; dose truncated ≤1500 | H7 |
| `verify_claims` keeps `source_type=research` | H2 |
| `verify_node`: hit ⇒ no refuse; miss ⇒ refuse; non-dosing ⇒ no refuse | H1 |
| assemble: `on_chart=false` ⇒ not-on-list even with zero research facts if meta present | H5 |
| `is_dosing_like` true for “typical adult dose”, “how many mg”, “starting dose” | H17 |

### Integration

- Meds + mock research hit → clinical has label text, **assert `no_research` absent**.
- Meds + mock miss → refuse present; response not SSE error.
- `route=brief` tools node → research client call count **0**.
- Off-chart hit → not-on-list in assembled clinical.

### Manual

| Bind | Ask | Expect |
| --- | --- | --- |
| pid **6** | typical adult dose for **simvastatin** | label-backed dose; no `no_research` |
| pid **2** | dosing for **lisinopril** | uncertain chart + refuse; no FDA required |
| pid **6** | typical adult dose for **amoxicillin** | not-on-list + label or refuse; amoxicillin ≠ patient’s Rx |
| pid **6** | what meds is the patient on? | chart only; no “Looking up label” |

---

## 8. Acceptance Criteria

- [ ] H1–H17 all true in code + covered by tests where listed in §7.
- [ ] `meds` + dosing + clear identity → openFDA (DailyMed on miss) → research facts in `tool_results`.
- [ ] Verified research uses tool fact prose; `source_type` stays `research`.
- [ ] Research miss/timeout ≠ graph/SSE `error`.
- [ ] Missing RxNorm never triggers outbound HTTP.
- [ ] Off-chart path always informs via allowlisted assembly line.
- [ ] **No** conflict feature shipped.
- [ ] `/ready` does not call research APIs.
- [ ] PHP/`tool_proxy` unchanged for research.
- [ ] Obsolete “research always dropped” tests removed/replaced.
- [ ] Manual smoke pid 6 simvastatin + pid 2 lisinopril documented.

**Performance:** research ≤5s wall; truncated facts before draft.  
**Security:** scrubbed queries only; no chart writes; no PHI in research HTTP.

---

## 9. Dependencies and Considerations

| Item | Notes |
| --- | --- |
| `OPENFDA_API_KEY` | Optional; recommended on DO |
| Egress | Sidecar must reach api.fda.gov + dailymed.nlm.nih.gov |
| Breaking | Dosing may succeed when research hits (intended); tests that assume always-refuse/drop must change |
| Deploy | Recreate `copilot-sidecar`; batch with PRD 04 overlay on DO if needed |

---

## 10. Project Notes

- Mid-level builder: keep module small; deterministic resolve > LLM tool-calling.
- Talk track: “Fallback-only labels; conflict UX deferred; cite-or-silence still holds.”
- Store URL/title in `excerpt`/`meta` now for PRD 06.
- Re-check pid 6 still has simvastatin `312961` after any Synthea re-import.
- **Do not** implement conflict “just in case.”

### Decisions locked

1. Skip conflict entirely for MVP/demo.  
2. Off-chart named drug allowed + mandatory not-on-list assembly.  
3. Happy path = pid 6 simvastatin dosing.  
4. Sidecar-only; conditional `no_research`; preserve research `source_type`.  
5. DailyMed fallback; ≤5s; no retries; meds-route only; H1–H17 invariants.

---

## 11. References

- `ARCHITECTURE.md` §4.3 / §7 item 5  
- `docs/ai-decision-guide.md` §11  
- https://open.fda.gov/apis/authentication/ · https://open.fda.gov/apis/drug/label/  
- https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm  

No `./attachments/` folder.
