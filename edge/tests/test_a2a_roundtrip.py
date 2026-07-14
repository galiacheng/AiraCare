"""A2A round-trip tests: the stub server + client speak the same contract (report +
fetch_policy), and the EdgeAgent works end-to-end over real HTTP (localhost).
"""

from __future__ import annotations

from datetime import datetime, timezone

from airacare_edge.agent import EdgeAgent
from airacare_edge.cloud.a2a_client import A2AClient
from airacare_edge.cloud.a2a_stub import A2AStubServer, _Handler
from airacare_edge.cloud.contracts import DailyLivingEvent, EdgePolicyUpdate, utcnow
from airacare_edge.cloud.stub import LocalCloudStub
from airacare_edge.config import EdgeConfig, PatientConfig, QuietHours, Thresholds
from airacare_edge.reasoning.baseline import BaselineTracker
from airacare_edge.reasoning.classifier import WanderClassifier
from airacare_edge.sensors.simulator import nighttime_wander_events

# Reuse the fakes from the flow test module.
from tests.test_wander_flow import FakeAlerts, FakeVoice

NIGHT = datetime(2026, 7, 13, 3, 0, 0, tzinfo=timezone.utc)


def _wander_event(response: str, level: str = "L3", action: str = "escalated") -> DailyLivingEvent:
    return DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=utcnow(),
        patient_id="p-001",
        baseline_deviation=0.95,
        edge_assessed_level=level,
        edge_action_taken=action,
        context={"time_of_day": "night", "door_open": True, "response": response},
    )


def test_a2a_report_roundtrip_returns_assessment():
    with A2AStubServer(port=0) as server:
        client = A2AClient(server.endpoint)
        assessment = client.report(_wander_event("no_response", "L3"))
    assert assessment is not None
    assert assessment.considered_level == "L3"
    assert any(a.channel == "family" for a in assessment.caregiver_notifications)


def test_a2a_fetch_policy_roundtrip():
    policy = EdgePolicyUpdate(version=7, patient_id="p-001", wander_confidence=0.6)
    # Point the shared handler gateway at a stub that has a v7 policy.
    _Handler.gateway = LocalCloudStub(policy=policy)
    try:
        with A2AStubServer(port=0) as server:
            client = A2AClient(server.endpoint)
            assert client.fetch_policy("p-001", since_version=1).version == 7
            assert client.fetch_policy("p-001", since_version=7) is None
    finally:
        _Handler.gateway = LocalCloudStub()


def test_a2a_offline_report_returns_none():
    client = A2AClient("http://127.0.0.1:59997/a2a", timeout=0.5)
    assert client.report(_wander_event("ok", "L1", "reassured")) is None


def test_edge_agent_over_a2a_end_to_end():
    config = EdgeConfig(
        patient=PatientConfig(id="p-001", name="Grandpa Zhang", disease_stage="moderate"),
        quiet_hours=QuietHours(start="22:00", end="07:00"),
        thresholds=Thresholds(wander_confidence=0.7, no_response_seconds=8),
    )
    baseline = BaselineTracker(config.quiet_hours)
    classifier = WanderClassifier(baseline, config.thresholds.correlation_window_seconds)
    alerts = FakeAlerts()

    with A2AStubServer(port=0) as server:
        agent = EdgeAgent(
            config=config,
            voice=FakeVoice(reply=None),  # no response -> edge L3
            cloud=A2AClient(server.endpoint),
            alerts=alerts,
            classifier=classifier,
            clock=lambda: NIGHT,
        )
        result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))

    assert result.handled
    assert result.path == "edge_L3"
    assert result.reported
    assert result.assessment is not None
    assert result.assessment.considered_level == "L3"
    assert len(alerts.escalations) == 1  # edge acted immediately


def test_edge_agent_a2a_offline_still_acts_and_queues(tmp_path):
    from airacare_edge.cloud.queue import OfflineQueue

    config = EdgeConfig(
        patient=PatientConfig(id="p-001", name="Grandpa Zhang", disease_stage="moderate"),
        quiet_hours=QuietHours(start="22:00", end="07:00"),
        thresholds=Thresholds(wander_confidence=0.7, no_response_seconds=8),
    )
    baseline = BaselineTracker(config.quiet_hours)
    classifier = WanderClassifier(baseline, config.thresholds.correlation_window_seconds)
    alerts = FakeAlerts()
    queue = OfflineQueue(tmp_path / "q")

    # A2A endpoint with no server -> report returns None -> edge already acted, report queued.
    agent = EdgeAgent(
        config=config,
        voice=FakeVoice(reply=None),
        cloud=A2AClient("http://127.0.0.1:59996/a2a", timeout=0.5),
        alerts=alerts,
        classifier=classifier,
        clock=lambda: NIGHT,
        queue=queue,
    )
    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))

    assert not result.reported
    assert result.event.edge_action_taken == "escalated"
    assert len(alerts.escalations) == 1
    assert queue.count() == 1
