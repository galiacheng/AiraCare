"""Console helpers."""

from __future__ import annotations

import sys


def ensure_utf8_stdout() -> None:
    """Force UTF-8 on stdout/stderr so emoji output doesn't crash when piped on Windows.

    Interactive Windows Terminal handles UTF-8, but a redirected/piped stream defaults to
    the locale (e.g. cp1252) and raises UnicodeEncodeError on emoji. Call from entrypoints.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 — best-effort; never fatal
            pass
