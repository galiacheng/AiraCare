# AiraCare Edge Agent

Privacy-first, offline-capable **edge agent** for in-home Alzheimer's care. Flagship
scenario: **Nighttime Wandering**. Design: [../spec/edge-design.md](../spec/edge-design.md).

> **Privacy boundary:** raw audio never leaves the device — only a structured
> `DailyLivingEvent` is sent to the cloud.

## Status — build step 1 (pure logic)

Implemented so far (no models, no mic, no network required):

- `cloud/contracts.py` — `DailyLivingEvent`, `ReplyIntent`, `CloudDecision` (typed).
- `sensors/` — raw sensor events + a canned nighttime-wander simulator.
- `reasoning/` — rule-based baseline drift, wander classifier, escalation policy.
- `agent.py` — the Edge Core state machine + service protocols (`VoiceService`,
  `CloudClient`, `AlertSink`).
- `cloud/stub.py` — in-process grading engine + offline-capable stub client.
- `tests/` — end-to-end wander-flow tests using fakes.

Coming next: A2A network stub (step 3), voice pipeline (step 4–5), privacy scrub + UI
(step 6).

## Quickstart (dev)

```powershell
cd edge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q
```

Run the scripted console demo (no mic/LLM — uses the local stub):

```powershell
python -m airacare_edge.main
```

## Layout

See [../spec/edge-design.md](../spec/edge-design.md) §3 for the full module map.
