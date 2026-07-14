# AiraCare — Foundry Care Orchestrator Design (PoC)

Detailed design for the **cloud side** of AiraCare — the **Foundry Care Orchestrator**
that the edge talks to over A2A. Flagship scenario **Nighttime Wandering**.

See also: [architecture.md](architecture.md) · [edge-design.md](edge-design.md) ·
[demo-scenarios.md](demo-scenarios.md) · [demo-runbook.md](demo-runbook.md).

The edge is feature-complete and **freezes the contract** (`airacare.grade` →
`CloudDecision`). The Foundry side is therefore not greenfield: it is a **drop-in
replacement for the local `LocalGradingEngine` stub** that speaks the same A2A wire
protocol but adds real depth (personalization, knowledge grounding, autonomous
escalation, reporting).

---

## 1. Locked decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Runtime | **Azure AI Foundry Agent Service** — Care Orchestrator as a **Hosted Agent** |
| 2 | Multi-agent | **Foundry Connected Agents** for the deliberate (T2) orchestration |
| 3 | Latency strategy | **Two-tier**: synchronous **reflex grade** (< 5 s) + asynchronous **deliberate** reasoning/escalation |
| 4 | Knowledge | **Azure AI Search** RAG over care guidelines / clinical protocols |
| 5 | Models | GPT-4o-mini for reflex + most sub-agents; GPT-4o for hard reasoning |
| 6 | Data (see §7) | **Demo/MVP = local store (SQLite/in-memory)**; **production target = Cosmos DB (operational) mirrored into Microsoft Fabric/OneLake for analytics + Power BI** |
| 7 | Notifications | **Cloud-owned** dispatch + timed escalation ladder (edge only executes `edge_directive`) |
| 8 | Drop-in | Same A2A `airacare.grade` contract → edge switches via `cloud.mode: foundry` only |
| 9 | MVP scope | Flagship **wander** grade + escalation ladder + one knowledge-grounded advice + family briefing |

**Constraint that drives everything:** the edge `A2AClient` timeout is **5 s**; on any
timeout/failure the edge goes **offline** and self-handles. So the Foundry agent must
return a **safe grade within ~5 s** no matter how deep the reasoning goes.

## 2. Design principles

- **Reflex before reflection.** A fast, safe grade is returned synchronously (T1); the
  expensive multi-agent reasoning, knowledge grounding, escalation, and reporting run
  **after** the response as a long-running, autonomous workflow (T2). The edge never
  waits on deliberation.
- **Drop-in, not rebuild.** The Foundry agent honors the exact `airacare.grade` →
  `CloudDecision` contract the edge already speaks. Switching from the local stub is a
  config change (`cloud.mode: foundry`), never an edge code change.
- **The cloud owns notifications & escalation.** The cloud has the contact directory,
  ack tracking, and escalation timers. The edge only ever acts on
  `edge_directive.voice_prompt` (the L1 loop-back) and its own **offline** local alerts.
- **Privacy boundary is inherited and absolute.** Only `DailyLivingEvent` crosses;
  everything the cloud stores is **derived** from it. No raw audio/video/point-cloud is
  persisted anywhere, edge or cloud.
- **Cheap fast-path, expensive only when needed.** Mirrors the edge's own pattern: the
  reflex grade is policy/light-model; the LLM + RAG multi-agent deliberation only fires
  on real events (the edge already filters ~99% of no-event data) — token-frugal.

## 3. The frozen contract (inherited from the edge)

```jsonc
// Inbound — A2A / JSON-RPC 2.0
{ "jsonrpc":"2.0", "id":1, "method":"airacare.grade",
  "params": { "event": DailyLivingEvent } }

// DailyLivingEvent (the ONLY thing that crosses the privacy boundary)
DailyLivingEvent {
  type: "fall|wander|med|meal|routine", confidence, timestamp, patient_id,
  features: [float],            // privacy-scrubbed; never raw audio
  baseline_deviation, edge_action_taken: "none|prompted|local_alert",
  context: { time_of_day, door_open, response, ... }
}

// Outbound — CloudDecision (drives edge action)
CloudDecision {
  grade: "L0|L1|L2|L3",
  reason: "explainable why",
  actions: [ { channel:"log|family|community|emergency", message, target } ],  // audit of what the cloud is doing
  edge_directive: { voice_prompt: string|null }   // the ONLY field the edge acts on directly
}
```

## 4. Two-tier decision architecture

| Tier | When | What | Latency budget |
|---|---|---|---|
| **T1 — Reflex grade** (sync) | every event | patient-state-aware policy → `CloudDecision` (grade + reason + intended actions). Reads hot patient state (baseline, disease stage). Guarantees a safe answer to the edge. | **< 5 s** (target < 1 s) |
| **T2 — Deliberate** (async, long-running) | after the sync reply | Connected Agents: knowledge-ground the advice, dispatch multi-channel notifications **with a timed escalation ladder**, update baseline/trend, generate briefings. May *upgrade* and push a follow-up on a separate caregiver channel. | seconds–minutes, autonomous |

This split is also the answer to the judges' *"long-running autonomous / token-hungry?"*
questions: the autonomous escalation + trend work lives in T2; tokens are spent only on
real events, and heavy analytics is offloaded to compute (not the LLM).

## 5. Architecture on Azure AI Foundry

```
                 A2A endpoint  (airacare.grade)
                        │  DailyLivingEvent
                        ▼
      ┌──────────── Care Orchestrator (Foundry Hosted Agent) ─────────────┐
      │  T1 Reflex Grader ───────────────► returns CloudDecision (<5s) ────┼──► edge
      │        │  (reads patient state + grading policy)                    │
      │        └─ enqueues async job ▼                                      │
      │  T2 Connected Agents (orchestrated):                               │
      │   • Risk-Reasoning agent   fusion × disease-stage × baseline drift  │
      │   • Knowledge agent   ───► Azure AI Search (care-guideline RAG)     │
      │   • Escalation agent  ───► timed ladder: family→community→emergency │
      │   • Cognitive-Trend agent ─► batch voice-biomarker modeling         │
      │   • Briefing agent    ───► family daily / clinician monthly report  │
      │                                                                    │
      │  Tools: NotifyTool(push/SMS) · GeofenceTool · EscalationTimer       │
      │  Memory: Patient State Store (baseline, disease-stage, history)     │
      └────────────────────────────────────────────────────────────────────┘
```

## 6. Grading policy (how L0–L3 is decided)

The reflex grade combines three inputs, weighted by disease stage:

`risk = f(event.type, event.confidence, baseline_deviation, context) × disease_stage_weight`

Flagship **wander** policy (parity with the current stub, now personalized):

| Reply / context | Grade | Cloud action | Edge directive |
|---|---|---|---|
| `no_response` / `distress` | **L3** | notify family → (ladder) community → emergency | — |
| `unclear` | **L2** | notify family to check | — |
| `ok` (patient reassured) | **L1** | none (log) | `voice_prompt`: gentle guidance back to bed |
| below confidence threshold | **L0** | log only → daily briefing | — |

Disease stage tunes thresholds (e.g. a *severe*-stage patient's nighttime out-of-bed
weights higher). The **reason** string is always populated for explainability, and is
enriched by the Knowledge agent in T2.

## 7. Data & storage (decision #6 = **C**)

**Demo / MVP (build now):** the reflex grade + escalation run against a **tiny local
store** — SQLite (or in-memory) holding per-patient baseline, disease stage, and recent
event history. This keeps the 5 s reflex budget safe and adds **zero cloud
infrastructure** to the live demo.

**Production target (stated, not built for the hackathon):** split by workload and let
Fabric mirror handle analytics with no ETL:

| Data | Store | Notes |
|---|---|---|
| **Raw audio/video/point-cloud** | **nowhere** — edge RAM only, discarded after feature extraction | the privacy boundary |
| Offline event backlog | **edge disk** `.airacare_queue/` (TTL-bounded) | already built |
| **Patient State** (baseline, stage, contacts, history) | **Azure Cosmos DB**, partition = `patient_id` | single-digit-ms → protects the 5 s budget |
| Analytics / trends / longitudinal modeling | **Microsoft Fabric** (Eventhouse/KQL + Lakehouse/Delta, Spark) via **Cosmos→OneLake mirroring** | zero-copy, no ETL |
| Family daily / clinician monthly reports | **Power BI** on OneLake | native dashboards |
| Condition-based alert triggers | **Data Activator** | complements the agent's escalation ladder |
| Care-guidelines KB (RAG) | **Azure AI Search** (vector) | enterprise knowledge, kept separate from patient data |

**Why C for the hackathon:** standing up the full Fabric stack is hours of infra a judge
never sees and adds live-demo failure surface. Cosmos→OneLake **mirroring means
graduating local → Cosmos is a swap, not a rewrite**, and analytics is never migrated.
For the pitch, feed **one Power BI dashboard** with exported/sample events to sell the
"clinician view / population-health / biz potential" — one screenshot buys that
criterion; a live pipeline does not buy more.

**Privacy invariant (unchanged):** only `DailyLivingEvent` crosses; OneLake/Cosmos store
only structured/derived data; **no raw modality data is ever persisted**.

## 8. Notifications & escalation ladder (cloud-owned, long-running)

L3 is not one message — it is an **autonomous timed ladder**:

```
notify family ──(ack? within T_family)──► resolve
     │ no ack
     ▼
notify community/watch ──(ack? within T_community)──► resolve
     │ no ack
     ▼
emergency (120 / caregiver-on-call), attach location + event context
```

The Escalation agent + `EscalationTimer` tool own this. `CloudDecision.actions` returned
synchronously is an **audit record** of what the cloud is initiating; the actual sends
and ack-waits happen in T2. This is the concrete "long-running autonomous agent."

## 9. Multi-modal understanding (honest framing under the privacy boundary)

Because raw modality data stays on the edge, Foundry's multi-modal understanding is over
**fused feature/event streams + longitudinal history**:
- **Now:** fuse radar out-of-bed + door-open + voice `ReplyIntent` + baseline drift into
  one risk judgment.
- **Over weeks:** the Cognitive-Trend agent batch-models scrubbed **voice-biomarker
  features** into a cognitive trajectory (this hits the multi-modal / streaming-plus-batch
  bonus). Heavy modeling is **compute, not tokens** — keeps the agent frugal.

## 10. Proposed repo / module layout (`foundry/`)

```
foundry/
  pyproject.toml
  config.yaml                    # models, AI Search endpoint, store mode (local|cosmos), contacts
  airacare_foundry/
    a2a_server.py                # A2A/JSON-RPC endpoint: airacare.grade -> CloudDecision (drop-in for a2a_stub)
    orchestrator.py              # Care Orchestrator: T1 reflex + enqueue T2
    reflex/
      grader.py                  # patient-state-aware reflex policy (parity+ with stub)
      policy.py                  # L0–L3 thresholds × disease stage
    agents/                      # T2 Connected Agents
      risk_reasoning.py
      knowledge.py               # Azure AI Search RAG
      escalation.py              # timed ladder
      cognitive_trend.py         # batch modeling
      briefing.py                # family/clinician reports
    tools/
      notify.py                  # push/SMS
      geofence.py
      escalation_timer.py
    store/
      base.py                    # PatientStateStore protocol
      local.py                   # SQLite/in-memory (MVP)  ← used for the demo
      cosmos.py                  # production (mirrored to Fabric/OneLake)
    contracts.py                 # re-uses the SAME DailyLivingEvent/CloudDecision models
  tests/
    test_grade_parity.py         # returns identical grades to the stub for the flagship
    test_escalation_ladder.py
```

`contracts.py` must stay byte-compatible with `edge/airacare_edge/cloud/contracts.py`
(share or vendor the same pydantic models).

## 11. Build order (MVP-first)

1. **A2A server + reflex grader** returning the flagship `wander` grade with **parity to
   the stub** (proves drop-in; `test_grade_parity`). ← start here
2. **Local PatientStateStore** (SQLite) + disease-stage/baseline personalization in the
   reflex grade.
3. **Async escalation ladder** (family→community→emergency + ack timers) — the
   long-running story.
4. **Knowledge agent** (Azure AI Search) → grounded advice woven into `reason`/briefing.
5. **Cognitive-Trend + Briefing agents** (batch) → one **Power BI** clinician dashboard
   from exported events (pitch asset).
6. Swap edge `cloud.mode: foundry`, run the **demo-runbook** end-to-end against real
   Foundry.

## 12. Mapping to the challenge criteria

| Foundry capability the challenge asks for | Where it lives here |
|---|---|
| Deep reasoning & planning | Risk-Reasoning agent; disease-stage × baseline × fusion policy |
| Enterprise knowledge access | Knowledge agent → Azure AI Search (care guidelines) |
| Multi-agent orchestration | Care Orchestrator + Connected Agents (§5) |
| Toolboxes / Skills / Hosted Agents | Notify/Geofence/EscalationTimer tools; Hosted Agent runtime |
| Complex multi-modal understanding | fused event streams + longitudinal voice-biomarker modeling (§9) |
| Long-running autonomous | timed escalation ladder + batch trend/briefing (T2, §8) |
| Token-frugal | reflex policy is cheap; LLM/RAG only on real events; analytics is compute |
| Vertical template / biz potential | `DailyLivingEvent` one-engine model + Fabric/Power BI population-health story |

## 13. Switching the edge from stub → Foundry

No edge code change — config only:
```yaml
cloud:
  mode: foundry
  a2a_endpoint: "https://<foundry-hosted-agent-endpoint>/a2a"
```
The edge already speaks `airacare.grade` → `CloudDecision`; point it at the real endpoint
and provide credentials. The local `a2a_stub` and this Foundry agent are wire-identical.
