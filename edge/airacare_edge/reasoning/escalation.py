"""Edge-side escalation policy.

The edge does NOT grade risk (that is the cloud's job). It decides the local action
already taken (``edge_action_taken``) and whether the event warrants waking the cloud.
"""

from __future__ import annotations

from pydantic import BaseModel

from airacare_edge.cloud.contracts import EdgeActionTaken, ReplyIntent


class EdgeDecision(BaseModel):
    edge_action_taken: EdgeActionTaken
    escalate_to_cloud: bool
    reason: str


class EscalationPolicy:
    """Maps the interpreted reply to the edge's local action + escalation choice."""

    def decide(self, intent: ReplyIntent, *, prompted: bool) -> EdgeDecision:
        action: EdgeActionTaken = "prompted" if prompted else "none"
        # Any confirmed wander candidate is worth a cloud grade; the cloud decides L0-L3.
        return EdgeDecision(
            edge_action_taken=action,
            escalate_to_cloud=True,
            reason=f"reply={intent.status}, urgency={intent.urgency:.2f}",
        )
