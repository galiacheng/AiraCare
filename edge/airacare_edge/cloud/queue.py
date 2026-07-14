"""Offline store-and-forward queue for DailyLivingEvents.

When the edge cannot reach the cloud (Foundry) it must not lose the event: the immediate
safety response happens locally, and the event is **persisted to disk** so it can be
re-sent once connectivity is restored. Events older than a configured TTL are dropped
(a stale wandering event has little cloud value after a while).

Durable across process restarts: each pending event is one JSON file in a directory.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from airacare_edge.agent import CloudGateway
from airacare_edge.cloud.contracts import CloudAssessment, DailyLivingEvent, utcnow


@dataclass
class FlushResult:
    sent: list[tuple[DailyLivingEvent, CloudAssessment]] = field(default_factory=list)
    expired: int = 0
    remaining: int = 0

    @property
    def sent_count(self) -> int:
        return len(self.sent)


class OfflineQueue:
    def __init__(self, directory: str | Path, ttl_seconds: float = 3600.0) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl_seconds

    def count(self) -> int:
        return sum(1 for _ in self._dir.glob("*.json"))

    def enqueue(self, event: DailyLivingEvent, now: datetime | None = None) -> Path:
        moment = now or utcnow()
        record = {
            "enqueued_at": moment.isoformat(),
            "event": json.loads(event.model_dump_json()),
        }
        name = f"{moment.strftime('%Y%m%dT%H%M%S%f')}_{uuid.uuid4().hex[:8]}.json"
        path = self._dir / name
        # Atomic write: temp file then replace, so a reader never sees a partial record.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record), encoding="utf-8")
        os.replace(tmp, path)
        return path

    def _pending(self) -> list[tuple[Path, dict]]:
        items: list[tuple[Path, dict]] = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                items.append((path, json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError):
                continue
        return items

    def flush(self, client: CloudGateway, now: datetime | None = None) -> FlushResult:
        """Re-send pending events oldest-first; drop expired; stop if still offline."""
        moment = now or utcnow()
        result = FlushResult()
        for path, record in self._pending():
            enqueued_at = datetime.fromisoformat(record["enqueued_at"])
            if (moment - enqueued_at).total_seconds() > self._ttl:
                path.unlink(missing_ok=True)
                result.expired += 1
                continue
            event = DailyLivingEvent.model_validate(record["event"])
            assessment = client.report(event)
            if assessment is None:
                break  # still offline — keep this and the rest for next time
            path.unlink(missing_ok=True)
            result.sent.append((event, assessment))
        result.remaining = self.count()
        return result
