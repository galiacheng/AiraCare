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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from airacare_edge.agent import EdgeAgent
from airacare_edge.cloud.factory import make_cloud_client
from airacare_edge.cloud.queue import OfflineQueue
from airacare_edge.config import EdgeConfig
from airacare_edge.main import ConsoleAlerts, ConsoleVoice
from airacare_edge.reasoning.baseline import BaselineTracker
from airacare_edge.reasoning.classifier import WanderClassifier
from airacare_edge.sensors.simulator import (
    nighttime_wander_events,
    restless_but_in_bed_events,
)

def _demo_night() -> datetime:
    """The wander incident, stamped at *last night's* 3 AM (UTC) relative to now.

    Making it the freshest event ensures the dashboard's latest-day family briefing always
    recaps this live run instead of an older seeded day (see spec/demo-runbook.md).
    """
    now = datetime.now(timezone.utc)
    night = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if night > now:  # before 3 AM UTC — use yesterday so we never file a future event
        night -= timedelta(days=1)
    return night


NIGHT = _demo_night()

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


def run(scenario: str, config: EdgeConfig, *, voice_mode: str = "console", reply_wav: str | None = None, panel: bool = False, show_briefing: bool = False) -> None:
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
        queue=OfflineQueue(config.cloud.offline_queue_dir, ttl_seconds=config.cloud.offline_ttl_seconds),
    )

    # Store-and-forward: on (re)connect, drain any locally-persisted offline events.
    flush = agent.flush_offline_queue()
    if flush and (flush.sent_count or flush.expired):
        print(
            f"  🔁 re-synced {flush.sent_count} queued event(s) to cloud "
            f"({flush.expired} expired, {flush.remaining} remaining)"
        )

    events = sensor_factory(at=NIGHT)
    result = agent.handle_sensor_events(events)

    # Safety action is done. Wait for the async report only so the demo can show the
    # cloud's considered assessment (the edge never waits for this in production).
    # The live Foundry hosted agent narrates via an LLM, so the standard-A2A round trip
    # (message/send ~8-11s, then poll tasks/get) takes ~25-30s; 6s is enough for the
    # in-proc/local stubs but too short to display the real cloud result. Scale to the mode.
    report_wait = 45.0 if config.cloud.mode == "foundry" else 6.0
    agent.reporter.join(timeout=report_wait)
    outcome = agent.reporter.last_outcome

    if panel:
        from airacare_edge.ui.panel import show

        show(
            result,
            sensors=[e.kind for e in events],
            provenance=getattr(voice, "last_interpretation", None),
            features=getattr(voice, "last_features", None),
            cloud_mode=config.cloud.mode,
            outcome=outcome,
            show_briefing=show_briefing,
        )
        return

    reported = outcome.reported if outcome else False
    dispatch_note = " (report sent async)" if result.dispatched else ""
    print(f"\n=== AiraCare edge — scenario '{scenario}' (cloud={config.cloud.mode}, voice={voice_mode}) ===")
    print(f"  🛰️ sensors: {[e.kind for e in events]} @ {NIGHT.isoformat()}")
    print("\n--- edge decision (authoritative — acted immediately) ---")
    if result.decision is not None:
        print(f"  level={result.decision.level} action={result.decision.action} reason={result.decision.reason}")
    print(f"  handled={result.handled} path={result.path} reported={reported}{dispatch_note}")
    if result.event is not None and result.handled:
        print("\n--- 🔒 ONLY this crosses the boundary (DailyLivingEvent report) ---")
        print(json.dumps(json.loads(result.event.model_dump_json()), indent=2))
    if outcome is not None and outcome.assessment is not None:
        print("\n--- cloud assessment (async · considered) ---")
        print(f"  considered_level={outcome.assessment.considered_level} policy_version={outcome.assessment.policy_version}")
        print(f"  reason={outcome.assessment.reason}")
        for action in outcome.assessment.caregiver_notifications:
            print(f"  cloud sent: [{action.channel}] {action.message}")
        if show_briefing and outcome.assessment.briefing:
            print("\n--- ☁️ Foundry response (hosted model — grounded family briefing) ---")
            for line in outcome.assessment.briefing.splitlines():
                if line.strip():
                    print(f"  {line.strip()}")
    elif result.dispatched:
        print("\n--- cloud: OFFLINE — report queued (edge already acted) ---")
    print()


def main() -> None:
    from airacare_edge._console import ensure_utf8_stdout

    ensure_utf8_stdout()
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
    parser.add_argument("--reply-wav", default=None, help="explicit WAV file to transcribe (forces voice.input=file)")
    parser.add_argument("--panel", action="store_true", help="render the split-screen edge/cloud demo panel")
    parser.add_argument(
        "--show-briefing",
        action="store_true",
        help="also print Foundry's grounded family briefing (hosted-model narrative) at the bottom; "
        "off by default to preserve the original output",
    )
    parser.add_argument("--endpoint", default=None, help="override the A2A endpoint URL")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    args = parser.parse_args()

    config = _load_config(args.config, args.cloud, args.endpoint)

    # An explicit --reply-wav only takes effect in voice.input == "file"; force it so the WAV is always used.
    if args.reply_wav is not None and config.voice.input != "file":
        config = config.model_copy(update={"voice": config.voice.model_copy(update={"input": "file"})})

    run(args.scenario, config, voice_mode=args.voice, reply_wav=args.reply_wav, panel=args.panel, show_briefing=args.show_briefing)


if __name__ == "__main__":
    main()
