"""Policy-Learning agent — distills an EdgePolicyUpdate from accumulated events (T2).

This is the *learning* half of the hybrid system: the cloud can never reach back into an
event the edge already handled, so its insight is encoded as a versioned
:class:`EdgePolicyUpdate` that tunes the edge's **future** behavior (thresholds + personalized
prompts). It runs in the async deliberate tier and **never** affects the synchronous T1
response — it only writes new policy the edge lazily pulls on the next ``policy_version`` bump.

Scaffold rule (deterministic, demoable): count a patient's *nighttime wander* reports; on the
Nth recurrence, distill a tuned policy — lower the confirm threshold and personalize the
reassure prompt — and bump the version once. A real T2 tier would fuse this over the full
event history / disease-stage trend via the Connected Agents (design §5).
"""

from __future__ import annotations

from airacare_foundry.contracts import DailyLivingEvent, EdgePolicyUpdate
from airacare_foundry.store.base import BASE_POLICY_VERSION, PatientState, PolicyStore


class PolicyLearningAgent:
    """Turns recurring nighttime wanders into a tuned, versioned edge policy."""

    #: Number of nighttime wanders after which a tuned policy is distilled (once).
    WANDER_LEARN_THRESHOLD = 3

    def __init__(self, policy_store: PolicyStore, *, enabled: bool = True) -> None:
        self._store = policy_store
        self.enabled = enabled
        self._wander_counts: dict[str, int] = {}  # per-patient nighttime-wander tally

    def observe(
        self, event: DailyLivingEvent, state: PatientState | None = None
    ) -> EdgePolicyUpdate | None:
        """Record an event and, when the pattern crosses the bar, emit + persist a new policy.

        Returns the distilled :class:`EdgePolicyUpdate` (also written to the store) the one
        time the threshold is crossed, else ``None``.
        """
        if not self.enabled:
            return None
        if event.type != "wander" or event.context.get("time_of_day") != "night":
            return None

        pid = event.patient_id
        count = self._wander_counts.get(pid, 0) + 1
        self._wander_counts[pid] = count
        if count != self.WANDER_LEARN_THRESHOLD:  # emit exactly once, on crossing
            return None

        current = self._store.get(pid)
        next_version = (current.version if current is not None else BASE_POLICY_VERSION) + 1
        name = state.name if state is not None and state.name else None
        reassure = (
            f"It's late, {name}. Let's go back to bed." if name else "It's late. Let's head back to bed."
        )
        update = EdgePolicyUpdate(
            version=next_version,
            patient_id=pid,
            wander_confidence=0.6,  # lower the confirm threshold — catch the wander earlier
            no_response_seconds=10.0,
            reassure_prompt=reassure,
            disease_stage=state.disease_stage if state is not None else None,
            notes=f"night wandering recurring ({count}x) → lowered confirm threshold",
        )
        self._store.upsert(update)
        return update
