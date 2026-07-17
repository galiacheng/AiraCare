"""Deterministic demo data — a month of filed events for the flagship patient (offline dry-run).

Used only by the ``--seed`` convenience path and the tests so the local (no-Cosmos) dashboard
lights up without a live account. The live demo does **not** seed — it reads the real events the
Foundry hosted agent wrote to Cosmos.

The generated trajectory encodes a **gently declining** voice-biomarker (the story the
Cognitive-Trend agent surfaces), a daily routine baseline, recurring **nighttime wanders** (every
5th day), and an occasional missed medication.

Considered-level fidelity: the hosted agent's deterministic assessor mirrors the edge's own level
for a default/moderate patient with no elevated state (the parity invariant). This seed carries a
moderate patient, so ``considered_level`` equals ``edge_assessed_level`` here — byte-identical to
what the assessor would derive, without importing the assessor.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from airacare_dashboard.contracts import DailyLivingEvent
from airacare_dashboard.stores import RecordedEvent

DEFAULT_PATIENT_ID = "p-001"
DEFAULT_DAYS = 30


def generate_events(
    patient_id: str = DEFAULT_PATIENT_ID,
    *,
    days: int = DEFAULT_DAYS,
    end: datetime | None = None,
) -> list[DailyLivingEvent]:
    """Generate ``days`` days of deterministic events ending on ``end`` (UTC midnight)."""
    end_date = (end or datetime(2026, 7, 15, tzinfo=timezone.utc)).date()
    events: list[DailyLivingEvent] = []
    for i in range(days):  # i = 0 is the oldest day
        day = end_date - timedelta(days=days - 1 - i)
        # Voice-biomarker gently declines over the window (higher = better fluency).
        score = round(0.82 - 0.004 * i, 4)
        baseline = round(min(0.2 + 0.01 * i, 1.0), 4)

        # Daily routine baseline (morning).
        events.append(
            DailyLivingEvent(
                type="routine",
                confidence=0.95,
                timestamp=datetime(day.year, day.month, day.day, 9, 0, tzinfo=timezone.utc),
                patient_id=patient_id,
                features=[score],
                baseline_deviation=baseline,
                edge_assessed_level="L0",
                edge_action_taken="none",
                context={"time_of_day": "morning", "response": "ok"},
            )
        )
        # Recurring nighttime wander every 5th day.
        if i % 5 == 0:
            events.append(
                DailyLivingEvent(
                    type="wander",
                    confidence=0.9,
                    timestamp=datetime(day.year, day.month, day.day, 2, 30, tzinfo=timezone.utc),
                    patient_id=patient_id,
                    features=[round(score - 0.05, 4)],
                    baseline_deviation=round(min(baseline + 0.6, 1.0), 4),
                    edge_assessed_level="L2",
                    edge_action_taken="local_alert",
                    context={
                        "time_of_day": "night",
                        "door_open": True,
                        "response": "no_response",
                    },
                )
            )
        # Occasional missed medication (every 12th day).
        if i % 12 == 6:
            events.append(
                DailyLivingEvent(
                    type="med",
                    confidence=0.85,
                    timestamp=datetime(day.year, day.month, day.day, 20, 0, tzinfo=timezone.utc),
                    patient_id=patient_id,
                    features=[score],
                    baseline_deviation=baseline,
                    edge_assessed_level="L1",
                    edge_action_taken="reassured",
                    context={"time_of_day": "evening", "response": "unclear"},
                )
            )
    return events


def to_records(events: list[DailyLivingEvent]) -> list[RecordedEvent]:
    """Wrap events as :class:`RecordedEvent`s (considered level = the edge level; see module doc)."""
    return [
        RecordedEvent(event=e, considered_level=e.edge_assessed_level) for e in events
    ]


def seed_event_store(
    event_store,
    *,
    patient_id: str = DEFAULT_PATIENT_ID,
    days: int = DEFAULT_DAYS,
    end: datetime | None = None,
) -> int:
    """Write ``days`` of deterministic demo history into ``event_store``; return the count."""
    records = to_records(generate_events(patient_id, days=days, end=end))
    for record in records:
        event_store.append(record)
    return len(records)


__all__ = [
    "DEFAULT_PATIENT_ID",
    "DEFAULT_DAYS",
    "generate_events",
    "to_records",
    "seed_event_store",
]
