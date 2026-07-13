"""A2A round-trip tests: the stub server + client speak the same contract, and the
EdgeAgent works end-to-end over real HTTP (localhost). Offline is handled gracefully.
"""

from __future__ import annotations

from datetime import datetime, timezone

from airacare_edge.agent import EdgeAgent
from airacare_edge.cloud.a2a_client import A2AClient
from airacare_edge.cloud.a2a_stub import A2AStubServer
from airacare_edge.cloud.contracts import DailyLivingEvent, ReplyIntent, utcnow
from airacare_edge.config import EdgeConfig, PatientConfig, QuietHours, Thresholds
from airacare_edge.reasoning.baseline import BaselineTracker
from airacare_edge.reasoning.classifier import WanderClassifier
from airacare_edge.sensors.simulator import nighttime_wander_events

# Reuse the fakes from the flow test module.
from tests.test_wander_flow import FakeAlerts, FakeVoice

NIGHT = datetime(2026, 7, 13, 3, 0, 0, tzinfo=timezone.utc)


def _wander_event(response: str) -> DailyLivingEvent:
    return DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=utcnow(),
        patient_id="p-001",
        baseline_deviation=0.95,
        edge_action_taken="prompted",
        context={"time_of_day": "night", "door_open": True, "response": response},
    )


def test_a2a_roundtrip_grades_l3():
    with A2AStubServer(port=0) as server:  # port 0 -> ephemeral free port
        client = A2AClient(server.endpoint)
        decision = client.submit(_wander_event("no_response"))
    assert decision is not None
    assert decision.grade == "L3"
    assert any(a.channel == "family" for a in decision.actions)


def test_a2a_roundtrip_grades_l1_with_prompt():
    with A2AStubServer(port=0) as server:
        client = A2AClient(server.endpoint)
        decision = client.submit(_wander_event("ok"))
    assert decision is not None
    assert decision.grade == "L1"
    assert decision.edge_directive.voice_prompt is not None


def test_a2a_offline_returns_none():
    # Nothing is listening on this port -> client returns None (edge will fall back).
    client = A2AClient("http://127.0.0.1:59997/a2a", timeout=0.5)
    assert client.submit(_wander_event("ok")) is None


def test_edge_agent_over_a2a_end_to_end():
    config = EdgeConfig(
        patient=PatientConfig(id="p-001", name="Grandpa Zhang", disease_stage="moderate"),
        quiet_hours=QuietHours(start="22:00", end="07:00"),
        thresholds=Thresholds(wander_confidence=0.7, no_response_seconds=8),
    )
    baseline = BaselineTracker(config.quiet_hours)
    classifier = WanderClassifier(baseline, config.thresholds.correlation_window_seconds)

    with A2AStubServer(port=0) as server:
        agent = EdgeAgent(
            config=config,
            voice=FakeVoice(reply=None),  # no response -> L3
            cloud=A2AClient(server.endpoint),
            alerts=FakeAlerts(),
            classifier=classifier,
            clock=lambda: NIGHT,
        )
        result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))

    assert result.handled
    assert result.path == "cloud_L3"
    assert not result.offline
    assert result.cloud_decision is not None
    assert result.cloud_decision.grade == "L3"


def test_edge_agent_a2a_offline_falls_back():
    config = EdgeConfig(
        patient=PatientConfig(id="p-001", name="Grandpa Zhang", disease_stage="moderate"),
        quiet_hours=QuietHours(start="22:00", end="07:00"),
        thresholds=Thresholds(wander_confidence=0.7, no_response_seconds=8),
    )
    baseline = BaselineTracker(config.quiet_hours)
    classifier = WanderClassifier(baseline, config.thresholds.correlation_window_seconds)
    alerts = FakeAlerts()

    # A2A endpoint with no server -> submit returns None -> local fallback.
    agent = EdgeAgent(
        config=config,
        voice=FakeVoice(reply=None),
        cloud=A2AClient("http://127.0.0.1:59996/a2a", timeout=0.5),
        alerts=alerts,
        classifier=classifier,
        clock=lambda: NIGHT,
    )
    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))

    assert result.offline
    assert result.path == "offline_fallback"
    assert result.event.edge_action_taken == "local_alert"
    assert len(alerts.local_alerts) == 1
