# Power BI pitch dashboard (AiraCare cloud)

Decision #6 = C for the hackathon: we **don't** stand up the full Cosmos DB → Microsoft
Fabric/OneLake → Power BI pipeline (hours of infra a judge won't watch). Instead we export the
same privacy-scrubbed events the production store would hold to a flat CSV and load it into one
Power BI report — enough to *sell* the population-health / longitudinal-care story.

In production this CSV is replaced with a **live OneLake mirror of the Cosmos DB events
container** (zero-copy, no ETL); the visuals below are unchanged.

## Generate the dataset

From the `foundry-a2a-server/` directory:

```powershell
python powerbi/generate.py   # writes powerbi/sample_events.csv
```

This runs the deterministic demo seed (`airacare_foundry/tools/demo_seed.py`) — a month of
filed events for the flagship patient `p-001` with a gently **declining voice-biomarker**,
recurring **nighttime wanders** (every 5th day), and an occasional missed medication — then
exports it through `airacare_foundry/tools/powerbi_export.py`.

## Load in Power BI

1. **Get data → Text/CSV** → select `powerbi/sample_events.csv`.
2. In Power Query set types: `timestamp` = Date/Time, `biomarker` / `baseline_deviation` =
   Decimal, the rest Text/True-False. Close & Apply.
3. Build the four visuals below.

## Dataset columns

| Column | Meaning |
|---|---|
| `date`, `time`, `timestamp` | when the event occurred (UTC) |
| `patient_id` | partition key (Cosmos) — one patient per page in the pitch |
| `type` | `wander` / `fall` / `med` / `meal` / `routine` |
| `considered_level` | the cloud's T1 considered grade (`L0`–`L3`) |
| `edge_assessed_level` | the edge's own immediate grade (`L0`–`L3`) |
| `baseline_deviation` | rolling-baseline drift for the event (0–1) |
| `biomarker` | reduced voice-biomarker cognitive index (0–1, higher = better) |
| `time_of_day`, `door_open`, `response` | scrubbed context flags |

## Dashboard pages (the pitch)

1. **Cognitive trajectory** — line chart of `biomarker` by `timestamp` with a trend line. This
   is the headline: the same slope the Cognitive-Trend agent computes, made visible to a
   clinician. The demo data trends gently **declining**.
2. **Event mix** — stacked column of event `type` count by week, so routine vs. wander vs. med
   volume is legible at a glance.
3. **Escalation funnel** — `considered_level` distribution (`L0`→`L3`) plus an
   edge-vs-cloud level comparison, showing where the cloud *refined* the edge's grade.
4. **Nighttime risk** — count of `wander` events where `time_of_day = night` and
   `door_open = true`, the elopement signal that drives policy learning.

> **Privacy invariant (unchanged):** only derived `DailyLivingEvent` data is exported — never
> raw audio/video, and no feature vector beyond the single reduced biomarker index.
