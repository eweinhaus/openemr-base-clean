# Architecture Tech Primer — Clinical Co-Pilot

**Purpose:** Learn the relevant technologies and tradeoffs *before* locking remaining technical decisions for [`ARCHITECTURE.md`](../ARCHITECTURE.md).  
**Audience:** Software engineers new to LangGraph / OpenRouter / LangSmith / EHR agent patterns.  
**Product inputs already locked:** see [Locked product / UX decisions](#locked-product--ux-decisions) below and [`USERS.md`](../USERS.md).

This is a study guide, not the architecture doc. After you work through it, you should be able to choose auth, research sources, verification placement, and gateway contracts with intent.

**NotebookLM / podcast pack:** narrative sources + a 30-minute Audio Overview prompt live in [`docs/notebooklm/`](./notebooklm/README.md).

---

## Locked product / UX decisions

| Decision | Choice |
| --- | --- |
| UI surface | First-class OpenEMR **tab page** (same shell pattern as Calendar / Messages / Dashboard) — not a floating widget |
| Chat start | **Empty chat** for MVP; optional auto-brief / starter buttons later |
| Citations | Clinical facts that need a source are **hyperlinks**; click opens an **in-pane popup** with the exact source; **do not leave the chat tab** |
| Uncertainty | Extremely explicit when unsure / missing data; **prefer silence or “not on file” over a plausible guess** (anti-hallucination over completeness) |
| Streaming | **Stream tokens** (and preferably progressive stages) — physician has ~30–90s |
| Verbosity | **Concise by default** — short answers; drill-down via follow-ups, not walls of text |

**Technical decisions are locked** in [`ARCHITECTURE.md`](../ARCHITECTURE.md). This primer remains useful as a study guide for interview defense.

---

## How OpenEMR’s UI shell works (what “match Calendar/Messages” means)

OpenEMR is **not** a classic multi-frame `left_nav` app anymore. After login:

```
Login → interface/main/main_screen.php
     → interface/main/tabs/main.php   (shell: navbar + tab bar + iframe host)
          └─ each menu item opens a named iframe tab
```

| Concept | Meaning |
| --- | --- |
| **Shell** | `interface/main/tabs/main.php` + Knockout menu |
| **Tab** | One iframe; `target` id like `cal`, `msg`, `pat` |
| **Menu JSON** | `interface/main/tabs/menu/menus/standard.json` |
| **Page chrome** | Often `OemrUI` heading (`src/OeUI/OemrUI.php`) + Bootstrap 4 + jQuery |
| **ACL** | Menu `acl_req` + page-level `AclMain` checks |

**Implication for Ask Co-Pilot:** add a menu entry + PHP page under `interface/` that loads in its own tab (e.g. `target: "cop"`). Prefer **Calendar/Messages-style** top-level item (`requirement: 0`) so it works without a patient selected — then bind to session `pid` when present, and refuse chart tools when missing. (Dashboard-style `requirement: 1` is an alternative if you want the menu disabled until a patient is selected.)

Details of Calendar / Messages / Dashboard navigation and file paths: see the companion section in session notes or re-read this repo’s menu JSON; summary is also in Memory Bank updates after this primer lands.

### Suggested implementation sketch (UI only)

1. `interface/main/copilot/index.php` — session via `globals.php`, `Header::setupHeader`, OemrUI heading “Ask Co-Pilot”, clear `<title>`.
2. Menu object in `standard.json` (and other role menus if needed).
3. Optional: `default_open_tabs` list option; optional Alt-hotkey in `shortcuts.js`.
4. Chat UI inside the iframe: empty composer; stream replies; citation links → modal/popover with source payload (stay in tab).

Patient binding: read session `pid` (and/or `top.getSessionValue('pid')`). Tools must still enforce allowed `pid` server-side.

---

## Learning path (recommended order)

Work top-to-bottom. Each block lists *what to learn*, *why it matters here*, and *enough to decide*.

### 1. Your problem shape (30–45 min)

Re-read:

- [`docs/directions.md`](./directions.md) — Hard Problems + Agent Requirements (verification, observability, eval)
- [`AUDIT.md`](../AUDIT.md) — especially authZ ≠ patient scope, empty demo data, no LLM audit category
- [`USERS.md`](../USERS.md) — UC-1 / UC-2 / UC-3

**Decision lens:** every technical choice must serve speed + trust for one PCP, one open patient, three jobs.

### 2. Hybrid EHR agent topology (45–60 min)

**Idea:** OpenEMR owns login, menu, patient session, and a **thin gateway**. A **sidecar** owns the agent loop (LLM + tools + verification).

```
Physician → Ask Co-Pilot tab (OpenEMR iframe)
         → Gateway (auth session, bind pid, correlation ID)
         → LangGraph sidecar
              ├─ Chart tools (via gateway / FHIR / services)
              ├─ Research tools (no PHI in queries)
              └─ Verification → stream cited, concise answer
```

**Why hybrid (already preferred in audit):** LangGraph + research + streaming fit poorly as pure PHP; interviewers also recognize this stack. Pure-PHP agent is possible but weaker for UC-3 research + modern agent tooling.

**Tradeoffs to internalize:**

| Approach | Pros | Cons |
| --- | --- | --- |
| **Hybrid (OpenEMR + LangGraph)** | Best tool ecosystem; clear EHR integration story | Two processes; auth across boundary; 2 GB RAM pressure |
| **PHP-only agent** | Single deploy; session trivial | Weak agent/research/streaming ecosystem; harder eval/obs |
| **External SaaS agent** | Fast demo | Weak “embedded in OpenEMR” story; more PHI surface |

**Decide later:** exact process boundaries and compose services on the droplet.

### 3. LangGraph (core agent framework) — 1–2 hours

**What it is:** A library for building **stateful multi-step agents** as graphs (nodes = steps, edges = control flow). Better than a single “chat completion with tools” when you need: tool loops, a dedicated **verify** step, branching on missing data, etc.

**Official docs (start here):**

1. [LangGraph overview](https://langchain-ai.github.io/langgraph/) — what a graph is  
2. [Quickstart](https://langchain-ai.github.io/langgraph/tutorials/introduction/) — build a tiny graph  
3. [Tool calling](https://langchain-ai.github.io/langgraph/how-tos/tool-calling/) — how tools attach  
4. [Streaming](https://langchain-ai.github.io/langgraph/how-tos/streaming/) — token + event streams (maps to your UX)  
5. [Persistence / threads](https://langchain-ai.github.io/langgraph/concepts/persistence/) — multi-turn conversation state  

**Mental model for Co-Pilot (illustrative, not final):**

```
START → route_intent (brief / labs / meds / refuse)
     → gather_tools (chart ± research)
     → draft_answer (concise)
     → verify (citations + fail-closed)
     → STREAM to UI
```

**Tradeoffs:**

| Choice | Notes |
| --- | --- |
| LangGraph vs raw LangChain agent | Graph makes verification/refusal nodes explicit — better for liability story |
| LangGraph vs custom FSM in PHP | Custom is simpler ops; worse streaming/tools/evals story |
| Python vs JS LangGraph | Python is the mature path; stick with Python unless you have a strong Node preference |

**Practice exercise:** Build a local graph with two fake tools (`get_meds`, `web_dose`) and a `verify` node that drops claims without `source_id`.

### 4. OpenRouter (LLM gateway) — 30–45 min

**What it is:** One API to many models (Anthropic Haiku, etc.). You call OpenRouter; it routes to the provider.

**Docs:**

- [OpenRouter quickstart](https://openrouter.ai/docs/quickstart)
- [Streaming](https://openrouter.ai/docs/api/reference/streaming)
- [Models](https://openrouter.ai/models) — compare Haiku vs Sonnet on cost/latency

**Why we chose it:** Swap models without rewriting the agent; start **Haiku** for latency/cost; treat as BAA-covered / no-training for **demo data only** (case-study posture).

**Tradeoffs:**

| Topic | Consideration |
| --- | --- |
| Haiku vs larger models | Haiku = speed/cost; may need stricter prompts + verification. Larger = smarter, slower, pricier |
| Direct Anthropic API vs OpenRouter | Direct = fewer hops; OpenRouter = flexibility + one key for experiments |
| PHI | Minimize payload; never send more chart than the turn needs; demo data only on public droplet |

### 5. LangSmith (observability) — 30–45 min

**What it is:** Tracing / datasets / evals for LangChain/LangGraph runs.

**Docs:**

- [LangSmith overview](https://docs.smith.langchain.com/)
- [Trace LangGraph](https://docs.smith.langchain.com/observability/how_to_guides/trace_with_langgraph)
- [Evaluation concepts](https://docs.smith.langchain.com/evaluation/concepts)

**Case-study requirements it helps satisfy:** request traces, step latency, tool failures, token/cost; dashboards; room for evals. Directions also require **correlation IDs** in *your* logs across OpenEMR ↔ sidecar — LangSmith does not replace that.

**Critical tradeoff:** **Redact PHI** from traces. Prefer: tool names, timings, verification pass/fail, hashed/truncated ids — not full notes. Keep a separate **app disclosure/verification log** for “what PHI left the EHR boundary.”

### 6. Streaming to a browser chat — 45–60 min

You want tokens early inside an OpenEMR iframe.

**Concepts to learn:**

| Mechanism | Use |
| --- | --- |
| **SSE (Server-Sent Events)** | One-way server→client stream; common for LLM tokens; simple |
| **WebSocket** | Bidirectional; more complex; useful if you need cancel + client events heavily |
| **Fetch + ReadableStream** | Browser consumes SSE/stream without a special client lib |

**Suggested default to evaluate:** Gateway exposes `POST /copilot/chat` that returns **SSE**; events like `token`, `tool_start`, `citation`, `done`, `error`. UI appends tokens; on `citation` registers hyperlink targets for the popup.

**Tradeoffs:**

| Approach | Pros | Cons |
| --- | --- | --- |
| Stream raw model tokens | Feels fastest | May show text later **revoked** by verification |
| Stream only after verify | Safer | Feels slower; fights 90s budget |
| **Hybrid stream** (recommended to consider) | Stream “status” (“pulling labs…”) immediately; stream answer tokens only from **post-verify** text, or stream draft then replace if verify fails | Slightly more UI complexity |

Given your liability stance, prefer **not** showing unverified clinical claims. Streaming **progress** + **verified** answer tokens is the conservative design.

### 7. Authorization across the OpenEMR ↔ sidecar boundary — 1 hour

OpenEMR GACL answers “can this role open medical records?” — **not** “can this user access *this* `pid`?” Your tools must enforce patient scope.

**Patterns to compare:**

| Pattern | How it works | Pros | Cons |
| --- | --- | --- |
| **A. Session proxy gateway** | Browser talks only to OpenEMR PHP; PHP checks session + pid; PHP calls sidecar with an internal secret + `{user, pid, correlation_id}` | Pid binding stays in EHR; sidecar never sees cookies | Sidecar must trust gateway; all chart fetches may proxy through PHP or use short-lived tickets |
| **B. SMART on FHIR** | OAuth patient-scoped token; sidecar calls FHIR with token | Industry-standard; scopes | Heavier setup; still re-check pid; AUDIT asks you to verify whether tokens can be abused cross-patient |
| **C. Sidecar reads DB** | Sidecar gets DB creds | Fast | Violates layering; weak audit story; easy to get wrong |

**Recommended study order:** understand A deeply first (matches “thin gateway”); skim OpenEMR [SMART docs](../Documentation/api/SMART_ON_FHIR.md) so you can defend why you did or didn’t pick B for MVP.

**Invariant (non-negotiable):** every chart tool fails closed if requested `pid` ≠ bound session/token patient.

### 8. Chart access: FHIR vs services vs SQL — 45 min

| Path | When |
| --- | --- |
| **OpenEMR services** (`/src/...`) | Best for `PatientContextService` snapshot inside PHP |
| **FHIR / REST** | Natural for sidecar if tokens/gateway expose them; citations can use FHIR ids |
| **Raw SQL** | Avoid in new agent paths |

Labs join path (from audit): `procedure_order → procedure_report → procedure_result`. Meds: `prescriptions` (free text ± RxNorm). Problems/allergies: `lists` by `type`.

### 9. Verification & anti-hallucination — 1 hour

Directions require: **source attribution** + **domain constraints**. Your UX requires: hyperlink → popup with exact source; extreme honesty when unsure.

**Design questions to answer in ARCHITECTURE.md:**

1. What counts as a “fact” that needs a link? (labs, meds, conditions, note quotes, research claims — almost certainly all of these)
2. Where does verification run? (LangGraph node after draft; tool outputs already structured with ids)
3. What happens on failure? (strip claim / refuse turn / ask clarifying question)
4. How do research claims differ from chart claims? (URL/title/section vs FHIR id / table+pk / note span)

**Patterns:**

- **Structured generation:** model must emit JSON like `{ "claims": [ { "text", "source_type", "source_id", "span?" } ] }` then render to concise prose + links  
- **Cite-or-silence:** verifier drops any sentence without a resolvable source  
- **Two evidence classes:** chart vs research — never let model memory fill dosing gaps  

**Popup payload sketch:** `{ source_type, title, retrieved_at, locator (fhir id / table+pk / note_id+span / url), excerpt }` — rendered in a Bootstrap modal inside the Co-Pilot iframe.

### 10. External research tools (UC-3) — 45 min

Outbound queries: **drug/condition terms only** — never name/DOB/MRN/identifying note text.

**Options to compare before choosing:**

| Source class | Examples (investigate current APIs) | Fit |
| --- | --- | --- |
| Open drug-label APIs | openFDA drug labels, DailyMed | Strong for “what does the label say” |
| Interaction checkers | Various open/commercial APIs | Need license + trust review |
| Guided web search | Search API + allowlisted domains | Flexible; noisier; needs stricter verify |
| Static monograph corpus | Embed a small vetted set | Predictable; narrow coverage |

**Decision criteria:** license, rate limits, whether results are citable, latency, and how easy it is to **fail closed** when nothing relevant is retrieved.

### 11. Concision, latency, and the 90-second budget — 20 min

Product rules to encode in prompts **and** architecture:

- Default max length (e.g. brief ≤ ~8–12 short lines; labs = direct answer; meds = short bullets + sources)
- Prefer tool fan-out in parallel where safe
- Timeouts on research; return chart facts with “research incomplete” rather than hanging
- Progressive UI status without dumping unverified clinical prose

### 12. Deploy realities (DigitalOcean 2 GB) — 20 min

Live stack today: OpenEMR + MariaDB on a **2 GB** droplet. Adding LangGraph + LLM traffic will pressure RAM.

**Tradeoffs:** swap (already used), smaller models, single worker, optional later split host. Document `/health` vs `/ready` (OpenEMR, LLM, LangSmith reachability).

### 13. Case-study engineering extras (skim now, deep-dive at Early)

From [`docs/directions.md`](./directions.md) Engineering Requirements — know they exist so architecture leaves room:

- Correlation IDs across services  
- Strict tool schemas (Pydantic / Zod)  
- LangSmith (or equiv) dashboard + alerts  
- `/health` and `/ready`  
- Eval suite with boundaries (cross-pid, empty chart, missing RxNorm, no research hit)  
- Load tests 10 / 50 concurrent  
- Runnable API collection (Bruno/Postman)  

You do not implement these in Stage 5 — but `ARCHITECTURE.md` should not paint you into a corner that makes them impossible.

---

## Decision checklist (complete before / while writing ARCHITECTURE.md)

### Already decided (product/UX)

- [x] Top-level Ask Co-Pilot tab (Calendar/Messages-like shell)
- [x] Empty chat start
- [x] Citation hyperlinks → in-pane source popup
- [x] Fail closed / prefer omission over hallucination
- [x] Streaming (with care about unverified text)
- [x] Concise responses

### Decide next (technical) — locked in ARCHITECTURE.md

- [x] **Gateway auth** — session-proxy (SMART later)
- [x] **Chart path** — PHP services via gateway (FHIR phase 2)
- [x] **Research** — openFDA → DailyMed; fail closed on dosing
- [x] **Verification** — structured claims; cite-or-silence
- [x] **Stream policy** — hybrid SSE (progress early; clinical after verify)
- [x] **Sidecar** — Python + LangGraph; single worker
- [x] **Compose/deploy** — same 2 GB host; document concurrency limits
- [x] **Conversation persistence** — open-tab transcript until closed

### Explicitly deferrable

- Exact tool function names/list  
- Auto-brief / starter buttons  
- Full eval case catalog  
- Multi-role auth  

---

## Suggested weekend study schedule

| Block | Time | Focus |
| --- | --- | --- |
| 1 | 1 h | Directions + AUDIT + USERS + this primer’s OpenEMR UI section |
| 2 | 2 h | LangGraph quickstart + tool calling + streaming how-to |
| 3 | 1 h | OpenRouter streaming hello-world + Haiku latency feel |
| 4 | 1 h | LangSmith trace a toy graph; practice redaction mindset |
| 5 | 1.5 h | Auth patterns A vs B; sketch sequence diagram on paper |
| 6 | 1 h | Pick research source candidates; note licenses |
| 7 | 1 h | Draft decision answers for the checklist → then write ARCHITECTURE.md |

---

## Glossary (quick)

| Term | Meaning here |
| --- | --- |
| **Gateway** | Thin OpenEMR-side API that authenticates the physician, binds `pid`, assigns correlation ID, talks to sidecar |
| **Sidecar** | Separate agent process (LangGraph) beside OpenEMR |
| **Tool** | Function the model can call (get labs, get meds, research label, …) |
| **Verification** | Gate that drops or rewrites claims lacking resolvable sources / violating constraints |
| **Citation popup** | In-tab modal showing the exact chart or research excerpt for a linked claim |
| **Fail closed** | On doubt or auth failure → refuse or omit, don’t guess |
| **Correlation ID** | UUID per user ask, present in every log/tool/LLM call for that ask |

---

## After you finish this primer

1. Technical checklist is **locked** — see [`ARCHITECTURE.md`](../ARCHITECTURE.md).  
2. Use this primer to rehearse *why* those choices (interview defense).  
3. Next build step: Synthea + implement the roadmap in `ARCHITECTURE.md`.  
4. Keep `memory-bank/` aligned via `/update-memory-bank` after major shifts.
