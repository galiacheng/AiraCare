"""Personal activity baseline + drift scoring (rule-based for the PoC).

Deviation reflects how anomalous the current events are versus the patient's own
routine. For the flagship we key off quiet-hours (nighttime out-of-bed + door is a
strong drift signal); a production version would learn per-patient rolling stats.
"""

from __future__ import annotations

from datetime import datetime, time

from airacare_edge.config import QuietHours
from airacare_edge.sensors.events import RawSensorEvent


def _parse_hhmm(value: str) -> time:
    hours, minutes = (int(part) for part in value.split(":"))
    return time(hour=hours, minute=minutes)


class BaselineTracker:
    """Tracks the patient's routine and scores how far an event set drifts from it."""

    def __init__(self, quiet_hours: QuietHours) -> None:
        self._start = _parse_hhmm(quiet_hours.start)
        self._end = _parse_hhmm(quiet_hours.end)

    def is_quiet_hour(self, moment: datetime) -> bool:
        """True if ``moment`` falls inside the (possibly wrap-around) quiet window."""
        current = moment.time()
        if self._start <= self._end:
            return self._start <= current < self._end
        # wrap-around window, e.g. 22:00 -> 07:00
        return current >= self._start or current < self._end

    def deviation(self, events: list[RawSensorEvent], moment: datetime) -> float:
        """Return a 0..1 drift score for the given events at ``moment``."""
        score = 0.3
        if self.is_quiet_hour(moment):
            score += 0.5
        if any(event.kind == "door_open" for event in events):
            score += 0.15
        return min(score, 1.0)
