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
- **T2 — Deliberate (asynchronous):** fire-and-forget multi-agent tier (Risk-Reasoning /
  Knowledge / Escalation / Cognitive-trend / Briefing / Policy-Learning), dispatched through a
  pluggable executor (`InlineExecutor` default; `ThreadExecutor` for a real background worker,
  drained via `join()`). Scheduled after the T1 reply and never affects it. **Wired:**
  Policy-Learning (distills a versioned `EdgePolicyUpdate`), the **ack-tracked escalation
  ladder** (family → community → emergency with per-rung ack timers), the **Knowledge agent**
  (RAG over care guidelines that grounds cloud advice), and the batch **Cognitive-Trend**
  (least-squares voice-biomarker trajectory) + **Briefing** (family daily · clinician monthly)
  agents. Every scheduled event is also **filed** to the `EventStore` those batch agents read.

### Patient state & policy (Decision #6 = C)

Patient state (disease stage + rolling baseline) and the versioned per-patient edge policy
live in **local** stores — `store/local.py` (`LocalPatientStateStore` + `LocalPolicyStore`,
SQLite, file or `:memory:`). T1 personalizes the considered level by disease stage / baseline
drift; `fetch_policy` serves the stored policy only when the edge is behind. Filed events land
in `LocalEventStore` (the append-only analytics log the batch agents + Power BI read).
`store/cosmos.py` now implements the **same** three protocols against **Azure Cosmos DB**
(partition `/patient_id`, lazy `[cosmos]` SDK) so graduating local → Cosmos is a config flip
(`store.backend: cosmos`), not a rewrite — see [`docs/production.md`](docs/production.md).

### Analytics & briefings

The Cognitive-Trend + Briefing agents batch-read the `EventStore`. `powerbi/` exports the same
scrubbed events to a flat CSV (`python powerbi/generate.py`) that a **Power BI** dashboard loads
— the hackathon stand-in for the production Cosmos DB → Fabric/OneLake mirror (see
`powerbi/README.md`).

## Layout

```
airacare_foundry/
  contracts.py      # byte-compatible copy of the edge contracts
  config.py         # typed config (pydantic) from config.yaml
  orchestrator.py   # CareOrchestrator: T1 considered assessment (sync) + deliberate (async stub)
  a2a_server.py     # A2A / JSON-RPC server (Foundry stand-in)
  assess/           # considered assessor (personalized) + policy (reads the state store)
  store/            # base protocols + local SQLite stores (state + policy + events) + Cosmos impls
  agents/           # DELIBERATE tier + policy-learning + escalation + knowledge + cognitive-trend + briefing
  tools/            # notification/escalation timers + demo seed + Power BI export
tests/              # parity + a2a + store + orchestrator + personalization + policy + knowledge + trend/briefing
powerbi/            # Power BI pitch asset: generate.py -> sample_events.csv + dashboard README
docs/               # production.md — Cosmos/Fabric/Hosted-Agent graduation guide
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
- `[search]` — Azure AI Search vector RAG for the Knowledge agent (placeholder today).
- `[cosmos]` — Azure Cosmos DB backend (state + policy + events); `store.backend: cosmos`.
- `[dev]` — pytest + ruff.
