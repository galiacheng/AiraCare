"""Rule-based classifier that turns raw sensor events into a DailyLivingEvent.

The flagship recognizes the *wander* pattern: an out-of-bed event correlated with a
door-open within a short window, weighted by nighttime context and baseline drift.
Classification is deliberately deterministic (no LLM) so the live demo is reliable.
"""

from __future__ import annotations

from datetime import datetime

from airacare_edge.cloud.contracts import DailyLivingEvent
from airacare_edge.reasoning.baseline import BaselineTracker
from airacare_edge.sensors.events import RawSensorEvent


class WanderClassifier:
    def __init__(self, baseline: BaselineTracker, correlation_window_seconds: float) -> None:
        self._baseline = baseline
        self._window = correlation_window_seconds

    def classify(
        self,
        events: list[RawSensorEvent],
        patient_id: str,
        now: datetime,
    ) -> DailyLivingEvent | None:
        """Return a candidate wander event, or None if the pattern is absent.

        ``edge_action_taken`` and the ``response`` context are filled in later by the
        agent once the active voice confirmation has run.
        """
        window = self._events_in_window(events)
        has_out_of_bed = any(event.kind == "out_of_bed" for event in window)
        has_door_open = any(event.kind == "door_open" for event in window)
        if not (has_out_of_bed and has_door_open):
            return None

        is_night = self._baseline.is_quiet_hour(now)
        confidence = 0.6 + 0.2  # out-of-bed + door correlated
        if is_night:
            confidence += 0.1
        confidence = min(confidence, 0.99)

        return DailyLivingEvent(
            type="wander",
            confidence=confidence,
            timestamp=now,
            patient_id=patient_id,
            features=[],
            baseline_deviation=self._baseline.deviation(window, now),
            edge_action_taken="none",
            context={
                "time_of_day": "night" if is_night else "day",
                "door_open": has_door_open,
                "response": "pending",
            },
        )

    def _events_in_window(self, events: list[RawSensorEvent]) -> list[RawSensorEvent]:
        if not events:
            return []
        latest = max(event.timestamp for event in events)
        return [
            event
            for event in events
            if (latest - event.timestamp).total_seconds() <= self._window
        ]
