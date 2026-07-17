"""Escalation agent — the cloud-owned, ack-tracked notification ladder (T2, long-running).

L3 is not one message: it is an autonomous, timed ladder (design §8). The edge already fired
its *own* immediate local alert + SMS to next of kin the moment it graded L2/L3 — the cloud
does not blindly repeat that. Instead it runs the **ack-tracked multi-channel ladder**:

    family --(no ack within T_family)--> community --(no ack within T_community)--> emergency

Each rung notifies via the :class:`~airacare_care.notify.NotificationTool` and arms an ack
window on a :class:`~airacare_care.escalation_timer.Scheduler`. An acknowledgement resolves the
ladder and cancels the pending timer; a timeout advances to the next rung. The final rung
(emergency) is terminal. This is the concrete "long-running autonomous agent" and lives entirely
in T2 — it never touches the synchronous T1 response.

Pure stdlib; ported verbatim from ``foundry-a2a-server``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum

from airacare_care.contracts import ActionChannel, CloudAction, CloudAssessment, DailyLivingEvent
from airacare_care.escalation_timer import Scheduler, ThreadScheduler
from airacare_care.notify import NotificationTool


@dataclass(frozen=True)
class Rung:
    """One step of the ladder: a channel, the message, and the ack window before advancing."""

    channel: ActionChannel
    message: str
    ack_window_seconds: float  # ignored on the terminal rung


# Default ladder. The emergency rung is terminal (its ack window is unused).
DEFAULT_LADDER: tuple[Rung, ...] = (
    Rung("family", "Please check on the patient now.", 60.0),
    Rung("community", "No response from family — please assist.", 120.0),
    Rung("emergency", "Escalating to emergency services with location + event context.", 0.0),
)


class LadderStatus(str, Enum):
    RUNNING = "running"
    RESOLVED_ACK = "resolved_ack"
    ESCALATED_EMERGENCY = "escalated_emergency"


class EscalationSession:
    """A single running escalation for one L3 event — a small thread-safe state machine."""

    def __init__(
        self,
        event: DailyLivingEvent,
        *,
        notifier: NotificationTool,
        scheduler: Scheduler,
        rungs: tuple[Rung, ...] = DEFAULT_LADDER,
        contacts: dict[str, str] | None = None,
    ) -> None:
        self._event = event
        self._notifier = notifier
        self._scheduler = scheduler
        self._rungs = rungs
        self._contacts = contacts or {}
        self._lock = threading.Lock()
        self._index = -1
        self._timer: object | None = None
        self.status = LadderStatus.RUNNING
        self.fired: list[ActionChannel] = []  # channels notified, in order

    @property
    def current_channel(self) -> ActionChannel | None:
        return self.fired[-1] if self.fired else None

    def start(self) -> "EscalationSession":
        with self._lock:
            self._advance_locked()
        return self

    def acknowledge(self, by: str | None = None) -> bool:
        """Resolve the ladder on an ack; returns True if it was still running."""
        with self._lock:
            if self.status is not LadderStatus.RUNNING:
                return False
            self._cancel_timer_locked()
            self.status = LadderStatus.RESOLVED_ACK
            return True

    def _on_timeout(self) -> None:
        with self._lock:
            if self.status is not LadderStatus.RUNNING:
                return
            self._advance_locked()

    def _advance_locked(self) -> None:
        self._index += 1
        rung = self._rungs[self._index]
        self._notifier.notify(
            CloudAction(
                channel=rung.channel,
                message=rung.message,
                target=self._contacts.get(rung.channel),
            )
        )
        self.fired.append(rung.channel)
        if self._index >= len(self._rungs) - 1:  # terminal rung reached
            self.status = LadderStatus.ESCALATED_EMERGENCY
            self._timer = None
            return
        self._timer = self._scheduler.call_later(rung.ack_window_seconds, self._on_timeout)

    def _cancel_timer_locked(self) -> None:
        if self._timer is not None:
            self._scheduler.cancel(self._timer)
            self._timer = None


class EscalationAgent:
    """Starts an ack-tracked ladder for every L3 event; a no-op below L3."""

    def __init__(
        self,
        *,
        notifier: NotificationTool | None = None,
        scheduler: Scheduler | None = None,
        rungs: tuple[Rung, ...] = DEFAULT_LADDER,
        contacts: dict[str, str] | None = None,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self._notifier = notifier or NotificationTool()
        self._scheduler = scheduler or ThreadScheduler()
        self._rungs = rungs
        self._contacts = contacts or {}
        self.sessions: list[EscalationSession] = []  # visibility for tests/demo

    @property
    def notifier(self) -> NotificationTool:
        return self._notifier

    def handle(
        self, event: DailyLivingEvent, assessment: CloudAssessment | None = None
    ) -> EscalationSession | None:
        """Start a ladder when the considered (or edge) level is L3, else return None."""
        if not self.enabled:
            return None
        level = assessment.considered_level if assessment is not None else event.edge_assessed_level
        if level != "L3":
            return None
        session = EscalationSession(
            event,
            notifier=self._notifier,
            scheduler=self._scheduler,
            rungs=self._rungs,
            contacts=self._contacts,
        ).start()
        self.sessions.append(session)
        return session
