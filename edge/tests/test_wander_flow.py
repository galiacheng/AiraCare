"""End-to-end tests for the flagship Nighttime Wandering flow.

The edge DECIDES and ACTS immediately (never waits for the cloud); the cloud returns an
async considered assessment. These exercise the Edge Core FSM with in-memory fakes.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from airacare_edge.agent import AlertSink, CloudGateway, EdgeAgent, VoiceService
from airacare_edge.cloud.contracts import (
    CloudAssessment,
    DailyLivingEvent,
    EdgePolicyUpdate,
    ReplyIntent,
)
from airacare_edge.config import EdgeConfig, PatientConfig, QuietHours, Thresholds
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
        self.escalations: list[DailyLivingEvent] = []

    def local_alert(self, event: DailyLivingEvent, reason: str) -> None:
        self.local_alerts.append(event)

    def notify_kin_sms(self, event: DailyLivingEvent, reason: str) -> None:
        self.sms.append(event)

    def escalate(self, event: DailyLivingEvent, reason: str) -> None:
        self.escalations.append(event)


class FakeCloud(CloudGateway):
    """In-memory CloudGateway: report -> CloudAssessment; fetch_policy -> policy."""

    def __init__(self, *, online: bool = True, policy: EdgePolicyUpdate | None = None) -> None:
        self.online = online
        self._policy = policy
        self.reported: list[DailyLivingEvent] = []

    def report(self, event: DailyLivingEvent) -> CloudAssessment | None:
        if not self.online:
            return None
        self.reported.append(event)
        version = self._policy.version if self._policy is not None else 1
        return CloudAssessment(
            considered_level=event.edge_assessed_level,
            reason="considered",
            policy_version=version,
        )

    def fetch_policy(self, patient_id: str, since_version: int) -> EdgePolicyUpdate | None:
        if self._policy is not None and self._policy.version > since_version:
            return self._policy
        return None


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
    cloud: CloudGateway | None = None,
    now: datetime = NIGHT,
) -> EdgeAgent:
    config = _config()
    baseline = BaselineTracker(config.quiet_hours)
    classifier = WanderClassifier(baseline, config.thresholds.correlation_window_seconds)
    return EdgeAgent(
        config=config,
        voice=voice,
        cloud=cloud or FakeCloud(online=True),
        alerts=alerts,
        classifier=classifier,
        clock=lambda: now,
    )


def test_no_response_edge_escalates_L3_and_acts_now():
    alerts = FakeAlerts()
    agent = _build_agent(FakeVoice(reply=None), alerts)

    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))

    assert result.handled
    assert result.path == "edge_L3"
    assert result.decision.level == "L3" and result.decision.action == "escalated"
    assert result.event.edge_assessed_level == "L3"
    assert result.event.edge_action_taken == "escalated"
    assert result.event.context["response"] == "no_response"
    assert len(alerts.escalations) == 1  # edge acted immediately
    assert result.reported
    assert result.assessment.considered_level == "L3"


def test_patient_ok_gets_L1_and_edge_reassures_locally():
    voice = FakeVoice(reply="I'm fine", intent=ReplyIntent(status="ok", urgency=0.1))
    agent = _build_agent(voice, FakeAlerts())

    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))

    assert result.path == "edge_L1"
    assert result.decision.action == "reassured"
    assert result.event.edge_action_taken == "reassured"
    assert result.decision.voice_prompt in voice.said  # edge spoke the reassure prompt


def test_distress_edge_escalates_L3():
    voice = FakeVoice(reply="help me", intent=ReplyIntent(status="distress", urgency=0.95))
    alerts = FakeAlerts()
    agent = _build_agent(voice, alerts)

    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))

    assert result.path == "edge_L3"
    assert len(alerts.escalations) == 1


def test_unclear_after_retry_L2_local_alert_and_sms():
    voice = FakeVoice(reply="mmm the garden", intent=ReplyIntent(status="unclear"))
    alerts = FakeAlerts()
    agent = _build_agent(voice, alerts)

    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))

    assert result.path == "edge_L2"
    assert result.event.edge_action_taken == "local_alert"
    assert len(alerts.local_alerts) == 1
    assert len(alerts.sms) == 1


def test_offline_edge_still_acts_and_queues_report(tmp_path):
    from airacare_edge.cloud.queue import OfflineQueue

    alerts = FakeAlerts()
    config = _config()
    baseline = BaselineTracker(config.quiet_hours)
    classifier = WanderClassifier(baseline, config.thresholds.correlation_window_seconds)
    queue = OfflineQueue(tmp_path / "q")
    agent = EdgeAgent(
        config=config,
        voice=FakeVoice(reply=None),
        cloud=FakeCloud(online=False),
        alerts=alerts,
        classifier=classifier,
        clock=lambda: NIGHT,
        queue=queue,
    )

    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))

    assert result.handled
    assert not result.reported
    assert len(alerts.escalations) == 1  # the EDGE still acted (L3)
    assert queue.count() == 1  # report persisted for store-and-forward


def test_minor_motion_stays_below_threshold():
    agent = _build_agent(FakeVoice(reply=None), FakeAlerts())

    result = agent.handle_sensor_events(restless_but_in_bed_events(at=NIGHT))

    assert not result.handled
    assert result.path == "below_threshold"


def test_daytime_wander_still_detected_but_lower_confidence():
    agent = _build_agent(FakeVoice(reply=None), FakeAlerts(), now=DAY)

    result = agent.handle_sensor_events(nighttime_wander_events(at=DAY))

    assert result.event is not None
    assert result.event.type == "wander"
    assert result.event.context["time_of_day"] == "day"


@pytest.mark.parametrize(
    "reply,intent_status,expected_level",
    [
        (None, "no_response", "L3"),
        ("help", "distress", "L3"),
        ("I'm okay", "ok", "L1"),
        ("mmm the garden", "unclear", "L2"),
    ],
)
def test_reply_level_matrix(reply, intent_status, expected_level):
    intent = ReplyIntent(status=intent_status) if reply is not None else None
    agent = _build_agent(FakeVoice(reply=reply, intent=intent), FakeAlerts())

    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))

    assert result.decision.level == expected_level
    assert result.event.edge_assessed_level == expected_level
