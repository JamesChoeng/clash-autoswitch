"""Set / unset the OS-level HTTP(S)+SOCKS proxy, per platform.

mihomo's mixed-port serves HTTP and SOCKS on the same port, so a single host:port
covers everything.

  - Windows : HKCU Internet Settings registry (winreg) + WinINet refresh (ctypes)
  - macOS   : networksetup against every network service
  - Linux   : gsettings (GNOME) best-effort; fall back to exporting http_proxy

All functions are best-effort and return a bool; they never raise so daemon
shutdown can always run cleanup.
"""

from __future__ import annotations

import subprocess
import sys

_WIN_INET_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
_WIN_BYPASS = "localhost;127.*;10.*;172.16.*;172.17.*;172.18.*;192.168.*;<local>"


# --- Windows -----------------------------------------------------------------


def _win_refresh() -> None:
    import ctypes

    INTERNET_OPTION_SETTINGS_CHANGED = 39
    INTERNET_OPTION_REFRESH = 37
    wininet = ctypes.windll.wininet  # type: ignore[attr-defined]
    wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
    wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)


def _win_set(server: str) -> bool:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_INET_KEY, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "ProxyServer", 0, winreg.REG_SZ, server)
        winreg.SetValueEx(k, "ProxyOverride", 0, winreg.REG_SZ, _WIN_BYPASS)
    _win_refresh()
    return True


def _win_unset() -> bool:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_INET_KEY, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 0)
    _win_refresh()
    return True


# --- macOS -------------------------------------------------------------------


def _mac_services() -> list[str]:
    r = subprocess.run(
        ["networksetup", "-listallnetworkservices"],
        capture_output=True, text=True,
    )
    # First line is an explanatory header; disabled services are prefixed with '*'.
    out = []
    for line in r.stdout.splitlines()[1:]:
        name = line.strip()
        if name and not name.startswith("*"):
            out.append(name)
    return out


def _mac_set(host: str, port: int) -> bool:
    ok = False
    for svc in _mac_services():
        for cmd in (
            ["networksetup", "-setwebproxy", svc, host, str(port)],
            ["networksetup", "-setwebproxystate", svc, "on"],
            ["networksetup", "-setsecurewebproxy", svc, host, str(port)],
            ["networksetup", "-setsecurewebproxystate", svc, "on"],
            ["networksetup", "-setsocksfirewallproxy", svc, host, str(port)],
            ["networksetup", "-setsocksfirewallproxystate", svc, "on"],
        ):
            subprocess.run(cmd, capture_output=True)
        ok = True
    return ok


def _mac_unset() -> bool:
    ok = False
    for svc in _mac_services():
        for cmd in (
            ["networksetup", "-setwebproxystate", svc, "off"],
            ["networksetup", "-setsecurewebproxystate", svc, "off"],
            ["networksetup", "-setsocksfirewallproxystate", svc, "off"],
        ):
            subprocess.run(cmd, capture_output=True)
        ok = True
    return ok


# --- Linux (GNOME / gsettings) ----------------------------------------------


def _linux_set(host: str, port: int) -> bool:
    cmds = [
        ["gsettings", "set", "org.gnome.system.proxy", "mode", "manual"],
        ["gsettings", "set", "org.gnome.system.proxy.http", "host", host],
        ["gsettings", "set", "org.gnome.system.proxy.http", "port", str(port)],
        ["gsettings", "set", "org.gnome.system.proxy.https", "host", host],
        ["gsettings", "set", "org.gnome.system.proxy.https", "port", str(port)],
        ["gsettings", "set", "org.gnome.system.proxy.socks", "host", host],
        ["gsettings", "set", "org.gnome.system.proxy.socks", "port", str(port)],
    ]
    try:
        for c in cmds:
            subprocess.run(c, capture_output=True)
    except FileNotFoundError:
        return False  # no gsettings: user must export http_proxy themselves
    return True


def _linux_unset() -> bool:
    try:
        subprocess.run(
            ["gsettings", "set", "org.gnome.system.proxy", "mode", "none"],
            capture_output=True,
        )
    except FileNotFoundError:
        return False
    return True


# --- Dispatch ----------------------------------------------------------------


def set_system_proxy(host: str, port: int) -> bool:
    try:
        if sys.platform == "win32":
            return _win_set(f"{host}:{port}")
        if sys.platform == "darwin":
            return _mac_set(host, port)
        return _linux_set(host, port)
    except Exception:  # noqa: BLE001
        return False


def unset_system_proxy() -> bool:
    try:
        if sys.platform == "win32":
            return _win_unset()
        if sys.platform == "darwin":
            return _mac_unset()
        return _linux_unset()
    except Exception:  # noqa: BLE001
        return False
