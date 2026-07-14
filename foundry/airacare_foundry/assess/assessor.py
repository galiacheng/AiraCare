"""Considered Assessor — deterministic T1 assessment with parity to the edge stub.

The edge is **authoritative**: it grades and acts on its own, then *reports* the event
(with its ``edge_assessed_level``). The cloud returns a *considered* :class:`CloudAssessment`
for the record and drives caregiver notifications — it **never gates the edge**, which has
already acted.

This reproduces ``edge/airacare_edge/cloud/stub.py::LocalCloudStub.report`` so the Foundry
orchestrator is a true drop-in for the edge's local stub. It is the synchronous T1 tier:
pure rule evaluation that always returns a valid :class:`CloudAssessment` promptly — off the
edge's safety path (the edge's report worker only waits ~5s before store-and-forward).

The optional :class:`PatientState` lets the assessment be personalized (disease stage /
baseline). Defaults preserve exact parity with the edge stub — see ``assess/policy.py`` for
how state is loaded and applied.
"""

from __future__ import annotations

from airacare_foundry.contracts import (
    CloudAction,
    CloudAssessment,
    DailyLivingEvent,
)
from airacare_foundry.store.base import PatientState


class ConsideredAssessor:
    """Deterministic assessment rules — the synchronous T1 considered-assessment tier."""

    def assess(
        self,
        event: DailyLivingEvent,
        state: PatientState | None = None,
        *,
        policy_version: int = 1,
    ) -> CloudAssessment:
        """Considered view of a reported event (mirrors the edge stub for parity)."""
        # The cloud's considered view. For T1 it mirrors the edge's own level and attaches
        # the caregiver comms it would send.
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
            policy_version=policy_version,
        )
