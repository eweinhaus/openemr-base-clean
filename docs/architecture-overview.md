# Clinical Co-Pilot — Architecture Overview

**Status:** Technical decisions locked · canonical plan in [`ARCHITECTURE.md`](../ARCHITECTURE.md).

## Summary (~95 words)

Hybrid agent: physician uses an **Ask Co-Pilot** tab in OpenEMR. A **session-proxy gateway** validates the OpenEMR session, binds patient `pid` (patient picker if unbound), and calls a **LangGraph** sidecar — the browser never sends cookies to the sidecar. Chart reads are **PHP services via gateway** (pid-scoped, fail closed). Research uses **openFDA** (DailyMed fallback); drug/condition terms only; dosing only from retrieved sources; conflicts surfaced. **Hybrid SSE:** progress immediately; clinical text only after structured verify. **OpenRouter (Haiku)**; **LangSmith** redacted + disclosure log. Same 2 GB host, one worker; open-tab transcript until closed. Chart read-only; SMART/FHIR primary later.

---

## System topology

```mermaid
flowchart LR
  Physician([Physician]) --> Tab["Ask Co-Pilot tab<br/>OpenEMR iframe"]
  Tab --> GW["Session-Proxy Gateway<br/>session + pid + correlation ID"]
  GW --> LG["LangGraph sidecar<br/>single worker"]
  LG --> OR["OpenRouter<br/>Haiku"]
  LG --> Chart["Chart tools<br/>PHP services via gateway"]
  LG --> Research["Research tools<br/>openFDA → DailyMed"]
  LG --> Verify["Verify<br/>structured claims"]
  Verify --> Stream["Hybrid SSE<br/>progress early · clinical after"]
  Stream --> Tab
  LG -.-> LS["LangSmith<br/>redacted traces"]
  GW -.-> Log["PHI disclosure /<br/>verification log"]
```

## Request path (auth)

```mermaid
sequenceDiagram
  participant B as Browser
  participant OE as OpenEMR Gateway
  participant SG as LangGraph Sidecar
  participant LLM as OpenRouter

  B->>OE: Chat request (session cookie)
  OE->>OE: Validate session, bind pid (or patient picker)
  OE->>SG: Internal call {user, pid, correlation_id, message, transcript}
  Note over B,SG: Sidecar never sees browser cookies
  SG->>LLM: Agent loop (tools + verify)
  SG-->>OE: progress events, then verified clinical text
  OE-->>B: SSE + citation payloads
```

## Agent loop (UC-1 / UC-2 / UC-3)

```mermaid
flowchart TD
  Start([User message]) --> Bind{pid bound?}
  Bind -->|no| Picker[Patient picker gate]
  Bind -->|yes| Plan[LangGraph route / tools]
  Picker --> Bind
  Plan --> Tools{Tool type}
  Tools -->|chart| Chart[PHP services via gateway<br/>re-check pid]
  Tools -->|research| Res[openFDA / DailyMed<br/>drug or condition terms only]
  Chart --> Draft[Draft structured claims]
  Res --> Draft
  Draft --> Verify{Verification}
  Verify -->|ok| Out[Stream clinical text + citation links]
  Verify -->|fail| Closed[Omit / not on file / research unavailable]
  Plan -.-> Progress[Stream non-clinical progress]
  Progress --> Plan
```

## Hybrid streaming policy

```mermaid
flowchart LR
  Run[Agent running] --> P[Stream progress<br/>e.g. checking labs…]
  Run --> V[Verification clears<br/>clinical claims]
  V --> C[Stream clinical text<br/>+ citation hyperlinks]
  C --> UI[In-pane source popup<br/>on click]
```

## Locked decision snapshot

| Topic | Choice |
| --- | --- |
| Auth | Session-proxy; SMART later |
| Chart | Services-first via gateway |
| Research | openFDA → DailyMed; fail closed on dosing |
| Verify | Structured claims; cite-or-silence |
| Stream | Hybrid SSE |
| State | Open-tab transcript until closed |
| Deploy | Same 2 GB host; one worker |
| Model | Haiku everywhere (MVP) |
| No pid | Patient picker before chart tools |
