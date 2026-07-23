# AI Decision Guide — Clinical Co-Pilot

**Purpose:** When docs leave room for judgment, use this file to choose.  
**Audience:** Coding agents (and humans) implementing the roadmap.  
**Status:** Local planning doc — not committed yet.

This guide does **not** replace locked product/architecture docs. It only says *how to choose* under ambiguity, time pressure, and demo constraints — including **product / physician UX** judgment, not only engineering.

---

## 1. Document hierarchy (highest wins)

| Priority | Source | Use for |
| --- | --- | --- |
| 1 | This file (`docs/ai-decision-guide.md`) | Ambiguity, tradeoffs, shortcuts, escalation, “good enough for demo”, physician UX defaults |
| 2 | `ARCHITECTURE.md` | Locked topology, auth, verify, stream, research, roadmap shape |
| 3 | `USERS.md` / `USER.md` | Persona, UC-1/2/3 jobs, UX intent |
| 4 | `memory-bank/activeContext.md` + `progress.md` | Current reality, deferred debt, next step |
| 5 | `memory-bank/*` other files + `.cursor/rules/` | Patterns and longer-lived context |
| 6 | `docs/architecture-tech-primer.md`, overview, directions | Teaching / background — not override locks |

**Conflict rule:** If `ARCHITECTURE.md` and this guide seem to disagree on a *locked* technical choice (session-proxy, cite-or-silence, hybrid SSE, services-first chart, etc.), **follow ARCHITECTURE**. This guide only governs *how to implement, cut, or stub* within those locks.

**Ambiguity rule:** Prefer the option closest to `ARCHITECTURE.md`. Record the choice in `memory-bank/activeContext.md` (and `progress.md` if it changes status).

---

## 2. Primary goals (north star)

1. **Interview MVP** — A working demo the builder can run on **live DigitalOcean** and defend as an SWE: clear boundaries (auth, verify, citations), not flashy complexity.
2. **Generally works** — Few bugs on the happy path and the failure modes we intentionally show. Not production-hardened.
3. **Easy to deepen later** — Prefer thin real seams (gateway, tools, verify node) over one-off hacks that block phase-2 SMART/FHIR/multi-worker talk track.
4. **Never wrong medicine** — Incorrect clinical content is worse than a thin or refused answer. Incomplete planned features are OK to discuss verbally.
5. **Physician time budget (~90 seconds)** — Between rooms, the physician needs *all relevant* grounded info fast. Uncached UC-1 may be slow now (accepted). **Post-cache / post-MVP**, the rich brief must feel instant enough to fit that ~90s window. Design gather shape and answer density for that future; do not thin the product job just because the first uncached call is slow.

**Not goals for this phase:** hospital concurrency, production HIPAA hardening, rubric completeness, impressive model cleverness.

---

## 3. Two different “guess” policies

| Domain | Policy |
| --- | --- |
| **Engineering** (APIs, UI chrome, stubs, deploy glue) | Informed guess is fine. Prefer reversible choices. Note debt in Memory Bank. |
| **Clinical claims shown to the physician** | No silent guessing. Every claim is either **verified + cited**, explicitly **`unverified`** (and never presented as fact), or **refused**. |

**Hard lock from architecture (do not shortcut):** Do not stream unverified clinical prose as if it were verified. Do not use a skim-able warning as a substitute for verification on the primary clinical path.

**Allowed softening for demo (only if needed to ship a turn):** You may show a clearly labeled `unverified` block *separate from* verified clinical text (e.g. “Unverified draft — not confirmed against chart”). Prefer refuse when confidence is low. Never mix unverified sentences into the verified answer without labels.

---

## 4. Shortcuts and fakes

### Allowed

- Stub or fake **complex unfinished work** to reach a demo faster (e.g. canned research JSON, simplified verify, progress-only SSE before full hybrid).
- Skip polish (perfect CSS, full eval catalog, LangSmith dashboards) if the interview story still holds.

### Not allowed (explicitly planned — do not fake away)

These are the roadmap spine. Implement real (even if minimal), don’t replace with theater:

1. Ask Co-Pilot UI (OpenEMR tab + picker + chat chrome)
2. Session-proxy gateway (session + pid + correlation ID)
3. LangGraph sidecar skeleton (route → tools → draft → verify)
4. Chart tools via gateway + PHP services + **pid fail-closed**
5. Research path (openFDA → DailyMed) *or* an honest refuse path with the same contracts
6. Citation wiring + hybrid stream contract (progress vs clinical)
7. Observability stubs at minimum (`/health`/`/ready`; correlation ID; disclosure log stub)

Synthea data and interview narrative are supporting — already largely done / can be thin.

### When you take a shortcut

1. Implement the smallest real seam that preserves the interview story.
2. Add a **Deferred debt** bullet to `memory-bank/activeContext.md` and mark status in `progress.md`.
3. Name *what* was faked, *why*, and *what “done later” means*.
4. Do not silently leave fakes undocumented.

---

## 5. Scope under time pressure

**Keep shipping the spine.** Prefer finishing PRD waves locally over pausing for DO polish. Deployment / DO flakiness (empty schedule, `draft_parse_failed`, overlay quirks) is **batchable at the end** (or before interview) — do not block chart tools / research / citations on a green DO smoke every turn. Still write code that *can* deploy on DO; do not invent local-only auth or chart paths.

**Live DO remains interview truth** for the final talk track — just not a per-commit gate while building 04–07.

### Use-case cut order (if forced)

| Priority | Use case | Rule |
| --- | --- | --- |
| Keep first | **UC-1** pre-visit brief | Core interview story: patient-bound chart synthesis + citations |
| Keep second | **UC-2** labs Q&A | Same tools/verify path; high signal, low extra surface |
| Prefer if easy | **UC-3** label-backed dosing / interaction | Nice for demo when openFDA→DailyMed path is relatively cheap; never invent dosing |
| Cut / thin first | Deep UC-3 option lists / interaction APIs | Chart meds + refuse dosing still acceptable if research path is hard |

Incomplete deep UC-3 is fine to *talk about* if UC-1 (and ideally UC-2) work; **one** label-backed dosing or interaction answer is worth doing when PRD 05 makes it straightforward.

### Vertical slice vs full skeleton

**Default:** smallest **vertical slice** that proves the trust story end-to-end:

`tab → gateway → sidecar → chart tools → verify → SSE clinical + citation`

Then widen (research, citation UI, polish). Only build a wide empty skeleton when the next PRD wave needs shared contracts (event shapes, claim schema) — keep skeletons compiling and health-checkable.

### Thin gather vs rich gather (tool fan-in)

Vertical slice means **real seams**, not “call the fewest tools.” When choosing how many chart tools to fire on a route:

| Prefer **rich parallel gather** when… | Prefer **thin / one tool** when… |
| --- | --- |
| The product job’s happy path needs that bundle (e.g. UC-1 brief = context + labs + meds + notes) | A follow-up route is domain-specific (`labs`, `meds`) |
| A **later cache** (TTL snapshot) will amortize the cost and should store the **full** bundle | Extra tools add clinical risk or PHI scope without improving the demo job |
| Parallel hop already exists and fail-closed is per-call | You’re still proving a brand-new unverified contract |

**Lesson (PRD 04, builder override 2026-07-21):** Agents recommended “brief → `patient_context` only” for slice thinness. Builder chose **all four tools on brief** because a snapshot/TTL cache is planned — gather the cacheable shape **now**, even if the first uncached brief is slower. Do **not** thin multi-tool fan-in solely to look like a smaller vertical slice when (1) the UC needs the rich answer and (2) cache will make rich cheap later.

**Ask the human (with a recommendation)** when thin-vs-rich changes **demo richness** or **future cache key shape** — not when it’s pure naming/layout.

---

## 6. Physician UX defaults (product chooser)

Persona: clinic PCP with **~30–90 seconds** between rooms. Voice: terse, clinical, non-technical. Trust > completeness; incompleteness must be **honest and scannable**.

### Answer density (UC-1 brief)

- Prefer **short structured bullets** over narrative paragraphs.
- Cover the job (why here / last visit, conditions, allergies, meds pointers, high-signal labs, selective notes) — not a chart dump.
- Caps exist so the answer stays scannable under ~90s *reading* time; uncached *latency* may exceed that today — progress events carry the wait (see below). Cache later makes the same rich shape feel instant.

### Partial tool / domain failure

**Ship the partial win.** If some chart tools succeed and one fails (timeout, 5xx, empty error):

1. Present **verified + cited** facts from successful tools.
2. For the failed domain, one honest clinical-ish line — e.g. `Notes unavailable — try again.` — **not** model-invented filler.
3. Do **not** fail the whole turn when any domain still has verified facts.
4. Do **not** silently omit a failed safety-critical domain (allergies / meds) without that unavailable line — absence of a section must not look like “none on file.”

### Empty chart domains (nothing on file)

Absence is clinical signal. Prefer **one short explicit line** per domain the job cares about:

| Domain | Empty copy (examples) |
| --- | --- |
| Allergies | `No allergies on file.` |
| Active meds | `No active medications on file.` |
| Conditions | `No active conditions on file.` |
| Recent labs | `No recent labs on file.` |
| Notes | `No recent notes on file.` |

Do **not** invent “likely none” or pad with speculative reassurance. Prefer structured emptiness over digging into notes to “confirm” absence.

### Citations (trust UI)

- **Link every verified clinical claim** in the answer (chart or research). Goal: physician can audit anything on screen — supports “zero silent hallucinations.”
- Citation target = in-pane popup (PRD 06): locator + useful excerpt / research title·section·URL as available.
- Conflicts (openFDA vs DailyMed): **deferred for MVP** (fallback-only path). When conflict UX lands later: short conflict statement in chat + both sides linkable — physician decides; never silently pick a winner.
- Unverified (if used at all): hard-labeled block, **no** citation links that imply chart backing.

### Progress events (waiting UX)

Use **clinical-ish** progress, not toolchain jargon. Physicians are not debugging agents.

| Prefer | Avoid |
| --- | --- |
| `Pulling labs…` | `Calling tool labs_stub` |
| `Checking medications…` | `ROUTE=meds fan-in` |
| `Looking up label information…` | `openFDA HTTP 200` |
| `Reviewing chart notes…` | `verify node started` |

Keep progress short; one domain at a time is enough. No fake precision (“87% complete”).

### UC-3 product bar

- Chart meds / allergies / conditions always cited when present.
- **Label-backed dosing or interaction** — implement when relatively easy in PRD 05 (openFDA primary, DailyMed fallback); worth one demo-script happy path.
- Without a retrieved label: refuse the unsupported dosing/interaction part; still return cited chart facts.
- Framing: decision support, not a prescription. Short disclaimer once per med turn is enough.

---

## 7. Ambiguity protocol

1. Re-read the relevant lock in `ARCHITECTURE.md`.
2. Choose the option **closest to architecture**.
3. If still tied, prefer: **safer clinically** > **simpler** > **more extensible** > **prettier**.
4. When “simpler” means dropping tools from a multi-domain happy path, check **§5 thin vs rich gather** and any stated plan to **cache** that bundle — extensibility/cache shape can beat one-call thinness.
5. For physician-facing copy / failure UX, prefer **§6 Physician UX defaults**.
6. Note the decision in `memory-bank/activeContext.md` under “Decisions that stuck” or “Deferred”.
7. Continue — do not block the builder for pure engineering taste.

### Thrash budget

- **~15–20 minutes** or **one failed approach** on a single ambiguous choice, then pick per rules above and document.
- **Stop and escalate** sooner if touching escalation topics (below), or if a change could corrupt demo data / break DO login.

---

## 8. Escalation (ask the human)

**Always escalate before coding:**

- Weakening pid binding, session-proxy, or fail-closed chart access
- Showing clinical text without verify/citation path (or redefining verify)
- Sending PHI to research/LLM in violation of “drug/condition terms only” / BAA posture
- Chart write-back or anything that mutates clinical data
- Destroying or bulk-changing DO demo patients / credentials
- Changing locked stack choices (drop LangGraph, skip gateway, FHIR-primary MVP, etc.)

**Escalate when it changes the ~90s physician story** (ask once, with a recommendation):

- Changing brief **shape** (which domains appear, default caps that drop clinically important rows, narrative vs bullets)
- Changing citation policy (e.g. stop linking every claim, move sources out of chat, remove popups)
- Changing refuse / empty / partial-failure **copy philosophy** (e.g. fail whole turn on one tool error; hide empty allergies)
- Shipping **uncached-only** shortcuts that permanently prevent the planned rich TTL cache bundle
- Adding physician-facing surfaces beyond Ask Co-Pilot chat (new tabs, dashboards, settings) for MVP
- Dropping UC-1 or UC-2 from the demo path to save time

**Do not escalate (decide and document):**

- Naming, file layout within `/src` vs sidecar package layout
- Minor UX spacing / OpenEMR-familiar chrome tweaks within locked patterns
- Exact progress string wording if still clinical-ish (`Pulling labs…` family)
- Test quantity for a vertical slice (prefer a few high-value tests)
- Whether to stub DailyMed if openFDA works for the demo script
- Logging field names, correlation ID format, health payload shape
- Batching DO redeploy / schedule seed / `draft_parse_failed` triage until end of a wave or pre-interview

**Ask once, with a recommendation:** when two options are both architecture-compatible but differ in **interview narrative** impact, **demo richness / future cache shape** (§5), or **physician story** (this section).

---

## 9. Clinical / safety tone (product copy)

**Goal:** Never give incorrect medical information. Incomplete > wrong.

| Situation | Behavior |
| --- | --- |
| Claim has resolvable chart/research locator and passes verify | Present as normal clinical text + **citation link** |
| Claim cannot be verified | Prefer **omit** or **refuse** that claim; if shown, hard-label **`unverified`** and keep it out of the verified block |
| Dosing / interactions / “what should I prescribe” without retrieved label | **Refuse** the unsupported part; may still return cited chart meds/allergies/conditions |
| Label conflict | **MVP deferred** (fallback-only). Later: surface both in chat; citations for each; physician decides |
| Missing RxNorm / unclear drug identity | Say identity is uncertain; **no** dosing research until clear |
| Tool domain failed | Partial verified answer + `… unavailable — try again.` for that domain |
| Empty domain | Explicit short “none / no recent … on file” (see §6) |
| Very unsure | Refuse: short, clinician-facing, non-apologetic |

**Default voice:** terse and honest — e.g. “Not on file.” / “No retrieved label source for dosing — I won’t guess.”  
**UC-3 framing:** decision support, not a recommendation. Include a short standing disclaimer on med answers (once per med turn is enough): physician remains responsible; co-pilot does not prescribe.

**Do not:** invent RxNorm, invent labs, invent note content, or “helpfully” complete sparse charts.

---

## 10. Intentional demo failures (show these)

Prefer scripting one clear failure in the interview over hiding all rough edges:

1. **Unbound patient** → picker / refuse chart tools (auth story)
2. **Missing RxNorm / free-text med** → uncertain identity, no invented code (data honesty)
3. **Research miss or refuse dosing** → cited chart + explicit refuse (verify story)
4. Optional: **label conflict** if easy with fixtures
5. Optional: **partial domain unavailable** if easy to script (honesty under failure)

Happy path still required: UC-1 brief with at least two **linked** cited facts on a Synthea patient (local first; DO before interview). Prefer also one label-backed UC-3 answer when PRD 05 is in.

---

## 11. Roadmap steps 4–7 — decision menus

Use these when implementing or writing PRDs. Defaults below; escalate only per §8.

### PRD 04 — Chart tools

| Choice | Default |
| --- | --- |
| Brief fan-in | All four tools in parallel (cacheable shape) |
| Caps | ~15 labs, ~3 notes, truncated excerpts — adjust only if demo patient needs it; escalate if dropping a safety domain |
| Empty domains | Explicit one-liners (§6) |
| Partial tool failure | Partial answer + unavailable line |
| Missing RxNorm | Uncertainty in fact text; no invented codes |
| Cache | Document debt only — do not implement TTL in 04 |
| DO smoke | Nice; do not block merge of real services |

### PRD 05 — Research (openFDA → DailyMed)

| Choice | Default |
| --- | --- |
| Outbound query | Drug/condition terms only — never PHI |
| Happy path | One label-backed dosing **or** interaction answer if relatively easy |
| Miss / timeout | Cited chart + refuse unsupported claim |
| Conflict | Both sources; chat states conflict; citations for both |
| DailyMed | Fallback when openFDA miss; stub only if needed and noted as debt |
| UC-3 depth | Prefer one solid demo path over broad option-list generation |

### PRD 06 — Citations + hybrid stream polish

| Choice | Default |
| --- | --- |
| Link density | **Every** verified clinical claim |
| Popup | Locator + excerpt / research metadata; stay in chat pane |
| Progress copy | Clinical-ish (`Pulling labs…`, etc.) |
| Unverified | Separate labeled block only if needed; no fake citation links |
| Stream | Progress early; clinical only after verify |

### PRD 07 — LangSmith + `/health` + `/ready`

| Choice | Default |
| --- | --- |
| Traces | Redacted; correlation ID joins app disclosure log |
| `/ready` false | Fail closed on agent path; short non-technical UI error if shown |
| Scope | Stubs OK; no LangSmith dashboard polish required for interview |

---

## 12. Anti-patterns (do not do)

- Thin UC-1 brief to one tool “for a smaller vertical slice” when rich gather + later cache is planned.
- Fail the whole clinical turn because one tool domain errored when others verified.
- Treat empty allergies/meds as “section omitted” (looks like none checked).
- Physician-facing jargon (`tool_proxy`, `fan-in`, raw HTTP codes) in progress or answer text.
- Skip citation links on verified claims to “reduce clutter.”
- Invent RxNorm, labs, notes, or dosing from model memory.
- Premature FHIR-primary path, SMART runtime, multi-worker, or durable checkpointer for MVP.
- New physician surfaces (dashboards, settings pages) unrelated to Ask Co-Pilot chat.
- Block PRD 04–07 implementation on DO redeploy / schedule seed / draft-parse flakiness.
- Lecture the builder on Docker/OpenRouter/LangGraph basics unless the PRD requires it.
- Silent fakes of spine steps 1–7 without Memory Bank debt.

---

## 13. Code placement and quality heuristics

### Where code lives

| Concern | Default home |
| --- | --- |
| Session, pid bind, SSE to browser, chart proxy, disclosure log | OpenEMR PHP (`/src` services + thin `interface/` entry) |
| Agent loop, tools orchestration, draft, verify, research HTTP | LangGraph sidecar (Python) |
| Claim schema / SSE event names | Shared contract (document in PRD; implement consistently both sides) |

**PHP vs Python rule:** EHR session, ACL/session realities, and chart reads stay in PHP behind the gateway. Reasoning, multi-step tools, verification graph, and external research stay in the sidecar. Do not put raw SQL in the sidecar. Do not call the LLM from PHP for the MVP agent loop.

### Quality bar for demo MVP

- Match OpenEMR conventions for new PHP (`declare(strict_types=1)`, `/src`, `BaseService`, no new legacy `/library` patterns).
- Prefer a few tests that lock **pid fail-closed**, **verify drops bad claims**, and **one gateway happy path** over broad coverage.
- Don’t block the demo on PHPStan-perfect drive-bys in untouched OpenEMR core.
- Manual escape on Co-Pilot Twig/HTML (Twig autoescape is off in OpenEMR).
- Smoke on **DO before interview**; during 04–07 waves, local green + ship forward is enough unless a change is DO-only.

### Extensibility without over-building

- Real interfaces/seams (gateway API, tool results, claim list, SSE events).
- No premature FHIR dual path, SMART, durable checkpointer, or multi-worker.
- Comments/docs only where the interview or next PRD needs the seam explained.

---

## 14. Build process (how this repo gets implemented)

The builder uses:

1. `/generate-prd` — **one PRD per roadmap step** (steps 1–7 below)
2. `/create-plan-ethan` — plan waves from that PRD (chat only)
3. `/execute-plan-ethan` — execute with parallel subagents when safe

### Roadmap steps → PRDs

| PRD # | Step (from `ARCHITECTURE.md` §7) |
| --- | --- |
| 1 | Ask Co-Pilot tab + empty chat + patient picker |
| 2 | Gateway SSE + correlation ID + disclosure log stub |
| 3 | Sidecar skeleton graph + Haiku via OpenRouter |
| 4 | `PatientContextService` + lab/med/note tools (pid checks) |
| 5 | openFDA + DailyMed fallback + conflict/miss behavior |
| 6 | Citation popup wiring + hybrid stream events |
| 7 | LangSmith redacted traces + `/health` + `/ready` |

Steps 8–9 in architecture (Synthea; eval + narrative) are supporting: Synthea is largely done; eval/narrative can be a thin follow-on, not a blocker for “works on DO.”

**Teaching:** PRDs and plans carry mental models; execution agents should not re-lecture Docker/OpenRouter basics unless the PRD says so. Prefer decision notes in Memory Bank over long chat essays.

**PR size:** One PRD wave ≈ one reviewable chunk. Prefer merging a working thin slice over a mega-PR.

---

## 15. Quick chooser cheat sheet

| Question | Answer |
| --- | --- |
| Architecture lock vs faster hack? | Keep the lock; thin the feature |
| Wrong med info vs thin demo? | Thin / refuse / unverified label |
| Fake now? | Only non-spine work; Memory Bank debt required |
| UC cut? | Keep UC-1; then UC-2; label-backed UC-3 if easy; else thin UC-3 |
| Brief: one tool vs all chart tools? | **Rich parallel** (cache later); thin only for domain follow-ups |
| Slow uncached brief? | Accept now; keep rich shape for post-cache ~90s goal |
| One tool failed? | Partial verified answer + domain unavailable line |
| Empty allergies/meds? | Explicit “none on file” — don’t omit the section |
| Citations? | Link **every** verified claim; popup for details |
| Progress copy? | Clinical-ish (`Pulling labs…`) |
| Where to implement agent logic? | Sidecar; PHP = session + chart proxy |
| DO flaky mid-wave? | Keep shipping; batch deploy fixes before interview |
| Unsure clinically? | Refuse or mark unverified — never silent guess |
| Unsure technically? | Closest to `ARCHITECTURE.md` → note in Memory Bank |
| Escalation? | Auth/PHI/verify/writes/stack locks **or** changes to the ~90s physician story (brief shape, citation policy, refuse/empty philosophy) |

---

## 16. After each significant decision

Update Memory Bank (do not wait for perfect docs):

- `activeContext.md` — what changed, what’s deferred, demo script notes
- `progress.md` — checkboxes / known issues
- This file — only if a **recurring** decision rule should change

Interview line to protect: *“Working MVP on a real OpenEMR deploy: session-bound patient access, tool-layer pid checks, verified citations, honest refuses — designed so SMART/FHIR and richer research plug in later.”*
