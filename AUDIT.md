# OpenEMR Audit — Clinical Co-Pilot

**Project:** Gauntlet AgentForge / Clinical Co-Pilot  
**Codebase:** fork of `Gauntlet-HQ/openemr-base-clean` → `eweinhaus/openemr-base-clean`  
**Deployed instance:** https://142.93.255.212/ (DigitalOcean NYC1, Docker `openemr/openemr` + MariaDB)  
**Scope:** security, performance, architecture, data quality, compliance — focused on what an embedded clinical AI agent must inherit, enforce, or work around.  
**Intended jobs (product input):** (1) pre-visit patient brief, (2) recent-labs Q&A, (3) medication decision-support with chart + external references.

---

## Executive Summary

This audit examined the OpenEMR fork that will host the Clinical Co-Pilot. Five findings should drive architecture before any agent code ships.

**1. Default deployment credentials and a weak “production” template.** Both `docker/production/docker-compose.yml` and `docker/development-easy/docker-compose.yml` hardcode `OE_USER=admin` / `OE_PASS=pass` and `MYSQL_ROOT_PASSWORD=root`. The production template also runs MariaDB **without TLS**, while development mounts SSL certs. Our DigitalOcean droplet currently uses those demo defaults. That is acceptable for Gauntlet **demo data only**, and must be called out explicitly — not presented as production-ready HIPAA hosting.

**2. Authorization is coarse GACL roles, not per-patient.** `src/Common/Acl/AclMain.php` gates sections such as `patients:med` / `patients:demo`. A provider with medical-records access can open *any* patient chart; there is no default “my panel only” restriction beyond optional facility scoping. The case study’s “who is asking?” requirement means **patient-scoped checks must live in the agent tool layer** (chart/session-bound `pid`, fail closed on cross-patient access). OpenEMR login alone is not a patient authorization boundary.

**3. Shipped demo patients are clinically empty.** `sql/example_patient_data.sql` has demographics-only rows — no trustworthy encounters, meds, labs, problems, allergies, or notes for the three planned jobs. Realistic demos require Synthea via `openemr-cmd import-random-patients` on **local and DO** (target ~5–10 rich patients), plus verification that FHIR UUIDs exist before FHIR-facing tools.

**4. Fast “patient context” is a multi-table synthesis problem; med jobs also need external knowledge.** Labs traverse `procedure_order → procedure_report → procedure_result`; chart UI is many independent fragments under `interface/patient_file/summary/`. Indexes are generally present — the cost is aggregation/design, not missing indexes. The agent needs a **`PatientContextService`** (snapshot: reason/visit, conditions, meds, recent labs, last visit, selective notes) plus fine-grained follow-up tools. Medication Q&A (dosing, add-on safety, symptom-oriented options) additionally needs **curated web/reference tools** — with **no patient identifiers** in outbound research queries, and answers framed as **decision support** (physician remains responsible), verified against retrieved label/interaction text rather than model memory.

**5. Audit logging is solid by default; LLM PHI disclosure and external research are not covered.** `enable_auditlog` and `audit_events_query` default on, with SHA3-512 per-row checksums in `LogTablesSink.php` — but checksums don’t catch row *deletion*, ATNA is off by default, and nothing records “which PHI fields were sent to an LLM” or “which external URLs were fetched for a prescribing question.” Co-Pilot must add its own correlation-ID’d disclosure/verification log, keep full clinical payloads out of third-party observability, and treat OpenRouter as BAA-covered / no-training per project constraints (demo data only).

These findings shape a **hybrid** integration: OpenEMR owns session, UI entry, and a thin gateway; a **LangGraph** sidecar owns the tool loop (OpenEMR tools + research tools + verification), with **LangSmith** for traces/evals experience. Details belong in `USERS.md` and `ARCHITECTURE.md`.

---

## 1. Security

Ranked by impact.

- **Default credentials in compose templates.** Production and development-easy set `admin`/`pass` and MySQL root `root`. Public DO deploy matches this for Gauntlet demo use — intentional, documented, not rotated for showmanship.
- **Production compose lacks DB TLS that dev has.** Dev passes MariaDB SSL flags and mounts `library/sql-ssl-certs-keys/`; production does not — app↔DB traffic is plaintext on the Docker network.
- **AuthZ is role/section ACL (GACL), not patient-scoped.** `AclMain` / `Gacl::acl_check()`. Closest built-in scope: facility restriction. Agent tools must enforce physician↔patient binding for the open chart.
- **Twig autoescape is off globally.** `TwigContainer` sets `'autoescape' => false`. Any co-pilot Twig must escape manually (`|e`); Semgrep rules already watch for this.
- **CSRF is selective.** Prefer read-only FHIR/API/service access for the agent; verify CSRF on any future write-back (MVP is read-only).
- **Core session cookie `Secure` defaults false** on some paths — prefer HTTPS front door; document for demo IP.
- **PHI at rest unencrypted by default** for core demographics/SSN. Field encryption targets OAuth/payment/MFA/optional drive — not `patient_data`.
- **SQLi largely mitigated via wrappers + Semgrep**, but legacy concatenation patterns remain in `/library`. New agent paths must use services / `QueryUtils` / DBAL only.
- **External research risk:** medication job will call the internet. Queries must be **drug/condition terms only** (never name/DOB/MRN/note text with identifiers). Research results are untrusted until verification; model must not “recall” dosing without a retrieved source.
- **Prescribing UX risk:** questions like dose or “is it safe to add X” can be over-trusted. Product stance: **decision support with citations**, explicit uncertainty, never silent auto-prescribe into the chart (MVP has no write-back anyway).

---

## 2. Performance

- **Labs = 3-join chain.** Prefer lab/procedure services over ad-hoc joins. Fine for “recent labs” and creatinine follow-ups if scoped by `pid` + date window.
- **`lists` / `prescriptions` / `form_encounter`:** generally indexed for per-patient reads; composite indexes nice-to-have at hospital scale, not blockers for demo.
- **No single patient-context API.** Summary UI fragments are independent queries — wrong shape for a ~90-second brief. Snapshot service + short TTL (~30–60s) avoids repeated multi-table fan-out within a turn.
- **Notes:** selective retrieval only (recent encounter notes / problem-relevant snippets). Dumping full note history into Haiku burns tokens and latency and raises hallucination risk.
- **External research latency** stacks on OpenRouter round-trips. Guard with timeouts, parallel tool calls where safe, and progressive answers (chart facts first, research second).
- **Audit SELECT logging** can amplify cost under agent-heavy reads. Keep EHR audit defaults; put agent disclosure in a **separate** log so we are not forced to disable SELECT auditing blindly.
- **Dev vs prod:** load-test thinking must use prod-style images without Xdebug bind-mount tax.

---

## 3. Architecture

- **Clean layering:** `/src` (PSR-4 services, REST/FHIR, events) · `/library` (legacy) · `/interface` (UI). New OpenEMR-side co-pilot code belongs in `/src` only.
- **`BaseService`** is the extension point for `PatientContextService` composing patient, encounter, condition, allergy, prescription, lab, and note services.
- **REST/FHIR + SMART** are the preferred cross-process surfaces for a sidecar (patient-bound tokens still re-checked in tools).
- **UI hooks:** patient summary / encounter Symfony events for “Ask Co-Pilot” without forking core templates carelessly.
- **Chosen runtime shape (product):** **hybrid** — OpenEMR session + embedded UI + thin PHP/API gateway; **LangGraph** sidecar for agent loop, OpenRouter (Haiku start), OpenEMR tools, web research tools, verification. Teaches a common industry stack while keeping the EHR integration visible.
- **Observability (product):** **LangSmith** (common with LangGraph) for traces, latency, tool failures, token/cost — redacted; plus app-level correlation IDs and separate PHI-disclosure/verification records.
- **DI / DB:** container-wired services; never string-built SQL for new paths.

---

## 4. Data Quality

- **`sql/example_patient_data.sql` — demographics only.** Insufficient for brief / labs / meds jobs.
- **Path to usable data:** `openemr-cmd import-random-patients N` (Synthea → CCDA) on local and DO.
- **Join-heavy clinical model** with `lists.type` discriminators — wrong type strings ⇒ silent empty answers (agent failure mode).
- **Free-text / coded dual paths:** e.g. `prescriptions.drug` vs `rxnorm_drugcode` — verification must not invent RxNorm; mark uncertainty.
- **Lab `procedure_result.result` is varchar**, typed by `result_data_type` — “abnormal?” and numeric compare must branch on type + reference ranges when present.
- **Notes quality varies** — treat as higher-risk evidence; cite note id + span; prefer structured facts when both exist.
- **UUIDs often nullable** on older/example rows — verify/backfill before FHIR IDs are used in citations.

---

## 5. Compliance & HIPAA

- **Strengths:** audit log on by default; optional SELECT auditing default-on; break-glass support; per-row SHA3-512 checksums.
- **Limits:** no hash-chaining (deletion undetected); ATNA off by default; no obvious built-in retention/purge schedule for all log classes; core PHI columns not encrypted by default.
- **LLM / BAA gap:** OpenEMR audit categories don’t cover external model calls or web research. Co-Pilot must log: correlation ID, user, pid, tool sequence, redacted payload summary, research URLs/titles used, verification outcome — without shipping full notes to observability vendors.
- **Directions constraint:** demo data only; treat LLM vendors (via OpenRouter) as BAA-covered / no training use. Public droplet with `admin`/`pass` is demo-only.

---

## Live deployment notes (this project)

| Item | Status |
| --- | --- |
| Public URL | https://142.93.255.212/ |
| Host | DigitalOcean Droplet `openemr`, NYC1, 2 GB, Ubuntu 24.04 |
| Runtime | `/opt/openemr` Docker Compose (`openemr/openemr:latest` + `mariadb:11.8`) |
| Login (demo) | `admin` / `pass` |
| DB TLS (compose) | Not enabled (matches production template gap) |
| Credential rotation | Not rotated (demo defaults; intentional until leaving demo mode) |
| Sample clinical richness | **Todo:** Synthea import on droplet + local before Early demos |
| Agent stack on droplet | Not deployed yet (planned: OpenEMR + LangGraph sidecar) |

---

## Open questions / verify next

1. Run Synthea import on local + DO; confirm meds/labs/notes/encounters and FHIR UUIDs.
2. Live ACL test: non-admin physician role — can API/UI still read arbitrary `pid`?
3. SMART `patient/*.read` token — can it fetch another patient’s resources?
4. Choose specific research sources for meds (e.g. open drug-label / interaction APIs vs general search) and blocklist unsafe destinations.
5. Decide SELECT-audit volume strategy once agent traffic exists (keep EHR audit; rely on separate disclosure log for LLM).
6. Before any non-demo use: rotate OE/MySQL passwords, force HTTPS cookie secure, consider DB volume encryption.

---

## How this feeds the agent plan

| Finding | Architecture implication |
| --- | --- |
| Role ACL ≠ patient scope | Tool layer enforces allowed `pid` (chart-bound); fail closed |
| Empty example patients | Synthea fixtures on local + DO before demos |
| Fragmented chart reads | `PatientContextService` snapshot + drill-down tools |
| Labs / meds / notes jobs | OpenEMR tools for chart; research tools for dosing/interaction/options — cite both |
| Prescribing questions are high-stakes | Decision-support framing; verify against retrieved sources; no chart write-back in MVP |
| No LLM audit category | Mandatory co-pilot disclosure + verification log + LangSmith (redacted) |
| Twig autoescape off | Manual escaping on any co-pilot UI |
| Hybrid + LangGraph + OpenRouter/Haiku | EHR-native UX with a common agent stack interviewers recognize |

Expand in `ARCHITECTURE.md`; ground capabilities in `USERS.md` / `USER.md`.
