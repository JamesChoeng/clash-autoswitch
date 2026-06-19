"""Per-user settings, subscription fetching, and the managed mihomo config.

In standalone mode this package owns the whole proxy config: the user supplies a
Clash/Mihomo subscription URL, we download it and inject our own
external-controller, secret, and mixed-port so the rest of the tool (and the OS
proxy) can talk to the core we launched.

YAML is patched textually rather than via PyYAML to keep zero third-party
dependencies -- Clash subscriptions are mappings keyed at column 0, so stripping
and prepending top-level keys is enough.

This module is the single source of truth for the per-user state directory; the
daemon and other modules import STATE_DIR from here.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import sys
import urllib.request
from pathlib import Path


def _default_state_dir() -> Path:
    home = Path.home()
    app = "clashpilot"
    if sys.platform == "win32":
        base = os.getenv("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return Path(base) / app
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / app
    base = os.getenv("XDG_STATE_HOME") or str(home / ".local" / "state")
    return Path(base) / app


STATE_DIR = Path(os.getenv("CLASHPILOT_STATE_DIR") or _default_state_dir())
try:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    STATE_DIR = Path.home()

MANAGED_DIR = STATE_DIR / "managed"
CORE_DIR = STATE_DIR / "core"
SETTINGS_FILE = STATE_DIR / "settings.json"
CONFIG_FILE = MANAGED_DIR / "config.yaml"
SUBSCRIPTION_FILE = MANAGED_DIR / "subscription.yaml"

DEFAULT_MIXED_PORT = 7890
DEFAULT_CONTROLLER_PORT = 9090


class ConfigError(RuntimeError):
    """Raised on missing subscription / unfetchable subscription content."""


# --- Settings ----------------------------------------------------------------


def get_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return {}


def save_settings(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def subscription_url() -> str | None:
    return os.getenv("CLASHPILOT_SUBSCRIPTION") or get_settings().get("subscription_url")


def set_subscription_url(url: str) -> None:
    s = get_settings()
    s["subscription_url"] = url
    save_settings(s)


def controller_port() -> int:
    try:
        return int(os.getenv("CLASHPILOT_CONTROLLER_PORT") or "")
    except ValueError:
        pass
    return int(get_settings().get("controller_port") or DEFAULT_CONTROLLER_PORT)


def mixed_port() -> int:
    try:
        return int(os.getenv("CLASHPILOT_MIXED_PORT") or "")
    except ValueError:
        pass
    return int(get_settings().get("mixed_port") or DEFAULT_MIXED_PORT)


def get_secret() -> str:
    """Stable controller secret, generated once and persisted in settings."""
    env = os.getenv("CLASH_SECRET")
    if env:
        return env
    s = get_settings()
    sec = s.get("secret")
    if not sec:
        sec = secrets.token_hex(16)
        s["secret"] = sec
        save_settings(s)
    return sec


# --- Subscription + managed config -------------------------------------------


def _opener() -> urllib.request.OpenerDirector:
    # Ignore any system/env proxy: we may be downloading *before* the proxy is up.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch_subscription(url: str | None = None) -> str:
    """Download the subscription body (decoding base64 panels) and cache it."""
    url = url or subscription_url()
    if not url:
        raise ConfigError("no subscription URL set; run: clashpilot set-sub <url>")
    req = urllib.request.Request(url, headers={"User-Agent": "clash-verge/v2.0.0"})
    try:
        with _opener().open(req, timeout=30) as r:
            raw = r.read()
    except Exception as e:  # noqa: BLE001
        raise ConfigError(f"failed to fetch subscription: {e}") from e
    text = raw.decode("utf-8", "replace")
    # Clash subs are YAML containing `proxies:`/`proxy-providers:`; if neither is
    # present the body may be base64-encoded -- try to decode it.
    if "proxies:" not in text and "proxy-providers:" not in text:
        stripped = text.strip()
        try:
            decoded = base64.b64decode(stripped + "=" * (-len(stripped) % 4)).decode("utf-8", "replace")
            if "proxies:" in decoded or "proxy-providers:" in decoded:
                text = decoded
        except Exception:  # noqa: BLE001
            pass
    MANAGED_DIR.mkdir(parents=True, exist_ok=True)
    SUBSCRIPTION_FILE.write_text(text, encoding="utf-8")
    return text


# Top-level keys we own; any subscription-provided copy is stripped so ours win
# and mihomo never sees a duplicate top-level key.
_OVERRIDE_KEYS = frozenset({
    "external-controller", "external-controller-tls", "secret", "external-ui",
    "mixed-port", "port", "socks-port", "redir-port", "tproxy-port",
    "allow-lan", "bind-address", "mode",
})

_TOP_KEY_RE = re.compile(r"^([A-Za-z0-9_.-]+):")


def _strip_top_level_keys(yaml_text: str, keys: frozenset) -> str:
    """Drop the listed top-level mapping keys (and their indented blocks)."""
    out: list[str] = []
    skipping = False
    for line in yaml_text.splitlines():
        m = _TOP_KEY_RE.match(line)
        if m:  # a new top-level key starts here
            skipping = m.group(1) in keys
        if not skipping:
            out.append(line)
    return "\n".join(out)


def build_managed_config(subscription_text: str | None = None) -> Path:
    """Regenerate the managed config.yaml from the subscription + our overrides."""
    text = subscription_text
    if text is None:
        if SUBSCRIPTION_FILE.exists():
            text = SUBSCRIPTION_FILE.read_text(encoding="utf-8")
        else:
            text = fetch_subscription()
    base = _strip_top_level_keys(text, _OVERRIDE_KEYS).lstrip("\n")
    header = (
        "# Managed by clashpilot -- do not edit; regenerated from your subscription.\n"
        f"mixed-port: {mixed_port()}\n"
        "allow-lan: false\n"
        "bind-address: 127.0.0.1\n"
        "mode: rule\n"
        f"external-controller: 127.0.0.1:{controller_port()}\n"
        f'secret: "{get_secret()}"\n'
    )
    MANAGED_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(header + "\n" + base + "\n", encoding="utf-8")
    return CONFIG_FILE


def update_subscription() -> Path:
    """Re-fetch the subscription and rebuild the managed config."""
    return build_managed_config(fetch_subscription())


def ensure_config() -> Path:
    """Make sure a managed config exists, building it from the subscription."""
    if CONFIG_FILE.exists():
        return CONFIG_FILE
    return build_managed_config()
