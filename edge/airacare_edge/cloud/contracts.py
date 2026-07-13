"""Data contracts shared across the edge agent and the cloud boundary.

Only :class:`DailyLivingEvent` crosses the privacy boundary to the cloud. It is built
exclusively from these typed models, so it is structurally impossible to attach raw
audio/video to the uplink.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal["fall", "wander", "med", "meal", "routine"]
EdgeActionTaken = Literal["none", "prompted", "local_alert"]
Grade = Literal["L0", "L1", "L2", "L3"]
ReplyStatus = Literal["ok", "distress", "unclear", "no_response"]
ActionChannel = Literal["log", "family", "community", "emergency"]


def utcnow() -> datetime:
    """Timezone-aware current UTC timestamp (never use naive datetimes)."""
    return datetime.now(timezone.utc)


class DailyLivingEvent(BaseModel):
    """The unified event abstraction — the ONLY thing that crosses to the cloud."""

    type: EventType
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: datetime
    patient_id: str
    features: list[float] = Field(default_factory=list)  # privacy-scrubbed; never raw audio
    baseline_deviation: float = Field(ge=0.0, le=1.0)
    edge_action_taken: EdgeActionTaken = "none"
    context: dict[str, Any] = Field(default_factory=dict)


class ReplyIntent(BaseModel):
    """Interpretation of the patient's spoken reply to the active-confirm prompt."""

    status: ReplyStatus
    urgency: float = Field(ge=0.0, le=1.0, default=0.0)
    transcript: str | None = None


class CloudAction(BaseModel):
    """A single action the cloud decision asks to be taken."""

    channel: ActionChannel
    message: str
    target: str | None = None


class EdgeDirective(BaseModel):
    """Instruction the cloud sends back to the edge (e.g. an L1 voice prompt to speak)."""

    voice_prompt: str | None = None


class CloudDecision(BaseModel):
    """Graded, explainable decision returned by the cloud (stub or Foundry)."""

    grade: Grade
    reason: str
    actions: list[CloudAction] = Field(default_factory=list)
    edge_directive: EdgeDirective = Field(default_factory=EdgeDirective)
