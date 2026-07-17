"""AiraCare care dashboard — a standalone, read-only analytics surface over filed events.

This package is the population-health / longitudinal view of the demo (the runbook's Beat 6).
It reads the **same** ``daily_event`` store that the deployed Foundry hosted agent writes to
(Cosmos in the live demo, or local SQLite for an offline dry-run) and renders the cognitive
trajectory, the event mix, the edge-vs-cloud escalation funnel, and the nighttime-risk signal.

It is deliberately self-contained: it depends only on ``pydantic`` + ``pyyaml`` (and, for the
Cosmos backend, the optional ``azure-cosmos`` / ``azure-identity`` extras). It never touches the
real-time safety path — it only *reads* the append-only event log. The deterministic assessment
and the Cosmos write both live in the Foundry hosted agent (``foundry-hosted-agent/``); the edge
speaks standard A2A directly to that agent. There is no bespoke A2A server anymore.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
