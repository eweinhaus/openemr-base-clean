# Clinical Co-Pilot — Architecture

**Hard gate:** Stage 5 AI integration plan.  
**Traces to:** [`USERS.md`](./USERS.md) (UC-1 / UC-2 / UC-3).  
**Inputs:** [`AUDIT.md`](./AUDIT.md), UX locks, technical decisions locked 2026-07-20.  
**Companion diagrams:** [`docs/architecture-overview.md`](./docs/architecture-overview.md).

---

## Summary (~500 words)

Clinical Co-Pilot is a **hybrid** agent embedded in OpenEMR for a clinic / primary care physician with roughly **30–90 seconds** between rooms. The physician opens a first-class **Ask Co-Pilot** tab (same iframe-tab shell as Calendar / Messages). Chat starts empty; answers are concise; follow-ups deepen the same thread. Every clinical claim the UI shows is cited (hyperlink → in-pane source popup). The chart stays **read-only**; meds framing is **decision support**, not prescribing.

**Topology.** The browser talks only to OpenEMR. A **session-proxy gateway** validates the existing OpenEMR session, binds patient `pid`, assigns a **correlation ID**, and calls a **LangGraph** sidecar with an internal credential — the sidecar never sees browser cookies. The sidecar owns the agent loop: chart tools, research tools, draft, verification, and streaming events. **OpenRouter (Haiku)** is the LLM; **LangSmith** holds redacted traces; the app still owns a PHI disclosure / verification log. We chose hybrid over PHP-only so verification, research, and streaming stay first-class, while still demonstrating real EHR session binding.

**AuthZ.** OpenEMR GACL is role/section, not panel-scoped ([`AUDIT.md`](./AUDIT.md)). Co-Pilot therefore enforces allowed `pid` in the **tool layer** on every chart call (fail closed). No patient selected → patient-picker gate before chart work. Client- or model-supplied patient ids are ignored. SMART on FHIR is a documented later migration, not MVP runtime.

**Chart path.** MVP reads chart via OpenEMR **PHP services** (`PatientContextService` snapshot for UC-1; fine-grained lab/med/note tools for follow-ups), always proxied through the gateway. FHIR IDs may appear in citations when present; FHIR-as-primary and SMART tokens are phase-2 talk track for interview depth without dual-path complexity now.

**Jobs.** **UC-1** synthesizes why-here, conditions, last visit, selective notes, and high-signal structured pointers. **UC-2** answers recent labs / abnormals with chart locators. **UC-3** combines chart meds/allergies/conditions with **openFDA** labels (DailyMed fallback); outbound queries are **drug/condition terms only** (no PHI). Dosing / interaction claims require retrieved sources — otherwise refuse that claim while still returning cited chart facts. **Label conflict UX is deferred for MVP** (openFDA primary → DailyMed fallback on miss/timeout/empty dose — never invent a dose; dual-source conflict surface is post-MVP). Missing RxNorm → uncertain drug identity; no invented codes; no dosing research until identity is clear.

**Verification & streaming.** The model emits structured claim/source pairs; a **verify** node drops anything without a resolvable locator (table+pk and/or FHIR id; note id+span; research URL/title/section) and applies domain checks (allergy contradiction, missing RxNorm uncertainty). **Hybrid SSE:** stream non-clinical progress immediately; stream clinical text only after verify clears it. We reject “show unverified claims with a warning” — warnings get skimmed under time pressure.

**State & deploy.** Typical thread is one brief + 1–2 follow-ups; transcript is held for the open Co-Pilot tab until closed (resend / session-held — no durable DB or pre-ask cache for MVP). Compose adds one Python sidecar **worker on the same 2 GB droplet**; concurrency limits are documented honestly for a one-physician interview demo. Pre-ask caching, multi-worker scale, interaction APIs, and production hardening are deferred.

**Tradeoff north star.** Optimize for a **defensible SWE interview demo**: trust and clear boundaries beat rubric completeness and premature scale. Prefer omit / “not on file” / “research unavailable” over a plausible unsupported sentence.

---

## 1. Goals and non-goals

| In scope (MVP) | Out of scope (MVP) |
| --- | --- |
| UC-1 / UC-2 / UC-3 from [`USERS.md`](./USERS.md) | Multi-role ACL (nurse/resident panels) |
| Session-proxy + tool-layer pid enforcement | SMART runtime; sidecar↔browser direct |
| Services-first chart tools via gateway | Raw DB access from sidecar; FHIR dual path |
| openFDA + DailyMed research, fail closed on dosing | Autonomous prescribing / chart write-back |
| Structured verify + hybrid SSE | Pre-ask caching; multi-worker HA |
| LangSmith (redacted) + correlation IDs + disclosure log | Production DB TLS / MFA / ATNA before demo value |

**Optimization target:** technical job-interview demo (trust story + working agent), not hospital-scale concurrency.

---

## 2. System topology

```
Physician → Ask Co-Pilot tab (OpenEMR iframe)
         → Session-proxy gateway (session, pid, correlation ID)
         → LangGraph sidecar (single worker)
              ├─ Chart tools → gateway → PHP services (re-check pid)
              ├─ Research tools → openFDA / DailyMed (no PHI)
              ├─ OpenRouter (Haiku)
              └─ Verify → SSE: progress early, clinical after clear
         ╌╌ LangSmith (redacted) · app disclosure/verification log
```

| Component | Owns |
| --- | --- |
| Ask Co-Pilot UI | Chat, SSE consume, citation popups, patient picker |
| Gateway (OpenEMR `/src` + `interface/`) | Session auth, pid bind, correlation ID, SSE to browser, chart proxy, disclosure log writes |
| LangGraph sidecar | Graph, tools, LLM calls, verification, progress/clinical event emit |
| OpenRouter | Model inference (Haiku) |
| LangSmith | Traces / later evals (redacted) |

Diagrams: [`docs/architecture-overview.md`](./docs/architecture-overview.md).

---

## 3. Capability map (must trace to USERS.md)

| Capability | Use case | Tools (sketch — names deferred) | Verify requirement |
| --- | --- | --- | --- |
| Pre-visit brief | UC-1 | `PatientContextService` snapshot (+ selective notes) | Every fact → chart locator; prefer structured over notes |
| Labs Q&A | UC-2 | Labs drill-down (order→report→result path) | Value/date/abnormal flags → result locator |
| Med decision-support | UC-3 | Meds/allergies/conditions + openFDA/DailyMed | Chart claims cited; dosing/interactions only from retrieved label; conflict UX deferred (fallback-only) |
| Multi-turn follow-up | UC-1/2/3 | Same tools; transcript in open tab | Pid still bound; no silent patient switch |
| Refuse unbound / wrong pid | All | N/A | Fail closed before chart tools |

---

## 4. Locked technical decisions

### 4.1 Authentication — session-proxy gateway

Browser → OpenEMR only. Gateway validates cookie/session, binds `pid`, calls sidecar with `{user, pid, correlation_id, message, transcript?}` plus internal service secret.

**Why:** Patient binding already lives in OpenEMR session; smaller CORS/spoof surface; fits “thin gateway” interview story.  
**Tradeoff:** Sidecar trusts the gateway; PHP is a hop.  
**Later:** SMART patient-scoped tokens when FHIR citations / portable scopes become the bottleneck — tool-layer pid checks remain either way.

### 4.2 Chart access — services-first, gateway-only hop

- Snapshot + drill-downs via PHP services in `/src` (extend `BaseService`).
- Sidecar does **not** call MariaDB and does **not** call OpenEMR with a second long-lived chart credential in MVP — chart reads go **gateway → services**.
- Citations: table+pk always; FHIR UUID when available (Synthea path should populate UUIDs).

**Why:** Fastest path to a shaped UC-1 brief for demo; one security boundary.  
**Tradeoff:** Less “pure FHIR” narrative; we explain FHIR/SMART as phase 2.

### 4.3 Research — openFDA primary, DailyMed fallback

- Outbound query = drug and/or condition terms only.
- Dosing / interaction / label-backed options: cite URL/title/section; model memory is not a source.
- Miss → return cited chart context + explicit “no retrieved source for dosing/interactions.”
- **MVP:** openFDA primary → DailyMed fallback only (no dual-fetch compare). Dual-source conflict surface (state both; physician decides) is deferred post-MVP.
- No separate interaction API in MVP.

### 4.4 Verification — structured claims, cite-or-silence

Illustrative graph:

```
START → bind/refuse → route (brief|labs|meds)
      → gather tools (parallel where safe)
      → draft structured claims
      → verify (resolve sources + domain constraints)
      → emit clinical SSE + citation payloads
```

**Claim shape (contract sketch):**

```json
{
  "claims": [
    {
      "text": "Creatinine 1.4 mg/dL on 2026-06-01",
      "source_type": "chart",
      "locator": { "table": "procedure_result", "id": "…" },
      "excerpt": "…"
    }
  ]
}
```

Domain constraints (MVP): allergy contradiction flags; missing RxNorm → uncertain identity (no invented codes; no dosing research); no staging/disease severity invented from a single lab; research claims require retrieved locator.

**UI:** clinical hyperlinks → in-pane popup `{ source_type, title, retrieved_at, locator, excerpt }`.

### 4.5 Streaming — hybrid SSE

| Event (sketch) | When | Content |
| --- | --- | --- |
| `progress` | Immediately / during tools | Non-clinical status (“Pulling labs…”) |
| `clinical` | After verify | Verified prose + link markers |
| `citation` | With/after clinical | Popup payloads |
| `done` / `error` | End | Terminal |

Transport: gateway `POST` → **SSE** to the Co-Pilot iframe. No unverified clinical tokens to the screen.

### 4.6 Conversation state — open-tab transcript

- Typical: brief + 1–2 follow-ups; may continue same day until the tab is closed.
- MVP: hold/resend transcript for the open session; no LangGraph durable checkpointer DB and no OpenEMR chat table yet.
- Patient switch: do not silently continue prior pid context; re-bind or reset thread when pid changes.

### 4.7 Deploy — same host, single worker

- Compose: existing OpenEMR + MariaDB + **one** LangGraph worker on the 2 GB DO droplet (swap already in play).
- `/health`: process up; `/ready`: can reach OpenEMR gateway path + OpenRouter (research optional degraded).
- Honest limit: one concurrent demo physician; scale-out is a later host split.

### 4.8 Model tiering — Haiku everywhere (MVP)

One model for route/draft/verify prompts. Temperature near zero for factual turns. Stronger models later if UC-3 quality demands it — **never** as a substitute for verification.

### 4.9 Unbound patient — picker gate

Tab may open without `pid` (Calendar/Messages-style). Before chart tools: **patient picker** popup. Wrong/spoofed pid at tool layer → refuse.

---

## 5. Hard problems (how architecture answers them)

| Hard problem | Approach |
| --- | --- |
| Authorization | Session-proxy + tool-layer pid; picker; fail closed |
| Verification & trust | Structured claims; cite-or-silence; domain checks; hybrid stream |
| Speed vs completeness | Concise defaults; progress SSE; services snapshot; research timeout → chart-only + refuse dosing |
| HIPAA / PHI | Demo data; minimize payloads; no PHI in research; redacted LangSmith; disclosure log; BAA/no-training posture |
| Failure modes | Tool errors surfaced; research miss partial; missing RxNorm explicit; no silent guess |

---

## 6. Observability & evaluation (plan, not implemented yet)

**Observability**

- Correlation ID on every gateway ↔ sidecar ↔ tool ↔ LLM hop.
- LangSmith: graph steps, latencies, tool failures, token/cost — **redact** note bodies / identifiers.
- App log: disclosure + verification pass/fail keyed by correlation ID.

**Eval categories (reserve now)**

- Empty / sparse chart  
- Cross-pid / unbound patient  
- Missing RxNorm (seed one free-text med if Synthea import is fully coded)  
- Research miss (label conflict surface deferred)  
- Ambiguous lab name  
- Happy paths: UC-1 brief, UC-2 creatinine, UC-3 label-backed question  

---

## 7. Implementation roadmap

1. Ask Co-Pilot tab + empty chat chrome + patient picker  
2. Gateway SSE endpoint + correlation ID + disclosure log stub  
3. Sidecar skeleton graph (route → tools → draft → verify) + Haiku via OpenRouter  
4. `PatientContextService` + lab/med/note tools (pid checks)  
5. openFDA tool + DailyMed fallback + miss behavior (conflict UX deferred)  
6. Citation popup wiring; hybrid stream events  
7. LangSmith redacted traces; `/health` + `/ready`  
8. Synthea ~5–10 patients local + DO; smoke demo script  
9. Eval suite + interview demo narrative (incl. phase-2 SMART/FHIR)

Exact tool schemas, auto-brief, and production hardening remain deferred.

---

## 8. Known limitations (defend honestly)

- Single-worker 2 GB host will not support meaningful concurrent load.  
- Services-first citations are less portable than pure FHIR until phase 2.  
- Label APIs are not a full clinical interaction engine.  
- Session-proxy trusts gateway configuration — SMART later strengthens portable scopes.  
- Twig `autoescape` off in OpenEMR — Co-Pilot UI must escape manually ([`AUDIT.md`](./AUDIT.md)).  
- Demo credentials / self-signed HTTPS / no DB TLS remain documented Gauntlet posture.

---

## 9. Decision log (quick reference)

| Topic | Choice |
| --- | --- |
| Topology | Hybrid OpenEMR gateway + LangGraph sidecar |
| Auth | Session-proxy; SMART later |
| Chart | PHP services via gateway; FHIR phase 2 |
| Research | openFDA → DailyMed; no PHI; fail closed on dosing |
| Verify | Structured claims; cite-or-silence; domain checks |
| Stream | Hybrid SSE (progress early; clinical after verify) |
| State | Open-tab transcript until closed |
| Deploy | Same droplet; one worker |
| Model | Haiku via OpenRouter |
| No pid | Patient picker before chart tools |
| UX | Tab; empty start; citation popups; concise; omit > guess |
