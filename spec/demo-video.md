# AiraCare — 1–2 Minute Demo Video Storyboard

A recording script for a **strict 90-second** video (hard cap **1:30**; optional **1:50** variant in §2)
that lands the three pitch anchors —
**hybrid edge/cloud division**, the **privacy boundary**, and **graded escalation** — while
making two things *visible* that the shipped CLI hides:

1. **Every event the edge forwards to Foundry** (the exact privacy-scrubbed `DailyLivingEvent`
   JSON that crosses the home boundary), and
2. **Foundry's value on top of the instant edge action** — the deterministic considered level
   *plus* the Foundry hosted model's family briefing **with its knowledge-base citations**.

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
python spec/tools/foundry_demo_feed.py --endpoint $EP --scenarios reply-ok distress

# Real on-device voice recognition (edge speaks the prompt, Whisper transcribes bundled reply WAVs):
python spec/tools/foundry_demo_feed.py --endpoint $EP --voice local --scenarios reply-ok distress
```

The short cut is **2 cases: `reply-ok` (contrast) then `distress` (hero + Foundry climax)** — see §2.
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

**Rule: open on the situation, not the tech.** No jargon, no scrolling code until beat 4.

**Timing is strict.** Each beat has a fixed **duration** and a **voiceover budget** (max words the
narrator may speak *within that beat's talk window*, at ≈ 2.6 words/sec of clear delivery — the rest
of the beat is on-screen action: the edge speaking, Whisper transcribing, or the speed-ramped cloud
wait). **Do not exceed the VO budget** — if a take runs long, cut words, not seconds. The cumulative
clock must hit each **Ends at** mark exactly.

| # | Time | Dur | Ends at | VO budget | Zone | On screen | Voiceover (≈) |
|---|------|-----|---------|-----------|------|-----------|----------------|
| 1 | 0:00–0:08 | 8s | 0:08 | ≤ 20 w | A+C | Dashboard + terminal **in one frame, still** — do **not** scroll code yet | *"It's 3 AM. A person with Alzheimer's leaves bed. **AiraCare is already running inside the home.**"* (16 w) |
| 2 | 0:08–0:25 | 17s | 0:25 | ≤ 30 w | A | `reply-ok`: edge **speaks** the prompt; `🎙️ edge heard (Whisper ASR) → 'ok'`; **L1** | *"The edge asks 'are you okay?' — and **actually hears** the answer, on-device. 'I'm fine' → a gentle reassurance. **The system doesn't over-alert.**"* (23 w) |
| 3 | 0:25–0:42 | 17s | 0:42 | ≤ 30 w | A | `distress`: `edge heard → 'distress'`; **L3 escalated** — **flash a red UI highlight + a short alert sound** on the escalation line | *"Now — 'Help me.' The edge decides **L3** and acts **immediately, locally, even offline**. No waiting on the cloud."* (19 w) |
| 4 | 0:42–0:55 | 13s | 0:55 | ≤ 30 w | A | 🔒 boundary feed — **hold on ~6–8 key lines only** (see §2a), don't scroll the whole payload | *"This is **the only thing sent to Foundry**. No raw audio. No raw video. Only derived, scrubbed signals."* (18 w) |
| 5 | 0:55–1:18 | 23s | 1:18 | ≤ 33 w | A | ☁️ Foundry panel: `considered_level = L3` **then** the grounded briefing + *"Grounded by AiraCare guidelines: Exit-seeking…, Nighttime wandering response…"* (speed-ramp the wait — §3) | *"Foundry adds what the edge **shouldn't** do locally: longer reasoning, care knowledge, and a **grounded briefing for the family — with citations**. It confirms the level; it never overrides safety."* (30 w) |
| 6 | 1:18–1:30 | 12s | **1:30** | ≤ 16 w | C | Dashboard refresh — event count ticks up; trajectory + escalation funnel update → **end card** | *"Every event becomes a durable record for the care team."* (10 w) → **End card: "Fast at the edge. Smart in Foundry. Private by design."** (held ~4s, silent) |

> **Total = exactly 90s (1:30). Sum check:** 8 + 17 + 17 + 13 + 23 + 12 = **90s**. VO budget total ≤ 159 w
> (actual ≈ 116 w) — comfortably inside a 90s track.
>
> **Optional 1:50 variant** — insert `no-response` as a new **Beat 3b** between beats 3 and 4 (silence →
> edge escalates with no reply at all — the strongest "acts without the patient *or* the cloud" moment).
> Re-timed so every later mark shifts by **+20s**:
>
> | # | Time | Dur | Ends at | VO budget | On screen | Voiceover (≈) |
> |---|------|-----|---------|-----------|-----------|----------------|
> | 3b | 0:42–1:02 | 20s | 1:02 | ≤ 24 w | `no-response`: prompt spoken, **silence**, edge still **L3 escalates** | *"And if there's **no answer at all**? The edge still escalates — it never waits for permission to keep someone safe."* (20 w) |
>
> Then beats 4→6 become 1:02–1:15, 1:15–1:38, 1:38–1:50. **New total = exactly 110s (1:50).**

### 2a. Subtitles / on-screen captions (burn these in)

Clean, readable captions matter more than the raw terminal text. Superimpose these:

- **Beat 2 (reply-ok):**
  ```
  On-device Whisper hears: “I'm fine”
  Edge decision: L1 reassurance
  No cloud dependency · No alarm
  ```
- **Beat 3 (distress):**
  ```
  On-device Whisper hears: “Help me”
  Edge decision: L3 escalation
  Immediate local action, even offline
  ```
- **Beat 4 (privacy boundary)** — a simplified, human-readable restatement of the event to overlay
  while the real payload is on screen (keep it to ~6–8 lines):
  ```json
  {
    "event_type": "night_wandering_distress",
    "edge_level": "L3",
    "raw_audio_uploaded": false,
    "raw_video_uploaded": false,
    "signals": ["speech_intent", "motion", "time_context"]
  }
  ```
  > This overlay is a *simplified caption*. The actual terminal payload uses the real
  > `DailyLivingEvent` fields (`type`, `edge_assessed_level`, `edge_action_taken`, `context`, …) —
  > there are **no** audio/video fields at all, because those bytes never enter the payload. Show the
  > real JSON; the caption just makes the privacy point legible in one glance.
- **Beat 5 (Foundry):** `considered_level = L3` · `Grounded briefing with citations`
- **End card:** **Fast at the edge. Smart in Foundry. Private by design.**

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

## 3a. Record safely — what must NOT appear on screen

- **No secrets or infra identifiers in frame.** Before recording, run the token/key exports and
  `az login` **off-camera** (a separate window), and **clear the scrollback**. The recorded terminal
  must not show: the Foundry **endpoint URL**, any **access token**, **tenant/subscription IDs**, or
  **Key Vault / secret names**. If any leak in, blur/crop them in the editor.
  - Tip: set `$EP` and `$env:AIRACARE_A2A_TOKEN` in a pre-roll step, then `Clear-Host` before the
    first recorded command so only `python spec/tools/foundry_demo_feed.py …` is visible.
- **Careful medical wording.** This is decision *support*, not medical practice. Say **"diagnostic
  assistance"**, **"clinical observation support"**, or **"professional insight"** — **never
  "diagnosis"** or "the AI diagnoses." The edge and Foundry **assist** caregivers and clinicians;
  they do not diagnose or treat.
- **Don't linger on the cloud wait.** Speed-ramp (4×) or hard-cut the ~20–26s Foundry round trip
  (see §3) so pacing stays tight.

---

## 4. Pre-stage checklist (before you hit record)

- [ ] **Off-camera:** `az login`; export `$env:AIRACARE_A2A_TOKEN` (resource `https://ai.azure.com`)
      and `$env:AIRACARE_COSMOS_KEY` — then `Clear-Host` so **no endpoint/token/Key-Vault name is in
      frame** (see §3a).
- [ ] Cosmos key for the dashboard comes from Key Vault `kv-airacare-beq4os`, secret
      `airacare-cosmos-primary-key` (acquire it off-camera).
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

# Recommended 2-case real-voice cut (edge speaks; Whisper transcribes bundled WAVs):
#   reply-ok = the graded contrast (L1); distress = hero shot (L3 escalate + Foundry's grounded briefing)
python spec/tools/foundry_demo_feed.py --endpoint $EP --voice local `
  --scenarios reply-ok distress

# …or the fast scripted cut (no audio hardware needed):
python spec/tools/foundry_demo_feed.py --endpoint $EP --scenarios reply-ok distress

# Optional Beat 3b only if you're doing the 1:50 variant (silence → escalate; strongest "no reply, offline" moment):
#   python spec/tools/foundry_demo_feed.py --endpoint $EP --voice local --scenarios reply-ok distress no-response
```

What each scenario proves on screen:

| Scenario | Reply (voice) | Edge (instant) | Foundry (considered) | The point | In the cut? |
|---|---|---|---|---|---|
| `distress` | "help me" | **L3** escalated | L3 | real distress → immediate action + Foundry value | ✅ hero |
| `reply-ok` | "I'm fine" | **L1** reassured | L1 | graded, not spammy | ✅ contrast |
| `no-response` | *(silence)* | **L3** escalated | L3 | acts with no patient reply, offline-safe | ➕ Beat 3b (1:50 variant) |

> `unclear` ("the garden over there" → L2 via the on-device LLM path) exists but is **left out of
> the short cut** — it needs Ollama and doesn't add a new anchor in 90s.

---

## 6. The two lines the video exists to show

Straight from a live run — this is Foundry's demonstrable value the shipped CLI drops:

```
☁️ FOUNDRY RESPONSE — the value on top of the instant edge action:
   • Deterministic considered_level = L3 (computed by middleware BEFORE the model — the LLM cannot override it)
   • Foundry hosted model — family briefing, grounded in a knowledge base:
       … A gentle next step for the family is to calmly confirm he is safely inside and settled …
       Grounded by AiraCare guidelines: Exit-seeking and elopement risk, Nighttime wandering
       response, Home safety and wandering prevention.
```

**Fast** (edge decides + acts in ms) · **smart** (grounded, cited cloud reasoning) ·
**trustworthy** (only structured data crosses; the model can never lower the safety level).
