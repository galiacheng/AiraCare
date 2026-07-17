"""AiraCare deterministic care domain — the safety-critical logic the hosted agent owns.

This is a **pure** package (pydantic + stdlib only; it never imports ``agent_framework`` or
any Azure SDK) so it can be imported and unit-tested offline, and so the advisory-only LLM in
``main.py`` can never sit in front of it. It holds the pieces ported out of the standalone
``foundry-a2a-server`` when the edge moved to speaking standard A2A directly to this Foundry
hosted agent (see ``spec/foundry-a2a-hosting.md``):

- :mod:`airacare_care.contracts` — the wire models (byte-compatible with the edge).
- :mod:`airacare_care.state` — ``PatientState`` used to personalize the considered level.
- :mod:`airacare_care.assessor` — :class:`ConsideredAssessor`, the deterministic T1 tier.
- :mod:`airacare_care.escalation` / :mod:`airacare_care.escalation_timer` /
  :mod:`airacare_care.notify` — the ack-tracked escalation ladder (T2 safety action).
- :mod:`airacare_care.render` — serialize a :class:`CloudAssessment` into the delimited
  ``CONSIDERED ASSESSMENT (JSON)`` block the edge parses deterministically.

``main.py`` wraps these behind Agent Framework middleware so the considered level and the
escalation are computed by this Python — never by the model — before the advisory narration runs.
"""

from __future__ import annotations

from airacare_care.assessor import ConsideredAssessor
from airacare_care.contracts import (
    CloudAction,
    CloudAssessment,
    DailyLivingEvent,
    Grade,
)
from airacare_care.escalation import DEFAULT_LADDER, EscalationAgent, EscalationSession, Rung
from airacare_care.escalation_timer import ManualScheduler, Scheduler, ThreadScheduler
from airacare_care.notify import NotificationTool
from airacare_care.render import ASSESSMENT_MARKER, parse_assessment_block, render_assessment_block
from airacare_care.state import DiseaseStage, PatientState

__all__ = [
    "ASSESSMENT_MARKER",
    "CloudAction",
    "CloudAssessment",
    "ConsideredAssessor",
    "DEFAULT_LADDER",
    "DailyLivingEvent",
    "DiseaseStage",
    "EscalationAgent",
    "EscalationSession",
    "Grade",
    "ManualScheduler",
    "NotificationTool",
    "PatientState",
    "Rung",
    "Scheduler",
    "ThreadScheduler",
    "parse_assessment_block",
    "render_assessment_block",
]
