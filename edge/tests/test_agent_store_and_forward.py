"""Agent-level store-and-forward: offline enqueues the event; reconnect re-sends it."""

from __future__ import annotations

from datetime import datetime, timezone

from airacare_edge.agent import EdgeAgent
from airacare_edge.cloud.queue import OfflineQueue
from airacare_edge.config import EdgeConfig, PatientConfig, QuietHours, Thresholds
from airacare_edge.reasoning.baseline import BaselineTracker
from airacare_edge.reasoning.classifier import WanderClassifier
from airacare_edge.sensors.simulator import nighttime_wander_events
from tests.test_wander_flow import FakeAlerts, FakeCloud, FakeVoice

NIGHT = datetime(2026, 7, 13, 3, 0, 0, tzinfo=timezone.utc)


def _config() -> EdgeConfig:
    return EdgeConfig(
        patient=PatientConfig(id="p-001", name="Grandpa Zhang", disease_stage="moderate"),
        quiet_hours=QuietHours(start="22:00", end="07:00"),
        thresholds=Thresholds(wander_confidence=0.7, no_response_seconds=8),
    )


def _agent(cloud, queue) -> EdgeAgent:
    config = _config()
    baseline = BaselineTracker(config.quiet_hours)
    classifier = WanderClassifier(baseline, config.thresholds.correlation_window_seconds)
    return EdgeAgent(
        config=config,
        voice=FakeVoice(reply=None),  # no response -> edge escalates (L3)
        cloud=cloud,
        alerts=FakeAlerts(),
        classifier=classifier,
        clock=lambda: NIGHT,
        queue=queue,
    )


def test_offline_enqueues_then_reconnect_resends(tmp_path):
    queue = OfflineQueue(tmp_path / "q", ttl_seconds=3600)

    # 1) Offline: report unreachable -> edge still acts, event persisted.
    result = _agent(FakeCloud(online=False), queue).handle_sensor_events(
        nighttime_wander_events(at=NIGHT)
    )
    assert not result.reported
    assert result.event.edge_action_taken == "escalated"
    assert queue.count() == 1  # persisted for later

    # 2) Connectivity restored: a new agent flushes the backlog to the cloud.
    flush = _agent(FakeCloud(online=True), queue).flush_offline_queue(now=NIGHT)
    assert flush is not None
    assert flush.sent_count == 1
    assert flush.remaining == 0
    assert queue.count() == 0
    assert flush.sent[0][1].considered_level == "L3"


def test_no_queue_still_works():
    # Agent without a queue still acts; the report is simply dropped when offline.
    agent = _agent(FakeCloud(online=False), queue=None)
    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))
    assert not result.reported
    assert agent.flush_offline_queue() is None
