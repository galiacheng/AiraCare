# Production graduation — from the local scaffold to Foundry + Cosmos + Fabric

This scaffold runs the whole cloud brain on **local SQLite stores** and a stdlib A2A server so
the demo needs zero cloud infra (Decision #6 = C). The design was built so graduating to
production is a **swap, not a rewrite**: every store sits behind a protocol, the A2A contract is
frozen, and analytics is mirrored (never migrated). This doc is the checklist for that swap.

## 1. Where each piece lands in production

| Concern | Scaffold (now) | Production target |
|---|---|---|
| Report / policy endpoint | `airacare_foundry.a2a_server` (stdlib HTTP) | **Foundry Hosted Agent** exposing the same A2A/JSON-RPC methods |
| Patient state | `LocalPatientStateStore` (SQLite) | **Azure Cosmos DB**, container `patient_state`, partition `/patient_id` |
| Edge policy | `LocalPolicyStore` (SQLite) | **Azure Cosmos DB**, container `edge_policy`, partition `/patient_id` |
| Filed events | `LocalEventStore` (SQLite) | **Azure Cosmos DB**, container `daily_event`, partition `/patient_id` |
| Trends / longitudinal analytics | in-process batch agents over SQLite | **Microsoft Fabric** (Eventhouse/KQL + Lakehouse/Delta) via **Cosmos → OneLake mirroring** |
| Family / clinician dashboards | `powerbi/` CSV export | **Power BI** on OneLake (live) |
| Care-guidelines RAG | `LocalKnowledgeBase` | **Azure AI Search** (vector) — `KnowledgeConfig.backend: azure` |
| Alert triggers | escalation ladder (in-process) | escalation ladder **+ Data Activator** on OneLake |

The **privacy invariant is unchanged** at every tier: only the derived `DailyLivingEvent`
crosses the edge boundary; Cosmos/OneLake store only structured/derived data; **no raw
audio/video/point-cloud is ever persisted**.

## 2. Swap the store: `local` → `cosmos`

The Cosmos stores (`airacare_foundry/store/cosmos.py`) implement the same
`PatientStateStore` / `PolicyStore` / `EventStore` protocols as the local ones, so nothing
upstream changes. Flip the backend in `config.yaml`:

```yaml
store:
  backend: cosmos
  cosmos_endpoint: "https://<account>.documents.azure.com:443/"
  cosmos_credential: "<key>"        # prefer injecting from env / Key Vault, not inlining
  cosmos_database: airacare
```

Then install the extra and run:

```powershell
pip install -e ".[cosmos]"
python -m airacare_foundry.a2a_server --config config.yaml
```

- All three containers are created on demand with **partition key `/patient_id`** — single-digit
  ms point reads keep the report response prompt, and per-patient event queries stay in one
  partition.
- `CareOrchestrator.from_config` builds the Cosmos trio and upserts the configured patient if
  the account is empty; real deployments provision patient state out of band.
- `azure-cosmos` is imported **lazily**, so the default local demo/tests never need the SDK;
  constructing a Cosmos store without it raises a clear, actionable error.

## 3. Analytics without ETL: Cosmos → OneLake mirroring

Enable **Mirroring** on the Cosmos DB `daily_event` container into **Microsoft Fabric /
OneLake**. This is zero-copy and continuous — no pipeline to build or babysit:

1. Fabric workspace → **New → Mirrored Azure Cosmos DB** → point at the account/database.
2. The `daily_event` container surfaces as a **Delta table** in OneLake, kept in near-real-time
   sync automatically.
3. Longitudinal modeling (the same math the `CognitiveTrendAgent` does per patient) runs as a
   **Spark/KQL batch job** over the mirrored Delta table — compute, not tokens — at population
   scale, without ever touching the operational Cosmos partitions.
4. **Power BI** builds directly on the OneLake Delta table (DirectLake), replacing the
   `powerbi/sample_events.csv` export with a live model. The four dashboard pages in
   `powerbi/README.md` are unchanged — only the data source is swapped.
5. Optionally attach **Data Activator** to the OneLake stream for condition-based alert
   triggers that complement the agent's escalation ladder.

## 4. Run the T2 agents as a Foundry Hosted Agent

The `CareOrchestrator` composes the two tiers today in-process. In production it becomes a
**Foundry Hosted Agent**:

- **T1 considered assessment** stays synchronous on the report call (prompt, patient-state
  aware) — unchanged logic.
- **T2 Connected Agents** (Risk-Reasoning, Knowledge, Escalation, Cognitive-Trend, Briefing,
  Policy-Learning) run on the **Microsoft Agent Framework** runtime (`[agents]` extra). The
  `DeliberateTier.executor` seam already isolates dispatch, so wiring the framework's async
  runtime in place of `ThreadExecutor` is a drop-in.
- Tools (notify, geofence, escalation timer) register as **Hosted Agent tools/skills**.
- The Hosted Agent exposes the **same** `airacare.report` / `airacare.fetch_policy` A2A methods
  the stdlib server does, so the edge does not change.

## 5. Flip the edge to Foundry (config-only, no edge code change)

The edge already speaks the frozen contract; point it at the hosted endpoint:

```yaml
# edge/config.yaml
cloud:
  mode: foundry
  a2a_endpoint: "https://<foundry-hosted-agent-endpoint>/a2a"
```

`edge/airacare_edge/cloud/factory.py` builds the same `A2AClient` for both `a2a` (local stub)
and `foundry` (hosted) — only the endpoint and credentials differ. Provide credentials as the
deployment requires.

## 6. End-to-end verification

Run `spec/demo-runbook.md` against the hosted agent instead of the local stub:

- Beats 1–3 are edge-local and unaffected.
- Beat 4 (offline → resync) now re-syncs the queued `DailyLivingEvent` to the **real** Foundry
  endpoint; confirm the `CloudAssessment` comes back with the expected `considered_level` and a
  `policy_version` piggyback, and that a subsequent `fetch_policy` returns the learned
  `EdgePolicyUpdate` after the nighttime-wander threshold trips.
- Confirm the event appears in Cosmos (`daily_event`) and, within the mirror latency, in the
  OneLake Delta table / Power BI model.

## 7. What is intentionally *not* built for the hackathon

Standing up the full Cosmos + Fabric + Hosted Agent stack is hours of infra a judge never sees
and adds live-demo failure surface. Because the seams above make graduation a swap, the pitch
ships the **local** path plus **one Power BI dashboard** fed by exported sample events
(`powerbi/`) — enough to sell the clinician-view / population-health story without the risk.
