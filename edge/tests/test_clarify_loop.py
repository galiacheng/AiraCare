"""Bounded clarify-loop tests for the Edge Core FSM (step 5).

On an ``unclear`` reply the agent re-asks once (``max_clarify_retries=1``) then escalates;
silence or distress on any attempt returns immediately.
"""

from __future__ import annotations

from datetime import datetime, timezone

from airacare_edge.agent import EdgeAgent, VoiceService
from airacare_edge.cloud.stub import LocalStubCloudClient
from airacare_edge.config import (
    EdgeConfig,
    PatientConfig,
    QuietHours,
    Thresholds,
    VoiceConfig,
)
from airacare_edge.reasoning.baseline import BaselineTracker
from airacare_edge.reasoning.classifier import WanderClassifier
from airacare_edge.sensors.simulator import nighttime_wander_events
from airacare_edge.voice.nlu import keyword_intent
from tests.test_wander_flow import FakeAlerts

NIGHT = datetime(2026, 7, 13, 3, 0, 0, tzinfo=timezone.utc)


class SequenceVoice(VoiceService):
    """Returns a scripted transcript per listen() call; interprets via keyword rules."""

    def __init__(self, replies: list[str | None]) -> None:
        self._replies = list(replies)
        self.said: list[str] = []

    def say(self, text: str) -> None:
        self.said.append(text)

    def listen(self, timeout: float) -> str | None:
        return self._replies.pop(0) if self._replies else None

    def interpret(self, transcript: str):
        return keyword_intent(transcript)


def _agent(voice: VoiceService, retries: int = 1) -> EdgeAgent:
    config = EdgeConfig(
        patient=PatientConfig(id="p-001", name="Grandpa Zhang", disease_stage="moderate"),
        quiet_hours=QuietHours(start="22:00", end="07:00"),
        thresholds=Thresholds(wander_confidence=0.7, no_response_seconds=8),
        voice=VoiceConfig(max_clarify_retries=retries),
    )
    baseline = BaselineTracker(config.quiet_hours)
    classifier = WanderClassifier(baseline, config.thresholds.correlation_window_seconds)
    return EdgeAgent(
        config=config,
        voice=voice,
        cloud=LocalStubCloudClient(),
        alerts=FakeAlerts(),
        classifier=classifier,
        clock=lambda: NIGHT,
    )


def _clarified(voice: SequenceVoice) -> bool:
    return any("didn't catch" in said.lower() for said in voice.said)


def test_clarify_then_ok_reasks_once_and_grades_l1():
    voice = SequenceVoice(["ummm the thing over there", "I'm fine"])
    result = _agent(voice).handle_sensor_events(nighttime_wander_events(at=NIGHT))
    assert result.cloud_decision.grade == "L1"
    assert _clarified(voice)  # the re-ask happened


def test_still_unclear_after_retry_grades_l2():
    voice = SequenceVoice(["ummm", "still confused"])
    result = _agent(voice).handle_sensor_events(nighttime_wander_events(at=NIGHT))
    assert result.event.context["response"] == "unclear"
    assert result.cloud_decision.grade == "L2"
    assert _clarified(voice)


def test_clarify_then_silence_grades_l3():
    voice = SequenceVoice(["ummm", None])  # unclear, then no response on re-ask
    result = _agent(voice).handle_sensor_events(nighttime_wander_events(at=NIGHT))
    assert result.event.context["response"] == "no_response"
    assert result.cloud_decision.grade == "L3"


def test_distress_on_first_reply_does_not_reask():
    voice = SequenceVoice(["help me please"])
    result = _agent(voice).handle_sensor_events(nighttime_wander_events(at=NIGHT))
    assert result.cloud_decision.grade == "L3"
    assert not _clarified(voice)


def test_zero_retries_escalates_immediately():
    voice = SequenceVoice(["ummm"])
    result = _agent(voice, retries=0).handle_sensor_events(nighttime_wander_events(at=NIGHT))
    assert result.event.context["response"] == "unclear"
    assert result.cloud_decision.grade == "L2"
    assert not _clarified(voice)  # no re-ask when retries=0
