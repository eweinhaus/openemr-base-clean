# Product Context

## Problem

Between rooms, clinic physicians must reconstruct who the patient is, why they’re here, what labs matter, and what meds are safe *today* under time pressure.

## Solution shape

- **Multi-turn agentic chat** inside OpenEMR (LangGraph sidecar + OpenEMR tools + research tools)
- Capabilities trace to `USERS.md` / `USER.md` (UC-1 brief, UC-2 labs, UC-3 meds)
- Verification before user sees answers (chart citations; note spans; research sources)
- Observability from day one (LangSmith + correlation IDs; separate PHI disclosure log)

## Target user (locked)

**Primary care / clinic physician** — ~30–90 seconds before / as they open the next visit.

## Jobs (locked — see USERS.md)

1. **UC-1 Pre-visit brief** — why here, conditions, last visit, recent notes
2. **UC-2 Recent labs Q&A** — abnormals, specific values (e.g. creatinine)
3. **UC-3 Medication decision-support** — current meds + conditions + reason for visit; options for symptoms, dosing questions, safety of adding a drug (chart **+** external references)

Other clinical roles (nurse, ED, hospitalist) explicitly out of scope for MVP.

## Notes / meds / hallucination stance (locked)

- Structured data + selective notes; note claims need id + span
- Prefer structured over notes when both exist
- Research-backed dosing/interactions must cite retrieved sources; no patient identifiers in outbound research
- Framing: **decision support**, not autonomous prescribing; chart remains read-only in MVP
- **Anti-hallucination over completeness:** prefer omit / “not on file” over a plausible guess

## UX surface (locked)

- First-class OpenEMR **tab** (same shell as Calendar / Messages / Dashboard) — not a floating widget
- Empty chat at start (auto-brief later optional); thread stays until tab closed
- No patient selected → **blocking schedule popup** over chat (next appointment + today's list + Finder search); never auto-select; Change patient when already bound
- Source-backed facts: trailing **Source** control → in-pane popup (stay in chat); research may offer allowlisted Open label (new tab)
- Hybrid streaming: progress early; clinical text only after verification; citation batch with/after clinical (PRD 06)
- Concise answers (claim lines scannable); depth via follow-ups (typical: brief + 1–2 follow-ups)

## Research / safety product rules (locked)

- Never present dosing/interactions without a retrieved source
- Research miss → cited chart facts + explicit refuse of unsupported claim (partial win OK)
- Off-chart named drug (resolves to single Rx SPL) → research OK but **must** tell physician it is not on the active list
- **Label conflict UX deferred for MVP** (fallback-only; architecture may add conflict later)
- All medical claims need citations; omit > plausible guess
- Ambiguity / labeled-unverified softening: see `docs/ai-decision-guide.md` (primary path remains cite-or-silence)

## Success for the human

Physician trusts answers enough to act (or knows when not to), gets a useful answer fast, and can drill with follow-ups without leaving the workflow. Demo bar: defendable SWE interview narrative.
