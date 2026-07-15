"""DELIBERATE tier — asynchronous multi-agent reasoning (T2).

The real deliberate tier hosts the Connected Agents (Risk-Reasoning / Knowledge / Escalation
/ Cognitive-Trend / Briefing / Policy-Learning; see foundry-design.md §5) that fuse events
over time, ground advice in knowledge, drive the cloud-owned timed escalation ladder, and
distill edge policy. It runs **off** the synchronous safety path: the orchestrator builds the
T1 considered assessment, then schedules this tier, which never blocks or alters that reply.

Execution is pluggable via a :class:`DeliberateExecutor`:

- :class:`InlineExecutor` (default) runs the job in-thread — deterministic for tests/demo.
- :class:`ThreadExecutor` runs jobs on a background worker so ``report`` returns immediately;
  ``join()`` drains it for tests.

Wired agents so far: :class:`~airacare_foundry.agents.policy_learning.PolicyLearningAgent`
(distills versioned edge policy), :class:`~airacare_foundry.agents.escalation.EscalationAgent`
(the ack-tracked family → community → emergency ladder for L3), and
:class:`~airacare_foundry.agents.knowledge.KnowledgeAgent` (grounds advice in care-guideline
RAG). Each scheduled event is also **filed** to the :class:`~airacare_foundry.store.base.EventStore`
so the batch Cognitive-Trend and Briefing agents (and the Power BI export) have history to read.
The remaining Connected Agents land in later phases.
"""

from __future__ import annotations

import queue
import threading
from typing import Callable, Protocol, runtime_checkable

from airacare_foundry.agents.escalation import EscalationAgent
from airacare_foundry.agents.knowledge import GroundedAdvice, KnowledgeAgent
from airacare_foundry.agents.policy_learning import PolicyLearningAgent
from airacare_foundry.contracts import CloudAssessment, DailyLivingEvent
from airacare_foundry.store.base import EventStore, PatientState, RecordedEvent


@runtime_checkable
class DeliberateExecutor(Protocol):
    """Runs a fire-and-forget T2 job; ``join`` awaits completion (for tests/shutdown)."""

    def submit(self, job: Callable[[], None]) -> None:
        ...

    def join(self) -> None:
        ...


class InlineExecutor:
    """Runs each job synchronously in the calling thread (deterministic default)."""

    def submit(self, job: Callable[[], None]) -> None:
        job()

    def join(self) -> None:
        return None


class ThreadExecutor:
    """Runs jobs on a single background daemon worker so ``report`` returns immediately."""

    def __init__(self) -> None:
        self._q: queue.Queue[Callable[[], None]] = queue.Queue()
        self._lock = threading.Lock()
        self._started = False
        self._thread = threading.Thread(target=self._loop, name="deliberate", daemon=True)

    def _ensure_started(self) -> None:
        with self._lock:
            if not self._started:
                self._started = True
                self._thread.start()

    def submit(self, job: Callable[[], None]) -> None:
        self._ensure_started()
        self._q.put(job)

    def _loop(self) -> None:
        while True:
            job = self._q.get()
            try:
                job()
            except Exception:  # noqa: BLE001 — a T2 failure must never crash the worker
                pass
            finally:
                self._q.task_done()

    def join(self) -> None:
        self._q.join()


class DeliberateTier:
    """Fire-and-forget async reasoning tier.

    ``enabled`` mirrors ``config.deliberate.enabled``; when off, :meth:`schedule` is a no-op.
    When on, it dispatches the wired agents through ``executor``, strictly after the T1
    response was built — nothing here can delay or alter that reply.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        policy_learning: PolicyLearningAgent | None = None,
        escalation: EscalationAgent | None = None,
        knowledge: KnowledgeAgent | None = None,
        event_store: EventStore | None = None,
        executor: DeliberateExecutor | None = None,
    ) -> None:
        self.enabled = enabled
        self._policy_learning = policy_learning
        self._escalation = escalation
        self._knowledge = knowledge
        self._event_store = event_store
        self._executor: DeliberateExecutor = executor or InlineExecutor()
        self.scheduled: list[str] = []  # patient_ids seen — visibility for tests/demo
        self.advice_log: list[GroundedAdvice] = []  # grounded advice produced — visibility

    def schedule(
        self,
        event: DailyLivingEvent,
        state: PatientState | None = None,
        assessment: CloudAssessment | None = None,
    ) -> None:
        if not self.enabled:
            return
        self.scheduled.append(event.patient_id)
        self._executor.submit(lambda: self._run(event, state, assessment))

    def _run(
        self,
        event: DailyLivingEvent,
        state: PatientState | None,
        assessment: CloudAssessment | None,
    ) -> None:
        # File the scrubbed event first so the batch trend/briefing agents can read it later.
        if self._event_store is not None:
            level = assessment.considered_level if assessment is not None else event.edge_assessed_level
            self._event_store.append(RecordedEvent(event=event, considered_level=level))
        if self._policy_learning is not None:
            self._policy_learning.observe(event, state)
        if self._knowledge is not None:
            advice = self._knowledge.advise(event, assessment)
            if advice is not None:
                self.advice_log.append(advice)
        if self._escalation is not None:
            self._escalation.handle(event, assessment)

    def join(self) -> None:
        """Await any in-flight async jobs (no-op for the inline executor)."""
        self._executor.join()
