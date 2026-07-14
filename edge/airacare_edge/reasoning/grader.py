"""Edge-side grader — the edge's OWN immediate L0-L3 decision and action.

The edge decides and acts autonomously; it never waits for the cloud. Rules are
deterministic and biased to escalate (for an Alzheimer's patient, silence/confusion is
itself a risk signal). The cloud later produces a *considered* assessment for records.

Mapping (for a confirmed wander candidate):
- reply ok        -> L1, reassure (speak a gentle guidance prompt locally)
- reply unclear   -> L2, local_alert (notify family to check)  [after the clarify loop]
- reply distress  -> L3, escalate (alarm + SMS + community/emergency)
- no response     -> L3, escalate
"""

from __future__ import annotations

from pydantic import BaseModel

from airacare_edge.cloud.contracts import EdgeActionTaken, Grade, ReplyIntent


class EdgeDecision(BaseModel):
    level: Grade
    action: EdgeActionTaken
    reason: str
    voice_prompt: str | None = None  # spoken locally for the reassure (L1) action


class EdgeGrader:
    def decide(self, intent: ReplyIntent, *, reassure_prompt: str) -> EdgeDecision:
        if intent.status == "ok":
            return EdgeDecision(
                level="L1",
                action="reassured",
                reason="patient responded and is okay",
                voice_prompt=reassure_prompt,
            )
        if intent.status == "unclear":
            return EdgeDecision(
                level="L2",
                action="local_alert",
                reason="unclear response after clarify — notify family to check",
            )
        # distress or no_response -> escalate
        return EdgeDecision(
            level="L3",
            action="escalated",
            reason=f"response={intent.status} -> high risk",
        )
