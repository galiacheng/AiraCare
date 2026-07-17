"""Serialize the deterministic :class:`CloudAssessment` into a wire block the edge parses.

The hosted agent's advisory model narrates a warm caregiver briefing, but the **considered
level** and its caregiver notifications are computed deterministically by
:class:`~airacare_care.assessor.ConsideredAssessor` (never by the model). To carry that
deterministic verdict back to the edge over standard A2A — regardless of whether Foundry's A2A
projection preserves a structured DataPart — the middleware appends a delimited
``CONSIDERED ASSESSMENT (JSON)`` block to the response text. The edge locates the marker and
decodes the JSON that immediately follows it (the same robust pattern the hosted agent already
uses for the ``DAILY EVENT RECORD (JSON)`` block on the inbound side).

This module is pure (stdlib only) so both the render and the parse round-trip are unit-testable
offline and shared by the edge client in Phase 3.
"""

from __future__ import annotations

import json

from airacare_care.contracts import CloudAssessment

ASSESSMENT_MARKER = "CONSIDERED ASSESSMENT (JSON)"


def render_assessment_block(assessment: CloudAssessment) -> str:
    """Return the delimited, self-describing block that carries the considered assessment.

    The JSON is emitted with ``CloudAssessment.model_dump_json()`` so it round-trips exactly
    through :func:`parse_assessment_block` (and through the edge's own ``CloudAssessment``,
    which is byte-compatible).
    """
    return f"{ASSESSMENT_MARKER}\n{assessment.model_dump_json()}"


def parse_assessment_block(text: str) -> CloudAssessment | None:
    """Extract the considered :class:`CloudAssessment` from a response's text, or ``None``.

    Locates the ``CONSIDERED ASSESSMENT (JSON)`` marker and decodes the JSON object that
    immediately follows it. Never raises: returns ``None`` when the marker is absent or the
    payload is not a valid assessment (so a plain conversational reply is simply ignored).
    """
    marker = text.find(ASSESSMENT_MARKER)
    if marker == -1:
        return None
    brace = text.find("{", marker)
    if brace == -1:
        return None
    try:
        obj, _end = json.JSONDecoder().raw_decode(text, brace)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "considered_level" not in obj:
        return None
    try:
        return CloudAssessment.model_validate(obj)
    except ValueError:
        return None
