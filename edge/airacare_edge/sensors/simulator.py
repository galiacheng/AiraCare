"""Simulated sensor injectors for the flagship Nighttime Wandering scenario.

Real hardware (mmWave radar, door/bed sensors, IMU) is out of scope for the PoC; these
helpers produce the same :class:`RawSensorEvent` stream the real sensing layer would.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airacare_edge.cloud.contracts import utcnow
from airacare_edge.sensors.events import RawSensorEvent


def nighttime_wander_events(at: datetime | None = None) -> list[RawSensorEvent]:
    """Out-of-bed followed ~20s later by a door-open — the classic wander pattern."""
    start = at or utcnow()
    return [
        RawSensorEvent(kind="out_of_bed", timestamp=start),
        RawSensorEvent(kind="door_open", timestamp=start + timedelta(seconds=20)),
    ]


def restless_but_in_bed_events(at: datetime | None = None) -> list[RawSensorEvent]:
    """Minor motion only — should stay below the wander threshold (L0 log)."""
    start = at or utcnow()
    return [RawSensorEvent(kind="motion", timestamp=start)]
