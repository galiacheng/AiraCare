"""Event contract — the privacy-scrubbed :class:`DailyLivingEvent` the dashboard reads.

This is a trimmed, byte-compatible copy of the edge/hosted-agent ``DailyLivingEvent`` (the ONLY
thing that ever crosses the privacy boundary). The dashboard only *reads* filed events, so it
carries just this model plus the shared type aliases — never the request/response envelopes.

Keep the field set in sync with ``edge/airacare_edge/cloud/contracts.py`` and
``foundry-hosted-agent/src/airacare-care-orchestrator/airacare_care/contracts.py`` so the JSON
that the hosted agent writes to ``daily_event`` validates here field-for-field.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal["fall", "wander", "med", "meal", "routine"]
EdgeActionTaken = Literal["none", "reassured", "local_alert", "escalated"]
Grade = Literal["L0", "L1", "L2", "L3"]
DiseaseStage = Literal["mild", "moderate", "severe"]


def utcnow() -> datetime:
    """Timezone-aware current UTC timestamp (never use naive datetimes)."""
    return datetime.now(timezone.utc)


class DailyLivingEvent(BaseModel):
    """The unified event abstraction — the ONLY thing that crosses to the cloud.

    It is a report: ``edge_assessed_level`` and ``edge_action_taken`` record the edge's own
    immediate decision and the action it already took. Only privacy-scrubbed data is present
    (``features`` are derived floats — never raw audio/video/point-cloud).
    """

    type: EventType
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: datetime
    patient_id: str
    features: list[float] = Field(default_factory=list)  # privacy-scrubbed; never raw audio
    baseline_deviation: float = Field(ge=0.0, le=1.0)
    edge_assessed_level: Grade = "L0"  # the edge's OWN immediate decision
    edge_action_taken: EdgeActionTaken = "none"
    context: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "DailyLivingEvent",
    "EventType",
    "EdgeActionTaken",
    "Grade",
    "DiseaseStage",
    "utcnow",
]
