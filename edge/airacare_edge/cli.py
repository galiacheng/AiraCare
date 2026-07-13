"""Interactive scenario runner for the flagship flow (step 2).

Fires a chosen simulated sensor scenario through the full Edge -> Cloud -> Edge loop and
prints the edge decision, the exact DailyLivingEvent that crosses the boundary, and the
cloud's graded decision. Works against the in-process stub or a real A2A endpoint.

Examples:
    python -m airacare_edge.cli --scenario no-response
    python -m airacare_edge.cli --scenario reply-ok
    python -m airacare_edge.cli --scenario no-response --cloud a2a          # needs the stub server
    python -m airacare_edge.cli --scenario no-response --cloud a2a --endpoint http://127.0.0.1:8971/a2a

Start the A2A stub server first (in another terminal) for --cloud a2a:
    python -m airacare_edge.cloud.a2a_stub --port 8971
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from airacare_edge.agent import EdgeAgent
from airacare_edge.cloud.factory import make_cloud_client
from airacare_edge.config import EdgeConfig
from airacare_edge.main import ConsoleAlerts, ConsoleVoice
from airacare_edge.reasoning.baseline import BaselineTracker
from airacare_edge.reasoning.classifier import WanderClassifier
from airacare_edge.sensors.simulator import (
    nighttime_wander_events,
    restless_but_in_bed_events,
)

NIGHT = datetime(2026, 7, 13, 3, 0, 0, tzinfo=timezone.utc)

# scenario -> (scripted spoken reply | None, sensor factory)
SCENARIOS = {
    "no-response": (None, nighttime_wander_events),
    "reply-ok": ("I'm fine", nighttime_wander_events),
    "distress": ("help me", nighttime_wander_events),
    "unclear": ("the garden over there", nighttime_wander_events),
    "restless": (None, restless_but_in_bed_events),  # stays below threshold
}


def _load_config(path: str | None, cloud_mode: str, endpoint: str | None) -> EdgeConfig:
    config_path = Path(path) if path else Path(__file__).resolve().parents[1] / "config.yaml"
    config = EdgeConfig.load(config_path)
    cloud = config.cloud.model_copy(
        update={
            "mode": "stub" if cloud_mode == "inproc" else cloud_mode,
            **({"a2a_endpoint": endpoint} if endpoint else {}),
        }
    )
    return config.model_copy(update={"cloud": cloud})


def run(scenario: str, config: EdgeConfig, *, voice_mode: str = "console", reply_wav: str | None = None) -> None:
    reply, sensor_factory = SCENARIOS[scenario]
    baseline = BaselineTracker(config.quiet_hours)
    classifier = WanderClassifier(baseline, config.thresholds.correlation_window_seconds)

    if voice_mode == "local":
        from airacare_edge.voice.service import LocalVoiceService

        voice = LocalVoiceService(config, reply_wav=reply_wav)
        print("  ⏳ warming up local models…")
        print(f"     warm-up: {voice.warm_up()}")
    else:
        voice = ConsoleVoice(scripted_reply=reply)

    agent = EdgeAgent(
        config=config,
        voice=voice,
        cloud=make_cloud_client(config),
        alerts=ConsoleAlerts(),
        classifier=classifier,
        clock=lambda: NIGHT,
    )

    print(f"\n=== AiraCare edge — scenario '{scenario}' (cloud={config.cloud.mode}, voice={voice_mode}) ===")
    events = sensor_factory(at=NIGHT)
    print(f"  🛰️ sensors: {[e.kind for e in events]} @ {NIGHT.isoformat()}")

    result = agent.handle_sensor_events(events)

    print("\n--- edge decision ---")
    print(f"  handled={result.handled} path={result.path} offline={result.offline}")
    if result.event is not None and result.handled:
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
    parser = argparse.ArgumentParser(description="AiraCare edge scenario runner")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="no-response")
    parser.add_argument(
        "--cloud",
        choices=["inproc", "a2a", "foundry"],
        default="inproc",
        help="inproc = in-process stub; a2a = local stub server; foundry = real hosted agent",
    )
    parser.add_argument(
        "--voice",
        choices=["console", "local"],
        default="console",
        help="console = printed fake voice; local = real TTS + mic/file ASR (needs .[audio])",
    )
    parser.add_argument("--reply-wav", default=None, help="WAV file to transcribe in voice.input=file mode")
    parser.add_argument("--endpoint", default=None, help="override the A2A endpoint URL")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    args = parser.parse_args()

    config = _load_config(args.config, args.cloud, args.endpoint)
    run(args.scenario, config, voice_mode=args.voice, reply_wav=args.reply_wav)


if __name__ == "__main__":
    main()
