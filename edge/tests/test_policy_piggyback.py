"""Policy piggyback: a report's CloudAssessment.policy_version triggers a lazy fetch+apply."""

from __future__ import annotations

from datetime import datetime, timezone

from airacare_edge.agent import EdgeAgent
from airacare_edge.cloud.contracts import EdgePolicyUpdate, ReplyIntent
from airacare_edge.config import EdgeConfig, PatientConfig, QuietHours, Thresholds
from airacare_edge.reasoning.baseline import BaselineTracker
from airacare_edge.reasoning.classifier import WanderClassifier
from airacare_edge.sensors.simulator import nighttime_wander_events
from tests.test_wander_flow import FakeAlerts, FakeCloud, FakeVoice

NIGHT = datetime(2026, 7, 13, 3, 0, 0, tzinfo=timezone.utc)


def _agent(cloud, policy_version: int = 1) -> EdgeAgent:
    config = EdgeConfig(
        patient=PatientConfig(id="p-001", name="Grandpa Zhang", disease_stage="moderate"),
        quiet_hours=QuietHours(start="22:00", end="07:00"),
        thresholds=Thresholds(wander_confidence=0.7, no_response_seconds=8),
    )
    baseline = BaselineTracker(config.quiet_hours)
    classifier = WanderClassifier(baseline, config.thresholds.correlation_window_seconds)
    return EdgeAgent(
        config=config,
        voice=FakeVoice(reply="I'm fine", intent=ReplyIntent(status="ok")),
        cloud=cloud,
        alerts=FakeAlerts(),
        classifier=classifier,
        clock=lambda: NIGHT,
        policy_version=policy_version,
    )


def test_new_policy_version_triggers_fetch_and_apply():
    policy = EdgePolicyUpdate(
        version=7,
        patient_id="p-001",
        reassure_prompt="Custom reassure prompt",
        wander_confidence=0.55,
        disease_stage="severe",
    )
    agent = _agent(FakeCloud(online=True, policy=policy), policy_version=1)

    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))
    agent.reporter.join(timeout=5.0)
    outcome = agent.reporter.last_outcome

    assert outcome.assessment.policy_version == 7
    assert outcome.policy_applied_version == 7
    assert agent.policy_version == 7
    # Applied to FUTURE behavior (config mutated).
    assert agent.config.voice.reassure_prompt == "Custom reassure prompt"
    assert agent.config.thresholds.wander_confidence == 0.55
    assert agent.config.patient.disease_stage == "severe"


def test_same_policy_version_no_apply():
    agent = _agent(FakeCloud(online=True), policy_version=1)  # stub reports policy_version=1

    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))
    agent.reporter.join(timeout=5.0)
    outcome = agent.reporter.last_outcome

    assert outcome.policy_applied_version is None
    assert agent.policy_version == 1


def test_offline_report_does_not_apply_policy(tmp_path):
    from airacare_edge.cloud.queue import OfflineQueue

    policy = EdgePolicyUpdate(version=9, patient_id="p-001", wander_confidence=0.5)
    agent = _agent(FakeCloud(online=False, policy=policy), policy_version=1)
    # Give it a queue so the (unreported) event is persisted rather than lost.
    agent._queue = OfflineQueue(tmp_path / "q")  # noqa: SLF001 (test wiring)

    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))
    agent.reporter.join(timeout=5.0)
    outcome = agent.reporter.last_outcome

    assert not outcome.reported
    assert outcome.policy_applied_version is None
    assert agent.policy_version == 1  # offline -> keep last-applied policy
