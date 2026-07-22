# PRD 04 — Chart Tools + PatientContextService (Step 4)

**Roadmap step:** `ARCHITECTURE.md` §7 item 4  
**Goal:** Replace stub chart fixtures with **real PHP chart services** behind `tool_proxy`: `PatientContextService` snapshot + lab/med/note tools; keep **pid/user fail-closed**; sidecar gathers **rich brief** (all four tools in parallel) with **per-domain empty vs error** handling.  
**Non-goal:** openFDA/DailyMed (PRD 05), citation UI/`citation` SSE (PRD 06), LangSmith (PRD 07), TTL/snapshot **cache implementation** (document as deferred debt), FHIR-primary path, SMART, chart writes, ReAct, durable checkpointer, seeding clinical notes (optional demo polish — see deferred).

---

## 1. Problem Statement and Context

### What

Make Co-Pilot answers come from the **bound patient’s chart**, not hardcoded fixtures:

1. Implement PHP chart readers under `src/ClinicalCopilot/Chart/` that return the existing fact shape `{text, table, id, excerpt}` with **real table+pk** locators (optional `fhir_uuid` when present).
2. Wire `ToolProxyService` to dispatch real tools: `patient_context`, `labs`, `meds`, `notes` — **remove** `*_stub` tools. (`notes` is **new**; stubs never had a notes tool.)
3. Update sidecar `ROUTE_TOOLS` so **`brief` calls all four in parallel**; `labs` → `labs`; `meds` → `meds`. Raise parallel cap from 3 → **4**.
4. Keep secret + correlation bind **pid + user_id** fail-closed unchanged.
5. Sidecar: **empty `facts: []` ≠ tool failure**; per-tool gateway errors → **partial verified answer** + domain unavailable line (decision guide §6) — do **not** kill the whole turn when any domain still returned facts.
6. Smoke on **rich Synthea** patients (local + DO): brief/labs/meds clinical text must match that patient’s chart, not fixture diabetes/creatinine/metformin ids. **Do not use Susan Underwood (local pid 2) as the labs/brief smoke patient** — she has no lab rows.

### Background

PRDs 02–03 proved the trust spine: session-proxy, tool_proxy fail-closed, LangGraph route→tools→draft→verify→hybrid SSE. Chart **data** was intentionally stubbed so verify could pass locators. Interview demo needs UC-1/UC-2 grounded in live Synthea rows; UC-3 chart side (meds/allergies) without research yet.

**Builder choice (2026-07-21):** brief gathers **all four tools now** (rich first answer). A TTL/snapshot cache is **planned later** so that rich bundle can return instantly — do **not** thin brief to one tool “for vertical slice.” Cache code is **out of this PRD**; only prepare the gather shape.

**Research (local MariaDB, 2026-07-21):** Standard Synthea CCDA import fills `form_encounter`, `lists`, `prescriptions`, `procedure_*` — **not** `form_clinical_notes` (0 rows across local pids). `form_soap` exists only on sparse example patients (pid 1–3), not Synthea. Encounter “why here” text lives in `form_encounter.reason`. Rich smoke candidates: local **pid 6** (labs + RxNorm meds) and **pid 8** (allergies + missing-RxNorm meds).

### Related Work

| Doc | Role |
| --- | --- |
| `ARCHITECTURE.md` §4.2, §7 item 4 | Services-first chart; PatientContextService + drill-downs |
| `AUDIT.md` §4 / Performance | Snapshot synthesis; labs join path; selective notes |
| `docs/PRDs/02-session-proxy-gateway.md` | tool_proxy secret + bind — **dependency** |
| `docs/PRDs/03-langgraph-sidecar.md` | Fact/claim schema, verify, tools node — **dependency** |
| `docs/ai-decision-guide.md` | §5 rich gather; §6 empty/partial UX; §11 PRD 04 menu |
| `memory-bank/activeContext.md` | Locked PRD 04 decisions |

**Depends on:** PRDs 01–03 working locally (LLM Send green). DO draft-parse flakiness does **not** block this PRD (decision guide §5).  
**Unblocks:** PRD 05 research (uses same meds chart facts); richer UC-1 demos; future cache over this tool bundle.

---

## 2. Technical Context

### Relevant Files/Modules

| Path | Why |
| --- | --- |
| `src/ClinicalCopilot/Gateway/ToolProxyService.php` | Replace stub payloads with service dispatch |
| `interface/ask_copilot/tool_proxy.php` | Wire Chart services into ToolProxyService ctor |
| `sidecar/app/nodes/tools.py` | Rename tools; brief → 4 tools; `max_workers` ≥ 4; **per-tool** error handling |
| `sidecar/app/claims.py` (`assemble_clinical`) | Append empty / unavailable domain lines (no fake locators) |
| `sidecar/tests/*` | Stub tool names → real names; partial-failure tests |
| `tests/Tests/Isolated/ClinicalCopilot/Gateway/ToolProxyServiceTest.php` | Update expected tools / inject fake chart layer |
| `src/ClinicalCopilot/Schedule/*` | **Pattern** for isolatable Co-Pilot services (injectable loaders; avoid BaseService bootstrap in isolated tests) |
| `src/Services/EncounterService.php` | Last visit / `form_encounter.reason` |
| `src/Services/ConditionService.php` / `PatientIssuesService.php` | Problems (`lists.type = medical_problem`) |
| `src/Services/AllergyIntoleranceService.php` | Allergies (`lists.type = allergy`) |
| `src/Services/PrescriptionService.php` | Meds (`prescriptions`) |
| `src/Services/ProcedureService.php` | Labs (`procedure_order` → `report` → `result`) |
| `src/Services/ClinicalNotesService.php` | `form_clinical_notes` (canonical; expect empty on Synthea) |

### Similar Implementations

- **Fail-closed gateway service:** `ToolProxyService` (keep auth path; swap data path).
- **Isolatable Co-Pilot service:** `ProviderDayScheduleService` — typed API, `QueryUtils`, injectable loader for PHPUnit; does **not** extend `BaseService` because BaseService DB bootstrap breaks isolated tests.
- **Fact → verify:** `sidecar/app/claims.py` `build_tool_fact_map` — already keys on `(table, id)`.

### Architecture Notes

- Sidecar **never** talks to MariaDB; chart reads only via gateway → PHP.
- Ignore client/model-supplied pid; tool body pid must match bind.
- Prefer **structured** facts over notes when both exist (draft prompt already prefers tool JSON; snapshot should not invent narrative).
- Missing RxNorm → state uncertainty in fact `text`; **never invent** codes.
- Read-only; no chart mutations.
- Twig autoescape off is irrelevant here (JSON API).

### Database/API Context

**No schema migrations.**

**Tool proxy request (unchanged envelope):**

```
POST /interface/ask_copilot/tool_proxy.php
Header: X-Copilot-Internal-Secret, X-Correlation-Id
Body: {
  "tool": "patient_context" | "labs" | "meds" | "notes",
  "args": { },
  "pid": <int>,
  "user_id": <int>,
  "correlation_id": "<id>"
}
```

**Success response:**

```json
{
  "ok": true,
  "tool": "labs",
  "data": {
    "facts": [
      {
        "text": "Serum creatinine 1.1 mg/dL (2026-06-01)",
        "table": "procedure_result",
        "id": "501",
        "excerpt": "CMP — reference range on file",
        "fhir_uuid": "optional-when-row-has-uuid"
      }
    ]
  }
}
```

- `id` = string or int primary key for that `table` (stringify consistently in PHP as string in JSON is fine).
- Empty chart domains → `ok: true` with `facts: []` (not an error; **not** a fake locator).
- Unknown tool → `ok: false`, `error: "not_implemented"` (existing).
- Auth/bind failures unchanged (`unauthorized`, `pid_mismatch`, `user_mismatch`, `bind_missing`, …).
- Chart service throw → tool_proxy `ok: false` + generic error (no SQL/exception text). Sidecar treats that as **one domain unavailable**, not automatic whole-turn failure (see §3).

**Claim / verify contract:** unchanged from PRD 03 for fact-backed claims. Optional `fhir_uuid` on facts is ignored by verify until PRD 06 citations need it. Empty/unavailable domain lines are **assembly copy**, not verified claims (no citation links).

---

## 3. Design Decisions (Pre-Made)

### Product locks (research + decision guide — 2026-07-21)

| Decision | Choice | Why |
| --- | --- | --- |
| Auth / bind | **Fail-closed** unchanged (secret + pid + user_id) | Spine; never weaken |
| Empty `facts: []` | Success; domain is empty | Not an exception; clinical signal |
| One tool gateway/5xx error | **Partial win:** keep successful tools’ facts; mark failed domain `unavailable` | Decision guide §6 — do not fail whole turn when other domains verified |
| All chart tools fail / auth fail | Whole turn SSE `error` (existing) | Nothing to ground |
| Empty-domain copy | Sidecar `assemble_clinical` (or thin helper) appends allowlisted one-liners — **no fake table/id** | “No allergies on file.” must not look cited |
| Unavailable-domain copy | Same path: e.g. `Notes unavailable — try again.` | Absence of section ≠ “none on file” for safety domains (allergies/meds) |
| Domain ownership | See table below — **no duplicate** allergy/med/lab/note dumps across tools | Avoid locator floods; brief merges all `tool_results` |
| Why-here / last visit | `form_encounter`: most recent by date → date + `reason` (table `form_encounter`, pk = encounter id) | Synthea populates this; calendar title deferred |
| Demographics in facts | **Omit** (UI patient header already shows identity) | Less PHI in tool JSON / draft context |
| Notes source | Canonical table **`form_clinical_notes`** via `ClinicalNotesService` / QueryUtils | Correct OpenEMR API; Synthea usually empty → honest empty domain |
| Notes fallbacks | **Do not** scrape `form_soap`, `documents`, or invent note text from encounter reason | Encounter reason belongs in `patient_context`; soap only on non-Synthea demos |
| Active meds filter | `prescriptions.active = '1'` **and** (`end_date` IS NULL or zero-date) | Matches PrescriptionService “active” status; many Synthea rows are `active=1` with past `end_date` (= completed) |
| `lists` discriminators | Problems: `type='medical_problem'`; allergies: `type='allergy'`; active ≈ open-ended enddate / activity | Wrong type ⇒ silent empty |
| Meds tool contents | Active prescriptions **+** allergies (canonical home for both) | UC-3 chart side |
| `patient_context` contents | Last encounter framing + **active conditions only** (no allergy/med/lab/note dumps) | Dedicated tools own those domains on brief |
| Labs abnormals | Surface chart `abnormal` / range fields only when present; **no** invented reference-range math | Synthea often leaves `abnormal` blank — UC-2 demo = specific value Q&A (e.g. creatinine) |
| Smoke patients | Local **pid 6** (labs/meds) and **pid 8** (allergies + missing RxNorm); not pid 2 for labs | Measured against local DB |
| DO sequencing | Implement locally; batch DO redeploy / draft-parse triage (decision guide §5) | Do not block PRD 04 on DO green |
| Draft payload risk | Richer tool JSON may worsen `draft_parse_failed` — monitor; if needed, truncate oldest labs before draft (debt) | Caps already limit size |
| BaseService | Chart facades follow **Schedule** pattern (injectable loaders); **do not** force `BaseService` if it breaks isolated tests | Overrides older Memory Bank wording |

### Domain ownership (brief merges all four)

| Tool | Owns | Locator tables |
| --- | --- | --- |
| `patient_context` | Last visit date + reason; active conditions | `form_encounter`, `lists` (problems only) |
| `labs` | Recent lab results (cap 15) | `procedure_result` (+ result pk) |
| `meds` | Active Rx + allergies | `prescriptions`, `lists` (allergy) |
| `notes` | Recent clinical notes (cap 3, excerpt ≤500) | `form_clinical_notes` |

Brief answer density (physician-facing) still covers allergies/meds/labs/notes because those tools run on `brief` — they just are **not** duplicated inside `patient_context`.

### Empty / unavailable allowlist (assembly)

Inject **after** verify, not as fake facts. Routes care about:

| Domain (tool) | Empty | Unavailable |
| --- | --- | --- |
| Conditions / visit (`patient_context`) | `No active conditions on file.` when problems empty; still show visit fact if present | `Chart summary unavailable — try again.` |
| Labs | `No recent labs on file.` | `Labs unavailable — try again.` |
| Meds (Rx) | `No active medications on file.` | `Medications unavailable — try again.` |
| Allergies (same `meds` tool) | If meds tool succeeded and allergy facts empty: `No allergies on file.` | Covered by meds unavailable (do not imply “none on file”) |
| Notes | `No recent notes on file.` | `Notes unavailable — try again.` |

Implementation note: meds tool returns one fact list (Rx + allergies). Sidecar/PHP may tag facts with a soft `domain` hint in `excerpt` **or** split counts in tool metadata — keep MVP simple: PHP can return optional `data.meta` like `{ "allergy_count": 0, "med_count": 2 }` without breaking verify (verify ignores unknown keys). If meta is too much, draft prompt + assembly can treat “meds tool empty facts” as both no meds and no allergies one-liners.

**Prefer:** optional `data.meta` on meds success: `{ "active_med_count": N, "allergy_count": M }` so empty copy is accurate when only one side is empty.

### Approach (engineering)

| Decision | Choice |
| --- | --- |
| Scope | Real chart tools + wire-up + sidecar partial/empty assembly; **no** research, citations UI, LangSmith, **no cache impl** |
| Tool names | `patient_context`, `labs`, `meds`, `notes` — delete stubs |
| Brief route | **All four in parallel** (rich UC-1); prep for future TTL cache of this bundle |
| Labs / meds routes | Single tool each (`labs` / `meds`) |
| Caps | Labs: **15** most recent results; Notes: **3** most recent, excerpt **≤500** chars; Meds: **20** active Rx + all allergies (usually small) |
| Parallelism | Sidecar `max_workers` = `min(len(tools), 4)` (was 3) |
| Partial tool failure | Per-future try/except in `tools_node`; merge successes; track failures by tool name |
| PHP layout | `src/ClinicalCopilot/Chart/` — services + fact DTO/builder; Schedule isolatable pattern |
| Pid | Always the bind-checked pid from ToolProxyService — never trust `args.pid` |
| Cache | **Deferred debt** only: brief’s four-tool bundle is the future cache key/value |

### Rationale

- Spine step 4 must be **real** chart data (decision guide — do not fake).
- Rich brief matches UC-1 and future cache shape.
- Domain split avoids duplicate locators while Haiku still sees the full bundle on brief.
- Empty vs throw distinction preserves trust: empty is clinical signal; throw must not look like “none on file” for allergies/meds.
- Notes stay on `form_clinical_notes` even when Synthea is empty — honest empty > fake SOAP scraping.

### Patterns/Libraries

PHP 8.2+: `declare(strict_types=1)`, readonly DTOs where useful, `QueryUtils`, existing OpenEMR services. Python: tool names + tools_node partial merge + assemble empty/unavailable lines. No new Compose env vars required.

### Code Organization

```
src/ClinicalCopilot/Chart/
  ChartFact.php              # readonly value: text, table, id, excerpt, ?fhirUuid
  ChartFactSet.php           # list wrapper → toArray() for tool_proxy (+ optional meta)
  PatientContextService.php  # last encounter + active conditions
  LabsChartService.php       # recent procedure_result facts
  MedsChartService.php       # active prescriptions + allergies (+ meta counts)
  NotesChartService.php      # form_clinical_notes selective recent
  ChartToolDispatcher.php    # tool name → service (injected into ToolProxyService)
```

`ToolProxyService` constructor gains a `ChartToolDispatcher` (or callable map). `tool_proxy.php` constructs real dispatcher; tests inject fakes.

Sidecar:

```
ROUTE_TOOLS = {
  "brief": ["patient_context", "labs", "meds", "notes"],
  "labs": ["labs"],
  "meds": ["meds"],
}
```

---

## 4. Implementation Guidance

### Step-by-Step Plan

1. **Confirm contracts** — Read `ToolProxyService`, `claims.build_tool_fact_map` / `assemble_clinical`, Schedule service test pattern.
2. **Add Chart DTOs** — `ChartFact` / `ChartFactSet` with `toArray()` matching JSON above (+ optional `meta`).
3. **Implement four services** (injectable row loaders for isolated tests):
   - `PatientContextService::snapshot(int $pid): ChartFactSet`
   - `LabsChartService::recent(int $pid, int $limit = 15): ChartFactSet`
   - `MedsChartService::activeWithAllergies(int $pid, int $medLimit = 20): ChartFactSet` (+ meta counts)
   - `NotesChartService::recent(int $pid, int $limit = 3, int $excerptMax = 500): ChartFactSet` — `form_clinical_notes` only
4. **ChartToolDispatcher** — map tool string → service method; unknown → not_implemented path in ToolProxy.
5. **Refactor ToolProxyService** — after auth/bind success, call dispatcher with **bound pid**. Remove `stubToolData` / `STUB_TOOLS`. Chart throw → generic `ok: false` (log server-side).
6. **Wire `tool_proxy.php`** — construct real Chart services + dispatcher.
7. **Update sidecar tools_node** — rename tools; brief = four names; parallel 4; **per-tool** catch: successes → `tool_results`, failures → `tool_domain_errors` (or equivalent state); only set graph `error` if **zero** successful tool results (or auth-class errors that should still fail closed — e.g. `GatewayAuthError` / `GatewayForbiddenError` on any call).
8. **Update assemble_clinical** — accept domain empty/unavailable signals; append allowlisted lines (no locators).
9. **Update PHPUnit + pytest** — fake dispatcher; empty facts; one-tool failure partial merge; Chart service unit tests with fake loaders.
10. **Manual smoke** — local pid **6** brief + creatinine labs; pid **8** meds/allergies + missing RxNorm wording; dosing still refused. Then DO when batching deploy.
11. **Memory Bank** — clear stub-chart debt; note cache + optional note-seed deferred; fix BaseService wording.

### Key Functions/Methods

| Piece | Responsibility |
| --- | --- |
| `ChartFact` / `ChartFactSet` | Stable serialization for tool_proxy + verify |
| `PatientContextService` | Most recent `form_encounter` date/reason; active `medical_problem` |
| `LabsChartService` | Join chain → result rows newest-first; cap 15 |
| `MedsChartService` | Active Rx filter + allergies; meta counts; uncertain RxNorm wording |
| `NotesChartService` | `form_clinical_notes`; truncate excerpt; empty OK on Synthea |
| `ChartToolDispatcher` | Name → ChartFactSet |
| `ToolProxyService::handle` | Unchanged auth; real data path |
| `tools_node` | ROUTE_TOOLS + parallel 4 + per-tool partial merge |
| `assemble_clinical` | Verified claims + refusals + empty/unavailable lines |

### Data Flow

```
Physician Send (bound pid)
  → stream.php → sidecar /v1/chat
  → route=brief
  → tools_node: parallel tool_proxy ×4
       patient_context | labs | meds | notes
  → each: secret + correlation + pid/user echo
  → ToolProxyService bind check → Chart*Service(pid) → facts
       (empty domain → ok + facts:[]; throw → ok:false for that call)
  → tools_node merges successes; records per-tool failures
  → draft claims from successful tool_results → verify
  → assemble_clinical(+ empty/unavailable lines) → clinical SSE
```

### Complex Logic Breakdown

**Labs join:** Prefer existing `ProcedureService` search APIs scoped by pid. If shapes are awkward, use a thin `QueryUtils` query joining `procedure_order` → `procedure_report` → `procedure_result` filtered by order pid, `ORDER BY` date DESC, `LIMIT 15`. Every fact `table` = `procedure_result` + result pk. Put chart text in `text` (result is varchar — don’t force float). Include `abnormal` / range in `text` or `excerpt` only when columns are non-empty.

**Active meds:** `active = '1' AND (end_date IS NULL OR end_date = '0000-00-00')`. Cap 20 newest by start/date if needed. Allergies: `lists.type = 'allergy'` with active/open-ended filter consistent with `AllergyIntoleranceService`.

**Missing RxNorm:** If `rxnorm_drugcode` empty/null, fact text like `Lisinopril 10 mg daily (RxNorm not on file — drug identity uncertain)` — still cite `prescriptions` pk.

**Notes:** Query `form_clinical_notes` for pid, newest first, limit 3. Excerpt = first ≤500 chars of description/body (strip tags if HTML). Locator `table` = `form_clinical_notes`, `id` = note pk. Prefer omit empty bodies. **Expect Synthea → `facts: []`** → assembly `No recent notes on file.`

**Why-here:** One fact from most recent encounter, e.g. `Last visit 2026-01-18 — Encounter for check up (procedure)` with `table=form_encounter`. If no encounters: no visit fact; conditions may still exist.

**Deduping:** Do not put prescriptions/labs/notes/allergies into `patient_context`. Verify already dedupes by locator if duplicates slip through.

**Auth vs domain errors in tools_node:**  
- `GatewayAuthError` / `GatewayForbiddenError` → fail whole turn (bind/secret broken).  
- `GatewayServerError` / timeout / tool error on **one** tool → mark unavailable, continue.  
- If every requested tool failed → graph `error` (nothing to draft).

### Code Examples

**Dispatcher sketch:**

```php
final class ChartToolDispatcher
{
    public function __construct(
        private readonly PatientContextService $context,
        private readonly LabsChartService $labs,
        private readonly MedsChartService $meds,
        private readonly NotesChartService $notes,
    ) {
    }

    public function dispatch(string $tool, int $pid): ChartFactSet
    {
        return match ($tool) {
            'patient_context' => $this->context->snapshot($pid),
            'labs' => $this->labs->recent($pid),
            'meds' => $this->meds->activeWithAllergies($pid),
            'notes' => $this->notes->recent($pid),
            default => throw new \InvalidArgumentException('Unknown chart tool'),
        };
    }
}
```

**Sidecar route map:**

```python
ROUTE_TOOLS = {
    "brief": ["patient_context", "labs", "meds", "notes"],
    "labs": ["labs"],
    "meds": ["meds"],
}
# max_workers=min(len(tool_names), 4)
# per-future: success → results; domain error → record; auth → abort turn
```

---

## 5. Edge Cases and Error Handling

### Edge Cases

| Case | Behavior |
| --- | --- |
| Patient with no labs/meds/notes/problems | `ok: true`, `facts: []` for that tool; assembly empty one-liner; **not** SSE `error` |
| Sparse / demographics-only pid | Honest thin answer; never invent |
| Synthea notes empty | Expected; `No recent notes on file.` |
| Free-text med, no RxNorm | Fact + uncertain identity; no invented code |
| Note body huge | Truncate excerpt; still cite id |
| Duplicate locator across tools | Avoid in shaping; verify dedupe is safety net |
| `args` contain extra filters | **Ignore** in MVP (caps are server-side constants) |
| Wrong pid in body | Existing `pid_mismatch` (fail-closed) |
| Unknown tool name | `not_implemented` |
| One of four tools 500s | Partial clinical from the other three + unavailable line |
| All four tools 500 | SSE `error` |
| Auth/bind fail on any tool call | SSE `error` (fail-closed) |

### Error Scenarios

| Failure | Handling |
| --- | --- |
| Chart service throws | tool_proxy logs; `ok: false` generic — no SQL/exception text to sidecar |
| One parallel tool fails | Sidecar partial merge (not whole-turn failure) |
| Bind/secret fail | Unchanged 401/403 semantics; whole turn fails closed |

### Validation Requirements

- `pid` / `user_id` ints; correlation id present; secret match — existing.
- Chart services: `pid <= 0` → throw / refuse at dispatcher (should never happen post-bind).
- Fact: non-empty `text`, non-empty `table`, non-null `id` (only when a real row exists — never synthesize `id: "none"`).

### Error Messages

- Sidecar/browser: generic SSE errors only (no PHI, no SQL).
- Disclosure log: tool name + pass/fail reason (existing) — still no note bodies.
- Physician-facing empty/unavailable: allowlisted clinical-ish lines (§3) — not toolchain jargon.

---

## 6. Likely Pitfalls to Avoid

### Common Mistakes

- Leaving `*_stub` names in sidecar while PHP renames (or vice versa) → `not_implemented` on happy path.
- Returning fixture ids that don’t exist in DB → verify “passes” but interview citation story collapses.
- Dumping full note text into facts / LangSmith later — truncate now.
- Putting raw SQL in Python.
- Accepting `args.pid` over bind pid.
- Treating `facts: []` as an error or inventing a fake locator for “none on file.”
- Failing the whole brief because `notes` 500’d while labs/meds succeeded.
- Using Susan pid 2 for labs smoke (0 results locally).
- Counting `prescriptions.active=1` with past `end_date` as active.
- Scraping `form_soap` / CCDA `documents` as “notes” for Synthea.

### Gotchas

- `BaseService` constructor side effects break isolated PHPUnit — use Schedule-style injectable loaders.
- Lab `result` is varchar — don’t force float parse; put chart text in `text`.
- `lists.type` discriminators — wrong type ⇒ silent empty problems/allergies.
- PRD 03 said ≤3 parallel tools — **must** raise to 4 for brief.
- Gateway timeout is 120s; four tools + two LLM calls can be slow **without** cache — acceptable for PRD 04; document cache debt.
- Richer draft context may increase `draft_parse_failed` — don’t block ship; truncate labs first if needed.

### Performance Concerns

- Four parallel PHP queries per brief — fine for demo; cache later.
- Don’t load unbounded note/lab history.
- Prefer indexed pid filters; avoid full table scans.

### Security Considerations

- Never weaken bind checks.
- Disclosure log: no note bodies.
- Read-only services only.
- Empty/unavailable lines must not leak exception/SQL text.

### Integration Issues

- DO overlay must include new `src/ClinicalCopilot/Chart/` paths (same overlay pattern as Schedule).
- Isolated tests must not require MariaDB; DB-backed smoke is manual / optional services-test later.
- PHP + sidecar must ship **together** (tool rename).

---

## 7. Testing Requirements

### Test Scenarios

1. ToolProxy: secret/pid/user fail-closed still pass (regression).
2. ToolProxy: each real tool name returns `facts` from fake dispatcher.
3. ToolProxy: unknown tool → `not_implemented`.
4. Chart services: fake loaders → correct tables/ids/caps/truncation/RxNorm uncertainty/active-med filter.
5. Chart services: empty loader → `facts: []` (not throw).
6. Sidecar: brief requests four renamed tools; labs/meds routes request one.
7. Sidecar: three tools succeed + one server error → clinical from successes + unavailable line; no graph `error`.
8. Sidecar: all tools fail → graph `error`.
9. Assemble: empty labs → contains `No recent labs on file.` without a fake citation locator.

### Unit Tests

- PHP: `ChartFactSet` serialization; each `*ChartService` with fake loaders; `ToolProxyService` with fake dispatcher.
- Python: `ROUTE_TOOLS` / tools_node partial merge / assemble empty lines.

### Integration Tests

- Optional: one in-container call against Synthea pid 6 if cheap — **not** required to merge if isolated + manual smoke green.

### Manual Testing

| Step | Expect |
| --- | --- |
| Local: bind **pid 6** → “Give me a pre-visit brief” | progress → clinical with real problems/labs/meds language; locators not 101/501 fixtures; notes empty one-liner OK |
| “What’s their creatinine?” (pid 6) | Labs facts from chart |
| Bind **pid 8** → meds ask | Allergies + meds; missing RxNorm uncertain wording; dosing still refused |
| Unbound / wrong secret | Unchanged refuse / 401 |
| Force notes tool 500 (if easy) | Partial brief + `Notes unavailable — try again.` |
| DO after overlay sync (batched) | Same happy path on a rich droplet patient |

### Test Data

- Local: **pid 6** Gonzalo160 Wisozk929 (labs/meds); **pid 8** Lorelei90 Buckridge80 (allergies + missing RxNorm). Avoid pid 2 for UC-2.
- DO: confirm a Synthea patient with labs/meds (and ideally allergies) before interview; do not block PRD 04 merge on DO.

---

## 8. Acceptance Criteria

### Functional Requirements

- [ ] Stub tools removed; four real tool names work end-to-end (`notes` added).
- [ ] Facts use real DB primary keys for the bound pid (when rows exist).
- [ ] `brief` gathers all four tools in parallel (sidecar).
- [ ] Pid/user/secret fail-closed behavior unchanged and tested.
- [ ] Empty domains return empty `facts` + physician-facing empty one-liner (assembly) — not crashes, not fake ids.
- [ ] One tool hard-failure → partial verified answer + unavailable line (not whole-turn kill if others succeeded).
- [ ] Missing RxNorm never invents a code.
- [ ] Active meds exclude completed (`end_date` set) rows.
- [ ] Notes use `form_clinical_notes` only; Synthea empty is acceptable.
- [ ] Isolated PHPUnit + sidecar pytest updated and green.
- [ ] Manual smoke local pid 6 (+ pid 8 meds); DO smoke when batching deploy.

### User-Facing Behavior

- UC-1 brief is **patient-specific** and richer than PRD 03 fixtures (visit + conditions + meds/allergies + labs; notes honest empty on Synthea).
- UC-2 labs Q&A grounded in that patient’s results (prefer pid 6).
- UC-3 chart side lists meds/allergies; dosing without research still refused.

### Performance Requirements

- No hard SLA; stay within existing 120s gateway budget on happy path.
- Caps enforced (15 labs / 3 notes / 500-char excerpt / 20 active Rx).

### Security Requirements

- No chart access without bind match.
- No exception/SQL leakage to SSE or tool JSON `error` strings.
- Read-only.

---

## 9. Dependencies and Considerations

### External Services

- None new. OpenRouter already required for draft/route.

### Database Changes

- None.

### Configuration

- No new env vars. Existing `COPILOT_INTERNAL_SECRET`, gateway tool URL, timeouts.

### Breaking Changes

- Sidecar + PHP must ship **together** (tool rename). Deploy overlay + sidecar recreate in one wave.

### Migration Steps

1. Land code locally; pytest + phpunit-isolated.
2. Smoke local pid 6 / 8.
3. When batching DO: rsync overlay Chart + ToolProxy changes; recreate/restart sidecar; smoke rich patient.
4. Update Memory Bank.

### Deferred (explicit)

- TTL/snapshot **cache** of the four-tool brief bundle (~30–60s) — later PRD/chore once latency hurts demo.
- Optional **seed 1–2 `form_clinical_notes`** on a demo patient if interview script wants a cited note (not required for PRD 04 acceptance).
- Calendar “today’s visit” title as why-here (encounter reason is enough now).
- Draft tool-JSON truncation / parse hardening if rich payloads worsen `draft_parse_failed`.
- openFDA/DailyMed, citation popups, LangSmith, FHIR-primary, per-turn tool tickets.

---

## 10. Project Notes from Ticket

### Important Notes

- Spine step 4 must be **real** PHP chart services — fixtures are not acceptable as the final state.
- Builder chose **rich brief (all tools)** over one-tool vertical slice because **cache will come later**.
- **Fail-closed** = auth/bind. **Empty ≠ error.** **Domain error ≠ kill turn** when other domains succeeded (decision guide §6).
- Interview line: “Every chart claim is verified against tool facts from the bound patient’s OpenEMR services, re-checked for pid at the gateway.”
- Live DO remains interview truth; mid-wave DO green is not a merge gate.

### Assumptions

- Synthea patients on local (and DO) still have usable labs/meds/problems on **rich** pids (6/8 class).
- Fact shape and verify logic from PRD 03 remain stable for fact-backed claims.
- Schedule-style service testing pattern is acceptable vs forcing BaseService inheritance.
- `form_clinical_notes` empty on Synthea is OK for MVP.

### Deferred debt to record after ship

- “Brief four-tool bundle not cached yet (planned TTL); first brief may be slow.”
- “Synthea has no clinical notes — empty notes domain is honest; optional seed later for demo script.”
- “Watch draft_parse_failed under richer tool JSON; truncate labs first if needed.”

---

## 11. Attachments and References

No Jira attachments folder.

**Canonical:** `ARCHITECTURE.md` · `AUDIT.md` · `docs/ai-decision-guide.md` (§5–6, §11 PRD 04) · `memory-bank/activeContext.md` (PRD 04 decisions)  
**Prior PRDs:** `docs/PRDs/01-ask-copilot-tab.md`, `02-session-proxy-gateway.md`, `03-langgraph-sidecar.md`  
**Pattern reference:** `src/ClinicalCopilot/Schedule/`  
**Local data check (2026-07-21):** pid 6 labs/meds rich; pid 8 allergies + missing RxNorm; all pids `form_clinical_notes` count = 0; pid 2 not suitable for UC-2.
