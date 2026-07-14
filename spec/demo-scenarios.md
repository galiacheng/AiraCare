# AiraCare — Demo Scenarios

Demo scripts that showcase the **hybrid edge–cloud division of responsibility**. Each
scenario highlights: what the **edge** does locally, what **Foundry** reasons about in
the cloud, and where the **privacy boundary** sits.

Throughout, emphasize the recurring proof point: **raw audio/video/point-cloud never
leaves the home — only structured `DailyLivingEvent` objects are uploaded.**

> **Division of responsibility (applies to every scenario):** the **edge decides and acts
> immediately** — its own L0–L3 grading + action — and **never waits for the cloud**. The
> **Foundry** agent adds an *asynchronous* considered assessment (for reports + enriched
> caregiver comms) and feeds **policy updates** back to the edge. The cloud is never on the
> real-time safety path.

> **🎯 PRIMARY FOCUS — we are building Scenario 1 (Nighttime Wandering) first.**
> All other scenarios are documented below as **additional / optional** choices that
> reuse the same edge agent, the same `DailyLivingEvent` abstraction, and the same
> edge grading + Foundry assessment engine. They are the roadmap, not the MVP.

---

# ⭐ PRIMARY SCENARIO — Nighttime Wandering (flagship, build first)

**Story**
> 3:00 AM. The patient gets out of bed → opens the front door.

**Edge (in-home)**
1. mmWave radar detects out-of-bed; door sensor detects door open.
2. Edge agent recognizes a `wander` event; context = nighttime + door.
3. **Active voice confirmation:** "Grandpa Zhang, are you okay?" → no response.
4. Edge **self-assesses L3** and **acts now** (no cloud wait): local alarm + SMS to next
   of kin, escalate toward community/emergency.
5. Edge reports only: `{type: wander, confidence: 0.9, timestamp, features, edge_assessed_level: L3, edge_action_taken: escalated}`.
   *(Raw audio/video never leaves the home; the report is fire-and-forget.)*

**Foundry (cloud · async — does not gate the action)**
6. Receives the reported event; Monitoring / Companion / Cognitive-trend / Briefing agents
   fuse it with history + disease stage → a **considered assessment** + an explainable
   family briefing ("3rd nighttime wander this week — escalating"). May refine the record
   and issue an **EdgePolicyUpdate** (e.g. lower the night threshold).

**Why hybrid:** detection, judgment, and first response must be instant and offline — so
the **edge** decides and acts on its own. The **cloud** adds fused context, caregiver
briefings, and policy tuning **asynchronously** (never gating the action). Full raw stream
never left the house.

### Why this is the right first scenario
- **Highest stakes, clearest hybrid story:** millisecond local sensing + offline
  fallback (edge) vs. contextual risk fusion (cloud) — the division is obvious and
  compelling to judges.
- **Strongest privacy proof point:** bedroom/doorway monitoring via **radar instead of
  camera**, raw data never leaving the home.
- **End-to-end in one link:** sense → active confirm → **edge L3 decision + act (alarm +
  SMS + escalate)** → report to cloud → async briefing/policy. A single, filmable demo path.
- **Everything else is an extension:** once this link works, the other scenarios are new
  `DailyLivingEvent` types flowing through the same engine.

### MVP scope for the flagship
- **Edge simulator:** laptop/phone — microphone does real-time voice **active-confirm**
  ("are you okay?" + no-response timeout); a sensor-event injector simulates
  out-of-bed + door-open. Edge uploads only JSON events.
- **Foundry agent:** one orchestrator that fuses the reported event + disease-stage +
  history → a **considered assessment** + explainable briefing + (optional) EdgePolicyUpdate.
- **Split-screen panel:** the **edge's** immediate decision/action vs. the cloud's
  considered assessment, side by side; highlight **"raw data never went to the cloud"** and
  **"the edge acted without waiting."**

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
3. Edge reports: `{type: med, confidence: 0.95, timestamp, edge_assessed_level: L2, edge_action_taken: local_alert}`.

**Edge decides & acts (immediate)**
4. Edge self-assesses **L2**, re-prompts, then **notifies family** ("Mom's BP medication
   not taken, please remind").

**Foundry (cloud · async)**
5. Links the miss to drug type + disease stage + adherence trend → enriched caregiver
   context + the clinician monthly report; may adjust reminder policy.

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
4. When online, reports: `{type: fall, confidence, timestamp, edge_assessed_level: L3, edge_action_taken: escalated}`.

**Edge decides & acts (immediate):** the fall + no-response is an **L3** the edge
escalates **itself** (alarm + SMS + community/emergency) — offline too.

**Foundry (cloud · async):** confirms severity, attaches fused context + location to the
record, and files the report.

**Why hybrid:** a fall cannot wait for a round-trip to the cloud — the edge must decide
and act in milliseconds and keep working offline. Bathroom privacy is preserved by using
**radar instead of a camera**, and no raw data leaves the home.

## Option C — On-time Medication (L0, the quiet case)

**Story**
> The patient takes medication on time.

**Edge:** pillbox opened within window → self-assesses **L0**, no action →
`{type: med, edge_assessed_level: L0, edge_action_taken: none}`.
**Foundry (async):** curates it into the daily report ("medication taken on time ✓") — no alert.

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
3. **Foundry agent (async):** orchestrator fuses the reported event + disease stage →
   considered assessment + explainable briefing (+ optional EdgePolicyUpdate). The edge
   already decided and acted.
4. **Split-screen panel:** the edge's immediate decision + action vs. the cloud's
   considered assessment; highlight **"raw data never went to the cloud"** and **"the edge
   acted without waiting."**
5. **Verbally** point at Options A–D as the same engine + a new `DailyLivingEvent` type
   — the extensibility / vertical-template story.
