"""Notification tool — cloud-owned delivery of graded actions (STUB for this scaffold).

Per the design, the **cloud** owns notifications/escalation (family -> community ->
emergency); the edge acts autonomously on its own and never depends on the cloud. This tool is
where cloud-side delivery lives. In this scaffold it records actions instead of sending them,
so the flow is observable without external services (SMS/push/geofence come later).

Pure stdlib; ported from ``foundry-a2a-server``.
"""

from __future__ import annotations

from airacare_care.contracts import CloudAction


class NotificationTool:
    """Records notifications instead of sending them (stub)."""

    def __init__(self) -> None:
        self.sent: list[CloudAction] = []

    def notify(self, action: CloudAction) -> None:
        # Placeholder: a real tool would dispatch via SMS/push/community/emergency channels.
        self.sent.append(action)
