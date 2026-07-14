"""In-process cloud stub — a Foundry stand-in that speaks the async gateway contract.

It receives an event *report* (the edge has already acted), returns a considered
:class:`CloudAssessment` (with a ``policy_version`` piggyback hint), and can hand out an
:class:`EdgePolicyUpdate` via ``fetch_policy``. The A2A stub server wraps this; the real
Foundry agent drops in by changing config only.
"""

from __future__ import annotations

from airacare_edge.cloud.contracts import (
    CloudAction,
    CloudAssessment,
    DailyLivingEvent,
    EdgePolicyUpdate,
)


class LocalCloudStub:
    """In-process CloudGateway: report -> CloudAssessment; fetch_policy -> EdgePolicyUpdate.

    ``online`` toggles connectivity (offline ⇒ report returns None ⇒ the edge queues it;
    the edge has already taken its own action regardless). ``policy`` + ``policy_version``
    let a test/demo simulate the cloud learning a new policy the edge then pulls.
    """

    def __init__(
        self,
        *,
        online: bool = True,
        policy: EdgePolicyUpdate | None = None,
        policy_version: int = 1,
    ) -> None:
        self.online = online
        self._policy = policy
        self._policy_version = policy.version if policy is not None else policy_version

    def report(self, event: DailyLivingEvent) -> CloudAssessment | None:
        if not self.online:
            return None
        # The cloud's *considered* view. For the stub it mirrors the edge's level and
        # attaches the caregiver comms it would send.
        notifications: list[CloudAction] = []
        if event.edge_assessed_level in ("L2", "L3"):
            notifications.append(
                CloudAction(channel="family", message="Please check on the patient.")
            )
        if event.edge_assessed_level == "L3":
            notifications.append(
                CloudAction(channel="community", message="Escalate if no acknowledgement.")
            )
        return CloudAssessment(
            considered_level=event.edge_assessed_level,
            reason=(
                f"considered {event.edge_assessed_level} for {event.type}"
                f" (response={event.context.get('response')},"
                f" baseline_deviation={event.baseline_deviation:.2f})"
            ),
            caregiver_notifications=notifications,
            policy_version=self._policy_version,
        )

    def fetch_policy(self, patient_id: str, since_version: int) -> EdgePolicyUpdate | None:
        if self._policy is not None and self._policy.version > since_version:
            return self._policy
        return None
