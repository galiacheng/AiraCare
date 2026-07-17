# AiraCare — Care Dashboard

A standalone, read-only analytics surface over the **filed events** the AiraCare system records —
the population-health / longitudinal view (the demo run-book's **Beat 6**). It reads the **same**
`daily_event` store the deployed Foundry **hosted agent** writes to, and renders:

1. **Cognitive trajectory** — per-event voice-biomarker index over time + the OLS trend line.
2. **Event mix** — event-type counts bucketed by ISO week.
3. **Escalation funnel** — considered-level distribution + an edge-vs-cloud comparison.
4. **Nighttime risk** — nighttime wanders with the door open (the elopement signal).
5. **Briefings** — a family daily recap and a clinician monthly roll-up.

It never touches the real-time safety path — it only *reads* the append-only log. The
deterministic assessment and the Cosmos write both live in the Foundry hosted agent
(`../foundry-hosted-agent/`); the edge speaks standard A2A directly to that agent. There is no
bespoke A2A server.

## Layout

```
dashboard/
  airacare_dashboard/
    contracts.py   # DailyLivingEvent (privacy-scrubbed; the only thing read)
    config.py      # DashboardConfig: patient + store (local | cosmos)
    stores.py      # store protocols + local SQLite + Azure Cosmos + build_stores()
    analytics.py   # cognitive trend, briefings, flattened rows (compute, not tokens)
    seed.py        # deterministic demo month (offline dry-run / tests only)
    data.py        # DashboardData: filed events -> the dashboard JSON payload
    server.py      # stdlib HTTP server + CLI (python -m airacare_dashboard.server)
    static/        # single-page front-end (index.html, app.css, app.js — Chart.js via CDN)
  tests/           # offline: data layer + HTTP smoke over an ephemeral port
  config.cosmos.yaml
```

## Install

```powershell
cd dashboard
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"        # offline dry-run + tests (local SQLite; no Azure)
pip install -e ".[cosmos]"     # add the Azure Cosmos backend for the live demo
```

## Run

```powershell
# Live: read the events the hosted agent wrote to Cosmos (needs the [cosmos] extra + key/AAD)
$env:AIRACARE_COSMOS_KEY = (az keyvault secret show `
  --vault-name <kv> --name airacare-cosmos-primary-key --query value -o tsv)
python -m airacare_dashboard.server --config config.cosmos.yaml --host 127.0.0.1 --port 8975
# open http://127.0.0.1:8975/

# Offline dry-run: a seeded in-memory demo month, no Azure needed
python -m airacare_dashboard.server --seed
# open http://127.0.0.1:8975/
```

`--seed` writes a deterministic 30-day history into the (local) event store so the page lights up
without a live account. The live demo does **not** seed — it reads the real filed events.

## Test

```powershell
pytest -q
ruff check .
```

Tests are offline and network-free (in-memory SQLite + an ephemeral-port HTTP smoke). The Cosmos
backend is exercised in the live demo, not in unit tests.
