"""Cognitive-Trend agent tests — least-squares voice-biomarker trajectory over filed events."""

from __future__ import annotations

from datetime import datetime, timezone

from airacare_foundry.agents.cognitive_trend import CognitiveTrendAgent
from airacare_foundry.contracts import DailyLivingEvent
from airacare_foundry.store.base import RecordedEvent
from airacare_foundry.store.local import LocalEventStore
from airacare_foundry.tools.demo_seed import generate_events, to_records


def _store_with(scores: list[float], patient_id: str = "p-001") -> LocalEventStore:
    store = LocalEventStore(":memory:")
    for i, score in enumerate(scores):
        store.append(
            RecordedEvent(
                event=DailyLivingEvent(
                    type="routine",
                    confidence=0.9,
                    timestamp=datetime(2026, 7, i + 1, 9, 0, tzinfo=timezone.utc),
                    patient_id=patient_id,
                    features=[score],
                    baseline_deviation=0.1,
                ),
                considered_level="L0",
            )
        )
    return store


def test_declining_trajectory_from_demo_seed() -> None:
    store = LocalEventStore(":memory:")
    for r in to_records(generate_events()):
        store.append(r)
    trend = CognitiveTrendAgent(store).analyze("p-001")
    assert trend.n_samples == 38
    assert trend.direction == "declining"
    assert trend.slope_per_day < 0
    assert trend.latest_score is not None and trend.mean_score is not None


def test_improving_trajectory() -> None:
    trend = CognitiveTrendAgent(_store_with([0.5, 0.55, 0.6, 0.65, 0.7])).analyze("p-001")
    assert trend.direction == "improving"
    assert trend.slope_per_day > 0


def test_stable_trajectory_within_band() -> None:
    trend = CognitiveTrendAgent(_store_with([0.6, 0.6, 0.6, 0.6])).analyze("p-001")
    assert trend.direction == "stable"
    assert trend.slope_per_day == 0.0


def test_single_sample_is_unknown() -> None:
    trend = CognitiveTrendAgent(_store_with([0.6])).analyze("p-001")
    assert trend.direction == "unknown"
    assert trend.n_samples == 1


def test_no_data_returns_empty_trend() -> None:
    trend = CognitiveTrendAgent(LocalEventStore(":memory:")).analyze("nobody")
    assert trend.n_samples == 0
    assert trend.direction == "unknown"
    assert "no data" in trend.summary


def test_disabled_agent_short_circuits() -> None:
    trend = CognitiveTrendAgent(_store_with([0.5, 0.9]), enabled=False).analyze("p-001")
    assert trend.direction == "unknown"
    assert "disabled" in trend.summary


def test_biomarker_falls_back_to_baseline_when_no_features() -> None:
    store = LocalEventStore(":memory:")
    for i, dev in enumerate((0.1, 0.2, 0.3, 0.4)):  # rising deviation => worse => declining
        store.append(
            RecordedEvent(
                event=DailyLivingEvent(
                    type="routine",
                    confidence=0.9,
                    timestamp=datetime(2026, 7, i + 1, 9, 0, tzinfo=timezone.utc),
                    patient_id="p-001",
                    features=[],
                    baseline_deviation=dev,
                ),
                considered_level="L0",
            )
        )
    trend = CognitiveTrendAgent(store).analyze("p-001")
    assert trend.direction == "declining"
