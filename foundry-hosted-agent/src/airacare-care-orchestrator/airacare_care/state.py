"""Patient state — the per-patient context that personalizes the considered assessment.

Ported from ``foundry-a2a-server``'s ``store/base.py`` but reduced to just the model the
:class:`~airacare_care.assessor.ConsideredAssessor` needs. In this hosted agent the state is
read from the Cosmos ``patient_state`` container by ``main.py`` and handed to the assessor;
there is no store protocol here (the assessor stays pure and backend-agnostic).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from airacare_care.contracts import DiseaseStage

# The edge boots at policy version 1 (its own config baseline). The hosted agent piggybacks this
# constant version on every assessment so the edge is already current and never calls fetch_policy.
BASE_POLICY_VERSION = 1


class PatientState(BaseModel):
    """Persisted per-patient state that personalizes cloud grading.

    ``baseline_deviation`` is the patient's own rolling-baseline drift the cloud fuses with the
    incoming event; the disease stage weights how aggressively to escalate.
    """

    patient_id: str
    name: str = ""
    disease_stage: DiseaseStage = "moderate"
    baseline_deviation: float = Field(default=0.0, ge=0.0, le=1.0)
