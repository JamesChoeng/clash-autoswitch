"""Install/uninstall clash-autoswitch as a login-launched background service.

One command per platform, paths filled in automatically -- no hand-editing:
  - macOS : launchd LaunchAgent (~/Library/LaunchAgents)
  - Linux : systemd --user unit (~/.config/systemd/user)
  - Windows: Scheduled Task triggered at logon (schtasks)

All three run `<python> -m clash_autoswitch run`, restart on crash where the
init system supports it, and survive logout/login.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .daemon import PYTHON, _NO_WINDOW

LABEL = "com.clash-autoswitch"
TASK_NAME = "clash-autoswitch"


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
        <string>clash_autoswitch</string>
        <string>run</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/clash-autoswitch.out.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/clash-autoswitch.err.log</string>
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
Description=Clash auto-switch (fastest-node picker + failover)
After=network-online.target

[Service]
Type=simple
ExecStart={PYTHON} -m clash_autoswitch run
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


# --- Windows (Scheduled Task at logon) --------------------------------------


def _install_windows() -> str:
    # /SC ONLOGON for the current user; pythonw keeps it windowless.
    tr = f'"{PYTHON}" -m clash_autoswitch run'
    code, out = _run([
        "schtasks", "/Create", "/TN", TASK_NAME, "/SC", "ONLOGON",
        "/TR", tr, "/RL", "LIMITED", "/F",
    ])
    if code != 0:
        return f"`schtasks /Create` failed:\n{out}".rstrip()
    # Kick it off now so the user doesn't have to log out/in to start it.
    _run(["schtasks", "/Run", "/TN", TASK_NAME])
    return f"installed scheduled task '{TASK_NAME}' (runs at logon + started now)."


def _uninstall_windows() -> str:
    _run(["schtasks", "/End", "/TN", TASK_NAME])
    code, out = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    if code != 0:
        return f"not installed or delete failed:\n{out}".rstrip()
    return f"removed scheduled task '{TASK_NAME}'."


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
