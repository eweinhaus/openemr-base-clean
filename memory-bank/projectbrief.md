# Project Brief — Clinical Co-Pilot

## Goal

Build a **Clinical Co-Pilot**: an AI agent embedded in OpenEMR that gives a physician patient-specific context in the ~90 seconds between rooms — meds, labs, recent changes, what’s on file for *this* visit — via a multi-turn conversational interface (not a generic medical chatbot).

## Source / program

- Gauntlet AI Austin Admission Track — AgentForge case study (`docs/directions.md`)
- Base: fork of `Gauntlet-HQ/openemr-base-clean` → `eweinhaus/openemr-base-clean`
- Evaluated for trust / auth / verification / HIPAA awareness; builder prioritizes **SWE interview demo** defensibility over rubric completeness
- Agent tradeoff rules: [`docs/ai-decision-guide.md`](../docs/ai-decision-guide.md) (how to choose; does not override `ARCHITECTURE.md` locks)

## Hard problems (must address deliberately)

1. **Authorization** — who may query which patient (physician ≠ nurse ≠ resident)
2. **Verification & trust** — every claim grounded in record sources; domain constraints
3. **Speed vs completeness** — seconds, not minutes; communicate uncertainty
4. **HIPAA / PHI** — demo data only; treat LLM providers as BAA-covered (no training use)
5. **Failure modes** — graceful degradation, transparent errors

## Planned MVP capabilities (jobs)

Codified as UC-1 / UC-2 / UC-3 in `USERS.md` (twin: `USER.md`):

1. Pre-visit patient brief (why here, conditions, last visit, recent notes)
2. Recent labs Q&A (abnormals / specific values)
3. Medication decision-support using chart + external research (options, dosing questions, add-on safety) — physician remains responsible

## Non-goals (for MVP week 1)

- Building OpenEMR from scratch
- Generic medical Q&A detached from patient record
- Production PHI with real patients
- Autonomous prescribing / writing meds back into the chart
