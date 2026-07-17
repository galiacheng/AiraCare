"""Deterministic demo data — a month of filed events for the flagship patient.

Used by the Power BI export asset and the batch-agent tests so both have a stable, realistic
history without any randomness. The generated trajectory encodes a **gently declining**
voice-biomarker (the story the Cognitive-Trend agent is meant to surface), a daily routine
baseline, and recurring **nighttime wanders** (every 5th day) plus an occasional missed
medication — enough to exercise trend, briefing, and the dashboard visuals.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from airacare_foundry.assess.assessor import ConsideredAssessor
from airacare_foundry.contracts import DailyLivingEvent
from airacare_foundry.store.base import RecordedEvent

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


def to_records(
    events: list[DailyLivingEvent],
    *,
    assessor: ConsideredAssessor | None = None,
) -> list[RecordedEvent]:
    """Wrap events as :class:`RecordedEvent`s, deriving the considered level from the assessor."""
    assessor = assessor or ConsideredAssessor()
    return [
        RecordedEvent(event=e, considered_level=assessor.assess(e).considered_level)
        for e in events
    ]


def seed_event_store(
    event_store,
    *,
    patient_id: str = DEFAULT_PATIENT_ID,
    days: int = DEFAULT_DAYS,
    end: datetime | None = None,
    assessor: ConsideredAssessor | None = None,
) -> int:
    """Write ``days`` of deterministic demo history into ``event_store``; return the count.

    Backend-agnostic — accepts any :class:`~airacare_foundry.store.base.EventStore`
    (``LocalEventStore`` or ``CosmosEventStore``) so the same 30-day trajectory can seed the
    Cosmos analytics store post-swap and light up Cognitive-Trend / Briefing / Power BI.
    """
    records = to_records(generate_events(patient_id, days=days, end=end), assessor=assessor)
    for record in records:
        event_store.append(record)
    return len(records)


def main(argv: list[str] | None = None) -> int:
    """CLI: seed a month of demo events into the configured (local **or cosmos**) event store.

    Examples::

        python -m airacare_foundry.tools.demo_seed --config config.yaml --backend cosmos
        python -m airacare_foundry.tools.demo_seed --config config.yaml --patient-id p-001 --days 30

    ``--backend`` overrides ``store.backend`` from the config (e.g. seed Cosmos from a
    local-default config). Cosmos requires the ``[cosmos]`` extra and a resolvable
    ``store.cosmos_credential`` (set ``$env:AIRACARE_COSMOS_KEY``).
    """
    import argparse

    from airacare_foundry.config import FoundryConfig
    from airacare_foundry.orchestrator import _build_stores

    parser = argparse.ArgumentParser(
        prog="python -m airacare_foundry.tools.demo_seed",
        description="Seed deterministic demo events into the configured event store.",
    )
    parser.add_argument("--config", required=True, help="Path to config.yaml.")
    parser.add_argument(
        "--backend",
        choices=["local", "cosmos"],
        help="Override store.backend from the config.",
    )
    parser.add_argument("--patient-id", default=DEFAULT_PATIENT_ID, help="Patient id to seed.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Days of history.")
    args = parser.parse_args(argv)

    config = FoundryConfig.load(args.config)
    if args.backend:
        config.store.backend = args.backend

    _state, _policy, event_store = _build_stores(config)
    count = seed_event_store(event_store, patient_id=args.patient_id, days=args.days)
    print(
        f"Seeded {count} events for {args.patient_id} "
        f"into the '{config.store.backend}' event store."
    )
    return 0


__all__ = [
    "DEFAULT_PATIENT_ID",
    "DEFAULT_DAYS",
    "generate_events",
    "to_records",
    "seed_event_store",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
