# AiraCare — Demo Run-book

Step-by-step script for demoing the **flagship Nighttime Wandering** scenario end to end.
The demo shows the three pitch anchors — **hybrid division of labor**, the **privacy
boundary**, and **graded escalation** — plus **real-time voice**, **on-device LLM
understanding**, and **offline resilience (store-and-forward)**.

> Cloud side note: the Foundry-hosted **Care Orchestrator** agent is owned by another
> team member. This run-book demos the **edge** against a local **A2A stub** that speaks
> the same contract; switching to real Foundry is config-only (`cloud.mode: foundry`).

---

## 0. Prerequisites (one-time)

- Windows devbox (CPU-only is fine), Python 3.10+.
- **Mic + speaker** available (on the devbox this is redirected **Remote Audio** over RDP —
  verified working).
- **Ollama** installed and running with the model pulled:
  ```powershell
  winget install --id Ollama.Ollama -e
  ollama pull phi3.5
  ```
- Edge environment:
  ```powershell
  cd C:\Users\<you>\Workspace\repos\AiraCare\edge
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  pip install -e ".[dev,audio,llm]"
  pytest -q -m "not slow"      # expect all green
  ```

## 1. Pre-flight (before you present)

- Close Chrome/Teams to free RAM (the models need ~4–5 GB).
- Confirm Ollama server is up:
  ```powershell
  (Invoke-WebRequest http://127.0.0.1:11434/api/version -UseBasicParsing).Content
  ```
- Optional: bump ASR accuracy for the room — set `voice.asr_model: medium` in
  `config.yaml` (slower first load, sharper transcripts).

---

## 2. The demo (beat by beat)

Run each in the **edge/** folder with the venv active. Use a wide terminal for the panel.

### Beat 1 — The split-screen story (no mic; fast + reliable)
Show the hybrid division + privacy boundary at a glance.

```powershell
python -m airacare_edge.cli --scenario no-response --panel
```
**Say:** *"3 AM — the patient gets out of bed and opens the door. The edge asks 'are you
okay?', hears no response, and escalates. Notice the **left** is the home/edge, the
**right** is Foundry, and the red strip shows the **only** thing that crossed — a
structured event, never raw audio."* → grade **L3**.

### Beat 2 — Graded, not spammy
```powershell
python -m airacare_edge.cli --scenario reply-ok --panel
```
**Say:** *"Same event, but the patient answers 'I'm fine'. The cloud grades it **L1** and
loops a gentle voice prompt back to the edge — no family alarm. Anti-alert-fatigue."*

### Beat 3 — Real voice + on-device LLM (the "smart" moment, live mic)
```powershell
python -m airacare_edge.voice.mic_check
```
Speak three replies, one run each:
1. *"I'm fine"* → resolved by the **keyword fast-path** (LLM not called).
2. *"Help me"* → **distress**, fast-path.
3. *"I don't know where I am, I'm scared"* → keyword can't classify → **🧠 LLM
   re-interprets → distress**. The output prints the provenance so the audience sees the
   LLM engage.
**Say:** *"Cheap, instant keyword matching handles the obvious cases; the local LLM only
wakes for the ambiguous ones — and it caught real distress that keywords miss. All
on-device; no audio leaves the home."*

### Beat 4 — Offline resilience + store-and-forward
Two terminals. Start with **no** A2A server running.

```powershell
# (server is OFF) — connectivity lost
python -m airacare_edge.cli --scenario no-response --cloud a2a
```
**Say:** *"Network's down. The edge still detects, still responds locally — light, sound,
SMS to next of kin — and **persists the event** so nothing is lost."* (Note
`path=offline_fallback`, `edge_action_taken=local_alert`, and one file queued.)

Now bring connectivity back:
```powershell
# terminal 2 — Foundry stand-in comes online
python -m airacare_edge.cloud.a2a_stub --port 8971

# terminal 1 — connectivity restored
python -m airacare_edge.cli --scenario reply-ok --cloud a2a
```
**Say:** *"The moment the cloud is reachable again, the edge **re-syncs** the queued event
automatically."* → look for `🔁 re-synced 1 queued event(s)`.

---

## 3. Judge-facing talking points (map to the criteria)

| Criterion | What to point at |
|---|---|
| Clear edge/cloud division + *why* | The split-screen: sensing/voice/first-response on the edge; fusion/grading in the cloud |
| Privacy / trustworthy | The red boundary strip — only `DailyLivingEvent` crosses; raw audio scrubbed on device |
| Real-time, multi-modal | Live mic → VAD → whisper → intent, all local and instant |
| Token-frugal, autonomous | Keyword fast-path filters the obvious; LLM only on ambiguous; edge runs 24/7 mostly silent |
| Faster / smarter / more trustworthy | Fast (edge ms + keyword), smart (LLM + cloud fusion), trustworthy (privacy boundary) |
| Reliability | Offline fallback + store-and-forward re-sync |
| Vertical template | `DailyLivingEvent` unified model → add a `type` to cover meds, falls, meals — no new system |

---

## 4. Switching to the real Foundry agent (when the teammate's agent is ready)

No edge code changes — just config:
```yaml
cloud:
  mode: foundry
  a2a_endpoint: "https://<foundry-hosted-agent-endpoint>/a2a"
```
The edge already speaks the A2A/JSON-RPC contract (`airacare.grade` → `CloudDecision`);
point it at the real endpoint and provide credentials as required.

---

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| LLM never engages / ambiguous stays `unclear` | Ollama not running — start it; `ollama list` should show `phi3.5` |
| Mic not captured on devbox | Ensure RDP "Remote audio recording" is on; test in Settings → Sound → Input |
| First LLM reply slow (~10 s) | Cold start — the CLI/mic_check **pre-warm** the model; run once before presenting |
| Emoji looks garbled when piped | Cosmetic only (UTF-8 over a cp1252 pipe); interactive terminals render fine |
| Panels stacked vertically | Widen the terminal window |
| Model RAM pressure | Close other apps; use `voice.asr_model: base` and the default `phi3.5` |

---

## 6. Reset between runs

```powershell
Remove-Item -Recurse -Force .airacare_queue -ErrorAction SilentlyContinue   # clear offline backlog
```
