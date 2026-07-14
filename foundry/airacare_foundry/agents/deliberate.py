"""DELIBERATE tier — asynchronous multi-agent reasoning (STUB for this scaffold).

The real deliberate tier hosts the Connected Agents (Risk-Reasoning / Knowledge /
Escalation / Cognitive-Trend / Briefing; see foundry-design.md §5) that fuse events over
time, ground advice in knowledge, and drive the cloud-owned timed escalation ladder. In
this scaffold it is a fire-and-forget placeholder: the orchestrator schedules it after
answering the synchronous reflex assessment, and it never blocks or affects that response.
"""

from __future__ import annotations

from airacare_foundry.contracts import DailyLivingEvent
from airacare_foundry.store.base import PatientState


class DeliberateTier:
    """Fire-and-forget async reasoning stub.

    ``enabled`` mirrors ``config.deliberate.enabled``; when off, :meth:`schedule` is a
    no-op. When on, it records the request (a real implementation would enqueue work for
    the Connected Agents). It intentionally does nothing that could delay the reflex reply.
    """

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled
        self.scheduled: list[str] = []  # patient_ids seen — visibility for tests/demo

    def schedule(self, event: DailyLivingEvent, state: PatientState | None = None) -> None:
        if not self.enabled:
            return
        # Placeholder: a real tier would hand this to the Connected Agents asynchronously.
        self.scheduled.append(event.patient_id)
