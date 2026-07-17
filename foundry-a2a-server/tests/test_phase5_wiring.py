"""Phase 5 wiring — report files events; orchestrator exposes trend + briefings end-to-end."""

from __future__ import annotations

from datetime import date, datetime, timezone

from airacare_foundry.agents.deliberate import DeliberateTier
from airacare_foundry.contracts import DailyLivingEvent
from airacare_foundry.orchestrator import CareOrchestrator
from airacare_foundry.store.local import LocalEventStore, seeded_local_store


def _event(day: int, score: float) -> DailyLivingEvent:
    return DailyLivingEvent(
        type="routine",
        confidence=0.9,
        timestamp=datetime(2026, 7, day, 9, 0, tzinfo=timezone.utc),
        patient_id="p-001",
        features=[score],
        baseline_deviation=0.1,
    )


def _orchestrator() -> CareOrchestrator:
    event_store = LocalEventStore(":memory:")
    tier = DeliberateTier(enabled=True, event_store=event_store)
    return CareOrchestrator(
        seeded_local_store(":memory:"), deliberate=tier, event_store=event_store
    )


def test_report_files_events_for_batch_agents() -> None:
    orch = _orchestrator()
    for d, score in enumerate([0.7, 0.65, 0.6, 0.55, 0.5], start=1):
        orch.report(_event(d, score))

    trend = orch.cognitive_trend("p-001")
    assert trend.n_samples == 5
    assert trend.direction == "declining"


def test_family_and_clinician_briefings_from_reports() -> None:
    orch = _orchestrator()
    for d, score in enumerate([0.7, 0.65, 0.6], start=1):
        orch.report(_event(d, score))

    family = orch.family_briefing("p-001", date(2026, 7, 1))
    assert family.event_count == 1

    clinician = orch.clinician_briefing("p-001", 2026, 7)
    assert clinician.event_count == 3
    assert clinician.trend is not None


def test_disabled_deliberate_files_nothing() -> None:
    # Default orchestrator has the deliberate tier disabled; nothing is filed.
    orch = CareOrchestrator(seeded_local_store(":memory:"))
    orch.report(_event(1, 0.7))
    assert orch.cognitive_trend("p-001").n_samples == 0
