"""In-process cloud stub: a local grading engine that speaks the CloudDecision contract.

This mirrors what the Foundry Hosted Agent will return, so the whole Edge->Cloud->Edge
loop runs deterministically with no network. Step 3 wraps this engine behind an A2A
endpoint; the real Foundry agent then drops in by changing config only.
"""

from __future__ import annotations

from airacare_edge.cloud.contracts import (
    CloudAction,
    CloudDecision,
    DailyLivingEvent,
    EdgeDirective,
)


class LocalGradingEngine:
    """Deterministic grading rules approximating the Foundry decision engine."""

    def grade(self, event: DailyLivingEvent) -> CloudDecision:
        if event.type == "wander":
            return self._grade_wander(event)
        # Fallback for other (future) event types.
        return CloudDecision(grade="L0", reason=f"{event.type} logged", actions=[
            CloudAction(channel="log", message=f"{event.type} event logged"),
        ])

    def _grade_wander(self, event: DailyLivingEvent) -> CloudDecision:
        response = str(event.context.get("response", "pending"))
        night = event.context.get("time_of_day") == "night"

        if response in ("no_response", "distress"):
            return CloudDecision(
                grade="L3",
                reason=(
                    "out-of-bed + door open"
                    + (" at night" if night else "")
                    + f" + response={response} + baseline_deviation={event.baseline_deviation:.2f}"
                    " -> high wandering risk"
                ),
                actions=[
                    CloudAction(
                        channel="family",
                        message="Patient left the bedroom and did not respond. Please check immediately.",
                    ),
                    CloudAction(
                        channel="community",
                        message="Escalate if family does not acknowledge.",
                        target="community-watch",
                    ),
                ],
            )

        if response == "unclear":
            return CloudDecision(
                grade="L2",
                reason="wander candidate with unclear response -> notify family to check",
                actions=[
                    CloudAction(
                        channel="family",
                        message="Possible nighttime wandering; please check on the patient.",
                    ),
                ],
            )

        # response == "ok" (patient reassured us)
        return CloudDecision(
            grade="L1",
            reason="patient responded and is okay -> gentle guidance back to bed",
            edge_directive=EdgeDirective(
                voice_prompt="It's late. Let's head back to bed — I'll leave a soft light on.",
            ),
        )


class LocalStubCloudClient:
    """CloudClient implementation backed by the in-process grading engine.

    ``online`` can be toggled to simulate loss of connectivity (the edge then falls
    back to local alerts).
    """

    def __init__(self, engine: LocalGradingEngine | None = None, *, online: bool = True) -> None:
        self._engine = engine or LocalGradingEngine()
        self.online = online

    def submit(self, event: DailyLivingEvent) -> CloudDecision | None:
        if not self.online:
            return None
        return self._engine.grade(event)
