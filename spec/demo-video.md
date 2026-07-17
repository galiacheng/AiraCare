# AiraCare — 1–2 Minute Demo Video Storyboard

A recording script for a **90–110 second** video that lands the three pitch anchors —
**hybrid edge/cloud division**, the **privacy boundary**, and **graded escalation** — while
making two things *visible* that the shipped CLI hides:

1. **Every event the edge forwards to Foundry** (the exact privacy-scrubbed `DailyLivingEvent`
   JSON that crosses the home boundary), and
2. **Foundry's value on top of the instant edge action** — the deterministic considered level
   *plus* the `gpt-5.4` family briefing **with its knowledge-base citations**.

It also shows the edge doing **real on-device voice recognition** (the edge speaks the prompt;
Whisper transcribes the reply).

> This aligns with `spec/demo-runbook.md`. The runbook is the authoritative manual procedure;
> this doc is the tighter, recording-optimized cut driven by one presenter script:
> **`spec/tools/foundry_demo_feed.py`**.

---

## 0. The one asset that makes the video

`spec/tools/foundry_demo_feed.py` runs the **real edge pipeline** per scenario (optionally with
real voice), prints the **boundary feed** (exact forwarded JSON), then forwards that genuine event
to the **live Foundry hosted agent** over standard A2A and prints the **full** response — the
deterministic `considered_level` *and* the grounded family briefing with citations. Two-phase,
sequential output = clean to record.

```powershell
# Entra token for the Foundry A2A endpoint (resource: https://ai.azure.com):
$env:AIRACARE_A2A_TOKEN = (az account get-access-token `
  --resource https://ai.azure.com --query accessToken -o tsv)
$EP = "https://cog-jo2jqgwc7xe2m.services.ai.azure.com/api/projects/airacare-agent/agents/airacare-care-orchestrator/endpoint/protocols/a2a"

# Fast/scripted replies (no audio hardware) — good for the boundary+Foundry beats:
python spec/tools/foundry_demo_feed.py --endpoint $EP

# Real on-device voice recognition (edge speaks the prompt, Whisper transcribes bundled reply WAVs):
python spec/tools/foundry_demo_feed.py --endpoint $EP --voice local
```

Reply WAVs ship in `spec/tools/voice-replies/` (`distress.wav`, `reply-ok.wav`, `unclear.wav`);
`no-response` is silence. `--voice local` defaults to that folder — override with `--wav-dir`.

---

## 1. Screen layout (three zones, one frame)

```
┌───────────────────────────────┬───────────────────────────────┐
│  ZONE A — BOUNDARY FEED        │  ZONE C — CARE DASHBOARD       │
│  (terminal: presenter)         │  (browser: http://127.0.0.1:  │
│  • edge speaks + Whisper hears │   8975  reading live Cosmos)  │
│  • 🔒 exact DailyLivingEvent   │  • cognitive trajectory       │
│    JSON that crosses           │  • event mix + escalation     │
│  • ☁️ Foundry: considered level│    funnel — fills as events   │
│    + grounded briefing w/ cites│    land                       │
├───────────────────────────────┴───────────────────────────────┤
│  ZONE B — narration lower-third (optional caption bar)         │
└────────────────────────────────────────────────────────────────┘
```

- **Left ~60%**: the presenter terminal (wide, large font, dark theme).
- **Right ~40%**: the dashboard browser (Beat 6 asset), refreshed as events land.
- Record at **1080p**, terminal font ≥ 18pt so the JSON is legible on replay.

---

## 2. The 90-second cut (beat by beat)

| # | Time | Zone | On screen | Voiceover (≈) |
|---|------|------|-----------|----------------|
| 1 | 0:00–0:10 | A | Title card → `--voice local` warms up (`warm-up: {'asr': True…}`) | *"3 AM. An Alzheimer's patient gets out of bed. AiraCare runs **on the edge, in the home**."* |
| 2 | 0:10–0:25 | A | `reply-ok`: edge **speaks** the prompt; `🎙️ edge heard (Whisper ASR) → 'ok'`; **L1 reassured** | *"The edge asks 'are you okay?' and **actually hears** the answer — on-device Whisper, no audio ever leaves. 'I'm fine' → graded **L1**, a gentle local reassurance. No alarm."* |
| 3 | 0:25–0:40 | A | `distress`: `edge heard → 'distress'`; **L3 escalated** *now* | *"'Help me' → **L3**. The edge escalates **immediately, on its own** — light, alarm, SMS to family — even fully offline. It never waits on the cloud."* |
| 4 | 0:40–0:52 | A | 🔒 the boundary-feed JSON block scrolls into view | *"And this red boundary is **the only thing that crosses** — a structured, privacy-scrubbed event. No audio. No video. Just derived signals."* |
| 5 | 0:52–1:15 | A | ☁️ Foundry panel: `considered_level = L3` **then** the grounded briefing with *"Grounded by AiraCare guidelines: Exit-seeking…, Nighttime wandering response…"* | *"Asynchronously, the **Foundry hosted agent** adds value the edge can't: deterministic middleware **confirms L3 before any model runs** — the LLM can't override safety — then `gpt-5.4` writes a warm family briefing **grounded in a knowledge base, with citations**."* |
| 6 | 1:15–1:30 | C | Dashboard refresh — event count ticks up, trajectory + escalation funnel update | *"Every event is persisted to Cosmos, so one clinician view shows the **cognitive trajectory** and the **edge-vs-cloud escalation funnel** over time. Fast at the edge, smart in the cloud, private by construction."* |

> **Total ≈ 90s.** To reach ~110s, add the `no-response` scenario between beats 3 and 4
> (silence → edge escalates with no reply at all — the strongest "acts without the patient/cloud"
> moment).

---

## 3. Handling the ~26s live-cloud wait (editing)

Each live Foundry round trip is **~20–26s** (LLM cold start + `tasks/get` polling). Don't show it
in real time. Two options:

- **Speed-ramp (recommended):** record the full run, then in the editor **2–4× speed-ramp** the
  `⏳ forwarding to live Foundry…` gap so the ☁️ response "snaps" in. Keeps it honestly live.
- **Hard cut:** cut on the `⏳` line and resume on the `☁️ FOUNDRY RESPONSE` line.

Recording tools: **OBS Studio** or **Win+G Game Bar** to capture; **Clipchamp** (built into
Windows) for the speed-ramp + captions.

---

## 4. Pre-stage checklist (before you hit record)

- [ ] `az login`; token exported: `$env:AIRACARE_A2A_TOKEN` (resource `https://ai.azure.com`).
- [ ] Cosmos key for the dashboard: `$env:AIRACARE_COSMOS_KEY` (Key Vault
      `kv-airacare-beq4os`, secret `airacare-cosmos-primary-key`).
- [ ] Dashboard up (Zone C): `cd dashboard; python -m airacare_dashboard.server --config config.cosmos.yaml --host 127.0.0.1 --port 8975` → open `http://127.0.0.1:8975/`.
- [ ] **Pre-warm** the presenter once (`--voice local` downloads the Whisper model on first run) so
      the recording starts warm.
- [ ] Speaker/mic audible if you want the edge's spoken prompt on the audio track (real Remote
      Audio over RDP works).
- [ ] UTF-8 console: `$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'` (the presenter also calls
      `ensure_utf8_stdout()`; this just guarantees emoji render if you pipe output).
- [ ] Wide terminal, ≥18pt font, dark theme; reset backlog: `Remove-Item -Recurse -Force .airacare_queue -ErrorAction SilentlyContinue` in `edge/`.

---

## 5. Exact recording commands

```powershell
# ── Zone C: dashboard (one terminal, leave running) ──────────────────────────
$env:AIRACARE_COSMOS_KEY = (az keyvault secret show `
  --vault-name kv-airacare-beq4os --name airacare-cosmos-primary-key --query value -o tsv)
cd dashboard
python -m airacare_dashboard.server --config config.cosmos.yaml --host 127.0.0.1 --port 8975

# ── Zone A: the presenter (record this terminal) ─────────────────────────────
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'
$env:AIRACARE_A2A_TOKEN = (az account get-access-token `
  --resource https://ai.azure.com --query accessToken -o tsv)
$EP = "https://cog-jo2jqgwc7xe2m.services.ai.azure.com/api/projects/airacare-agent/agents/airacare-care-orchestrator/endpoint/protocols/a2a"

# Full real-voice cut (edge speaks; Whisper transcribes bundled WAVs; silence for no-response):
python spec/tools/foundry_demo_feed.py --endpoint $EP --voice local `
  --scenarios reply-ok distress no-response

# …or the fast scripted cut (no audio hardware needed):
python spec/tools/foundry_demo_feed.py --endpoint $EP --scenarios reply-ok distress no-response
```

What each scenario proves on screen:

| Scenario | Reply (voice) | Edge (instant) | Foundry (considered) | The point |
|---|---|---|---|---|
| `reply-ok` | "I'm fine" | **L1** reassured | L1 | graded, not spammy |
| `distress` | "help me" | **L3** escalated | L3 | real distress → immediate action |
| `no-response` | *(silence)* | **L3** escalated | L3 | acts with no patient reply, offline-safe |
| `unclear` | "the garden over there" | L2 local alert | L2 | ambiguous intent (LLM path; Ollama optional) |

---

## 6. The two lines the video exists to show

Straight from a live run — this is Foundry's demonstrable value the shipped CLI drops:

```
☁️ FOUNDRY RESPONSE — the value on top of the instant edge action:
   • Deterministic considered_level = L3 (computed by middleware BEFORE the model — the LLM cannot override it)
   • gpt-5.4 family briefing, grounded in a knowledge base:
       … A gentle next step for the family is to calmly confirm he is safely inside and settled …
       Grounded by AiraCare guidelines: Exit-seeking and elopement risk, Nighttime wandering
       response, Home safety and wandering prevention.
```

**Fast** (edge decides + acts in ms) · **smart** (grounded, cited cloud reasoning) ·
**trustworthy** (only structured data crosses; the model can never lower the safety level).
