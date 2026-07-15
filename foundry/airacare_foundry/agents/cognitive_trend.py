"""Cognitive-Trend agent — batch model of scrubbed voice-biomarker features → trajectory (T2).

Over weeks, the edge's per-event **voice-biomarker features** (privacy-scrubbed floats; never
raw audio) accumulate in the :class:`~airacare_foundry.store.base.EventStore`. This agent runs
*batch* (compute, not tokens): it reduces each event's features to a single cognitive-index
sample and least-squares-fits the samples against time to estimate a **slope per day** and a
direction (improving / stable / declining). The trajectory feeds the clinician briefing and the
Power BI dashboard; it is off the synchronous safety path.

The biomarker reducer is intentionally simple and deterministic so the demo + tests are stable:
the mean of the scrubbed features when present (higher = better articulation/fluency), falling
back to ``1 - baseline_deviation`` as a proxy when an event carries no features.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Literal

from pydantic import BaseModel

from airacare_foundry.store.base import EventStore, RecordedEvent

TrendDirection = Literal["improving", "stable", "declining", "unknown"]

# Biomarker slope (index units per day) within +/- this band counts as clinically stable.
DEFAULT_STABLE_BAND = 0.003


def default_biomarker(record: RecordedEvent) -> float:
    """Reduce one event to a scalar cognitive index in [0, 1] (higher = better)."""
    features = record.event.features
    if features:
        return sum(features) / len(features)
    return 1.0 - record.event.baseline_deviation


class CognitiveTrend(BaseModel):
    """A patient's cognitive trajectory distilled from voice-biomarker samples over time."""

    patient_id: str
    n_samples: int = 0
    window_start: datetime | None = None
    window_end: datetime | None = None
    latest_score: float | None = None
    mean_score: float | None = None
    slope_per_day: float = 0.0
    direction: TrendDirection = "unknown"
    summary: str = ""


class CognitiveTrendAgent:
    """Batch-models filed voice-biomarker features into a :class:`CognitiveTrend`."""

    def __init__(
        self,
        event_store: EventStore,
        *,
        enabled: bool = True,
        stable_band: float = DEFAULT_STABLE_BAND,
        biomarker: Callable[[RecordedEvent], float] = default_biomarker,
    ) -> None:
        self._store = event_store
        self.enabled = enabled
        self._stable_band = stable_band
        self._biomarker = biomarker

    def analyze(
        self,
        patient_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> CognitiveTrend:
        """Fit a cognitive trajectory for a patient over the optional time window."""
        if not self.enabled:
            return CognitiveTrend(patient_id=patient_id, summary="trend agent disabled")

        records = self._store.list_for_patient(patient_id, since=since, until=until)
        samples = [(r.event.timestamp, self._biomarker(r)) for r in records]
        if not samples:
            return CognitiveTrend(patient_id=patient_id, summary="no data in window")

        scores = [s for _, s in samples]
        start, end = samples[0][0], samples[-1][0]
        mean_score = sum(scores) / len(scores)
        latest = scores[-1]

        slope = self._slope_per_day(samples)
        direction = self._classify(len(samples), slope)
        return CognitiveTrend(
            patient_id=patient_id,
            n_samples=len(samples),
            window_start=start,
            window_end=end,
            latest_score=round(latest, 4),
            mean_score=round(mean_score, 4),
            slope_per_day=round(slope, 5),
            direction=direction,
            summary=self._summary(direction, slope, len(samples)),
        )

    def _slope_per_day(self, samples: list[tuple[datetime, float]]) -> float:
        """Ordinary least-squares slope of score vs. elapsed days (0.0 when degenerate)."""
        if len(samples) < 2:
            return 0.0
        origin = samples[0][0]
        xs = [(ts - origin).total_seconds() / 86400.0 for ts, _ in samples]
        ys = [s for _, s in samples]
        n = len(xs)
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        var_x = sum((x - mean_x) ** 2 for x in xs)
        if var_x == 0.0:  # all samples on the same day
            return 0.0
        cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        return cov / var_x

    def _classify(self, n_samples: int, slope: float) -> TrendDirection:
        if n_samples < 2:
            return "unknown"
        if slope > self._stable_band:
            return "improving"
        if slope < -self._stable_band:
            return "declining"
        return "stable"

    @staticmethod
    def _summary(direction: TrendDirection, slope: float, n: int) -> str:
        if direction == "unknown":
            return "Not enough samples to establish a trend."
        per_week = slope * 7.0
        return (
            f"Voice-biomarker trajectory is {direction} "
            f"({per_week:+.3f} index/week over {n} samples)."
        )


__all__ = [
    "CognitiveTrend",
    "CognitiveTrendAgent",
    "TrendDirection",
    "default_biomarker",
    "DEFAULT_STABLE_BAND",
]
