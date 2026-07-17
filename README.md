# AiraCare

**A guardian that watches on the edge, thinks in the cloud.**

AiraCare is a **hybrid edge–Foundry AI agent** for in-home Alzheimer's care. A local
**edge agent** does privacy-sensitive, real-time sensing **and self-determined graded
response** inside the home — it decides L0–L3 and acts **immediately, even offline**. A
**Foundry-hosted agent** does multi-event fusion, disease-stage reasoning, and long-horizon
learning in the cloud **asynchronously** — never on the real-time safety path. Together they
turn fragmented sensor alerts into **graded, explainable actions** caregivers can act on.

> Flagship scenario: **Nighttime Wandering** — 3 AM, the patient leaves the bedroom; the
> edge confirms by voice and escalates **on its own**, while the cloud follows up
> asynchronously with an enriched briefing.

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
| [`spec/foundry-design.md`](spec/foundry-design.md) | Foundry Care Orchestrator design (async considered assessment, connected agents, escalation, policy feedback, data layer) |
| [`spec/demo-runbook.md`](spec/demo-runbook.md) | **Step-by-step demo script** |
| [`edge/`](edge/) | Edge agent implementation (Python) — see [`edge/README.md`](edge/README.md) |
| [`foundry-a2a-server/`](foundry-a2a-server/) | Foundry Care Orchestrator implementation (Python) — see [`foundry-a2a-server/README.md`](foundry-a2a-server/README.md) |

## Components

- **Edge agent** (`edge/`, this repo) — sensors (simulated) → real voice (TTS + mic +
  VAD + faster-whisper) → keyword/LLM understanding (Ollama Phi-3.5-mini) → **edge grades
  L0–L3 and acts locally** → reports the `DailyLivingEvent` via A2A → offline
  store-and-forward. **Runs CPU-only.**
- **Foundry Care Orchestrator** (`foundry-a2a-server/` + `foundry-hosted-agent/`, this repo —
  see [`foundry-a2a-server/README.md`](foundry-a2a-server/README.md)) — the cloud "brain", **off the real-time safety
  path**: a **two-tier** agent (a synchronous **considered assessment** returned on the
  report + an asynchronous **deliberate** tier for fusion / escalation / trends / policy
  learning) built on Foundry Connected Agents and Toolboxes, with knowledge grounded in a
  **Foundry IQ** knowledge base (agentic RAG over Azure AI Search). It
  is a **drop-in** for the local A2A stub — same `airacare.report` → `CloudAssessment` and
  `airacare.fetch_policy` → `EdgePolicyUpdate` contract; `cloud.mode: foundry` switches to
  the real one. Demo state runs on a local store; production graduates to **Cosmos DB**
  (live, via Managed Identity), with a **live care dashboard** over the filed events (Fabric/
  OneLake + Power BI remain the stated production analytics target). The conversational
  **hosted agent** (`foundry-hosted-agent/`) is deployed to **Azure AI Foundry Agent Service**
  on `gpt-5.4`.

## Quick start

**Edge** (CPU-only; the panel needs no mic or network):

```powershell
cd edge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q -m "not slow"

# split-screen demo panel against the in-process cloud stub
python -m airacare_edge.cli --scenario no-response --panel
```

**Foundry orchestrator** (the cloud drop-in) — its **own** venv, since it's an independent
deployable that will grow its own deps (Agent Framework, Foundry IQ / Azure AI Search, Cosmos). In a
second terminal:

```powershell
cd foundry-a2a-server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q

# start the A2A server the edge points at
python -m airacare_foundry.a2a_server --port 8971
```

**End-to-end** — with the server running, point the edge (first terminal) at the real
orchestrator instead of the in-process stub:

```powershell
python -m airacare_edge.cli --scenario no-response --cloud a2a --endpoint http://127.0.0.1:8971/a2a
```

For the full voice + LLM + offline demo, follow [`spec/demo-runbook.md`](spec/demo-runbook.md).
