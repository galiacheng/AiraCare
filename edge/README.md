# AiraCare Edge Agent

Privacy-first, offline-capable **edge agent** for in-home Alzheimer's care. Flagship
scenario: **Nighttime Wandering**. Design: [../spec/edge-design.md](../spec/edge-design.md).

> **Privacy boundary:** raw audio never leaves the device — only a structured
> `DailyLivingEvent` is sent to the cloud.

## Status — build steps 1–4

Implemented so far:

- **Step 1** — pure-logic core: `cloud/contracts.py`, `sensors/`, `reasoning/`,
  `agent.py` (Edge Core FSM + `VoiceService`/`CloudClient`/`AlertSink` protocols),
  in-process grading stub, unit tests.
- **Step 2** — `cli.py`: interactive scenario runner driving the full
  Edge → Cloud → Edge loop with a printed privacy-boundary panel.
- **Step 3** — A2A network path: `cloud/a2a_stub.py` (Foundry stand-in server) +
  `cloud/a2a_client.py` (JSON-RPC/A2A client) + `cloud/factory.py`.
- **Step 4** — real voice I/O behind `VoiceService` (`voice/`): SAPI TTS (`say`),
  mic → energy-VAD → faster-whisper (`listen`), keyword `interpret` (rule path).
  All audio imports are lazy; `[audio]` extra required only to run it.

Coming next: **step 5** — Ollama reply understanding for `unclear` replies + the
1-retry clarify loop; **step 6** — privacy scrub + split-screen UI.

## Quickstart (dev)

```powershell
cd edge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"            # core + tests (no audio)
pytest -q -m "not slow"            # fast suite

# to run the real voice pipeline:
pip install -e ".[dev,audio]"
pytest -q                          # includes the TTS->ASR round-trip
```

Scenario runner (fake console voice):

```powershell
python -m airacare_edge.cli --scenario no-response      # -> L3
python -m airacare_edge.cli --scenario reply-ok         # -> L1 voice loop-back
```

Real voice (step 4) — live mic check, and the full loop with local TTS/ASR:

```powershell
python -m airacare_edge.voice.mic_check                 # speak; see transcript + intent
python -m airacare_edge.cli --scenario reply-ok --voice local   # config voice.input=mic for live mic
```

A2A network path (step 3) — start the stub, then point the CLI at it:

```powershell
python -m airacare_edge.cloud.a2a_stub --port 8971
python -m airacare_edge.cli --scenario no-response --cloud a2a --endpoint http://127.0.0.1:8971/a2a
```

## Layout

See [../spec/edge-design.md](../spec/edge-design.md) §3 for the full module map.
