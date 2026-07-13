"""Split-screen demo panel: EDGE (in-home) vs FOUNDRY (cloud), with the privacy boundary.

Renders the flagship flow so judges can see the three anchors at a glance:
  - division of labor (edge does sensing/voice/first-response; cloud does grading)
  - the privacy boundary (ONLY the DailyLivingEvent crosses; raw audio discarded)
  - graded escalation (L0-L3 with an explainable reason)
"""

from __future__ import annotations

import json
from typing import Any

from airacare_edge.agent import FlowResult

_GRADE_STYLE = {"L0": "green", "L1": "cyan", "L2": "yellow", "L3": "bold red"}


def _edge_body(result: FlowResult, sensors: list[str], provenance: dict[str, Any] | None,
               features: list[float] | None) -> str:
    lines: list[str] = []
    lines.append(f"[bold]🛰 Sensors[/bold]: {', '.join(sensors) if sensors else '—'}")
    lines.append('[bold]🗣 Edge asks[/bold]: "are you okay?"')

    reply = result.reply
    if reply is not None:
        transcript = reply.transcript or "[dim](no spoken response)[/dim]"
        lines.append(f'[bold]🧑 Patient[/bold]: "{transcript}"')

    if provenance:
        if provenance.get("llm_used") and provenance.get("llm_result") in ("ok", "distress"):
            lines.append(
                f"[bold]🧠 Understanding[/bold]: keyword=[i]unclear[/i] → "
                f"LLM=[b]{provenance['llm_result']}[/b]"
            )
        elif provenance.get("llm_used"):
            lines.append("[bold]🧠 Understanding[/bold]: keyword=[i]unclear[/i] → LLM kept unclear")
        else:
            lines.append(f"[bold]🧠 Understanding[/bold]: keyword=[b]{provenance.get('keyword')}[/b] (LLM not called)")

    if result.event is not None:
        ev = result.event
        lines.append(f"[bold]⚖ Edge action[/bold]: {ev.edge_action_taken}")
        lines.append(
            f"[bold]📦 Local decision[/bold]: {ev.type} "
            f"(conf {ev.confidence:.2f}, drift {ev.baseline_deviation:.2f})"
        )

    lines.append("")
    if features is not None:
        lines.append(f"[green]🔐 Raw audio scrubbed → features {features}[/green]")
    lines.append("[green]🔐 Raw audio/video/point-cloud discarded on device[/green]")
    return "\n".join(lines)


def _cloud_body(result: FlowResult) -> str:
    if result.offline or result.cloud_decision is None:
        return (
            "[bold red]⚠ OFFLINE[/bold red] — cloud unreachable\n\n"
            "Edge fell back locally:\n"
            "  🚨 local alert (light + sound)\n"
            "  📩 SMS to next of kin"
        )
    decision = result.cloud_decision
    style = _GRADE_STYLE.get(decision.grade, "white")
    lines = [f"[bold]Grade[/bold]: [{style}]{decision.grade}[/{style}]"]
    lines.append(f"[bold]Reason[/bold]: {decision.reason}")
    if decision.actions:
        lines.append("[bold]Actions[/bold]:")
        for action in decision.actions:
            lines.append(f"  [{action.channel}] {action.message}")
    if decision.edge_directive.voice_prompt:
        lines.append(f"[bold]↩ Voice back to edge[/bold]: \"{decision.edge_directive.voice_prompt}\"")
    return "\n".join(lines)


def render_split(
    console,
    result: FlowResult,
    sensors: list[str],
    provenance: dict[str, Any] | None = None,
    features: list[float] | None = None,
    cloud_mode: str = "stub",
) -> None:
    """Render the split-screen panel to a rich Console."""
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table

    console.print(Rule("[bold]AiraCare — Nighttime Wandering[/bold]"))
    edge = Panel(
        _edge_body(result, sensors, provenance, features),
        title="🏠 EDGE — in the home",
        subtitle="private · real-time · offline-capable",
        border_style="blue",
    )
    cloud = Panel(
        _cloud_body(result),
        title=f"☁ FOUNDRY — cloud · {cloud_mode}",
        subtitle="deep reasoning · graded",
        border_style="green" if not result.offline else "red",
    )
    # Table.grid forces a true side-by-side split (wraps content inside each column).
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    grid.add_row(edge, cloud)
    console.print(grid)

    console.print(
        Rule("[bold red]🔒 ONLY the DailyLivingEvent crossed — no raw audio/video left the home[/bold red]")
    )
    if result.event is not None and result.handled:
        payload = json.dumps(json.loads(result.event.model_dump_json()), indent=2)
        console.print(
            Panel(payload, title="🔒 What crossed the boundary — DailyLivingEvent", border_style="red")
        )


def show(
    result: FlowResult,
    sensors: list[str],
    provenance: dict[str, Any] | None = None,
    features: list[float] | None = None,
    cloud_mode: str = "stub",
) -> None:
    """Convenience: render to a default console (stdout)."""
    from rich.console import Console

    render_split(Console(), result, sensors, provenance, features, cloud_mode)
