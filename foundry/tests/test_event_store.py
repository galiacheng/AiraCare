"""EventStore tests — the append-only filed-event log the batch agents read."""

from __future__ import annotations

from datetime import datetime, timezone

from airacare_foundry.contracts import DailyLivingEvent
from airacare_foundry.store.base import EventStore, RecordedEvent
from airacare_foundry.store.local import LocalEventStore


def _rec(day: int, patient_id: str = "p-001", level: str = "L0") -> RecordedEvent:
    return RecordedEvent(
        event=DailyLivingEvent(
            type="routine",
            confidence=0.9,
            timestamp=datetime(2026, 7, day, 9, 0, tzinfo=timezone.utc),
            patient_id=patient_id,
            features=[0.5],
            baseline_deviation=0.1,
        ),
        considered_level=level,  # type: ignore[arg-type]
    )


def test_local_event_store_satisfies_protocol() -> None:
    assert isinstance(LocalEventStore(), EventStore)


def test_append_and_list_ordered_by_timestamp() -> None:
    store = LocalEventStore(":memory:")
    store.append(_rec(3))
    store.append(_rec(1))
    store.append(_rec(2))
    got = store.list_for_patient("p-001")
    assert [r.event.timestamp.day for r in got] == [1, 2, 3]


def test_list_filters_by_patient() -> None:
    store = LocalEventStore(":memory:")
    store.append(_rec(1, patient_id="p-001"))
    store.append(_rec(1, patient_id="p-002"))
    assert len(store.list_for_patient("p-001")) == 1
    assert len(store.list_for_patient("p-002")) == 1


def test_window_since_inclusive_until_exclusive() -> None:
    store = LocalEventStore(":memory:")
    for d in (1, 2, 3, 4):
        store.append(_rec(d))
    since = datetime(2026, 7, 2, tzinfo=timezone.utc)
    until = datetime(2026, 7, 4, tzinfo=timezone.utc)
    got = store.list_for_patient("p-001", since=since, until=until)
    assert [r.event.timestamp.day for r in got] == [2, 3]


def test_roundtrip_preserves_considered_level() -> None:
    store = LocalEventStore(":memory:")
    store.append(_rec(1, level="L3"))
    assert store.list_for_patient("p-001")[0].considered_level == "L3"
