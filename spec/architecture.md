# AiraCare — Architecture Specification

**AiraCare** — Hybrid Edge–Foundry Agent for Alzheimer's Home Care
*A quiet guardian: watches on the edge, thinks in the cloud.*

---

## 1. Overview

AiraCare is a **hybrid AI agent** for in-home Alzheimer's Disease (AD) care. An
**edge agent** performs privacy-sensitive, real-time sensing and fallback response
inside the home; a **Foundry-hosted agent** performs multi-modal fusion,
personalized reasoning, and graded decision-making in the cloud. Together they turn
fragmented sensor alerts into **graded actions + explainable briefings** that
caregivers can actually use.

### Why this problem is inherently hybrid
- Bedroom/bathroom monitoring → raw data **must never leave the home** (privacy) →
  forces sensing onto the edge.
- Fall / wandering detection needs **millisecond response + offline fallback** →
  must be on the edge.
- Multi-event fusion, disease-stage reasoning, personalized decisions → must be in
  the cloud (Foundry).

This is not "hybrid for the sake of hybrid" — the solution is impossible without it.

---

## 2. Edge / Foundry Division of Responsibilities

### Edge Agent (in-home, privacy boundary, real-time, offline-capable)
| Challenge capability | How AiraCare Edge delivers it |
|---|---|
| Real-time interaction | Millisecond local decision for fall/wandering; voice guidance |
| Device integration | mmWave radar + door/bed sensors + wearable IMU + smart pillbox |
| Local context awareness | Maintains today's rolling activity baseline on-device |
| **Privacy-sensitive processing** | **Raw audio/video/point-cloud never leaves home; only events + feature vectors uploaded** |
| Offline operation | Local light/sound alert + SMS to next of kin when disconnected |

### Foundry Agent (cloud, deep reasoning, orchestration)
| Challenge capability | How AiraCare Foundry delivers it |
|---|---|
| Deep reasoning & planning | Temporal fusion of multiple events → graded decision (L0–L3) |
| Enterprise knowledge | Care guidelines / disease-progression knowledge base for advice |
| **Multi-agent orchestration** | Monitoring / Companion / Cognitive-trend / Briefing sub-agents |
| Toolboxes / Skills / Hosted Agents | Notification tool, geofence tool, daily-report Skill |
| **Complex multi-modal understanding** | Fuses radar + acoustic + behavior + voice cognitive trends |

**Multi-modal bonus:** Edge does real-time acoustic event detection on the voice
stream (cry-for-help / fall sound) plus passive collection of **cognitive voice
biomarkers** from daily conversation; edge does streaming inference, cloud does
batch trend modeling.

---

## 3. Architecture & Data Flow

```
╔═══════════════════════════════ HOME / EDGE (privacy boundary · raw data never leaves) ═══════════════════════════════╗
║                                                                                                          ║
║   Sensing Layer (Device Integration)              Edge Agent (on-device · real-time · offline-capable)    ║
║   ┌────────────────────────┐                     ┌──────────────────────────────────────────┐            ║
║   │ mmWave radar  breath/pose/fall│─┐             │ 1. Sense: lightweight local inference       │            ║
║   │ door/bed      out-of-bed/door │ │             │    fall · wander · med · meal · routine     │            ║
║   │ wearable IMU  gait/activity/GPS│ ├─►raw stream►│ 2. Personal baseline: rolling stats + drift │            ║
║   │ smart pillbox open/weight     │ │  (local)     │ 3. Privacy scrub: discard raw A/V/point-cloud│            ║
║   │ microphone    acoustic/voice  │ │             │ 4. Active voice confirm + gentle guide (L1) │            ║
║   │ camera(local CV) "pill-to-mouth"│─┘            │ 5. Offline fallback: local alert + SMS kin  │            ║
║   └────────────────────────┘                     └───────────────────┬──────────────────────┘            ║
║                                                                       │                                  ║
╚═══════════════════════════════════════════════════════════════════════│══════════════════════════════════╝
                                                                        │
                     upload only unified event object (no raw data · token-frugal)
                     DailyLivingEvent {                                  │
                       type: fall|wander|med|meal|routine                ▼
                       confidence, timestamp, patient_id,
                       features:[…], baseline_deviation,
                       edge_action_taken: none|prompted|local_alert }
                                                                        │
╔═══════════════════════════════ AZURE AI FOUNDRY / CLOUD (deep reasoning · orchestration) ═══│════════════════════════╗
║                                                                        ▼                                  ║
║   ┌──────────────────────────── Care Orchestrator Agent ───────────────────────────────────┐             ║
║   │                                                                                          │             ║
║   │   ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐             │             ║
║   │   │ Monitoring     │  │ Companion      │  │ Cognitive-trend│  │ Briefing       │             │             ║
║   │   │ temporal fusion│  │ active confirm │  │ voice biomarker│  │ family daily   │             │             ║
║   │   │ +stage weight  │  │ /reduce FP     │  │ batch model    │  │ clinician month│             │             ║
║   │   └───────┬───────┘  └───────────────┘  └───────────────┘  └───────────────┘             │             ║
║   │           │                                                                              │             ║
║   │   Unified decision engine: personal baseline drift × disease stage × event fusion → risk │             ║
║   │           │                                                                              │             ║
║   │   Tools / Skills / Knowledge                                                             │             ║
║   │   [Notification tool] [Geofence tool] [Daily-report Skill] [KB: care guidelines / advice]│             ║
║   └───────────────────────────────────────┬──────────────────────────────────────────────┘             ║
║                                            │ graded + explainable ("why" + "what to do")                  ║
╚════════════════════════════════════════════│══════════════════════════════════════════════════════════════╝
                                             ▼
        ┌──────────────── Graded Notification & Action (anti-alert-fatigue: aggregate · quiet hours) ──────┐
        │  L0 self-handle   log to daily report (e.g. medication taken on time ✓)                          │
        │  L1 edge guidance return voice prompt to edge ("time for your medicine" / "let's rest")  ← loop  │
        │  L2 notify family push + suggested action ("Mom's BP med not taken, please remind")              │
        │  L3 escalate      family → community → 120/emergency, with location/event context               │
        └────────────────────────────────────────────────────────────────────────────────────────────────┘
                                             │
                          ┌──────────────────┴──────────────────┐
                          ▼                                      ▼
                   Family App (report/alert)         Clinician (trend report: routine·cognition·med adherence·falls)
```

---

## 4. Three Key Loops

1. **Real-time safety loop (edge self-contained):** sense → local decision → L1 voice
   guidance / offline fallback. **Cloud-independent, millisecond, offline-capable.**
2. **Decision loop (Edge → Foundry → Edge):** event upload → multi-modal fusion +
   disease-stage reasoning → grading → L1 instruction returned to edge.
3. **Insight loop (long-term):** cognitive-trend agent batch-models the daily voice
   stream → clinician monthly report. **One capture serves both companion-relief and
   early-warning.**

---

## 5. Three Design Anchors (pitch talking points)

- **Privacy boundary** = the dashed line: raw audio/video/point-cloud stays in the
  home; only structured events go to the cloud → trustworthy.
- **DailyLivingEvent unified abstraction:** fall / wander / medication / meal all flow
  through one engine → elegant and extensible (answers the "vertical template"
  question).
- **Token economics:** the edge filters 99% of no-event data; only real events wake the
  cloud LLM → token-frugal, long-running, autonomous.

---

## 6. DailyLivingEvent — Unified Event Model

The edge collapses all monitored activities of daily living (ADL) into one abstraction;
Foundry processes every type through the **same** baseline-drift × disease-stage ×
fusion → grading engine.

```jsonc
DailyLivingEvent {
  "type": "fall | wander | med | meal | routine",
  "confidence": 0.0-1.0,
  "timestamp": "ISO-8601",
  "patient_id": "string",
  "features": [ /* modality-specific feature vector, privacy-scrubbed */ ],
  "baseline_deviation": 0.0-1.0,   // drift vs the patient's own rolling baseline
  "edge_action_taken": "none | prompted | local_alert"
}
```

Adding a new monitored behavior (e.g. hydration, sleep) = a new `type`, **not** a new
system.

---

## 7. Graded Response Ladder

| Level | Trigger | Action |
|---|---|---|
| L0 self-handle | minor deviation | log only, into daily report |
| L1 gentle guidance | suspected anomaly | edge voice prompt ("time for your medicine" / "it's late, let's rest") |
| L2 notify caregiver | medium risk | push to family + **suggested action** ("wandering 5 min, please check") |
| L3 emergency escalation | fall no-response / left geofence | family → community → emergency, with location + event replay |

**Notification principles:** anti-alert-fatigue (grading + aggregation + quiet hours);
explainable (every alert carries *why* + *what to do*); deliverables = family daily
briefing + clinician monthly trend report.
