"""Offline store-and-forward queue tests: persist, flush, expiry, durability."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from airacare_edge.cloud.contracts import DailyLivingEvent
from airacare_edge.cloud.queue import OfflineQueue
from airacare_edge.cloud.stub import LocalStubCloudClient

T0 = datetime(2026, 7, 13, 3, 0, 0, tzinfo=timezone.utc)


def _event(pid: str = "p-001") -> DailyLivingEvent:
    return DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=T0,
        patient_id=pid,
        baseline_deviation=0.95,
        edge_action_taken="local_alert",
        context={"response": "no_response"},
    )


def test_enqueue_persists_and_survives_new_instance(tmp_path):
    q = OfflineQueue(tmp_path / "q", ttl_seconds=3600)
    q.enqueue(_event(), now=T0)
    q.enqueue(_event("p-002"), now=T0)
    assert q.count() == 2
    # A fresh instance over the same directory sees the pending events (durability).
    q2 = OfflineQueue(tmp_path / "q", ttl_seconds=3600)
    assert q2.count() == 2


def test_flush_online_sends_and_clears(tmp_path):
    q = OfflineQueue(tmp_path / "q", ttl_seconds=3600)
    q.enqueue(_event(), now=T0)
    q.enqueue(_event("p-002"), now=T0)

    result = q.flush(LocalStubCloudClient(online=True), now=T0)

    assert result.sent_count == 2
    assert result.remaining == 0
    assert q.count() == 0
    assert all(d.grade == "L3" for _, d in result.sent)


def test_flush_offline_keeps_events(tmp_path):
    q = OfflineQueue(tmp_path / "q", ttl_seconds=3600)
    q.enqueue(_event(), now=T0)

    result = q.flush(LocalStubCloudClient(online=False), now=T0)

    assert result.sent_count == 0
    assert result.remaining == 1
    assert q.count() == 1  # still persisted for the next attempt


def test_flush_drops_expired(tmp_path):
    q = OfflineQueue(tmp_path / "q", ttl_seconds=60)  # 1-minute TTL
    q.enqueue(_event(), now=T0)

    # Flush 2 minutes later -> event is expired and dropped (not sent).
    result = q.flush(LocalStubCloudClient(online=True), now=T0 + timedelta(minutes=2))

    assert result.sent_count == 0
    assert result.expired == 1
    assert q.count() == 0
