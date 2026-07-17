"""Analytics the dashboard renders — cognitive trajectory, briefings, and flattened event rows.

All of it is **compute, not tokens**: it reduces each event's privacy-scrubbed voice-biomarker
features to a scalar index and least-squares-fits it over time (Cognitive-Trend), rolls filed
events up into family/clinician briefings, and flattens events into stable rows for the raw-events
table. These mirror the batch agents the hosted agent runs off the safety path, so the dashboard
numbers match the rest of the system.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Literal

from pydantic import BaseModel, Field

from airacare_dashboard.stores import EventStore, RecordedEvent

TrendDirection = Literal["improving", "stable", "declining", "unknown"]
Audience = Literal["family", "clinician"]

# Biomarker slope (index units per day) within +/- this band counts as clinically stable.
DEFAULT_STABLE_BAND = 0.003

# Human-readable, plain-language labels for the flagship event types (family briefing).
_TYPE_LABEL = {
    "wander": "wandering",
    "fall": "a possible fall",
    "med": "a medication moment",
    "meal": "a meal",
    "routine": "routine activity",
}
_LEVEL_LABEL = {"L0": "logged", "L1": "gentle check", "L2": "alerted", "L3": "escalated"}


def default_biomarker(record: RecordedEvent) -> float:
    """Reduce one event to a scalar cognitive index in [0, 1] (higher = better)."""
    features = record.event.features
    if features:
        return sum(features) / len(features)
    return 1.0 - record.event.baseline_deviation


# --------------------------------------------------------------------------------------------
# Cognitive trend
# --------------------------------------------------------------------------------------------


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


# --------------------------------------------------------------------------------------------
# Briefings
# --------------------------------------------------------------------------------------------


class Briefing(BaseModel):
    """A generated report for a given audience over a time window."""

    patient_id: str
    audience: Audience
    period: str  # e.g. "2026-07-15" (daily) or "2026-07" (monthly)
    window_start: datetime
    window_end: datetime
    event_count: int = 0
    counts_by_type: dict[str, int] = Field(default_factory=dict)
    counts_by_level: dict[str, int] = Field(default_factory=dict)
    highlights: list[str] = Field(default_factory=list)
    trend: CognitiveTrend | None = None
    summary: str = ""


class BriefingAgent:
    """Composes family-daily and clinician-monthly briefings from filed events."""

    def __init__(
        self,
        event_store: EventStore,
        trend_agent: CognitiveTrendAgent | None = None,
        *,
        enabled: bool = True,
    ) -> None:
        self._store = event_store
        self._trend = trend_agent or CognitiveTrendAgent(event_store)
        self.enabled = enabled

    def family_daily(self, patient_id: str, day: date | None = None) -> Briefing:
        """A reassuring plain-language recap of a single day (UTC)."""
        day = day or datetime.now(timezone.utc).date()
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        records = self._store.list_for_patient(patient_id, since=start, until=end)

        by_type, by_level = self._counts(records)
        highlights = [self._family_line(r) for r in records if r.considered_level != "L0"]
        summary = self._family_summary(patient_id, records, by_level)
        return Briefing(
            patient_id=patient_id,
            audience="family",
            period=day.isoformat(),
            window_start=start,
            window_end=end,
            event_count=len(records),
            counts_by_type=by_type,
            counts_by_level=by_level,
            highlights=highlights,
            summary=summary,
        )

    def clinician_monthly(self, patient_id: str, year: int, month: int) -> Briefing:
        """A clinical roll-up over a calendar month, including the cognitive trajectory."""
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        end = (
            datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            if month == 12
            else datetime(year, month + 1, 1, tzinfo=timezone.utc)
        )
        records = self._store.list_for_patient(patient_id, since=start, until=end)

        by_type, by_level = self._counts(records)
        trend = self._trend.analyze(patient_id, since=start, until=end)
        highlights = self._clinician_highlights(by_type, by_level, trend)
        summary = self._clinician_summary(patient_id, records, trend)
        return Briefing(
            patient_id=patient_id,
            audience="clinician",
            period=f"{year:04d}-{month:02d}",
            window_start=start,
            window_end=end,
            event_count=len(records),
            counts_by_type=by_type,
            counts_by_level=by_level,
            highlights=highlights,
            trend=trend,
            summary=summary,
        )

    @staticmethod
    def _counts(records: list[RecordedEvent]) -> tuple[dict[str, int], dict[str, int]]:
        by_type: dict[str, int] = {}
        by_level: dict[str, int] = {}
        for r in records:
            by_type[r.event.type] = by_type.get(r.event.type, 0) + 1
            by_level[r.considered_level] = by_level.get(r.considered_level, 0) + 1
        return by_type, by_level

    @staticmethod
    def _family_line(record: RecordedEvent) -> str:
        when = record.event.timestamp.strftime("%H:%M")
        what = _TYPE_LABEL.get(record.event.type, record.event.type)
        did = _LEVEL_LABEL.get(record.considered_level, record.considered_level)
        return f"{when} — {what} ({did})"

    @staticmethod
    def _family_summary(
        patient_id: str, records: list[RecordedEvent], by_level: dict[str, int]
    ) -> str:
        if not records:
            return "A calm day — no notable events were recorded."
        concerns = sum(by_level.get(lvl, 0) for lvl in ("L2", "L3"))
        if concerns == 0:
            return (
                f"A settled day with {len(records)} everyday moments and nothing that "
                "needed a caregiver alert."
            )
        return (
            f"{len(records)} moments today; {concerns} needed a caregiver alert. "
            "See the highlights below."
        )

    @staticmethod
    def _clinician_highlights(
        by_type: dict[str, int], by_level: dict[str, int], trend: CognitiveTrend
    ) -> list[str]:
        highlights = [f"Cognitive trajectory: {trend.summary}"]
        wanders = by_type.get("wander", 0)
        if wanders:
            highlights.append(f"{wanders} wandering event(s) this month.")
        escalated = by_level.get("L3", 0)
        if escalated:
            highlights.append(f"{escalated} event(s) reached L3 escalation.")
        return highlights

    @staticmethod
    def _clinician_summary(
        patient_id: str, records: list[RecordedEvent], trend: CognitiveTrend
    ) -> str:
        if not records:
            return "No events filed this month; cognitive trajectory indeterminate."
        return (
            f"{len(records)} events filed this month for {patient_id}. "
            f"Voice-biomarker trajectory is {trend.direction} "
            f"({trend.slope_per_day:+.4f} index/day, n={trend.n_samples})."
        )


# --------------------------------------------------------------------------------------------
# Flattened rows (raw-events table)
# --------------------------------------------------------------------------------------------


def record_to_row(record: RecordedEvent) -> dict[str, object]:
    """Flatten one recorded event into a dashboard-friendly row (privacy-scrubbed only)."""
    event = record.event
    ctx = event.context
    return {
        "date": event.timestamp.date().isoformat(),
        "time": event.timestamp.strftime("%H:%M"),
        "timestamp": event.timestamp.isoformat(),
        "patient_id": event.patient_id,
        "type": event.type,
        "considered_level": record.considered_level,
        "edge_assessed_level": event.edge_assessed_level,
        "baseline_deviation": round(event.baseline_deviation, 4),
        "biomarker": round(default_biomarker(record), 4),
        "time_of_day": ctx.get("time_of_day", ""),
        "door_open": bool(ctx.get("door_open", False)),
        "response": ctx.get("response", ""),
    }


__all__ = [
    "TrendDirection",
    "Audience",
    "DEFAULT_STABLE_BAND",
    "default_biomarker",
    "CognitiveTrend",
    "CognitiveTrendAgent",
    "Briefing",
    "BriefingAgent",
    "record_to_row",
]
