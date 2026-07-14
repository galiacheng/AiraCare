# AiraCare

**A guardian that watches on the edge, thinks in the cloud.**

AiraCare is a **hybrid edge–Foundry AI agent** for in-home Alzheimer's care. A local
**edge agent** does privacy-sensitive, real-time sensing and first response inside the
home; a **Foundry-hosted agent** does multi-event fusion, disease-stage reasoning, and
graded decision-making in the cloud. Together they turn fragmented sensor alerts into
**graded, explainable actions** caregivers can act on.

> Flagship scenario: **Nighttime Wandering** — 3 AM, the patient leaves the bedroom; the
> edge confirms by voice, and (with the cloud) escalates appropriately.

## Why it's inherently hybrid

- **Privacy** — privacy-sensitive rooms (bedroom/bathroom) use **radar, not cameras**;
  where a camera or mic *is* used (e.g. the medication "pill-to-mouth" check), it's
  processed **on-device** and the **raw audio/video/point-cloud never leaves the home** —
  only a structured `DailyLivingEvent` crosses to the cloud.
- **Real-time + offline** — fall/wander detection and first response must be instant and
  keep working with no network.
- **Deep reasoning** — multi-event fusion, personalization, and graded decisions need the
  cloud (Foundry).

## Repository layout

| Path | What |
|---|---|
| [`spec/architecture.md`](spec/architecture.md) | Architecture, data flow, `DailyLivingEvent`, graded response ladder |
| [`spec/demo-scenarios.md`](spec/demo-scenarios.md) | Flagship + roadmap scenarios |
| [`spec/edge-design.md`](spec/edge-design.md) | Edge agent design (frameworks, models, state machine, voice pipeline) |
| [`spec/foundry-design.md`](spec/foundry-design.md) | Foundry Care Orchestrator design (two-tier grading, connected agents, escalation, data layer) |
| [`spec/demo-runbook.md`](spec/demo-runbook.md) | **Step-by-step demo script** |
| [`edge/`](edge/) | Edge agent implementation (Python) — see [`edge/README.md`](edge/README.md) |

## Components

- **Edge agent** (`edge/`, this repo) — sensors (simulated) → real voice (TTS + mic +
  VAD + faster-whisper) → keyword/LLM understanding (Ollama Phi-3.5-mini) → grading via
  A2A → offline store-and-forward. **Runs CPU-only.**
- **Foundry Care Orchestrator** (see [`spec/foundry-design.md`](spec/foundry-design.md)) —
  the cloud "brain": a **two-tier** decision agent (synchronous **reflex grade** < 5 s +
  asynchronous **deliberate** reasoning/escalation) built on Foundry Connected Agents,
  Toolboxes, and Azure AI Search knowledge. It is a **drop-in** for the local A2A stub —
  same `airacare.grade` → `CloudDecision` contract; `cloud.mode: foundry` switches to the
  real one. Demo state runs on a local store; production graduates to Cosmos DB mirrored
  into Microsoft Fabric/OneLake for analytics + Power BI reporting.

## Quick start (edge)

```powershell
cd edge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q -m "not slow"

# see the split-screen demo panel (no mic needed)
python -m airacare_edge.cli --scenario no-response --panel
```

For the full voice + LLM + offline demo, follow [`spec/demo-runbook.md`](spec/demo-runbook.md).

## Status

The **edge side is feature-complete for the flagship flow**: sensing → voice → LLM
understanding (with a bounded clarify loop) → `DailyLivingEvent` → A2A → graded L0–L3 →
offline fallback + store-and-forward → split-screen demo panel. Validated on a CPU-only
devbox.
