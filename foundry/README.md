# AiraCare — Foundry Care Orchestrator

Cloud-side graded reasoning for [AiraCare](../README.md). The Foundry Care Orchestrator is
the deep-reasoning counterpart to the [edge agent](../edge/README.md) and, for the flagship
**Nighttime Wandering** scenario, a **drop-in replacement for the edge's local A2A stub**.

Design: [../spec/foundry-design.md](../spec/foundry-design.md) ·
Architecture: [../spec/architecture.md](../spec/architecture.md).

## What it does

The edge is **authoritative**: it grades and acts on its own, then *reports* the event to
the cloud (with the level it already assessed). The orchestrator receives that
`DailyLivingEvent` over **A2A / JSON-RPC 2.0** and returns a considered `CloudAssessment`;
it also serves control-plane policy updates. It speaks the exact same two-method wire
contract as `edge/airacare_edge/cloud/a2a_stub.py`:

- `airacare.report` — params `{event}` → `CloudAssessment` (considered level + caregiver
  notifications + `policy_version` piggyback hint)
- `airacare.fetch_policy` — params `{patient_id, since_version}` → `EdgePolicyUpdate` (or
  `null` when nothing changed)

Switching the edge from the local stub to Foundry is an endpoint change only:

```yaml
# edge/config.yaml
cloud:
  mode: foundry
  a2a_endpoint: "http://localhost:8971/a2a"
```

> **Contract source of truth:** this package follows the edge **code** — the real A2A wire
> contract (`airacare.report` / `airacare.fetch_policy`) — so it stays a genuine drop-in.
> `spec/foundry-design.md` describes the same edge-authoritative `report` / `fetch_policy`
> model.

### Two decision tiers

- **T1 — Considered assessment (synchronous):** deterministic assessment with **parity** to
  the edge stub. It is **off the edge's safety path** — the edge already decided and acted;
  this response is for records + caregiver comms (the edge's report worker only waits ~5s
  before store-and-forward).
- **T2 — Deliberate (asynchronous):** placeholder for the multi-agent fusion tier
  (Risk-Reasoning / Knowledge / Escalation / Cognitive-trend / Briefing). Scheduled
  fire-and-forget; stubbed in this scaffold.

### Patient state (Decision #6 = C)

Patient state (disease stage + rolling baseline) lives in a **local** store —
`store/local.py` (SQLite, file or `:memory:`). `store/cosmos.py` is a placeholder behind the
`PatientStateStore` protocol so a Cosmos DB / Fabric backend can drop in later.

## Layout

```
airacare_foundry/
  contracts.py      # byte-compatible copy of the edge contracts
  config.py         # typed config (pydantic) from config.yaml
  orchestrator.py   # CareOrchestrator: T1 considered assessment (sync) + deliberate (async stub)
  a2a_server.py     # A2A / JSON-RPC server (Foundry stand-in)
  assess/           # considered assessor (parity) + policy (reads the store)
  store/            # base protocol + local SQLite store + cosmos placeholder
  agents/           # DELIBERATE tier stub
  tools/            # cloud-owned notification stub
tests/              # parity + A2A roundtrip + store + orchestrator
```

## Install & run

```powershell
cd foundry
python -m pip install -e ".[dev]"

# Start the orchestrator (edge points at this endpoint)
python -m airacare_foundry.a2a_server --config config.yaml
# -> AiraCare Foundry orchestrator listening on http://127.0.0.1:8971/a2a

# Run the tests
pytest -q
```

The parity test (`tests/test_report_parity.py`) compares the Foundry considered assessor
against the edge stub directly; it imports the sibling `edge/` package and skips gracefully
if it isn't present.

## Optional extras

- `[agents]` — Microsoft Agent Framework for the real DELIBERATE tier (future).
- `[cosmos]` — Azure Cosmos DB backend for the patient store (placeholder today).
- `[dev]` — pytest + ruff.
