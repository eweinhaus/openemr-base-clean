# AI Decision Guide — Clinical Co-Pilot

**Purpose:** When docs leave room for judgment, use this file to choose.  
**Audience:** Coding agents (and humans) implementing the roadmap.  
**Status:** Local planning doc — not committed yet.

This guide does **not** replace locked product/architecture docs. It only says *how to choose* under ambiguity, time pressure, and demo constraints.

---

## 1. Document hierarchy (highest wins)

| Priority | Source | Use for |
| --- | --- | --- |
| 1 | This file (`docs/ai-decision-guide.md`) | Ambiguity, tradeoffs, shortcuts, escalation, “good enough for demo” |
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

**Live DO > local.** Prefer changes that deploy and demo on https://142.93.255.212/. Local is for speed of iteration; DO is the interview source of truth.

### Use-case cut order (if forced)

| Priority | Use case | Rule |
| --- | --- | --- |
| Keep first | **UC-1** pre-visit brief | Core interview story: patient-bound chart synthesis + citations |
| Keep second | **UC-2** labs Q&A | Same tools/verify path; high signal, low extra surface |
| Cut / thin first | **UC-3** med decision-support | Highest clinical risk; may demo as chart meds + refuse dosing, or stubbed label fetch — never invent dosing |

Incomplete UC-3 is fine to *talk about* as planned work if UC-1 (and ideally UC-2) work on DO.

### Vertical slice vs full skeleton

**Default:** smallest **vertical slice** that proves the trust story end-to-end:

`tab → gateway → sidecar → one chart tool → verify → SSE clinical + citation`

Then widen (more tools, research, polish). Only build a wide empty skeleton when the next PRD wave needs shared contracts (event shapes, claim schema) — keep skeletons compiling and health-checkable.

---

## 6. Ambiguity protocol

1. Re-read the relevant lock in `ARCHITECTURE.md`.
2. Choose the option **closest to architecture**.
3. If still tied, prefer: **safer clinically** > **simpler** > **more extensible** > **prettier**.
4. Note the decision in `memory-bank/activeContext.md` under “Decisions that stuck” or “Deferred”.
5. Continue — do not block the builder for pure engineering taste.

### Thrash budget

- **~15–20 minutes** or **one failed approach** on a single ambiguous choice, then pick per rules above and document.
- **Stop and escalate** sooner if touching escalation topics (below), or if a change could corrupt demo data / break DO login.

---

## 7. Escalation (ask the human)

**Always escalate before coding:**

- Weakening pid binding, session-proxy, or fail-closed chart access
- Showing clinical text without verify/citation path (or redefining verify)
- Sending PHI to research/LLM in violation of “drug/condition terms only” / BAA posture
- Chart write-back or anything that mutates clinical data
- Destroying or bulk-changing DO demo patients / credentials
- Changing locked stack choices (drop LangGraph, skip gateway, FHIR-primary MVP, etc.)

**Do not escalate (decide and document):**

- Naming, file layout within `/src` vs sidecar package layout
- Minor UX copy/spacing (keep concise; OpenEMR-familiar)
- Test quantity for a vertical slice (prefer a few high-value tests)
- Whether to stub DailyMed if openFDA works for the demo script
- Logging field names, correlation ID format, health payload shape

**Ask once, with a recommendation:** when two options are both architecture-compatible but differ in **interview narrative** impact (e.g. show conflict UI now vs later).

---

## 8. Clinical / safety tone (product copy)

**Goal:** Never give incorrect medical information. Incomplete > wrong.

| Situation | Behavior |
| --- | --- |
| Claim has resolvable chart/research locator and passes verify | Present as normal clinical text + citation link |
| Claim cannot be verified | Prefer **omit** or **refuse** that claim; if shown, hard-label **`unverified`** and keep it out of the verified block |
| Dosing / interactions / “what should I prescribe” without retrieved label | **Refuse** the unsupported part; may still return cited chart meds/allergies/conditions |
| Label conflict | Surface both; say they conflict; physician decides |
| Missing RxNorm / unclear drug identity | Say identity is uncertain; **no** dosing research until clear |
| Very unsure | Refuse: short, clinician-facing, non-apologetic |

**Default voice:** terse and honest — e.g. “Not on file.” / “No retrieved label source for dosing — I won’t guess.”  
**UC-3 framing:** decision support, not a recommendation. Include a short standing disclaimer on med answers (once per med turn is enough): physician remains responsible; co-pilot does not prescribe.

**Do not:** invent RxNorm, invent labs, invent note content, or “helpfully” complete sparse charts.

---

## 9. Intentional demo failures (show these)

Prefer scripting one clear failure in the interview over hiding all rough edges:

1. **Unbound patient** → picker / refuse chart tools (auth story)
2. **Missing RxNorm / free-text med** → uncertain identity, no invented code (data honesty)
3. **Research miss or refuse dosing** → cited chart + explicit refuse (verify story)
4. Optional: **label conflict** if easy with fixtures

Happy path still required: UC-1 brief with at least two cited facts on a Synthea patient on DO.

---

## 10. Code placement and quality heuristics

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
- After each roadmap PRD wave: smoke on **DO** if the wave touches runtime behavior.

### Extensibility without over-building

- Real interfaces/seams (gateway API, tool results, claim list, SSE events).
- No premature FHIR dual path, SMART, durable checkpointer, or multi-worker.
- Comments/docs only where the interview or next PRD needs the seam explained.

---

## 11. Build process (how this repo gets implemented)

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

## 12. Quick chooser cheat sheet

| Question | Answer |
| --- | --- |
| Architecture lock vs faster hack? | Keep the lock; thin the feature |
| Wrong med info vs thin demo? | Thin / refuse / unverified label |
| Fake now? | Only non-spine work; Memory Bank debt required |
| UC cut? | Keep UC-1; then UC-2; thin UC-3 |
| Where to implement agent logic? | Sidecar; PHP = session + chart proxy |
| Deploy target? | DigitalOcean first |
| Unsure clinically? | Refuse or mark unverified — never silent guess |
| Unsure technically? | Closest to `ARCHITECTURE.md` → note in Memory Bank |
| Escalation? | Auth, PHI, verify bypass, writes, DO data loss, stack-lock changes |

---

## 13. After each significant decision

Update Memory Bank (do not wait for perfect docs):

- `activeContext.md` — what changed, what’s deferred, demo script notes
- `progress.md` — checkboxes / known issues
- This file — only if a **recurring** decision rule should change

Interview line to protect: *“Working MVP on a real OpenEMR deploy: session-bound patient access, tool-layer pid checks, verified citations, honest refuses — designed so SMART/FHIR and richer research plug in later.”*
