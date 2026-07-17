# AiraCare Edge Agent

Privacy-first, offline-capable **edge agent** for in-home Alzheimer's care. Flagship
scenario: **Nighttime Wandering**. Design: [../spec/edge-design.md](../spec/edge-design.md).

> **Privacy boundary:** raw audio never leaves the device — only a structured
> `DailyLivingEvent` report is sent to the cloud.

> **Edge is authoritative.** The edge decides L0–L3 and acts **immediately**
> (reassure / local-alert / escalate); it **never waits on the cloud** on the safety
> path. The cloud replies **asynchronously** with a `CloudAssessment` (considered
> level, caregiver notifications, records) that piggybacks a `policy_version`; the
> edge lazily pulls an `EdgePolicyUpdate` only when that version increases and
> applies it to *future* behavior.

## Status — build steps 1–5

Implemented so far:

- **Step 1** — pure-logic core: `cloud/contracts.py`, `sensors/`, `reasoning/`
  (`grader.py` = `EdgeGrader`/`EdgeDecision`), `agent.py` (edge-authoritative flow +
  `VoiceService`/`CloudGateway`/`AlertSink` protocols), in-process cloud stub, unit tests.
- **Step 2** — `cli.py`: interactive scenario runner with a printed privacy panel.
- **Step 3** — A2A network path: `cloud/a2a_stub.py` + `cloud/a2a_client.py` +
  `cloud/factory.py` (local dev stub for `mode: a2a`). The **real deployed Foundry Hosted Agent** is
  reached over **standard A2A** by `cloud/foundry_client.py` (`mode: foundry`).
- **Step 4** — real voice I/O behind `VoiceService` (`voice/`): SAPI TTS (`say`),
  mic → energy-VAD → faster-whisper (`listen`), keyword `interpret`.
- **Step 5** — `voice/llm.py` Ollama reply-understanding for *ambiguous* replies
  (keyword fast-path first; LLM only on `unclear`; safe fallback if Ollama is absent)
  + bounded **clarify loop** in the FSM (`max_clarify_retries`, default 1).
- **Step 6** — `privacy/scrub.py` (raw audio → non-reconstructable features) +
  `ui/panel.py` **split-screen demo panel** (EDGE vs FOUNDRY, with the "only the
  DailyLivingEvent crossed" privacy boundary). Run with `--panel`.

The edge is **feature-complete for the flagship flow**.

> **Ollama is optional.** The LLM enhances only ambiguous replies. If Ollama isn't
> running, the edge keeps the keyword result and the clarify loop / graded action
> handles it. To enable it: install Ollama, `ollama pull phi3.5`, and
> `pip install -e ".[llm]"`.

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
python -m airacare_edge.cli --scenario no-response      # edge -> L3 escalated (acts now)
python -m airacare_edge.cli --scenario reply-ok         # edge -> L1 reassured (speaks locally)
python -m airacare_edge.cli --scenario no-response --panel   # split-screen demo panel
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
