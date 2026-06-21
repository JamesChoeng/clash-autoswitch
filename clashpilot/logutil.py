"""Daemon log file + optional foreground console mirroring."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime

from .config import STATE_DIR
from .env_config import LOG_MAX_BYTES

LOG_FILE = STATE_DIR / "clashpilot.log"

_CONSOLE_NOTIFY: Callable[[str], None] | None = None


def set_console_notify(fn: Callable[[str], None] | None) -> None:
    """Mirror key status lines to stdout during foreground `clashpilot up`."""
    global _CONSOLE_NOTIFY
    _CONSOLE_NOTIFY = fn


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%H:%M:%S')}  {msg}"
    try:
        if LOG_MAX_BYTES > 0 and LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_MAX_BYTES:
            LOG_FILE.replace(LOG_FILE.with_name(LOG_FILE.name + ".1"))
    except OSError:
        pass
    try:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def notify(msg: str) -> None:
    """Log plus mirror to stdout when a foreground console hook is installed."""
    log(msg)
    if _CONSOLE_NOTIFY:
        try:
            _CONSOLE_NOTIFY(msg)
        except Exception:  # noqa: BLE001
            pass


def tail_log(lines: int = 15) -> str:
    if not LOG_FILE.exists():
        return "(no log yet)"
    try:
        with LOG_FILE.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 65536))
            data = fh.read()
    except OSError:
        return "(log unreadable)"
    text = data.decode("utf-8", "replace").splitlines()
    return "\n".join(text[-lines:])
