"""Data contracts shared across the edge agent and the cloud boundary.

Only :class:`DailyLivingEvent` crosses the privacy boundary to the cloud. It is a
*report* of what the edge saw AND already did (the edge decides and acts on its own;
the cloud never gates the action). The cloud returns an async :class:`CloudAssessment`
(with a ``policy_version`` piggyback hint) and, when policy changes, an
:class:`EdgePolicyUpdate` fetched lazily.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal["fall", "wander", "med", "meal", "routine"]
EdgeActionTaken = Literal["none", "reassured", "local_alert", "escalated"]
Grade = Literal["L0", "L1", "L2", "L3"]
ReplyStatus = Literal["ok", "distress", "unclear", "no_response"]
ActionChannel = Literal["log", "family", "community", "emergency"]
DiseaseStage = Literal["mild", "moderate", "severe"]


def utcnow() -> datetime:
    """Timezone-aware current UTC timestamp (never use naive datetimes)."""
    return datetime.now(timezone.utc)


class DailyLivingEvent(BaseModel):
    """The unified event abstraction — the ONLY thing that crosses to the cloud.

    It is a report: ``edge_assessed_level`` and ``edge_action_taken`` record the edge's
    own immediate decision and the action it already took.
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


class ReplyIntent(BaseModel):
    """Interpretation of the patient's spoken reply to the active-confirm prompt."""

    status: ReplyStatus
    urgency: float = Field(ge=0.0, le=1.0, default=0.0)
    transcript: str | None = None


class CloudAction(BaseModel):
    """A caregiver notification the cloud sent (informational — recorded on the edge)."""

    channel: ActionChannel
    message: str
    target: str | None = None


class CloudAssessment(BaseModel):
    """Cloud's async, *considered* view of a reported event — never gates the edge.

    ``policy_version`` is the piggyback hint: if it exceeds the edge's current version,
    the edge lazily fetches a new :class:`EdgePolicyUpdate`.
    """

    considered_level: Grade
    reason: str
    caregiver_notifications: list[CloudAction] = Field(default_factory=list)
    policy_version: int = 1
    report_ref: str | None = None


class EdgePolicyUpdate(BaseModel):
    """Control-plane feedback: tunes how the edge behaves for FUTURE events.

    Produced by the cloud's fusion / learning over accumulated events. Fetched lazily
    when a report's ``CloudAssessment.policy_version`` exceeds the edge's current version.
    """

    version: int
    issued_at: datetime = Field(default_factory=utcnow)
    patient_id: str
    wander_confidence: float | None = None
    no_response_seconds: float | None = None
    max_clarify_retries: int | None = None
    confirm_prompt: str | None = None
    reassure_prompt: str | None = None
    clarify_prompt: str | None = None
    disease_stage: DiseaseStage | None = None
    notes: str | None = None
