"""AiraCare demo presenter — the "events → Foundry" feed with Foundry's value made visible.

Purpose (a recording aid for the 1–2 minute demo video). For each scenario it:

  1. Runs the **real edge pipeline** (optionally with real voice: TTS prompt + Whisper ASR of
     a reply WAV) so the decision and the forwarded record are genuine — not hand-built.
  2. Prints the **BOUNDARY FEED** row: the exact privacy-scrubbed ``DailyLivingEvent`` JSON that
     is the *only* thing crossing the home boundary.
  3. Forwards that record to the **live Foundry hosted agent** over standard A2A and prints the
     **full** response the shipped CLI hides — the deterministic ``considered_level`` *and* the
     Foundry hosted model — family briefing **with its knowledge-base citations** ("Grounded by AiraCare
     guidance: …"). That briefing + grounding is Foundry's value on top of the instant edge action.

The edge always acts locally first; Foundry is advisory (it never sets the risk level — the hosted
agent's deterministic middleware does) and durable (every event is written to Cosmos).

Usage (PowerShell)::

    $env:AIRACARE_A2A_TOKEN = (az account get-access-token --resource https://ai.azure.com `
        --query accessToken -o tsv)
    $EP = "https://<account>.services.ai.azure.com/api/projects/<project>/agents/<agent>/endpoint/protocols/a2a"

    # fast/scripted replies (no audio hardware):
    python spec/tools/foundry_demo_feed.py --endpoint $EP

    # real on-device voice recognition (edge speaks the prompt, Whisper transcribes the reply WAVs):
    python spec/tools/foundry_demo_feed.py --endpoint $EP --voice local

WAV directory layout for ``--voice local`` — defaults to the bundled ``spec/tools/voice-replies/``
(override with ``--wav-dir``); one file per spoken scenario; ``no-response`` is silence, so no file
is needed::

    reply-ok.wav   distress.wav   unclear.wav
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make the edge package importable whether run from the repo root or elsewhere.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "edge"))

from airacare_edge.agent import EdgeAgent  # noqa: E402
from airacare_edge.cloud.contracts import DailyLivingEvent  # noqa: E402
from airacare_edge.cloud.factory import make_cloud_client  # noqa: E402
from airacare_edge.cloud.foundry_client import (  # noqa: E402
    FoundryA2AClient,
    parse_assessment_block,
)
from airacare_edge.cloud.queue import OfflineQueue  # noqa: E402
from airacare_edge.config import EdgeConfig  # noqa: E402
from airacare_edge.main import ConsoleAlerts, ConsoleVoice  # noqa: E402
from airacare_edge.reasoning.baseline import BaselineTracker  # noqa: E402
from airacare_edge.reasoning.classifier import WanderClassifier  # noqa: E402
from airacare_edge.sensors.simulator import nighttime_wander_events  # noqa: E402

# The same fixed "night" the edge scenarios use, so out-of-bed + door events are anomalous.
NIGHT = datetime(2026, 7, 13, 3, 0, 0, tzinfo=timezone.utc)

# scenario -> scripted reply (console voice) used only when --voice console.
SCENARIO_REPLIES: dict[str, str | None] = {
    "no-response": None,
    "reply-ok": "I'm fine",
    "distress": "help me",
    "unclear": "the garden over there",
}
DEFAULT_ORDER = ["reply-ok", "distress", "no-response", "unclear"]


class VerboseFoundryClient(FoundryA2AClient):
    """FoundryA2AClient that also returns the full response text the CLI parses-then-drops."""

    def report_verbose(self, event: DailyLivingEvent) -> tuple[object | None, str]:
        params = {"message": self._message_params(event)}
        result = self._rpc("message/send", params)
        if result is None:
            return None, ""
        text = self._await_text(result)
        assessment = parse_assessment_block(text) if text else None
        return assessment, text


def _load_config(voice_mode: str) -> EdgeConfig:
    config = EdgeConfig.load(_REPO_ROOT / "edge" / "config.yaml")
    # The edge decides against the fast in-process stub; we forward to Foundry ourselves so the
    # feed shows one clean synchronous request/response per event.
    cloud = config.cloud.model_copy(update={"mode": "stub"})
    voice = config.voice.model_copy(update={"input": "file" if voice_mode == "local" else config.voice.input})
    return config.model_copy(update={"cloud": cloud, "voice": voice})


def _build_voice(scenario: str, voice_mode: str, wav_dir: Path | None):
    if voice_mode != "local":
        return ConsoleVoice(scripted_reply=SCENARIO_REPLIES[scenario])
    from airacare_edge.voice.service import LocalVoiceService

    reply_wav = None
    if SCENARIO_REPLIES[scenario] is not None and wav_dir is not None:
        candidate = wav_dir / f"{scenario}.wav"
        reply_wav = str(candidate) if candidate.exists() else None
    return LocalVoiceService(_load_config(voice_mode), reply_wav=reply_wav)


def _edge_event(scenario: str, config: EdgeConfig, voice_mode: str, wav_dir: Path | None):
    """Run the real edge pipeline and return (result, voice) — result.event is the forwarded record."""
    baseline = BaselineTracker(config.quiet_hours)
    classifier = WanderClassifier(baseline, config.thresholds.correlation_window_seconds)
    voice = _build_voice(scenario, voice_mode, wav_dir)
    if voice_mode == "local":
        print("  ⏳ warming up on-device voice models…", flush=True)
        print(f"     warm-up: {voice.warm_up()}", flush=True)
    agent = EdgeAgent(
        config=config,
        voice=voice,
        cloud=make_cloud_client(config),
        alerts=ConsoleAlerts(),
        classifier=classifier,
        clock=lambda: NIGHT,
        queue=OfflineQueue(config.cloud.offline_queue_dir, ttl_seconds=config.cloud.offline_ttl_seconds),
    )
    result = agent.handle_sensor_events(nighttime_wander_events(at=NIGHT))
    agent.reporter.join(timeout=6.0)  # let the harmless in-proc stub report settle
    return result, voice


def _print_boundary(scenario: str, result, voice, voice_mode: str) -> None:
    print("\n" + "═" * 78)
    print(f"SCENARIO: {scenario}")
    heard = getattr(voice, "last_interpretation", None)
    if voice_mode == "local":
        # Show the real ASR transcript path so the audience sees on-device recognition, not a script.
        prov = heard or {}
        print(f"  🎙️ edge heard (Whisper ASR) → interpreted: {prov or 'no response (silence)'}")
    d = result.decision
    if d is not None:
        print(f"  🏠 EDGE (authoritative, acted in ms): level={d.level} action={d.action}")
    print("  🔒 ONLY THIS CROSSES THE BOUNDARY → Foundry (privacy-scrubbed DailyLivingEvent):")
    if result.event is not None:
        record = json.loads(result.event.model_dump_json())
        for line in json.dumps(record, indent=2).splitlines():
            print(f"     {line}")


def _print_foundry(client: VerboseFoundryClient, event: DailyLivingEvent) -> None:
    print("  ⏳ forwarding to live Foundry hosted agent over standard A2A…", flush=True)
    assessment, text = client.report_verbose(event)
    if not text:
        print("  ⚠️ Foundry unreachable — edge already acted; report would queue (store-and-forward).")
        return
    print("\n  ☁️ FOUNDRY RESPONSE — the value on top of the instant edge action:")
    briefing, considered = _split_response(text)
    if considered is not None:
        print(f"     • Deterministic considered_level = {considered.considered_level} "
              "(computed by middleware BEFORE the model — the LLM cannot override it)")
    if briefing:
        print("     • Foundry hosted model — family briefing, grounded in a knowledge base:")
        for line in briefing.splitlines():
            if line.strip():
                print(f"         {line.strip()}")
    print("     • …and the scrubbed event was persisted to Cosmos DB (durable, longitudinal).")


def _split_response(text: str) -> tuple[str, object | None]:
    """Split the two response artifacts: the human briefing and the CONSIDERED ASSESSMENT block."""
    marker = "CONSIDERED ASSESSMENT (JSON)"
    considered = parse_assessment_block(text)
    briefing = text.split(marker)[0].strip() if marker in text else text.strip()
    return briefing, considered


def main() -> None:
    from airacare_edge._console import ensure_utf8_stdout

    ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description="AiraCare events→Foundry demo feed")
    parser.add_argument("--endpoint", required=True, help="Foundry agent A2A protocol base URL")
    parser.add_argument("--voice", choices=["console", "local"], default="console",
                        help="console = scripted replies; local = real TTS prompt + Whisper ASR of reply WAVs")
    parser.add_argument("--wav-dir", default=None,
                        help="directory of <scenario>.wav files for --voice local "
                             "(default: the bundled spec/tools/voice-replies/)")
    parser.add_argument("--scenarios", nargs="*", default=DEFAULT_ORDER,
                        help=f"subset/order of scenarios (default: {' '.join(DEFAULT_ORDER)})")
    args = parser.parse_args()

    token = os.environ.get("AIRACARE_A2A_TOKEN")
    if not token:
        sys.exit("ERROR: set AIRACARE_A2A_TOKEN (az account get-access-token --resource https://ai.azure.com …)")

    default_wavs = Path(__file__).resolve().parent / "voice-replies"
    wav_dir = Path(args.wav_dir) if args.wav_dir else default_wavs
    config = _load_config(args.voice)
    client = VerboseFoundryClient(args.endpoint, token=token)

    print("AiraCare — every event the edge forwards to Foundry (live).  "
          f"voice={args.voice}  scenarios={', '.join(args.scenarios)}")
    for scenario in args.scenarios:
        result, voice = _edge_event(scenario, config, args.voice, wav_dir)
        _print_boundary(scenario, result, voice, args.voice)
        if result.event is not None:
            _print_foundry(client, result.event)
    print("\n" + "═" * 78)
    print("Edge = instant safety · Foundry = grounded reasoning + durable memory · only structured data crosses.")


if __name__ == "__main__":
    main()
