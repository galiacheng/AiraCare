# AiraCare Edge Agent

Privacy-first, offline-capable **edge agent** for in-home Alzheimer's care. Flagship
scenario: **Nighttime Wandering**. Design: [../spec/edge-design.md](../spec/edge-design.md).

> **Privacy boundary:** raw audio never leaves the device — only a structured
> `DailyLivingEvent` is sent to the cloud.

## Status — build steps 1–3

Implemented so far (no ML models / mic required):

- **Step 1** — pure-logic core: `cloud/contracts.py`, `sensors/`, `reasoning/`,
  `agent.py` (Edge Core FSM + `VoiceService`/`CloudClient`/`AlertSink` protocols),
  in-process grading stub, unit tests.
- **Step 2** — `cli.py`: interactive scenario runner driving the full
  Edge → Cloud → Edge loop with a printed privacy-boundary panel.
- **Step 3** — A2A network path: `cloud/a2a_stub.py` (Foundry stand-in server) +
  `cloud/a2a_client.py` (JSON-RPC/A2A client) + `cloud/factory.py`. Drop-in for the
  real Foundry Hosted Agent by switching `cloud.mode` / endpoint.

Coming next: voice pipeline (step 4–5: Piper TTS, faster-whisper ASR, silero-VAD,
Ollama reply understanding), privacy scrub + split-screen UI (step 6).

## Quickstart (dev)

```powershell
cd edge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q
```

Scripted one-shot demo (in-process stub, no mic/LLM):

```powershell
python -m airacare_edge.main
```

Interactive scenario runner (step 2):

```powershell
python -m airacare_edge.cli --scenario no-response      # -> L3 escalation
python -m airacare_edge.cli --scenario reply-ok         # -> L1 voice loop-back
python -m airacare_edge.cli --scenario distress         # -> L3
python -m airacare_edge.cli --scenario restless         # -> below threshold (L0)
```

Run over the A2A network path (step 3) — start the stub server, then point the CLI at it:

```powershell
# terminal 1 — Foundry stand-in
python -m airacare_edge.cloud.a2a_stub --port 8971

# terminal 2 — edge talks to it over HTTP (drop-in for real Foundry)
python -m airacare_edge.cli --scenario no-response --cloud a2a --endpoint http://127.0.0.1:8971/a2a
```

(Run `--cloud a2a` *without* starting the server to see the offline fallback beat.)

## Layout

See [../spec/edge-design.md](../spec/edge-design.md) §3 for the full module map.
