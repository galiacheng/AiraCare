"""Escalation timers — the scheduling primitive behind the ack-tracked ladder.

The cloud-owned escalation ladder (family → community → emergency) arms an **ack window** on
each rung and advances when no acknowledgement arrives in time. That timing is abstracted
behind a tiny :class:`Scheduler` protocol so the same ladder runs two ways:

- :class:`ThreadScheduler` — real wall-clock timers (``threading.Timer``) for production/demo:
  the ladder is genuinely long-running and autonomous, off any request thread.
- :class:`ManualScheduler` — a deterministic fake for tests: callbacks fire only when the
  test advances virtual time, so ladder behavior is asserted without flaky ``sleep``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class Scheduler(Protocol):
    """Schedule a callback to run after ``delay`` seconds; return a cancellable handle."""

    def call_later(self, delay: float, fn: Callable[[], None]) -> object:
        ...

    def cancel(self, handle: object) -> None:
        ...


class ThreadScheduler:
    """Real scheduler backed by daemon :class:`threading.Timer` — fires on wall-clock time."""

    def call_later(self, delay: float, fn: Callable[[], None]) -> object:
        timer = threading.Timer(delay, fn)
        timer.daemon = True
        timer.start()
        return timer

    def cancel(self, handle: object) -> None:
        if isinstance(handle, threading.Timer):
            handle.cancel()


@dataclass
class _Scheduled:
    due: float
    fn: Callable[[], None]
    seq: int
    cancelled: bool = False


class ManualScheduler:
    """Deterministic scheduler: callbacks fire when :meth:`advance` passes their due time.

    Virtual time starts at 0. Callbacks scheduled *during* a callback (e.g. arming the next
    rung's timer) are honored within the same :meth:`advance` call, so a single advance past
    several ack windows walks the whole ladder.
    """

    def __init__(self) -> None:
        self._now = 0.0
        self._pending: list[_Scheduled] = []
        self._seq = 0

    @property
    def now(self) -> float:
        return self._now

    def call_later(self, delay: float, fn: Callable[[], None]) -> object:
        self._seq += 1
        item = _Scheduled(due=self._now + max(0.0, delay), fn=fn, seq=self._seq)
        self._pending.append(item)
        return item

    def cancel(self, handle: object) -> None:
        if isinstance(handle, _Scheduled):
            handle.cancelled = True

    def advance(self, seconds: float) -> None:
        """Advance virtual time by ``seconds``, firing due callbacks in due order."""
        target = self._now + seconds
        while True:
            due = [i for i in self._pending if not i.cancelled and i.due <= target]
            if not due:
                break
            nxt = min(due, key=lambda i: (i.due, i.seq))
            self._pending.remove(nxt)
            self._now = nxt.due
            nxt.fn()
        self._now = target
