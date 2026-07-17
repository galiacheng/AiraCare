"""Considered Assessor — deterministic T1 assessment, personalized by patient state.

The edge is **authoritative**: it grades and acts on its own, then *reports* the event
(with its ``edge_assessed_level``). The cloud returns a *considered* :class:`CloudAssessment`
for the record and drives caregiver notifications — it **never gates the edge**, which has
already acted.

Baseline behavior reproduces ``edge/airacare_edge/cloud/stub.py::LocalCloudStub.report`` so
this hosted agent is a true drop-in for the edge's local stub. It is the synchronous T1 tier:
pure rule evaluation that always returns a valid :class:`CloudAssessment` promptly — off the
edge's safety path (the edge already acted before it reported).

**Personalization (design §6).** When a :class:`PatientState` is supplied, disease stage and
the patient's rolling baseline drift weight the risk (``risk = f(event) × disease_stage_weight``)
and can **refine** the considered level *upward* from the edge's level — never downward, since
silence/confusion is itself a risk signal and the safe default is bias-to-escalate. With no
state (or a ``moderate``-stage patient with no unresolved risk) the output is byte-identical to
the edge stub, preserving the drop-in parity guarantee.

This module is **pure** (pydantic + stdlib only) so it is unit-testable offline and the
advisory-only LLM can never sit in front of it.
"""

from __future__ import annotations

from airacare_care.contracts import (
    CloudAction,
    CloudAssessment,
    DailyLivingEvent,
    DiseaseStage,
    Grade,
)
from airacare_care.state import PatientState

# Escalation ladder, ordered. Index arithmetic drives one-rung refinements.
_LEVELS: tuple[Grade, ...] = ("L0", "L1", "L2", "L3")

# Disease stage weights the risk: a severe-stage patient's nighttime deviation weighs more
# (design §6). moderate = 1.0 keeps exact parity with the edge stub for the default patient.
_STAGE_WEIGHT: dict[DiseaseStage, float] = {"mild": 0.85, "moderate": 1.0, "severe": 1.2}

# Event types whose considered level may be refined upward (real-time safety events).
_SAFETY_EVENTS: frozenset[str] = frozenset({"wander", "fall"})

# Baseline drift above which a severe-stage safety event escalates one rung.
_ESCALATION_DRIFT_THRESHOLD = 0.9


def _escalate_one(level: Grade) -> Grade:
    """Return the next rung up, capped at L3."""
    return _LEVELS[min(_LEVELS.index(level) + 1, len(_LEVELS) - 1)]


class ConsideredAssessor:
    """Deterministic assessment rules — the synchronous T1 considered-assessment tier."""

    def assess(
        self,
        event: DailyLivingEvent,
        state: PatientState | None = None,
        *,
        policy_version: int = 1,
    ) -> CloudAssessment:
        """Considered view of a reported event.

        With no ``state`` the result mirrors the edge stub (parity). With a
        :class:`PatientState` the considered level may be refined upward for higher-risk
        patients (see module docstring). Caregiver notifications and the reason string track
        the *considered* level, so an escalation both explains itself and adds the matching
        comms.
        """
        edge_level = event.edge_assessed_level
        considered_level, drift, refined = self._refine_level(event, state, edge_level)

        detail = (
            f"response={event.context.get('response')},"
            f" baseline_deviation={event.baseline_deviation:.2f}"
        )
        if refined:
            detail += (
                f"; refined from {edge_level}"
                f" (severe-stage nighttime {event.type}, drift {drift:.2f})"
            )
        reason = f"considered {considered_level} for {event.type} ({detail})"

        return CloudAssessment(
            considered_level=considered_level,
            reason=reason,
            caregiver_notifications=self._notifications(considered_level),
            policy_version=policy_version,
        )

    def _refine_level(
        self,
        event: DailyLivingEvent,
        state: PatientState | None,
        edge_level: Grade,
    ) -> tuple[Grade, float, bool]:
        """Return ``(considered_level, combined_drift, refined)``.

        Only escalates (never de-escalates) so the edge's own decision is a safety floor.
        Returns the edge level unchanged when no state is available or the risk does not
        clear the escalation bar — preserving byte-parity with the edge stub.
        """
        if state is None:
            return edge_level, event.baseline_deviation, False

        # Fuse the event's drift with the patient's persisted rolling-baseline drift.
        combined_drift = max(event.baseline_deviation, state.baseline_deviation)
        weight = _STAGE_WEIGHT.get(state.disease_stage, 1.0)

        actionable = edge_level in ("L1", "L2")
        unresolved = event.context.get("response") != "ok"  # explicit reassurance is not escalated
        high_risk = combined_drift * weight >= _ESCALATION_DRIFT_THRESHOLD * _STAGE_WEIGHT["severe"]

        if (
            weight > 1.0
            and event.type in _SAFETY_EVENTS
            and actionable
            and unresolved
            and high_risk
        ):
            return _escalate_one(edge_level), combined_drift, True
        return edge_level, combined_drift, False

    @staticmethod
    def _notifications(level: Grade) -> list[CloudAction]:
        """Caregiver comms keyed off the *considered* level (design §6)."""
        notifications: list[CloudAction] = []
        if level in ("L2", "L3"):
            notifications.append(
                CloudAction(channel="family", message="Please check on the patient.")
            )
        if level == "L3":
            notifications.append(
                CloudAction(channel="community", message="Escalate if no acknowledgement.")
            )
        return notifications
