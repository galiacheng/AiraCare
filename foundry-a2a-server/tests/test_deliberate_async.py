"""Async deliberate-tier tests: T2 runs off the report thread; the T1 reply is unaffected.

The default :class:`InlineExecutor` keeps behavior deterministic; :class:`ThreadExecutor`
proves the tier can run on a background worker that ``join()`` drains. Either way the
synchronous ``report`` response is built before T2 runs and is never altered by it.
"""

from __future__ import annotations

from airacare_foundry.agents.deliberate import (
    DeliberateTier,
    InlineExecutor,
    ThreadExecutor,
)
from airacare_foundry.agents.escalation import EscalationAgent, LadderStatus
from airacare_foundry.agents.policy_learning import PolicyLearningAgent
from airacare_foundry.contracts import DailyLivingEvent, utcnow
from airacare_foundry.orchestrator import CareOrchestrator
from airacare_foundry.store.base import BASE_POLICY_VERSION
from airacare_foundry.tools.escalation_timer import ManualScheduler
from airacare_foundry.tools.notify import NotificationTool


def _night_wander(level: str = "L2", response: str = "unclear") -> DailyLivingEvent:
    return DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=utcnow(),
        patient_id="p-001",
        baseline_deviation=0.95,
        edge_assessed_level=level,  # type: ignore[arg-type]
        edge_action_taken="local_alert",
        context={"time_of_day": "night", "door_open": True, "response": response},
    )


def test_thread_executor_runs_and_drains() -> None:
    ran: list[str] = []
    executor = ThreadExecutor()
    for i in range(5):
        executor.submit(lambda i=i: ran.append(f"job-{i}"))
    executor.join()
    assert sorted(ran) == [f"job-{i}" for i in range(5)]


def test_inline_executor_runs_synchronously() -> None:
    ran: list[int] = []
    InlineExecutor().submit(lambda: ran.append(1))
    assert ran == [1]


def test_tier_disabled_is_noop() -> None:
    from airacare_foundry.store.local import LocalPolicyStore

    tier = DeliberateTier(
        enabled=False,
        policy_learning=PolicyLearningAgent(LocalPolicyStore(":memory:")),
    )
    tier.schedule(_night_wander())
    tier.join()
    assert tier.scheduled == []


def test_thread_executor_defers_policy_learning_until_join() -> None:
    from airacare_foundry.store.local import LocalPolicyStore, seeded_local_store

    policy_store = LocalPolicyStore(":memory:")
    learning = PolicyLearningAgent(policy_store, enabled=True)
    tier = DeliberateTier(enabled=True, policy_learning=learning, executor=ThreadExecutor())
    orch = CareOrchestrator(
        seeded_local_store(":memory:"), deliberate=tier, policy_store=policy_store
    )

    for _ in range(PolicyLearningAgent.WANDER_LEARN_THRESHOLD):
        orch.report(_night_wander())
    tier.join()  # await the background worker

    # After draining, the learned policy is visible.
    assert policy_store.get("p-001").version == BASE_POLICY_VERSION + 1


def test_thread_executor_runs_escalation_ladder() -> None:
    from airacare_foundry.store.local import LocalPolicyStore, seeded_local_store

    sched, notifier = ManualScheduler(), NotificationTool()
    escalation = EscalationAgent(notifier=notifier, scheduler=sched)
    tier = DeliberateTier(enabled=True, escalation=escalation, executor=ThreadExecutor())
    orch = CareOrchestrator(
        seeded_local_store(":memory:"), deliberate=tier, policy_store=LocalPolicyStore(":memory:")
    )

    assessment = orch.report(_night_wander(level="L3", response="no_response"))
    assert assessment.considered_level == "L3"  # T1 response unaffected by T2
    tier.join()

    assert len(escalation.sessions) == 1
    session = escalation.sessions[0]
    assert session.current_channel == "family"
    sched.advance(10_000)
    assert session.status is LadderStatus.ESCALATED_EMERGENCY
