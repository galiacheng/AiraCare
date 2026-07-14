# AiraCare — Foundry Care Orchestrator Design (PoC)

Detailed design for the **cloud side** of AiraCare — the **Foundry Care Orchestrator**
that the edge talks to over A2A. Flagship scenario **Nighttime Wandering**.

See also: [architecture.md](architecture.md) · [edge-design.md](edge-design.md) ·
[demo-scenarios.md](demo-scenarios.md) · [demo-runbook.md](demo-runbook.md).

The edge is authoritative: it **decides L0–L3 and acts immediately, and never waits for
the cloud**. The cloud is therefore **off the real-time safety path**. The edge freezes
the contract (`airacare.report` → `CloudAssessment`, `airacare.fetch_policy` →
`EdgePolicyUpdate`); the Foundry Care Orchestrator is a **drop-in replacement for the
local `LocalCloudStub`** that speaks the same A2A wire protocol but adds real depth:
personalized *considered* assessment, knowledge-grounded caregiver comms, an autonomous
ack-tracked escalation ladder, longitudinal trends/briefings, and the **policy learning**
that tunes the edge's future behavior.

---

## 1. Locked decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Runtime | **Azure AI Foundry Agent Service** — Care Orchestrator as a **Hosted Agent** |
| 2 | Multi-agent | **Foundry Connected Agents** for the deliberate (T2) orchestration |
| 3 | Latency strategy | **Off the safety path** — the edge already acted. The report returns a quick **considered assessment** (records + immediate caregiver comms); deep reasoning, the escalation ladder, trends, and policy learning run **asynchronously** (T2). |
| 4 | Knowledge | **Azure AI Search** RAG over care guidelines / clinical protocols |
| 5 | Models | GPT-4o-mini for the considered assessment + most sub-agents; GPT-4o for hard reasoning |
| 6 | Data (see §7) | **Demo/MVP = local store (SQLite/in-memory)**; **production target = Cosmos DB (operational) mirrored into Microsoft Fabric/OneLake for analytics + Power BI** |
| 7 | Notifications | **Cloud-owned** enriched dispatch + timed ack-tracked escalation ladder (the edge already fired its own immediate local alert + SMS to kin) |
| 8 | Drop-in | Same A2A `airacare.report` / `airacare.fetch_policy` contract → edge switches via `cloud.mode: foundry` only |
| 9 | MVP scope | Flagship **wander** considered assessment + escalation ladder + one knowledge-grounded advice + family briefing + a `policy_version` bump the edge pulls |

**What drives the design:** the edge never blocks on the cloud, so there is **no hard
real-time budget on the safety path**. The report call still returns promptly (the edge's
report worker uses a ~5 s timeout, then falls back to the store-and-forward queue), but a
slow or missing response only delays *records and caregiver enrichment* — never the
patient-facing action, which already happened on the edge.

## 2. Design principles

- **Edge acts, cloud reflects.** The edge has already decided and acted by the time the
  report arrives. The cloud never returns an action the edge waits on; it produces a
  *considered* assessment (for records + caregiver comms) and, separately, **policy** that
  tunes the edge's **future** behavior. Nothing here is on the real-time safety path.
- **Drop-in, not rebuild.** The Foundry agent honors the exact `airacare.report` →
  `CloudAssessment` and `airacare.fetch_policy` → `EdgePolicyUpdate` contract the edge
  already speaks. Switching from the local stub is a config change (`cloud.mode: foundry`),
  never an edge code change.
- **The cloud owns enriched notifications & escalation.** The edge fires its **own**
  immediate local action (light/sound, SMS to next of kin, or escalate) without waiting.
  The cloud then runs the **ack-tracked multi-channel ladder** (family → community →
  emergency) and enriches caregiver comms with fused history — it has the contact
  directory and the escalation timers.
- **Feedback as policy, not commands.** The cloud never micromanages a single event; its
  learning is distilled into an **`EdgePolicyUpdate`** (thresholds, clarify retries,
  personalized prompts, disease-stage) delivered lazily via the `policy_version` piggyback hint.
- **Privacy boundary is inherited and absolute.** Only `DailyLivingEvent` crosses;
  everything the cloud stores is **derived** from it. No raw audio/video/point-cloud is
  persisted anywhere, edge or cloud.
- **Cheap fast-path, expensive only when needed.** The considered assessment is
  policy/light-model; the LLM + RAG multi-agent deliberation only fires on real events
  (the edge already filters ~99% of no-event data) — token-frugal.

## 3. The frozen contract (inherited from the edge)

```jsonc
// Inbound — A2A / JSON-RPC 2.0 — a REPORT of what the edge saw AND already did
{ "jsonrpc":"2.0", "id":1, "method":"airacare.report",
  "params": { "event": DailyLivingEvent } }

// DailyLivingEvent (the ONLY thing that crosses the privacy boundary)
DailyLivingEvent {
  type: "fall|wander|med|meal|routine", confidence, timestamp, patient_id,
  features: [float],                 // privacy-scrubbed; never raw audio
  baseline_deviation,
  edge_assessed_level: "L0|L1|L2|L3",             // the edge's OWN immediate decision
  edge_action_taken: "none|reassured|local_alert|escalated",  // what the edge already did
  context: { time_of_day, door_open, response, ... }
}

// Outbound — CloudAssessment (async ack; the edge has ALREADY acted, it does not wait)
CloudAssessment {
  considered_level: "L0|L1|L2|L3",   // may match, enrich, or refine the edge's level
  reason: "explainable why",
  caregiver_notifications: [ { channel:"family|community|emergency", message, target } ],
  policy_version: 7,                 // PIGGYBACK HINT — latest policy the cloud has
  report_ref: "daily/2026-07-13"     // where this event was filed
}

// Inbound — lazy policy pull, only when the piggybacked policy_version changed
{ "jsonrpc":"2.0", "id":2, "method":"airacare.fetch_policy",
  "params": { "patient_id": "p-001", "since_version": 1 } }

// Outbound — EdgePolicyUpdate (tunes the edge's FUTURE behavior; null if unchanged)
EdgePolicyUpdate {
  version: 7, issued_at, patient_id,
  wander_confidence, no_response_seconds, max_clarify_retries,   // thresholds
  confirm_prompt, reassure_prompt, clarify_prompt,               // personalized prompts
  disease_stage, notes
}
```

## 4. Two-tier processing (both OFF the safety path)

The edge never waits, so neither tier has a real-time deadline. The split is about the
*responsiveness of records/comms* vs *depth of reasoning*, not about gating the edge.

| Tier | When | What | Target |
|---|---|---|---|
| **T1 — Considered assessment** (on the report call) | every reported event | patient-state-aware policy → `CloudAssessment` (considered level + reason + the caregiver comms it is initiating + current `policy_version`). Reads hot patient state (baseline, disease stage). | **prompt** (~1 s; the edge worker times out ~5 s → store-and-forward) |
| **T2 — Deliberate** (async, long-running) | after the report reply | Connected Agents: knowledge-ground the advice, run the **ack-tracked** multi-channel escalation ladder, update baseline/trend, generate briefings, and **distill an `EdgePolicyUpdate`** (bumping `policy_version`) the edge pulls lazily. | seconds–minutes, autonomous |

This split is also the answer to the judges' *"long-running autonomous / token-hungry?"*
questions: the autonomous escalation + trend + policy-learning work lives in T2; tokens are
spent only on real events, and heavy analytics is offloaded to compute (not the LLM).

## 5. Architecture on Azure AI Foundry

```mermaid
flowchart TD
    edge["AiraCare Edge"]

    edge -->|"A2A / JSON-RPC 2.0<br/>airacare.report { DailyLivingEvent }"| T1

    subgraph orchestrator["Care Orchestrator — Foundry Hosted Agent"]
        direction TB
        T1["T1 · Considered Assessor<br/>patient-state-aware policy (+policy_version)"]
        store[("Patient State Store<br/>baseline · disease-stage · history")]
        policy[("Policy Store<br/>versioned EdgePolicyUpdate")]
        T1 <-->|reads state| store
        T1 <-->|reads version| policy

        subgraph T2["T2 · Connected Agents (async, long-running)"]
            direction TB
            risk["Risk-Reasoning<br/>fusion × stage × baseline drift"]
            know["Knowledge<br/>care-guideline RAG"]
            esc["Escalation<br/>ack-tracked ladder"]
            trend["Cognitive-Trend<br/>batch voice-biomarker modeling"]
            brief["Briefing<br/>family daily · clinician monthly"]
            learn["Policy-Learning<br/>distills EdgePolicyUpdate (version++)"]
        end

        T1 -->|enqueue async job| T2

        subgraph tools["Tools"]
            direction TB
            notify["NotifyTool · push/SMS"]
            geo["GeofenceTool"]
            timer["EscalationTimer"]
        end
    end

    T1 -->|"CloudAssessment (records + caregiver comms)"| edge
    edge -.->|"airacare.fetch_policy (lazy, on version bump)"| policy
    policy -.->|"EdgePolicyUpdate"| edge
    know -->|vector RAG| search[("Azure AI Search<br/>care-guideline KB")]
    esc -->|"family → community → emergency"| ladder(["Escalation ladder"])
    esc -.uses.-> notify
    esc -.uses.-> timer
    risk -.uses.-> geo
    learn -.writes.-> policy
    brief -.->|reports| report(["Power BI / family briefing"])
```

## 6. Assessment policy (how the considered level is decided)

The considered level combines three inputs, weighted by disease stage:

`risk = f(event.type, event.confidence, baseline_deviation, context) × disease_stage_weight`

Flagship **wander** policy (parity with the current stub, now personalized). The edge has
**already acted** on its `edge_assessed_level`; the cloud's `considered_level` may match,
enrich, or refine it, and drives the caregiver comms:

| Reply / context (from the report) | Considered | Cloud action (enriched, ack-tracked) |
|---|---|---|
| `no_response` / `distress` | **L3** | notify family → (ladder) community → emergency, with fused context |
| `unclear` | **L2** | notify family to check + "3rd wander this week" enrichment |
| `ok` (patient reassured) | **L1** | none (log); note the pattern → personalize the future `reassure_prompt` (policy) |
| below confidence threshold | **L0** | log only → daily briefing |

Disease stage tunes thresholds (e.g. a *severe*-stage patient's nighttime out-of-bed
weights higher). The **reason** string is always populated for explainability, and is
enriched by the Knowledge agent in T2. When the cloud's view diverges from the edge's over
time (e.g. it wants an earlier confirm threshold), it encodes that as an **`EdgePolicyUpdate`**
— never as a per-event command.

## 7. Data & storage (decision #6 = **C**)

**Demo / MVP (build now):** the considered assessment + escalation run against a **tiny
local store** — SQLite (or in-memory) holding per-patient baseline, disease stage, and
recent event history. This keeps the report response prompt and adds **zero cloud
infrastructure** to the live demo.

**Production target (stated, not built for the hackathon):** split by workload and let
Fabric mirror handle analytics with no ETL:

| Data | Store | Notes |
|---|---|---|
| **Raw audio/video/point-cloud** | **nowhere** — edge RAM only, discarded after feature extraction | the privacy boundary |
| Offline event backlog | **edge disk** `.airacare_queue/` (TTL-bounded) | already built |
| **Patient State** (baseline, stage, contacts, history) | **Azure Cosmos DB**, partition = `patient_id` | single-digit-ms → keeps the report response prompt |
| **Edge policy** (versioned per patient) | **Azure Cosmos DB**, partition = `patient_id` | served by `fetch_policy`; edge pulls on a `policy_version` bump |
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

The Escalation agent + `EscalationTimer` tool own this. Note the edge has **already** fired
its own immediate local alert + SMS to next of kin the moment it graded L2/L3 — the cloud
does **not** blindly repeat that; it runs the **ack-tracked multi-channel ladder** and
enriches with fused context. The `caregiver_notifications` returned on the report are an
**audit record** of what the cloud is initiating; the actual sends and ack-waits happen in
T2. This is the concrete "long-running autonomous agent."

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
    a2a_server.py                # A2A/JSON-RPC: airacare.report -> CloudAssessment + airacare.fetch_policy -> EdgePolicyUpdate (drop-in for a2a_stub)
    orchestrator.py              # Care Orchestrator: T1 considered assessment + enqueue T2
    assess/
      assessor.py                # patient-state-aware considered-level policy (parity+ with stub)
      policy.py                  # L0–L3 thresholds × disease stage
    agents/                      # T2 Connected Agents
      risk_reasoning.py
      knowledge.py               # Azure AI Search RAG
      escalation.py              # ack-tracked ladder
      cognitive_trend.py         # batch modeling
      briefing.py                # family/clinician reports
      policy_learning.py         # distills EdgePolicyUpdate (version++)
    tools/
      notify.py                  # push/SMS
      geofence.py
      escalation_timer.py
    store/
      base.py                    # PatientStateStore + PolicyStore protocols
      local.py                   # SQLite/in-memory (MVP)  ← used for the demo
      cosmos.py                  # production (mirrored to Fabric/OneLake)
    contracts.py                 # re-uses the SAME DailyLivingEvent / CloudAssessment / EdgePolicyUpdate models
  tests/
    test_report_parity.py        # returns the same CloudAssessment as the stub for the flagship
    test_fetch_policy.py         # fetch_policy returns EdgePolicyUpdate only when version changed
    test_escalation_ladder.py
```

`contracts.py` must stay byte-compatible with `edge/airacare_edge/cloud/contracts.py`
(share or vendor the same pydantic models).

## 11. Build order (MVP-first)

1. **A2A server + considered assessor** returning the flagship `wander` `CloudAssessment`
   with **parity to the stub** (proves drop-in; `test_report_parity`), plus `fetch_policy`
   returning an `EdgePolicyUpdate` only when `policy_version` changed. ← start here
2. **Local PatientStateStore** (SQLite) + disease-stage/baseline personalization in the
   considered assessment.
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
| Long-running autonomous | ack-tracked escalation ladder + batch trend/briefing + policy learning (T2, §8) |
| Token-frugal | the considered-assessment policy is cheap; LLM/RAG only on real events; analytics is compute |
| Vertical template / biz potential | `DailyLivingEvent` one-engine model + Fabric/Power BI population-health story |

## 13. Switching the edge from stub → Foundry

No edge code change — config only:
```yaml
cloud:
  mode: foundry
  a2a_endpoint: "https://<foundry-hosted-agent-endpoint>/a2a"
```
The edge already speaks `airacare.report` → `CloudAssessment` and `airacare.fetch_policy`
→ `EdgePolicyUpdate`; point it at the real endpoint and provide credentials. The local
`a2a_stub` and this Foundry agent are wire-identical.
