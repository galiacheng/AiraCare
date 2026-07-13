# AiraCare — Demo Scenarios

Demo scripts that showcase the **hybrid edge–cloud division of responsibility**. Each
scenario highlights: what the **edge** does locally, what **Foundry** reasons about in
the cloud, and where the **privacy boundary** sits.

Throughout, emphasize the recurring proof point: **raw audio/video/point-cloud never
leaves the home — only structured `DailyLivingEvent` objects are uploaded.**

> **🎯 PRIMARY FOCUS — we are building Scenario 1 (Nighttime Wandering) first.**
> All other scenarios are documented below as **additional / optional** choices that
> reuse the same edge agent, the same `DailyLivingEvent` abstraction, and the same
> Foundry grading engine. They are the roadmap, not the MVP.

---

# ⭐ PRIMARY SCENARIO — Nighttime Wandering (flagship, build first)

**Story**
> 3:00 AM. The patient gets out of bed → opens the front door.

**Edge (in-home)**
1. mmWave radar detects out-of-bed; door sensor detects door open.
2. Edge agent recognizes a `wander` event; context = nighttime + door.
3. **Active voice confirmation:** "Grandpa Zhang, are you okay?" → no response.
4. Edge uploads only: `{type: wander, confidence: 0.9, timestamp, features, edge_action_taken: prompted}`.
   *(Raw audio/video never leaves the home.)*

**Foundry (cloud)**
5. Monitoring sub-agent fuses "out-of-bed + door open + nighttime + moderate disease
   stage" → classifies as **high wandering risk**.
6. Decision engine → **L3 escalation**.

**Action**
7. Push to family with location + "please check immediately"; if no acknowledgement,
   escalate to community → emergency.

**Why hybrid:** detection & first response must be instant and offline (edge); risk
judgment requires event fusion + disease-stage reasoning (cloud). Full raw stream never
left the house.

### Why this is the right first scenario
- **Highest stakes, clearest hybrid story:** millisecond local sensing + offline
  fallback (edge) vs. contextual risk fusion (cloud) — the division is obvious and
  compelling to judges.
- **Strongest privacy proof point:** bedroom/doorway monitoring via **radar instead of
  camera**, raw data never leaving the home.
- **End-to-end in one link:** sense → active confirm → upload event → cloud fusion →
  L3 escalation → family push. A single, filmable demo path.
- **Everything else is an extension:** once this link works, the other scenarios are new
  `DailyLivingEvent` types flowing through the same engine.

### MVP scope for the flagship
- **Edge simulator:** laptop/phone — microphone does real-time voice **active-confirm**
  ("are you okay?" + no-response timeout); a sensor-event injector simulates
  out-of-bed + door-open. Edge uploads only JSON events.
- **Foundry agent:** one orchestrator that fuses the event + disease-stage parameter +
  time-of-day → grading (L3) + explainable reason + family notification payload.
- **Split-screen panel:** edge local decision vs. cloud fusion decision side by side;
  visibly highlight **"raw data never went to the cloud."**

---

# Additional Scenarios (roadmap / optional)

> These are **not** in the first build. They demonstrate that the same architecture
> extends by adding a new `DailyLivingEvent` type — no new system. Mention them in the
> pitch as the extensibility / vertical-template story.

## Option A — Missed Medication (medication adherence)

**Story**
> Scheduled dose time arrives; the smart pillbox stays closed.

**Edge (in-home)**
1. At dose time, edge issues a **voice reminder:** "Time for your medicine."
2. Smart pillbox not opened within 10 minutes (local sensing).
3. Edge uploads: `{type: med, confidence: 0.95, timestamp, edge_action_taken: prompted}`.

**Foundry (cloud)**
4. Reasons: "missed dose + this is a blood-pressure medication + moderate stage" →
   adherence risk.
5. Decision engine → **L2 notify family**.

**Action**
6. Push to family: "Mom's blood-pressure medication not taken today, please remind."
7. Logged into medication-adherence trend for the clinician monthly report.

**Why hybrid:** reminder + open/close sensing is local & privacy-safe; linking the miss
to drug type, disease stage, and adherence trend is cloud reasoning.

## Option B — Fall with No Response (real-time safety)

**Story**
> The patient falls in the bathroom.

**Edge (in-home)**
1. mmWave radar / wearable IMU detects a fall pattern in milliseconds (false-positive
   suppression: sitting vs falling).
2. **Active voice confirmation** → no response.
3. If **offline**, edge triggers local light/sound alert + SMS to next of kin
   immediately (offline fallback).
4. When online, uploads: `{type: fall, confidence, timestamp, edge_action_taken: local_alert}`.

**Foundry (cloud)**
5. Confirms severity, attaches context, and issues **L3 escalation** with location.

**Why hybrid:** a fall cannot wait for a round-trip to the cloud — the edge must decide
and act in milliseconds and keep working offline. Bathroom privacy is preserved by using
**radar instead of a camera**, and no raw data leaves the home.

## Option C — On-time Medication (L0, the quiet case)

**Story**
> The patient takes medication on time.

**Edge:** pillbox opened within window → `{type: med, edge_action_taken: none}`.
**Foundry:** **L0 self-handle** — no alert, just logged as "medication taken on time ✓".

**Why it matters:** demonstrates **anti-alert-fatigue** — most events are silent and
only summarized in the daily briefing. Also demonstrates **token economics**: routine
success does not wake heavy cloud reasoning.

## Option D — Cognitive Trend (long-term insight loop)

**Story**
> Over weeks, the companion agent chats with the patient daily.

**Edge (in-home)**
1. During normal conversation, edge **passively extracts cognitive voice biomarkers**
   (speech rate, pauses, vocabulary richness, syntactic complexity) via streaming
   inference.
2. Uploads only feature vectors — **raw audio never leaves the home**.

**Foundry (cloud)**
3. Cognitive-trend sub-agent **batch-models** the long-term signal.
4. Briefing agent produces a **clinician monthly report** (routine · cognition ·
   medication adherence · falls).

**Why hybrid & why it wins:** one capture serves **two value streams** — daily
companion-relief and early cognitive-decline warning. Edge = streaming; cloud = batch
trend modeling; this directly hits the multi-modal bonus.

---

## Judge-facing Talking Points (map demos to the "winning" criteria)

| Criterion | Which scenario proves it |
|---|---|
| Clear edge/cloud division & *why* | **Primary (Wandering)** — plus all others |
| Multi-modal real-time (bonus) | **Primary** (radar+voice), Option D (streaming voice biomarkers) |
| Long-running & autonomous | Option C + Option D — runs 24/7, mostly silent, self-managing |
| Token-hungry? (No — frugal) | Option C — edge filters 99% of no-event data before cloud LLM |
| Vertical template / market | DailyLivingEvent abstraction → extend AD → post-op → chronic care |
| Faster / smarter / more trustworthy | Fast (edge ms), smart (cloud fusion), trustworthy (privacy boundary) |

---

## Suggested Live Demo Flow (hackathon stage)

Keep scope tight; use simulators, not real hardware.

1. **Build & demo the flagship (Nighttime Wandering) end to end.** This is the whole
   MVP.
2. **Edge simulator:** laptop/phone microphone does real-time voice active-confirm; a
   simulated sensor-event injector fires out-of-bed + door-open. Edge uploads only JSON
   events.
3. **Foundry agent:** orchestrator fuses events + disease-stage parameter → L3 grading +
   explainable advice + family notification.
4. **Split-screen panel:** edge local decision vs cloud fusion decision side by side;
   visibly highlight **"raw data never went to the cloud."**
5. **Verbally** point at Options A–D as the same engine + a new `DailyLivingEvent` type
   — the extensibility / vertical-template story.
