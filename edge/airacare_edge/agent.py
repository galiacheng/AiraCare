"""Edge Core — the AiraCare edge agent state machine.

Orchestrates the flagship Nighttime Wandering flow:

    sense -> classify -> active voice confirm -> build DailyLivingEvent
          -> submit to cloud (A2A) -> act on graded decision
          -> offline fallback if the cloud is unreachable

The core depends only on small service *protocols* (voice / cloud / alerts), so it runs
deterministically in tests with fakes, and swaps to real implementations unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Protocol, runtime_checkable

from airacare_edge.cloud.contracts import (
    CloudDecision,
    DailyLivingEvent,
    ReplyIntent,
    utcnow,
)
from airacare_edge.config import EdgeConfig
from airacare_edge.reasoning.classifier import WanderClassifier
from airacare_edge.reasoning.escalation import EscalationPolicy
from airacare_edge.sensors.events import RawSensorEvent

if TYPE_CHECKING:
    from airacare_edge.cloud.queue import FlushResult, OfflineQueue


@runtime_checkable
class VoiceService(Protocol):
    """Speaks prompts and interprets the patient's spoken reply."""

    def say(self, text: str) -> None: ...

    def listen(self, timeout: float) -> str | None:
        """Return the transcript, or None on no-response (VAD timeout)."""

    def interpret(self, transcript: str) -> ReplyIntent: ...


@runtime_checkable
class CloudClient(Protocol):
    """Submits an event and returns a graded decision (None if offline)."""

    def submit(self, event: DailyLivingEvent) -> CloudDecision | None: ...


@runtime_checkable
class AlertSink(Protocol):
    """Offline fallback outputs (local alarm + SMS to next of kin)."""

    def local_alert(self, event: DailyLivingEvent, reason: str) -> None: ...

    def notify_kin_sms(self, event: DailyLivingEvent, reason: str) -> None: ...


@dataclass
class FlowResult:
    """Outcome of handling a batch of sensor events (drives tests + the UI panel)."""

    handled: bool
    path: str
    event: DailyLivingEvent | None = None
    reply: ReplyIntent | None = None
    cloud_decision: CloudDecision | None = None
    offline: bool = False


class EdgeAgent:
    def __init__(
        self,
        config: EdgeConfig,
        voice: VoiceService,
        cloud: CloudClient,
        alerts: AlertSink,
        classifier: WanderClassifier,
        escalation: EscalationPolicy | None = None,
        clock: Callable[[], datetime] = utcnow,
        queue: "OfflineQueue | None" = None,
    ) -> None:
        self._config = config
        self._voice = voice
        self._cloud = cloud
        self._alerts = alerts
        self._classifier = classifier
        self._escalation = escalation or EscalationPolicy()
        self._clock = clock
        self._queue = queue

    def flush_offline_queue(self, now: datetime | None = None) -> "FlushResult | None":
        """Re-send any locally-persisted events (call when connectivity may be restored)."""
        if self._queue is None:
            return None
        return self._queue.flush(self._cloud, now=now or self._clock())

    def handle_sensor_events(self, events: list[RawSensorEvent]) -> FlowResult:
        now = self._clock()
        candidate = self._classifier.classify(events, self._config.patient.id, now)

        if candidate is None or candidate.confidence < self._config.thresholds.wander_confidence:
            return FlowResult(handled=False, path="below_threshold", event=candidate)

        # Active voice confirmation with a bounded clarify loop (L1 first response).
        intent = self._active_confirm()

        decision = self._escalation.decide(intent, prompted=True)
        event = candidate.model_copy(
            update={
                "edge_action_taken": decision.edge_action_taken,
                "context": {**candidate.context, "response": intent.status},
            }
        )

        cloud_decision = self._cloud.submit(event) if decision.escalate_to_cloud else None
        if cloud_decision is None:
            return self._offline_fallback(event, intent)

        # Act on the graded decision (L1 loops a voice prompt back to the edge).
        if cloud_decision.edge_directive.voice_prompt:
            self._voice.say(cloud_decision.edge_directive.voice_prompt)

        return FlowResult(
            handled=True,
            path=f"cloud_{cloud_decision.grade}",
            event=event,
            reply=intent,
            cloud_decision=cloud_decision,
            offline=False,
        )

    def _resolve_intent(self, transcript: str | None) -> ReplyIntent:
        if transcript is None:
            return ReplyIntent(status="no_response", urgency=0.9, transcript=None)
        return self._voice.interpret(transcript)

    def _active_confirm(self) -> ReplyIntent:
        """Ask 'are you okay?', understand the reply, and re-ask on 'unclear'.

        Bounded by ``voice.max_clarify_retries`` — never loops indefinitely. Silence or
        distress on any attempt returns immediately (both escalate).
        """
        timeout = self._config.thresholds.no_response_seconds
        max_retries = self._config.voice.max_clarify_retries
        prompt = self._confirm_prompt()
        attempt = 0
        while True:
            self._voice.say(prompt)
            intent = self._resolve_intent(self._voice.listen(timeout))
            if intent.status != "unclear" or attempt >= max_retries:
                return intent
            attempt += 1
            prompt = self._clarify_prompt()

    def _offline_fallback(self, event: DailyLivingEvent, intent: ReplyIntent) -> FlowResult:
        # Escalate the edge action to a local alert since the cloud is unreachable.
        offline_event = event.model_copy(update={"edge_action_taken": "local_alert"})
        reason = "offline: cloud unreachable"
        self._alerts.local_alert(offline_event, reason)
        self._alerts.notify_kin_sms(offline_event, reason)
        # Persist for store-and-forward: re-sent to the cloud once connectivity returns.
        if self._queue is not None:
            self._queue.enqueue(offline_event, now=self._clock())
        return FlowResult(
            handled=True,
            path="offline_fallback",
            event=offline_event,
            reply=intent,
            cloud_decision=None,
            offline=True,
        )

    def _confirm_prompt(self) -> str:
        return f"{self._config.patient.name}, are you okay?"

    def _clarify_prompt(self) -> str:
        return "I didn't catch that. Are you okay?"
