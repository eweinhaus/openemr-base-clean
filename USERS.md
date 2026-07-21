# Users — Clinical Co-Pilot

**Canonical:** this file (`USERS.md`) is the Stage 4 hard gate.  
**Twin:** [`USER.md`](./USER.md) carries the same content for the submission table.

This document is the source of truth for who the agent serves and which jobs it may take on. [`ARCHITECTURE.md`](./ARCHITECTURE.md) and every agent capability must trace back to a use case here.

---

## Target user

**Clinic / primary care physician** in an outpatient clinic on a full day (on the order of ~15–20 scheduled visits), using OpenEMR as the chart system of record.

They are not an ED resident, hospitalist on rounds, nurse, or specialist — those roles have different time budgets, data needs, and tolerance for interruption. **Other roles are explicitly out of scope for MVP.** Capability, auth models, and UX that assume multi-role panels are deferred.

### Constraints this user imposes

| Constraint | Implication for the agent |
| --- | --- |
| ~30–90 seconds between rooms | First useful answer in seconds; progressive detail; no multi-minute research dumps before a brief |
| Context-switching all day | Bind tightly to the **open chart / next visit patient** (`pid`); never make the physician re-find the patient |
| High cost of wrong clinical facts | Every claim must be verifiable against chart (and, for meds, retrieved references); fail closed; say when uncertain |
| Physician remains clinically responsible | Framing is **decision support**, not autonomous prescribing or silent chart write-back |
| Demo / case-study data only | Treat LLM providers as BAA-covered / no-training; no real-patient PHI in this deployment |

### What “useful” means

They would choose the agent if it (1) regenerates a trustworthy pre-visit picture faster than clicking through chart fragments, (2) answers a focused lab follow-up without leaving the visit flow, and (3) helps reason about a med choice with chart context **plus** cited external evidence — while making it obvious what is on file vs. what is reference material.

---

## Workflow moment

**When the agent enters the day:** between rooms, as the physician is preparing for the **next** patient — often the same window in which they open (or are about to open) that patient’s chart.

**~30 seconds before:** they finish documenting or leaving the prior room; glance at the schedule; open the next chart. They need a compressed answer to: *Who is this? Why are they here today? What’s unstable? What’s relevant for this visit?*

**What they need from the agent:** a short, grounded **brief**, then optional follow-ups (labs, meds) in the same conversation without rebuilding context.

**What they do with the output:** walk into the room oriented; ask better opening questions; decide whether to chase a lab or discuss a med change; remain the decision-maker. The agent does not examine, diagnose, or prescribe for them.

**OpenEMR reality this workflow hits:** the patient summary is many independent fragments; there is no single “ready for visit” synthesis API ([`AUDIT.md`](./AUDIT.md)). The agent’s job is that synthesis — with tool follow-ups — not a prettier static dashboard.

---

## Use cases

### UC-1 — Pre-visit patient brief

**Job to be done:** In the seconds before / as I open the next visit, give me a trustworthy picture of *this* patient for *this* visit so I walk in oriented.

**Trigger:** Physician opens Co-Pilot on the scheduled / open-chart patient (or asks “brief me on my next patient”).

**Typical ask (examples):**  
“Brief me.” · “Why are they here?” · “What changed since last visit?” · “Anything I should worry about on file?”

**Required inputs (system):** session-authenticated physician; chart/session-bound `pid`; access to encounter/reason, problems/conditions, meds, recent labs summary, last visit, selective recent/relevant notes.

**Expected output:** A short pre-visit brief covering, as available:

1. Why here / visit reason  
2. Active conditions  
3. Last visit (when + gist)  
4. High-signal recent notes (selective — not a note dump)  
5. Pointers to urgent-looking structured signals (e.g. recent abnormals) without becoming a full labs or meds deep-dive unless asked  

Every factual claim cites a chart source (FHIR id and/or table+pk; note claims cite note id + span). Prefer structured fields when notes and structured data disagree or both exist. Explicit gaps when data is missing.

**Follow-ups this use case must support (multi-turn):**  
“Go deeper on the last visit.” · “What did the last note say about X?” · “What’s on the problem list for diabetes?”

**Why an agent (not a dashboard / sorted list / better chart view):**

- The brief is a **synthesis across many EHR fragments** with different retrieval paths; a static panel still forces the physician to decide what matters *today* under time pressure.
- Needs **prioritization and narrative** (“why here” + what changed), not a wall of widgets.
- Real visits generate **follow-ups** that reshape which fragments matter (“ignore the old derm note — focus on the renal visit”); that is conversational drill-down with tools, not another filter row.
- A sorted “what’s new” list cannot explain *relevance to this appointment* or cite and trade off structured vs note evidence the way a verified agent turn can.

**Edge cases / refusals:**

- Empty or demographics-only chart → say so; do not invent clinical history.  
- Cross-patient ask (“brief me on Mr. Smith in room 3” when chart is another pid) → **refuse**; tools enforce bound `pid`.  
- Unverifiable note paraphrase → do not state as fact; quote/span or omit.  
- Request for another clinician’s panel / bulk schedule brief for all patients → out of scope for this use case (single patient, open context).

**Architecture must support:** `PatientContextService` snapshot (~30–60s TTL) + note-selective tools + verification with citations ([`AUDIT.md`](./AUDIT.md)).

---

### UC-2 — Recent labs Q&A

**Job to be done:** Answer a specific labs question for the open patient quickly — abnormals or a named result — so I don’t hunt the procedure/report/result chain mid-prep.

**Trigger:** Follow-up after a brief, or a standalone labs question on the open chart.

**Typical ask (examples):**  
“Anything abnormal in recent labs?” · “What’s their creatinine?” · “When was the last A1c and what was it?”

**Required inputs:** same `pid` binding; lab/procedure results with dates, values, units, reference ranges / flags when present; typed handling of varchar results ([`AUDIT.md`](./AUDIT.md)).

**Expected output:** Direct answer with value(s), date(s), and citation; call out missing ranges or untyped results; distinguish “no recent labs” from “labs exist but none flagged abnormal.”

**Follow-ups:** “Compare to prior creatinine.” · “Show the rest of that CMP.” · “Any anemia workup labs?”

**Why an agent (not a dashboard / trend widget):**

- Questions are **ad hoc and nested** (“abnormals” then “just creatinine” then “trend vs last year”); a fixed labs panel answers the median question, not the one asked in this 30-second window.
- Abnormality is not always a single flag — units, ranges, and data types require **reasoning + retrieval**, then a plain-language answer with sources.
- Lives in the **same conversation** as the brief and meds jobs so the physician doesn’t bounce between modules and lose the thread.

**Edge cases / refusals:**

- Ambiguous analyte name → ask a short clarifying question or list candidates; don’t guess silently.  
- Missing RxNorm/codes elsewhere are irrelevant; missing reference range → report value + “range not on file.”  
- Interpretive overreach (“this creatinine means stage 4 CKD”) without chart diagnosis support → stay descriptive of the result; don’t invent staging.

**Architecture must support:** pid-scoped lab tools over the order→report→result path; verification of numeric/string branches; no hallucinated units.

---

### UC-3 — Medication decision-support (chart + research)

**Job to be done:** Help me think through a medication question for *this* patient using what’s on file **and** retrieved reference evidence — while I remain responsible for the prescribing decision.

**Trigger:** Physician considers starting, adjusting, or checking safety of a drug given current meds, conditions, allergies, and reason for visit.

**Typical ask (examples):**  
“What are options for their cough given current meds?” · “Is it reasonable to add drug X?” · “What’s a typical adult dose range for Y?” · “Any interaction concern with their ACE inhibitor?”

**Required inputs:**

- **Chart (required):** active meds (drug text ± RxNorm when present), conditions, allergies, reason/visit context, relevant recent notes if cited carefully.  
- **External research (required for dosing / interactions / option lists):** drug and condition **terms only** — never name, DOB, MRN, or identifying note text in outbound queries.

**Expected output:** Decision-support answer that:

1. Summarizes relevant chart facts with citations  
2. Brings in **retrieved** label / interaction / guideline-style evidence with source title/URL/section  
3. Flags conflicts (allergy, duplicate class, missing RxNorm → uncertainty)  
4. States clearly: **not a prescription**; physician decides; MVP **does not write** meds into the chart  

**Follow-ups:** “What about drug Z instead?” · “Renal dosing if creatinine is elevated?” (may chain UC-2 + research) · “Show me the interaction source you used.”

**Why an agent (not a drug monograph link / static interaction checker):**

- The question is always **patient-conditioned**: current list + allergies + why they’re here. A standalone checker forces re-entry of the list; a monograph ignores the chart.
- Real questions **chain tools**: read chart → research labels/interactions → reconcile → verify before display. That is agent tool-calling, not a single iframe.
- Multi-turn refinement (“not that class — they’re already on an ARB”) is the natural clinical back-and-forth; dashboards don’t hold that state.
- Verification must combine **two evidence classes** (chart vs research); an agent loop with an explicit verification stage matches the trust requirement better than an unchecked chatbot or a dump of search snippets.

**Edge cases / refusals:**

- No retrieved source for dosing/interaction → **do not** answer from model memory as fact; say evidence wasn’t retrieved.  
- Missing RxNorm on a free-text drug → proceed with uncertainty stated; never invent codes.  
- Requests to prescribe / send to pharmacy / write the chart → refuse write-back; offer decision-support only.  
- Attempts to research using patient identifiers → strip/block; query terms only.  
- Requests for controlled-substance regimens or clearly unsafe combinations → present retrieved warnings; do not soft-pedal; still framed as support, not approval.

**Architecture must support:** OpenEMR med/allergy/condition tools + research tools + verification (chart citations + research citations); separate PHI-disclosure / verification log; OpenRouter as BAA-covered / no-training posture for demo data ([`AUDIT.md`](./AUDIT.md)).

---

## Capability traceability (for architecture & build)

| Agent capability | Allowed only if traces to |
| --- | --- |
| Multi-turn conversation | UC-1 follow-ups; UC-2 nested lab asks; UC-3 regimen refinement |
| Tool chaining (chart → research → verify) | UC-3 (primary); UC-1↔UC-2 when brief leads to labs |
| `PatientContextService` snapshot | UC-1 |
| Fine-grained lab / note / med tools | UC-1, UC-2, UC-3 |
| External research tools | UC-3 only (no PHI in queries) |
| Verification + citations | All three |
| Chart write-back / e-prescribe | **None** — explicitly out of scope for MVP |

If a proposed feature does not map to UC-1, UC-2, or UC-3, it should not ship in this MVP.

---

## Explicit non-goals (user / product)

- Generic medical Q&A detached from the open patient’s chart  
- Multi-patient “session start” briefs for the whole schedule (unless later promoted to its own use case)  
- Nursing workflows, ED triage, or inpatient rounding  
- Autonomous prescribing or silent modification of the medication list  
- Real-patient production PHI on the current demo deployment  

---

## Success criteria (human-centered)

1. **Trust:** Physician can see *why* each claim is believed (citations); knows when to ignore the agent.  
2. **Speed:** Brief is usable inside the between-rooms window; labs/meds answers don’t require leaving the chat.  
3. **Choice:** For these three jobs, the physician would rather ask Co-Pilot than click through chart fragments + separate drug sites.
