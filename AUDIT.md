# OpenEMR Audit — Clinical Co-Pilot

**Project:** Gauntlet AgentForge / Clinical Co-Pilot  
**Codebase:** fork of `Gauntlet-HQ/openemr-base-clean`  
**Deployed instance:** https://142.93.255.212/ (DigitalOcean NYC1, Docker `openemr/openemr` + MariaDB)  
**Scope:** security, performance, architecture, data quality, compliance — with focus on what an embedded clinical AI agent must inherit, enforce, or work around.

---

## Executive Summary

This audit examined the OpenEMR fork that will host the Clinical Co-Pilot. Five findings should drive early architecture decisions.

**1. Default deployment credentials and a weak “production” template.** Both `docker/production/docker-compose.yml` and `docker/development-easy/docker-compose.yml` hardcode `OE_USER=admin` / `OE_PASS=pass` and `MYSQL_ROOT_PASSWORD=root`. The production template also runs MariaDB **without TLS**, while the development template mounts SSL certs. Stage 2 requires a public URL — our DO droplet currently uses those demo defaults (acceptable for Gauntlet demo data, but must be documented and tightened before any real PHI).

**2. Authorization is coarse GACL roles, not per-patient.** `src/Common/Acl/AclMain.php` gates sections such as `patients:med` / `patients:demo`. A provider with medical-records access can open *any* patient chart; there is no default “my panel only” restriction beyond optional facility scoping (`restrict_user_facility` in `library/globals.inc.php`). The case study’s “who is asking?” requirement means **patient-scoped checks must live in the agent tool layer** (or SMART launch context), not be assumed from OpenEMR alone.

**3. Shipped demo patients are clinically empty.** `sql/example_patient_data.sql` has 14 demographics-only rows — no encounters, meds, labs, problems, or allergies. Realistic context requires Synthea via `openemr-cmd import-random-patients` (or equivalent). Without that, the agent has nothing meaningful to verify against.

**4. Fast “patient context” is a multi-table synthesis problem.** Labs traverse `procedure_order → procedure_report → procedure_result`; the chart UI is ~10 AJAX fragments under `interface/patient_file/summary/`. Indexes are generally present, so this is aggregation/design cost more than missing indexes. The agent needs a dedicated context-aggregation service (compose existing `*Service` classes), not naive per-table tool spam.

**5. Audit logging is solid by default; LLM PHI disclosure is not covered.** `enable_auditlog` and `audit_events_query` default on, with SHA3-512 per-row checksums in `LogTablesSink.php` — but checksums don’t catch row *deletion*, ATNA is off by default, and nothing records “which PHI fields were sent to an LLM.” Core PHI columns (e.g. SSN in `patient_data`) are plaintext; field encryption targets OAuth/payment/MFA secrets, not demographics. Co-Pilot must add its own correlation-ID’d PHI-disclosure log.

These findings shape `ARCHITECTURE.md`: patient-scoped auth in tools, deliberate synthetic data, a single context service for speed, and an LLM-specific audit trail layered on OpenEMR’s existing logs.

---

## 1. Security

Ranked by impact.

- **Default credentials in compose templates.** `docker/production/docker-compose.yml` and `docker/development-easy/docker-compose.yml` set `admin`/`pass` and MySQL root `root`. Our public DO deploy currently matches this for Gauntlet demo use.
- **Production compose lacks DB TLS that dev has.** Dev passes MariaDB SSL flags and mounts `library/sql-ssl-certs-keys/`; production does not — app↔DB traffic is plaintext on the Docker network.
- **`GITHUB_COMPOSER_TOKEN` appears in `docker/development-easy/docker-compose.yml`.** Likely an upstream rate-limit/dev token pattern; do not reuse for co-pilot secrets. Confirm not treated as a live high-privilege credential.
- **AuthZ is role/section ACL (GACL), not patient-scoped.** `src/Common/Acl/AclMain.php`, `src/Gacl/Gacl.php::acl_check()`. Closest built-in scope: facility restriction. Agent tools must enforce physician↔patient binding.
- **Twig autoescape is off globally.** `src/Common/Twig/TwigContainer.php` sets `'autoescape' => false`. New co-pilot UI Twig must escape manually (`|e`, project filters); Semgrep rules already watch for this.
- **CSRF is selective.** `src/Common/Csrf/CsrfUtils.php` exists, but only a minority of `interface/` endpoints call `verifyCsrfToken`. Prefer read-only FHIR/API for the agent; verify CSRF on any write-back path.
- **Core session cookie `Secure` defaults false.** `src/Common/Session/SessionConfigurationBuilder.php` — `forCore()` does not force `cookie_secure`; OAuth/API paths do. Prefer HTTPS-only front doors.
- **PHI at rest unencrypted by default.** `CryptoGen` / `database_encryption` / `drive_encryption` cover payments, OAuth, MFA, optional document drive — not core `patient_data` demographics/SSN.
- **SQLi largely mitigated via wrappers + custom Semgrep rules**, but legacy `sqlStatement`/`sqlQuery` concatenation patterns are explicitly tracked (`semgrep.yaml`). New agent code must use Doctrine DBAL / `QueryUtils`, never string-built SQL.
- **Uploads live in legacy `/library`** (`Document.class.php`, `upload.php`). Defer “attach document” tools until upload validation is reviewed.
- **Login throttling exists; MFA is opt-in** (`MfaUtils`). Demo `admin` on the public droplet is unlikely MFA-enforced — acceptable for Gauntlet demo, not for real PHI.

---

## 2. Performance

- **Labs = 3-join chain.** `procedure_order` (has `patient_id`) → `procedure_report` → `procedure_result`. Indexes exist; no denormalized `patient_id` on results. Prefer `ObservationLabService` / `ProcedureService` over raw joins.
- **`lists` (problems/allergies) indexed separately on `pid` and `type`**, not composite `(pid, type)` — fine at demo scale; note for hospital-scale interviews.
- **`prescriptions` indexed on `patient_id` only** — active-med filters are post-index. Consider composite `(patient_id, active)` if every agent turn hits meds.
- **No single patient-context API.** Summary UI fragments under `interface/patient_file/summary/` (`labdata_fragment.php`, `vitals_fragment.php`, `pnotes_fragment.php`, …) are independent queries — wrong shape for a 90-second pre-visit snapshot.
- **`form_encounter` is well indexed** (`pid_encounter`, `encounter_date`) — good hot path for “what’s changed since last visit.”
- **Panel queries by provider are awkward** — `patient_data` lacks a strong “my patients” index; prefer encounter/`provider_id` joins or explicit care-team tables.
- **Dev vs prod latency.** `development-easy` bind-mounts + Xdebug inflate times. Load-test baselines (project engineering reqs) must use prod-style images without Xdebug.
- **Audit SELECT logging doubles cost** when `audit_events_query=1`. Agent-heavy read traffic may flood `log` — decide whether to keep SELECT auditing for agent tokens or log agent disclosures separately.

---

## 3. Architecture

- **Clean layering:** `/src` (PSR-4 services, REST/FHIR, events) · `/library` (legacy procedural) · `/interface` (UI). New agent code belongs in `/src` only.
- **`BaseService`** (`src/Services/BaseService.php`) is the extension point for a `PatientContextService` composing `PatientService`, `EncounterService`, `AllergyIntoleranceService`, `ConditionService`, lab services, etc.
- **REST/FHIR auth is a two-stage PEP/PDP.** `AuthorizationListener`, SMART scopes (`ScopePermissionParser`), `RestApiSecurityCheckEvent` — recommended external integration surface for a sidecar agent; inject patient-bound authorization via events/scopes.
- **SMART launch** (`SMARTAuthorizationController`, patient context search) is the natural “co-pilot for the chart currently open” mechanism.
- **Events to hook UI without forking core:** `Events/Patient/Summary/Card/*`, encounter menu/button events — add “Ask Co-Pilot” cards/buttons cleanly.
- **Templates:** Twig + Smarty coexist; new UI = Twig with manual escaping.
- **DI:** `/config` + `OpenEMR\BC` bridge legacy globals. Prefer container-wired services and `QueryUtils`/DBAL for new DB access.

---

## 4. Data Quality

- **`sql/example_patient_data.sql` — demographics only** (14 patients). Insufficient for Clinical Co-Pilot demos involving meds/labs/history.
- **Path to usable data:** `openemr-cmd import-random-patients N` (Synthea → CCDA). Dev mode can disable audit during import — fine for demo, document if used.
- **Join-heavy clinical model** — `patient_data`, `form_encounter`, `lists` (type discriminator), `prescriptions`, procedure_* lab chain. Wrong `lists.type` strings → silent empty answers (agent failure mode).
- **Free-text / coded dual paths:** e.g. `prescriptions.drug` vs `rxnorm_drugcode` (both nullable) — verification/domain rules cannot assume RxNorm always present.
- **Lab `procedure_result.result` is varchar**, typed by `result_data_type` — numeric trending must branch on type.
- **UUIDs often `DEFAULT NULL`.** Example SQL patients may lack UUIDs needed for FHIR IDs — verify/backfill before FHIR-facing tools.

---

## 5. Compliance & HIPAA

- **Strengths:** audit log on by default; SELECT auditing optional but default-on; break-glass support (`BreakglassChecker`); per-row SHA3-512 checksums.
- **Limits:** no hash-chaining (deletion undetected); ATNA off by default; no built-in retention/purge schedule found; PHI columns not encrypted by default.
- **LLM / BAA gap:** OpenEMR audit categories don’t cover external model calls. Co-Pilot must log: patient id, tool sequence, redacted/minimized payload summary, correlation ID, verification outcome, provider identity — without dumping full PHI into third-party observability if avoidable.
- **Directions constraint:** demo data only; treat LLM vendors as BAA-covered (no training use). Public droplet with `admin`/`pass` is demo-only — document prominently.

---

## Live deployment notes (this project)

| Item | Status |
| --- | --- |
| Public URL | https://142.93.255.212/ |
| Host | DigitalOcean Droplet `openemr`, NYC1, 2 GB, Ubuntu 24.04 |
| Runtime | `/opt/openemr` Docker Compose (`openemr/openemr:latest` + `mariadb:11.8`) |
| Login (demo) | `admin` / `pass` |
| DB TLS (compose) | Not enabled (matches production template gap) |
| Credential rotation | Not rotated (demo defaults; intentional for Gauntlet until hardening pass) |
| Sample clinical richness | Likely thin unless Synthea import run on droplet — **todo before Early Submission demos** |

---

## Open questions / verify next

1. Run Synthea import on local + DO and confirm FHIR UUIDs populated.
2. Live ACL test: non-admin physician role — can API/UI still read arbitrary `pid`?
3. SMART `patient/*.read` token — can it fetch another patient’s resources?
4. Semgrep baseline on HEAD for SQLi/Twig rules.
5. Decide SELECT-audit strategy for agent traffic vs separate PHI-disclosure table.
6. Before any non-demo use: rotate OE/MySQL passwords, force HTTPS cookie secure, consider DB volume disk encryption.

---

## How this feeds the agent plan

| Finding | Architecture implication |
| --- | --- |
| Role ACL ≠ patient scope | Tool layer / SMART context enforces allowed `pid` |
| Empty example patients | Budget Synthea fixture generation in MVP→Early path |
| Fragmented chart reads | One `PatientContextService` + cached snapshot TTL |
| No LLM audit category | Co-Pilot observability + verification log is mandatory, not optional |
| Verification/trust requirement | Every claim cites source row/FHIR id from that context service |

Details will be expanded in `ARCHITECTURE.md` and grounded in `USERS.md` / `USER.md` use cases.
