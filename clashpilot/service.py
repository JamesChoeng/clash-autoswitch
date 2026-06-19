"""Install/uninstall clashpilot as a login-launched background service.

One command per platform, paths filled in automatically -- no hand-editing:
  - macOS : launchd LaunchAgent (~/Library/LaunchAgents)
  - Linux : systemd --user unit (~/.config/systemd/user)
  - Windows: Scheduled Task triggered at logon (schtasks), falling back to a
             Startup-folder VBS launcher when Task Scheduler denies access.

All three run `<python> -m clashpilot up` (the full standalone stack: core +
system proxy + autoswitch), restart on crash where the init system supports it,
and survive logout/login.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .daemon import PYTHON, _NO_WINDOW

LABEL = "com.clashpilot"
TASK_NAME = "clashpilot"


def _run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, **_NO_WINDOW)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# --- macOS (launchd) ---------------------------------------------------------


def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _launchd_plist() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{PYTHON}</string>
        <string>-m</string>
        <string>clashpilot</string>
        <string>up</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/clashpilot.out.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/clashpilot.err.log</string>
</dict>
</plist>
"""


def _install_macos() -> str:
    path = _launchd_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_launchd_plist(), encoding="utf-8")
    _run(["launchctl", "unload", str(path)])  # ignore: may not be loaded yet
    code, out = _run(["launchctl", "load", str(path)])
    if code != 0:
        return f"wrote {path} but `launchctl load` failed:\n{out}".rstrip()
    return f"installed launchd agent: {path}\nstarts at login + restarts on crash."


def _uninstall_macos() -> str:
    path = _launchd_plist_path()
    if not path.exists():
        return "not installed (no launchd plist found)"
    _run(["launchctl", "unload", str(path)])
    path.unlink(missing_ok=True)
    return f"removed launchd agent: {path}"


# --- Linux (systemd --user) --------------------------------------------------


def _systemd_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"{TASK_NAME}.service"


def _systemd_unit() -> str:
    return f"""[Unit]
Description=clashpilot (standalone fastest-node Clash client + failover)
After=network-online.target

[Service]
Type=simple
ExecStart={PYTHON} -m clashpilot up
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""


def _install_linux() -> str:
    path = _systemd_unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_systemd_unit(), encoding="utf-8")
    _run(["systemctl", "--user", "daemon-reload"])
    code, out = _run(["systemctl", "--user", "enable", "--now", f"{TASK_NAME}.service"])
    if code != 0:
        return (
            f"wrote {path} but `systemctl --user enable --now` failed:\n{out}\n"
            "If you're on a headless box, you may need: loginctl enable-linger $USER"
        ).rstrip()
    return f"installed systemd --user unit: {path}\nstarts at login + restarts on crash."


def _uninstall_linux() -> str:
    path = _systemd_unit_path()
    if not path.exists():
        return "not installed (no systemd unit found)"
    _run(["systemctl", "--user", "disable", "--now", f"{TASK_NAME}.service"])
    path.unlink(missing_ok=True)
    _run(["systemctl", "--user", "daemon-reload"])
    return f"removed systemd --user unit: {path}"


# --- Windows (Scheduled Task at logon, Startup VBS fallback) -----------------


def _windows_startup_dir() -> Path:
    appdata = os.getenv("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _startup_vbs_path() -> Path:
    return _windows_startup_dir() / "clashpilot-start.vbs"


def _startup_vbs() -> str:
    return (
        'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.Run """{PYTHON}"" -m clashpilot up", 0, False\n'
    )


def _install_windows_startup_vbs(reason: str | None = None) -> str:
    path = _startup_vbs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_startup_vbs(), encoding="utf-8")
    _run(["wscript.exe", str(path)])
    prefix = f"`schtasks /Create` failed; using Startup launcher instead:\n{reason}\n" if reason else ""
    return f"{prefix}installed Startup launcher: {path}\nstarts at login + started now.".rstrip()


def _install_windows() -> str:
    # /SC ONLOGON for the current user; pythonw keeps it windowless.
    tr = f'"{PYTHON}" -m clashpilot up'
    code, out = _run([
        "schtasks", "/Create", "/TN", TASK_NAME, "/SC", "ONLOGON",
        "/TR", tr, "/RL", "LIMITED", "/F",
    ])
    if code != 0:
        return _install_windows_startup_vbs(out.rstrip())
    # Kick it off now so the user doesn't have to log out/in to start it.
    _run(["schtasks", "/Run", "/TN", TASK_NAME])
    return f"installed scheduled task '{TASK_NAME}' (runs at logon + started now)."


def _uninstall_windows() -> str:
    _run(["schtasks", "/End", "/TN", TASK_NAME])
    code, out = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    vbs = _startup_vbs_path()
    removed_vbs = vbs.exists()
    vbs.unlink(missing_ok=True)
    parts = []
    if code == 0:
        parts.append(f"removed scheduled task '{TASK_NAME}'")
    else:
        parts.append(f"scheduled task not installed or delete failed:\n{out}".rstrip())
    if removed_vbs:
        parts.append(f"removed Startup launcher: {vbs}")
    return "\n".join(parts).rstrip()


# --- Dispatch ----------------------------------------------------------------


def install_service() -> str:
    if sys.platform == "darwin":
        return _install_macos()
    if sys.platform == "win32":
        return _install_windows()
    return _install_linux()


def uninstall_service() -> str:
    if sys.platform == "darwin":
        return _uninstall_macos()
    if sys.platform == "win32":
        return _uninstall_windows()
    return _uninstall_linux()
