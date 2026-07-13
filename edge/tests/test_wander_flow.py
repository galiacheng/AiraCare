"""End-to-end tests for the flagship Nighttime Wandering flow.

These exercise the Edge Core FSM with in-memory fakes for voice/cloud/alerts — no mic,
no LLM, no network — so the core decision logic can be reviewed and regression-tested.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from airacare_edge.agent import AlertSink, EdgeAgent, VoiceService
from airacare_edge.cloud.contracts import DailyLivingEvent, ReplyIntent
from airacare_edge.cloud.stub import LocalStubCloudClient
from airacare_edge.config import (
    EdgeConfig,
    PatientConfig,
    QuietHours,
    Thresholds,
)
from airacare_edge.reasoning.baseline import BaselineTracker
from airacare_edge.reasoning.classifier import WanderClassifier
from airacare_edge.sensors.simulator import (
    nighttime_wander_events,
    restless_but_in_bed_events,
)

NIGHT = datetime(2026, 7, 13, 3, 0, 0, tzinfo=timezone.utc)
DAY = datetime(2026, 7, 13, 14, 0, 0, tzinfo=timezone.utc)


class FakeVoice(VoiceService):
    def __init__(self, reply: str | None, intent: ReplyIntent | None = None) -> None:
        self._reply = reply
        self._intent = intent
        self.said: list[str] = []

    def say(self, text: str) -> None:
        self.said.append(text)

    def listen(self, timeout: float) -> str | None:
        return self._reply

    def interpret(self, transcript: str) -> ReplyIntent:
        return self._intent or ReplyIntent(status="unclear", transcript=transcript)


class FakeAlerts(AlertSink):
    def __init__(self) -> None:
        self.local_alerts: list[DailyLivingEvent] = []
        self.sms: list[DailyLivingEvent] = []

    def local_alert(self, event: DailyLivingEvent, reason: str) -> None:
        self.local_alerts.append(event)

    def notify_kin_sms(self, event: DailyLivingEvent, reason: str) -> None:
        self.sms.append(event)


def _config() -> EdgeConfig:
    return EdgeConfig(
        patient=PatientConfig(id="p-001", name="Grandpa Zhang", disease_stage="moderate"),
        quiet_hours=QuietHours(start="22:00", end="07:00"),
        thresholds=Thresholds(
            wander_confidence=0.7,
            no_response_seconds=8,
            correlation_window_seconds=120,
        ),
    )


def _build_agent(
    voice: VoiceService,
    alerts: FakeAlerts,
    *,
    online: bool = True,
    now: datetime = NIGHT,
) -> EdgeAgent:
    config = _config()
    baseline = BaselineTracker(config.quiet_hours)
    classifier = WanderClassifier(baseline, config.thresholds.correlation_window_seconds)
    cloud = LocalStubCloudClient(online=online)
    return EdgeAgent(
        config=config,
        voice=voice,
        cloud=cloud,
        alerts=alerts,
        classifier=classifier,
        clock=lambda: now,
    )


def test_no_response_escalates_to_L3():
    alerts = FakeAlerts()
    agent = _build_agent(FakeVoice(reply=None), alerts)

    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))

    assert result.handled
    assert result.path == "cloud_L3"
    assert result.event is not None
    assert result.event.type == "wander"
    assert result.event.edge_action_taken == "prompted"
    assert result.event.context["response"] == "no_response"
    assert result.cloud_decision is not None
    assert result.cloud_decision.grade == "L3"
    assert any(a.channel == "family" for a in result.cloud_decision.actions)


def test_patient_ok_gets_L1_voice_loopback():
    voice = FakeVoice(reply="I'm fine", intent=ReplyIntent(status="ok", urgency=0.1))
    agent = _build_agent(voice, FakeAlerts())

    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))

    assert result.path == "cloud_L1"
    assert result.cloud_decision is not None
    assert result.cloud_decision.grade == "L1"
    prompt = result.cloud_decision.edge_directive.voice_prompt
    assert prompt is not None
    # The L1 prompt is looped back and spoken by the edge (2nd utterance after confirm).
    assert prompt in voice.said


def test_distress_escalates_to_L3():
    voice = FakeVoice(reply="help me", intent=ReplyIntent(status="distress", urgency=0.95))
    agent = _build_agent(voice, FakeAlerts())

    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))

    assert result.path == "cloud_L3"
    assert result.event.context["response"] == "distress"


def test_offline_triggers_local_fallback():
    alerts = FakeAlerts()
    agent = _build_agent(FakeVoice(reply=None), alerts, online=False)

    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))

    assert result.handled
    assert result.offline
    assert result.path == "offline_fallback"
    assert result.cloud_decision is None
    assert result.event.edge_action_taken == "local_alert"
    assert len(alerts.local_alerts) == 1
    assert len(alerts.sms) == 1


def test_minor_motion_stays_below_threshold():
    agent = _build_agent(FakeVoice(reply=None), FakeAlerts())

    result = agent.handle_sensor_events(restless_but_in_bed_events(at=NIGHT))

    assert not result.handled
    assert result.path == "below_threshold"
    assert result.cloud_decision is None


def test_daytime_wander_still_detected_but_lower_confidence():
    # Same pattern in the daytime is still a wander candidate, just less anomalous.
    agent = _build_agent(FakeVoice(reply=None), FakeAlerts(), now=DAY)

    result = agent.handle_sensor_events(nighttime_wander_events(at=DAY))

    assert result.event is not None
    assert result.event.type == "wander"
    assert result.event.context["time_of_day"] == "day"


@pytest.mark.parametrize(
    "reply,intent_status,expected_grade",
    [
        (None, "no_response", "L3"),
        ("help", "distress", "L3"),
        ("I'm okay", "ok", "L1"),
        ("mmm the garden", "unclear", "L2"),
    ],
)
def test_reply_grade_matrix(reply, intent_status, expected_grade):
    intent = ReplyIntent(status=intent_status) if reply is not None else None
    agent = _build_agent(FakeVoice(reply=reply, intent=intent), FakeAlerts())

    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))

    assert result.cloud_decision is not None
    assert result.cloud_decision.grade == expected_grade
