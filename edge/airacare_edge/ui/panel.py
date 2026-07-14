"""Split-screen demo panel: EDGE (in-home) vs FOUNDRY (cloud), with the privacy boundary.

Renders the flagship flow so judges can see the three anchors at a glance:
  - division of labor (edge decides + acts immediately; cloud does async assessment)
  - the privacy boundary (ONLY the DailyLivingEvent report crosses; raw audio discarded)
  - graded escalation (edge L0-L3, authoritative, never waits for the cloud)
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

    if result.decision is not None:
        style = _GRADE_STYLE.get(result.decision.level, "white")
        lines.append(
            f"[bold]⚖ Edge decision[/bold]: [{style}]{result.decision.level}[/{style}] "
            f"→ [b]{result.decision.action}[/b]  [dim](acted now — no cloud wait)[/dim]"
        )
    if result.event is not None:
        ev = result.event
        lines.append(
            f"[bold]📦 Event[/bold]: {ev.type} "
            f"(conf {ev.confidence:.2f}, drift {ev.baseline_deviation:.2f})"
        )

    lines.append("")
    if features is not None:
        lines.append(f"[green]🔐 Raw audio scrubbed → features {features}[/green]")
    lines.append("[green]🔐 Raw audio/video/point-cloud discarded on device[/green]")
    return "\n".join(lines)


def _cloud_body(result: FlowResult) -> str:
    if not result.reported or result.assessment is None:
        return (
            "[bold red]⚠ OFFLINE[/bold red] — report queued (store-and-forward)\n\n"
            "The edge [b]already acted[/b] on its own decision;\n"
            "the report will re-sync when connectivity returns."
        )
    a = result.assessment
    style = _GRADE_STYLE.get(a.considered_level, "white")
    lines = [f"[bold]Considered level[/bold]: [{style}]{a.considered_level}[/{style}]"]
    lines.append(f"[bold]Reason[/bold]: {a.reason}")
    lines.append(f"[bold]Policy version[/bold]: {a.policy_version}")
    if result.policy_applied_version is not None:
        lines.append(f"[bold green]↺ EdgePolicyUpdate applied → v{result.policy_applied_version}[/bold green]")
    if a.caregiver_notifications:
        lines.append("[bold]Cloud sent[/bold]:")
        for action in a.caregiver_notifications:
            lines.append(f"  [{action.channel}] {action.message}")
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
        title="🏠 EDGE — decides & acts (authoritative)",
        subtitle="private · real-time · offline-capable",
        border_style="blue",
    )
    cloud = Panel(
        _cloud_body(result),
        title=f"☁ FOUNDRY — cloud (async) · {cloud_mode}",
        subtitle="considered assessment · policy",
        border_style="green" if result.reported else "red",
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
            Panel(payload, title="🔒 What crossed the boundary — DailyLivingEvent (report)", border_style="red")
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
