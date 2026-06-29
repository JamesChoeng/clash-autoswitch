"""Windows UAC elevation helpers for TUN routing."""

from __future__ import annotations

import ctypes
import subprocess
import sys


def is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False


def _command_argv() -> list[str]:
    if len(sys.argv) >= 3 and sys.argv[1] == "-m" and sys.argv[2] == "clashpilot":
        return list(sys.argv[3:])
    return list(sys.argv[1:])


def relaunch_elevated(*, extra_args: list[str] | None = None) -> int:
    """Re-launch `python -m clashpilot …` with UAC. Parent should exit after 0."""
    from .daemon import PYTHON

    argv = _command_argv()
    if extra_args:
        for arg in extra_args:
            if arg not in argv:
                argv.append(arg)

    params = subprocess.list2cmdline(["-m", "clashpilot", *argv])
    rc = ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
        None,
        "runas",
        str(PYTHON),
        params,
        None,
        1,
    )
    if rc <= 32:
        print(
            f"clashpilot: UAC elevation failed (ShellExecute={rc}). "
            "Approve the prompt or run Terminal as Administrator.",
            file=sys.stderr,
        )
        return 1
    return 0
