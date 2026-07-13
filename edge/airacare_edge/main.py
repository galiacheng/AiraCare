"""Scripted console demo of the flagship flow — no mic, no LLM, no network.

Uses the local grading stub and a console voice that simulates a no-response, so you can
watch the full Edge -> Cloud -> Edge loop and the privacy boundary in the terminal:

    python -m airacare_edge.main
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from airacare_edge.agent import AlertSink, EdgeAgent, VoiceService
from airacare_edge.cloud.contracts import DailyLivingEvent, ReplyIntent
from airacare_edge.cloud.stub import LocalStubCloudClient
from airacare_edge.config import EdgeConfig
from airacare_edge.reasoning.baseline import BaselineTracker
from airacare_edge.reasoning.classifier import WanderClassifier
from airacare_edge.sensors.simulator import nighttime_wander_events
from airacare_edge.voice.nlu import keyword_intent


class ConsoleVoice(VoiceService):
    """Prints prompts; simulates the patient not responding (the L3 demo path)."""

    def __init__(self, scripted_reply: str | None = None) -> None:
        self._scripted_reply = scripted_reply

    def say(self, text: str) -> None:
        print(f"  🔊 edge says: “{text}”")

    def listen(self, timeout: float) -> str | None:
        if self._scripted_reply is None:
            print(f"  🎙️ listening… (no response within {timeout:.0f}s)")
        else:
            print(f"  🎙️ patient replied: “{self._scripted_reply}”")
        return self._scripted_reply

    def interpret(self, transcript: str) -> ReplyIntent:
        return keyword_intent(transcript)


class ConsoleAlerts(AlertSink):
    def local_alert(self, event: DailyLivingEvent, reason: str) -> None:
        print(f"  🚨 LOCAL ALERT ({reason}): light + sound in the home")

    def notify_kin_sms(self, event: DailyLivingEvent, reason: str) -> None:
        print(f"  📩 SMS to next of kin ({reason})")


def _run(config: EdgeConfig) -> None:
    baseline = BaselineTracker(config.quiet_hours)
    classifier = WanderClassifier(baseline, config.thresholds.correlation_window_seconds)
    cloud = LocalStubCloudClient(online=True)

    # Force a 3:00 AM timestamp so the scenario is unambiguously nighttime.
    night = datetime(2026, 7, 13, 3, 0, 0, tzinfo=timezone.utc)
    agent = EdgeAgent(
        config=config,
        voice=ConsoleVoice(scripted_reply=None),  # None => no response => L3
        cloud=cloud,
        alerts=ConsoleAlerts(),
        classifier=classifier,
        clock=lambda: night,
    )

    print("\n=== AiraCare edge — Nighttime Wandering (scripted) ===")
    events = nighttime_wander_events(at=night)
    print(f"  🛰️ sensors: {[e.kind for e in events]} @ {night.isoformat()}")

    result = agent.handle_sensor_events(events)

    print("\n--- edge decision ---")
    print(f"  handled={result.handled} path={result.path} offline={result.offline}")
    if result.event is not None:
        print("\n--- 🔒 ONLY this crosses the boundary (DailyLivingEvent) ---")
        print(json.dumps(json.loads(result.event.model_dump_json()), indent=2))
    if result.cloud_decision is not None:
        print("\n--- cloud decision ---")
        print(f"  grade={result.cloud_decision.grade}")
        print(f"  reason={result.cloud_decision.reason}")
        for action in result.cloud_decision.actions:
            print(f"  action: [{action.channel}] {action.message}")
    print()


def main() -> None:
    from pathlib import Path

    config_path = Path(__file__).resolve().parents[1] / "config.yaml"
    _run(EdgeConfig.load(config_path))


if __name__ == "__main__":
    main()
