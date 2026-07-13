"""Raw sensor events produced inside the home (simulated for the PoC)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

RawEventKind = Literal[
    "out_of_bed",
    "door_open",
    "motion",
    "bed_return",
    "pillbox_open",
]


class RawSensorEvent(BaseModel):
    """A single raw sensor reading. Never leaves the device in raw form."""

    kind: RawEventKind
    timestamp: datetime
    meta: dict[str, Any] = Field(default_factory=dict)
