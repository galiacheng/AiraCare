"""Escalation ladder: ack-tracked family -> community -> emergency, driven deterministically.

Uses :class:`ManualScheduler` so ack windows and advancement are asserted without wall-clock
sleeps. In the standard-A2A topology this ladder runs inside the hosted agent's
``ConsideredAssessmentMiddleware`` (pre-model, off the advisory path) and only ever for L3.
"""

from __future__ import annotations

from airacare_care import DEFAULT_LADDER, EscalationAgent, ManualScheduler, NotificationTool
from airacare_care.contracts import CloudAssessment, DailyLivingEvent, utcnow
from airacare_care.escalation import LadderStatus


def _event(level: str = "L3") -> DailyLivingEvent:
    return DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=utcnow(),
        patient_id="p-001",
        baseline_deviation=0.95,
        edge_assessed_level=level,  # type: ignore[arg-type]
        edge_action_taken="escalated",
        context={"time_of_day": "night", "door_open": True, "response": "no_response"},
    )


def _agent(scheduler: ManualScheduler, notifier: NotificationTool, **kw) -> EscalationAgent:
    return EscalationAgent(notifier=notifier, scheduler=scheduler, **kw)


def test_ladder_starts_at_family_on_l3() -> None:
    sched, notifier = ManualScheduler(), NotificationTool()
    session = _agent(sched, notifier).handle(_event("L3"))

    assert session is not None
    assert session.status is LadderStatus.RUNNING
    assert session.current_channel == "family"
    assert [a.channel for a in notifier.sent] == ["family"]


def test_ladder_advances_through_all_rungs_without_ack() -> None:
    sched, notifier = ManualScheduler(), NotificationTool()
    session = _agent(sched, notifier).handle(_event("L3"))

    sched.advance(DEFAULT_LADDER[0].ack_window_seconds)
    assert session.current_channel == "community"
    assert session.status is LadderStatus.RUNNING

    sched.advance(DEFAULT_LADDER[1].ack_window_seconds)
    assert session.current_channel == "emergency"
    assert session.status is LadderStatus.ESCALATED_EMERGENCY
    assert [a.channel for a in notifier.sent] == ["family", "community", "emergency"]


def test_single_advance_past_all_windows_walks_the_ladder() -> None:
    sched, notifier = ManualScheduler(), NotificationTool()
    session = _agent(sched, notifier).handle(_event("L3"))

    sched.advance(10_000)  # far past every ack window
    assert session.status is LadderStatus.ESCALATED_EMERGENCY
    assert [a.channel for a in notifier.sent] == ["family", "community", "emergency"]


def test_ack_resolves_and_stops_escalation() -> None:
    sched, notifier = ManualScheduler(), NotificationTool()
    session = _agent(sched, notifier).handle(_event("L3"))

    assert session.acknowledge(by="daughter") is True
    assert session.status is LadderStatus.RESOLVED_ACK

    sched.advance(10_000)  # a late timeout must not advance a resolved ladder
    assert [a.channel for a in notifier.sent] == ["family"]
    assert session.acknowledge() is False  # a second ack is a no-op


def test_ack_at_community_rung_stops_before_emergency() -> None:
    sched, notifier = ManualScheduler(), NotificationTool()
    session = _agent(sched, notifier).handle(_event("L3"))

    sched.advance(DEFAULT_LADDER[0].ack_window_seconds)  # -> community
    assert session.current_channel == "community"
    session.acknowledge(by="neighbor")

    sched.advance(10_000)
    assert session.status is LadderStatus.RESOLVED_ACK
    assert [a.channel for a in notifier.sent] == ["family", "community"]


def test_no_ladder_below_l3() -> None:
    sched, notifier = ManualScheduler(), NotificationTool()
    agent = _agent(sched, notifier)
    assert agent.handle(_event("L2")) is None
    assert agent.handle(_event("L1")) is None
    assert notifier.sent == []


def test_uses_considered_level_over_edge_level() -> None:
    # T1 refined the edge's L2 up to L3 -> the ladder should run on the considered level.
    sched, notifier = ManualScheduler(), NotificationTool()
    assessment = CloudAssessment(considered_level="L3", reason="refined")
    session = _agent(sched, notifier).handle(_event("L2"), assessment)
    assert session is not None
    assert session.current_channel == "family"


def test_contacts_are_attached_as_targets() -> None:
    sched, notifier = ManualScheduler(), NotificationTool()
    contacts = {"family": "+1-555-0100", "community": "watch", "emergency": "112"}
    _agent(sched, notifier, contacts=contacts).handle(_event("L3"))
    sched.advance(10_000)

    by_channel = {a.channel: a.target for a in notifier.sent}
    assert by_channel == contacts


def test_disabled_agent_does_nothing() -> None:
    sched, notifier = ManualScheduler(), NotificationTool()
    agent = _agent(sched, notifier, enabled=False)
    assert agent.handle(_event("L3")) is None
    assert notifier.sent == []
