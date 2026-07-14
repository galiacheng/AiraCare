"""Edge Core — the AiraCare edge agent state machine.

Orchestrates the flagship Nighttime Wandering flow:

    sense -> classify -> active voice confirm -> EDGE DECIDES (L0-L3) & ACTS NOW
          -> build DailyLivingEvent (report of what happened + what the edge did)
          -> report to cloud (fire-and-forget; offline -> store-and-forward queue)
          -> apply an EdgePolicyUpdate lazily when the report's policy_version changed

The edge is authoritative for the immediate action and **never waits for the cloud**.
The core depends only on small service *protocols* (voice / cloud / alerts), so it runs
deterministically in tests with fakes, and swaps to real implementations unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Protocol, runtime_checkable

from airacare_edge.cloud.contracts import (
    CloudAssessment,
    DailyLivingEvent,
    EdgePolicyUpdate,
    ReplyIntent,
    utcnow,
)
from airacare_edge.config import EdgeConfig
from airacare_edge.reasoning.classifier import WanderClassifier
from airacare_edge.reasoning.grader import EdgeDecision, EdgeGrader
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
class AlertSink(Protocol):
    """The edge's own immediate actions (taken without waiting for the cloud)."""

    def local_alert(self, event: DailyLivingEvent, reason: str) -> None: ...

    def notify_kin_sms(self, event: DailyLivingEvent, reason: str) -> None: ...

    def escalate(self, event: DailyLivingEvent, reason: str) -> None: ...


@runtime_checkable
class CloudGateway(Protocol):
    """Async cloud channel: report an event, and fetch policy when it changed."""

    def report(self, event: DailyLivingEvent) -> CloudAssessment | None:
        """Fire-and-forget report; returns the considered assessment, or None if offline."""

    def fetch_policy(self, patient_id: str, since_version: int) -> EdgePolicyUpdate | None: ...


@dataclass
class FlowResult:
    """Outcome of handling a batch of sensor events (drives tests + the UI panel)."""

    handled: bool
    path: str
    event: DailyLivingEvent | None = None
    reply: ReplyIntent | None = None
    decision: EdgeDecision | None = None
    assessment: CloudAssessment | None = None
    reported: bool = False  # did the report reach the cloud (vs. queued offline)?
    policy_applied_version: int | None = None


class EdgeAgent:
    def __init__(
        self,
        config: EdgeConfig,
        voice: VoiceService,
        cloud: CloudGateway,
        alerts: AlertSink,
        classifier: WanderClassifier,
        grader: EdgeGrader | None = None,
        clock: Callable[[], datetime] = utcnow,
        queue: "OfflineQueue | None" = None,
        policy_version: int = 1,
    ) -> None:
        self._config = config
        self._voice = voice
        self._cloud = cloud
        self._alerts = alerts
        self._classifier = classifier
        self._grader = grader or EdgeGrader()
        self._clock = clock
        self._queue = queue
        self._policy_version = policy_version

    @property
    def config(self) -> EdgeConfig:
        return self._config

    @property
    def policy_version(self) -> int:
        return self._policy_version

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

        # 1) Active voice confirmation (bounded clarify loop).
        intent = self._active_confirm()

        # 2) EDGE DECIDES and ACTS NOW — never waits for the cloud.
        decision = self._grader.decide(intent, reassure_prompt=self._config.voice.reassure_prompt)
        self._act(decision, candidate)

        # 3) Build the report of what happened + what the edge did.
        event = candidate.model_copy(
            update={
                "edge_assessed_level": decision.level,
                "edge_action_taken": decision.action,
                "context": {**candidate.context, "response": intent.status},
            }
        )

        # 4) Report to the cloud (fire-and-forget). Offline -> store-and-forward.
        assessment = self._cloud.report(event)
        reported = assessment is not None
        applied_version: int | None = None
        if not reported:
            if self._queue is not None:
                self._queue.enqueue(event, now=now)
        else:
            applied_version = self._maybe_apply_policy(assessment)

        return FlowResult(
            handled=True,
            path=f"edge_{decision.level}",
            event=event,
            reply=intent,
            decision=decision,
            assessment=assessment,
            reported=reported,
            policy_applied_version=applied_version,
        )

    # --- edge actions (immediate) -------------------------------------------
    def _act(self, decision: EdgeDecision, event: DailyLivingEvent) -> None:
        if decision.action == "reassured":
            if decision.voice_prompt:
                self._voice.say(decision.voice_prompt)
        elif decision.action == "local_alert":
            self._alerts.local_alert(event, decision.reason)
            self._alerts.notify_kin_sms(event, decision.reason)
        elif decision.action == "escalated":
            self._alerts.escalate(event, decision.reason)
        # "none" -> nothing (L0 log)

    # --- policy (piggyback) --------------------------------------------------
    def _maybe_apply_policy(self, assessment: CloudAssessment | None) -> int | None:
        if assessment is None or assessment.policy_version <= self._policy_version:
            return None
        update = self._cloud.fetch_policy(self._config.patient.id, self._policy_version)
        if update is None:
            return None
        self._apply_policy(update)
        return update.version

    def _apply_policy(self, update: EdgePolicyUpdate) -> None:
        voice_updates: dict[str, object] = {}
        for field in ("max_clarify_retries", "confirm_prompt", "reassure_prompt", "clarify_prompt"):
            value = getattr(update, field)
            if value is not None:
                voice_updates[field] = value
        threshold_updates: dict[str, object] = {}
        for field in ("wander_confidence", "no_response_seconds"):
            value = getattr(update, field)
            if value is not None:
                threshold_updates[field] = value

        config_updates: dict[str, object] = {}
        if voice_updates:
            config_updates["voice"] = self._config.voice.model_copy(update=voice_updates)
        if threshold_updates:
            config_updates["thresholds"] = self._config.thresholds.model_copy(update=threshold_updates)
        if update.disease_stage is not None:
            config_updates["patient"] = self._config.patient.model_copy(
                update={"disease_stage": update.disease_stage}
            )
        if config_updates:
            self._config = self._config.model_copy(update=config_updates)
        self._policy_version = update.version

    # --- voice confirmation --------------------------------------------------
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
            prompt = self._config.voice.clarify_prompt

    def _confirm_prompt(self) -> str:
        return self._config.voice.confirm_prompt.format(name=self._config.patient.name)
