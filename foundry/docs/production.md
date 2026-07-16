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

The `CareOrchestrator` composes the two tiers in-process during the demo. In production it runs
as a **hosted agent**: the FH2 container **is** the A2A endpoint, deployed on **Azure Container
Apps** (ACA) and wired to Cosmos over a **Managed Identity** — no key, no edge change.

- **T1 considered assessment** stays synchronous on the report call (prompt, patient-state
  aware) — unchanged logic.
- **T2 Connected Agents** (Risk-Reasoning, Knowledge, Escalation, Cognitive-Trend, Briefing,
  Policy-Learning) run behind the `DeliberateTier.executor` seam. `executor: thread` is the
  hosted default; `executor: agents` swaps in `AgentFrameworkExecutor` (the Microsoft Agent
  Framework substrate, `[agents]` extra). When `executor: agents` is selected **and** a Foundry
  model endpoint + deployment are configured (`deliberate.foundry_endpoint` /
  `deliberate.foundry_deployment`, e.g. `${AIRACARE_FOUNDRY_ENDPOINT}` / `${AIRACARE_FOUNDRY_DEPLOYMENT}`),
  `agents/agent_framework.build_workflow()` binds the six `connected_agent_specs()` to the live
  `gpt-5.4` deployment as MAF **connected agents** (each specialist wrapped via `Agent.as_tool`
  under one orchestrator agent) reached over the Azure OpenAI **Responses API** with
  `DefaultAzureCredential` (the same Managed Identity — no key; `api_version: preview`).
- **The model is advisory, narrative-only.** The workflow runs *after* the deterministic T2
  agents and produces a plain-language caregiver briefing from a **scrubbed `case_file`** (only
  derived facts — event type, timestamps, edge level/action, the considered level + reason,
  baseline drift, and a *count* of voice-biomarker features; never raw audio/transcripts/feature
  values). It is instructed to restate the authoritative considered level verbatim; it **never**
  sets the risk level or drives escalation — `ConsideredAssessor` / `EscalationAgent` remain the
  sole authority. A model failure is swallowed (the tier is off the safety path). The narrative is
  surfaced on `DeliberateTier.narrative_log`. Leaving the endpoint unset keeps `executor: agents`
  fully deterministic (no model call). Verified live against `gpt-5.4`: an L3 nighttime-wander
  report yields a family briefing that restates L3 and notes the edge already escalated.
- Tools (notify, geofence, escalation timer) are declared as pure descriptors in `tool_specs()`,
  ready to register as Hosted Agent tools/skills.
- The container exposes the **same** `airacare.report` / `airacare.fetch_policy` A2A methods the
  stdlib server does (plus `GET /healthz` and optional bearer auth), so the edge does not change.

### 4.1 Provision + deploy (reproducible IaC)

`infra/foundry.bicep` + `infra/deploy-foundry.ps1` deploy the whole hosted tier. It reuses an
existing Foundry account + model deployment and the existing Cosmos account, and creates a
user-assigned Managed Identity, an ACR, the container image (`az acr build`), and the ACA app:

```powershell
# From foundry/infra. Requires: az login, an existing Cosmos account + a Foundry model deployment.
./deploy-foundry.ps1 `
  -SubscriptionId <sub> -ResourceGroup airacare-rg -Location eastus2 `
  -CosmosAccountName <cosmos-account> `
  -FoundryAccountName <foundry-account> -FoundryResourceGroup <foundry-rg> -FoundryDeployment gpt-5.4 `
  -DeploySearch:$false      # Azure AI Search is decoupled — enable once the KB is wired
# Re-runs are idempotent; add -SkipBuild to reuse an already-pushed image, and pass
# -A2AToken <token> to keep the bearer token stable across deploys.
```

The script prints the hosted endpoint, the MI clientId, and the bearer token (never written to
disk). What it wires up:

- **Managed Identity → Cosmos (no key):** the app runs with `cosmos_auth: aad`; the bicep grants
  the MI the **Cosmos DB Built-in Data Contributor** SQL role and injects `AZURE_CLIENT_ID` so
  `DefaultAzureCredential` selects the user-assigned identity. The container config it runs is
  `config.aca.yaml` (`store.backend: cosmos`, endpoint/db injected as env).
- **Managed Identity → ACR** (`AcrPull`) so ACA can pull the image; **MI → Foundry account**
  (`Cognitive Services OpenAI User`, cross-RG) so T2's advisory workflow can call the `gpt-5.4`
  model via `DefaultAzureCredential` (no key) when `executor: agents` is enabled.
- **Auth + TLS:** ACA gives HTTPS; `AIRACARE_A2A_TOKEN` enables bearer auth (401 without it).

## 5. Flip the edge to Foundry (config-only, no edge code change)

The edge already speaks the frozen contract; point it at the hosted endpoint and supply the token
**via env, never baked into config**:

```yaml
# edge/config.yaml
cloud:
  mode: foundry
  a2a_endpoint: "https://airacare-foundry.<region>.azurecontainerapps.io"
  a2a_token: "${AIRACARE_A2A_TOKEN}"   # resolved from the environment at startup
```

`edge/airacare_edge/cloud/factory.py` builds the same `A2AClient` for `a2a` (local stub) and
`foundry` (hosted) — only the endpoint and token differ. The token is resolved from a `${VAR}`
reference or the `AIRACARE_A2A_TOKEN` fallback, so no secret lives in source. The client attaches
`Authorization: Bearer <token>` to every A2A call.

## 6. End-to-end verification (proven live)

```powershell
# health (unauthenticated) -> {"status": "ok"}
curl https://airacare-foundry.<region>.azurecontainerapps.io/healthz
```

Then drive the edge against the hosted agent — the session `e2e_foundry_roundtrip.py` driver
reads `AIRACARE_FOUNDRY_URL` + `AIRACARE_A2A_TOKEN`:

- **Beat 1 (online):** a nighttime wander — the edge acts locally first (**L3**, escalation fires
  *before* the cloud), then the hosted agent returns a considered **L3** `CloudAssessment` over
  real HTTPS + bearer auth, with `family` + `community` notifications and a `policy_version`
  piggyback.
- **Beat 2 (offline → resync):** the cloud is unreachable, so the edge still acts and the
  `DailyLivingEvent` is queued to disk; when connectivity returns, the queue flushes to the
  **real** hosted agent (resync sent, remaining 0).
- **Auth matrix:** `airacare.report` returns **401 without** a token and **200 with** it.
- **Cosmos via MI:** every reported event lands in the Cosmos `daily_event` container written by
  the app's Managed Identity (no key) — verify with a `SELECT` on `patient_id`; a subsequent
  `fetch_policy` returns the learned `EdgePolicyUpdate` after the nighttime-wander threshold
  trips. Within the mirror latency it also appears in the OneLake Delta table / Power BI model.

## 7. What is built vs. deferred

The **Cosmos store** (§2) and the **hosted agent on ACA → Cosmos via Managed Identity** (§4–§6)
are both provisioned by IaC and verified live. The **default demo path stays local** (SQLite +
in-process orchestrator + one Power BI dashboard fed by `powerbi/` sample events) so a judge sees
zero live-infra failure surface — the seams above make graduation a config swap, not a rewrite.

Deferred (seams in place, not yet wired):

- **Model-backed T2 in the deployed app** — `agents/agent_framework.build_workflow()` is **built
  and verified live** (the six Connected Agents bind to `gpt-5.4` as MAF connected agents and
  compose an advisory caregiver narrative; see §4). The deployed ACA app still defaults to
  `executor: thread` (no per-event model cost/latency); flip it to `executor: agents` with
  `deliberate.foundry_endpoint` / `deliberate.foundry_deployment` set to graduate the hosted app
  to model-backed narratives. The model stays advisory — it never sets the risk level.
- **Azure AI Search KB** — decoupled behind the `deploySearch` flag (free-tier capacity is
  scarce); the Knowledge agent uses the local in-memory KB until Search is provisioned.
- **Fabric / OneLake mirroring + Power BI DirectLake** — the analytics tail (§3) is downstream
  and unchanged by the store/hosting swaps.
