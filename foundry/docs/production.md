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
upstream changes. The swap is a **verified, reproducible runbook**, not just a flag flip.

### 2.1 Provision (reproducible IaC)

`infra/cosmos.bicep` provisions a **serverless** Cosmos SQL account (no idle cost — ideal for
demo/hackathon; pay per request), database `airacare`, and the three containers
(`patient_state`, `edge_policy`, `daily_event`, all partition `/patient_id`) with a composite
index on `daily_event (patient_id ASC, ts ASC)` for the range+order event query.
`infra/deploy.ps1` wraps resource-group creation + deployment and prints the endpoint, key, and
the exact config to paste (the key is **never written to disk**):

```powershell
cd foundry/infra
./deploy.ps1 -ResourceGroup airacare-rg -Location eastus2
# prod / provisioned throughput instead of serverless:
# ./deploy.ps1 -ResourceGroup airacare-rg -Location eastus2 -Serverless:$false -Throughput 800
```

Verify: `az cosmosdb sql container list --account-name <acct> --resource-group airacare-rg
--database-name airacare -o table` shows all three containers with PK `/patient_id`.

The code also creates containers on demand (`create_container_if_not_exists`), so Bicep is the
reproducible/prod path; the minimum viable manual path is just account + DB.

### 2.2 Secrets — keep the key out of source

`store.cosmos_credential` resolves `${VAR}` from the environment, so `config.yaml` holds only a
reference, never the secret:

```yaml
store:
  backend: cosmos
  cosmos_endpoint: "https://<account>.documents.azure.com:443/"
  cosmos_credential: "${AIRACARE_COSMOS_KEY}"   # expanded from env; nothing secret in the file
  cosmos_database: airacare
  cosmos_auth: key           # 'key' (account key) or 'aad' (Managed Identity / az login)
  cosmos_tls_verify: true    # set false only for the classic HTTPS emulator self-signed cert
```

```powershell
$env:AIRACARE_COSMOS_KEY = '<primary-key>'   # or source from Key Vault in prod
```

Prefer **`cosmos_auth: aad`** in production: it builds a client from
`azure.identity.DefaultAzureCredential` (Managed Identity on the Hosted Agent, `az login`
locally) and ignores the key entirely — no key to store or rotate. `az cosmosdb sql role
assignment create` grants the identity data-plane access. The `[cosmos]` extra pulls in both
`azure-cosmos` and `azure-identity`.

### 2.3 Install, flip, seed, verify

```powershell
pip install -e ".[cosmos]"
# seed the 30-day demo history so Cognitive-Trend / Briefing / Power BI light up post-swap:
python -m airacare_foundry.tools.demo_seed --config config.yaml --backend cosmos
# run the server on the Cosmos backend:
python -m airacare_foundry.a2a_server --config config.yaml
```

- `demo_seed --backend cosmos` writes 38 deterministic events (declining biomarker + nightly
  wanders) via `CosmosEventStore`; `--backend` overrides `store.backend` so you can seed from a
  local-default config.
- The env-gated `tests/test_cosmos_integration.py` proves the real round-trips (state upsert/get,
  policy version gate, event append + range query, trend over Cosmos). Point it at any account —
  the **Azure Cosmos DB Emulator** (free/local) or a real one — and run:
  ```powershell
  $env:AIRACARE_COSMOS_ENDPOINT = "https://<account>.documents.azure.com:443/"
  $env:AIRACARE_COSMOS_KEY = "<key>"; $env:AIRACARE_COSMOS_TLS_VERIFY = "1"
  python -m pytest tests/test_cosmos_integration.py -v
  ```
  Unset `AIRACARE_COSMOS_ENDPOINT` and the suite skips, so CI stays offline-green.

Notes that make the swap safe:
- All three containers use **partition key `/patient_id`** — single-digit-ms point reads keep the
  report response prompt, and per-patient event queries stay in one partition.
- `CareOrchestrator.from_config` builds the Cosmos trio and upserts the configured patient if the
  account is empty; real deployments provision patient state out of band.
- `azure-cosmos` is imported **lazily**, so the default local demo/tests never need the SDK;
  constructing a Cosmos store without it raises a clear, actionable error.
- Parity is untouched: `ConsideredAssessor.assess()` takes no state, so the store backend can
  never alter the frozen edge contract (`test_report_parity.py` stays green).

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
