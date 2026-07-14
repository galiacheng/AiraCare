"""Background report worker — ships DailyLivingEvents to the cloud OFF the safety path.

The edge decides and acts synchronously; the cloud report is then **submitted** to this
worker and sent on a background thread. ``submit(event)`` returns immediately, so a slow
or unreachable cloud can never delay the patient-facing safety action. On success the
worker applies any piggybacked ``EdgePolicyUpdate``; offline, it persists the event to the
store-and-forward queue.

Reporting is therefore a side-effect, not a state in the edge FSM.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from airacare_edge.cloud.contracts import CloudAssessment, DailyLivingEvent


@dataclass
class ReportOutcome:
    """Result of one asynchronous report attempt (read after ``ReportWorker.join``)."""

    event: DailyLivingEvent
    reported: bool
    queued: bool = False
    assessment: CloudAssessment | None = None
    policy_applied_version: int | None = None


_SHUTDOWN = object()


class ReportWorker:
    """Serial background worker: ``submit`` is non-blocking; a daemon thread reports."""

    def __init__(self, handler: Callable[[DailyLivingEvent], ReportOutcome]) -> None:
        self._handler = handler
        self._queue: queue.Queue[object] = queue.Queue()
        self._cond = threading.Condition()
        self._pending = 0
        self.last_outcome: ReportOutcome | None = None
        self._thread = threading.Thread(
            target=self._loop, name="airacare-reporter", daemon=True
        )
        self._thread.start()

    def submit(self, event: DailyLivingEvent) -> None:
        """Enqueue an event for background reporting and return immediately."""
        with self._cond:
            self._pending += 1
        self._queue.put(event)

    def join(self, timeout: float | None = None) -> bool:
        """Block until all submitted reports are processed. Returns False on timeout."""
        with self._cond:
            deadline = None if timeout is None else time.monotonic() + timeout
            while self._pending > 0:
                if deadline is None:
                    self._cond.wait()
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    self._cond.wait(remaining)
            return True

    def close(self) -> None:
        """Stop the worker thread (best-effort; the thread is a daemon)."""
        self._queue.put(_SHUTDOWN)
        self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is _SHUTDOWN:
                return
            event: DailyLivingEvent = item  # type: ignore[assignment]
            try:
                self.last_outcome = self._handler(event)
            except Exception:  # noqa: BLE001 — a report error must never kill the worker
                self.last_outcome = ReportOutcome(event=event, reported=False)
            finally:
                with self._cond:
                    self._pending -= 1
                    if self._pending == 0:
                        self._cond.notify_all()
