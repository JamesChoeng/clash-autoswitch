r"""Cross-platform HTTP client for Mihomo's external-controller (Clash Verge).

Transport is chosen automatically:
  - TCP  : the `external-controller: host:port` endpoint. Works on macOS,
           Linux, and Windows. Preferred everywhere.
  - Pipe : Windows named pipe (\\.\pipe\verge-mihomo) as a fallback when the
           TCP controller is disabled/unreachable (common on Windows where
           Verge defaults to the pipe).

Host/port/secret are auto-discovered from Clash Verge's config.yaml; override
with env vars CLASH_CONTROLLER (host:port) and CLASH_SECRET if needed.
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
from pathlib import Path

WIN_PIPE = r"\\.\pipe\verge-mihomo"


class ControllerError(RuntimeError):
    """Base error for any external-controller request failure."""


class ControllerUnreachable(ControllerError):
    """Transport failed entirely (controller down / pipe closed / TCP refused).

    Distinct from a controller that *responds* with a non-200 status -- callers
    use this to tell "Verge is temporarily gone" apart from "node is dead".
    """


def _verge_dirs() -> list[Path]:
    """Candidate Clash Verge Rev data dirs per platform."""
    home = Path.home()
    name = "io.github.clash-verge-rev.clash-verge-rev"
    if sys.platform == "win32":
        base = os.getenv("APPDATA", str(home / "AppData" / "Roaming"))
        return [Path(base) / name]
    if sys.platform == "darwin":
        return [home / "Library" / "Application Support" / name]
    # linux
    return [
        home / ".local" / "share" / name,
        home / ".config" / name,
    ]


def _discover() -> tuple[str | None, str]:
    """Return (controller 'host:port' or None, secret)."""
    env_ctrl = os.getenv("CLASH_CONTROLLER")
    env_secret = os.getenv("CLASH_SECRET")
    if env_ctrl:
        return env_ctrl, env_secret or ""

    controller, secret = None, ""
    for d in _verge_dirs():
        cfg = d / "config.yaml"
        if not cfg.exists():
            continue
        try:
            text = cfg.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        m = re.search(r"^external-controller:\s*([^\s#]+)", text, re.MULTILINE)
        if m:
            controller = m.group(1).strip().strip('"').strip("'")
        m = re.search(r"^secret:\s*([^\s#]+)", text, re.MULTILINE)
        if m:
            secret = m.group(1).strip().strip('"').strip("'")
        if controller:
            break
    return controller, secret or env_secret or "set-your-secret"


CONTROLLER, SECRET = _discover()


def _build_raw(method: str, path: str, body: str | None) -> bytes:
    head = (
        f"{method} {path} HTTP/1.1\r\n"
        "Host: localhost\r\n"
        f"Authorization: Bearer {SECRET}\r\n"
        "Accept: application/json\r\n"
    )
    payload = b""
    if body is not None:
        payload = body.encode("utf-8")
        head += "Content-Type: application/json\r\n"
        head += f"Content-Length: {len(payload)}\r\n"
    head += "Connection: close\r\n\r\n"
    return head.encode("utf-8") + payload


def _parse(data: bytes) -> tuple[int, str]:
    head, _, body = data.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1]) if head else 0
    if b"transfer-encoding: chunked" in head.lower():
        body = _dechunk(body)
    return status, body.decode("utf-8", "replace")


def _via_tcp(raw: bytes, host: str, port: int) -> bytes:
    # Raw socket bypasses any system HTTP proxy (Clash sets one!).
    with socket.create_connection((host, port), timeout=8) as s:
        s.sendall(raw)
        chunks = []
        while True:
            b = s.recv(65536)
            if not b:
                break
            chunks.append(b)
    return b"".join(chunks)


def _via_pipe(raw: bytes) -> bytes:
    with open(WIN_PIPE, "r+b", buffering=0) as p:
        p.write(raw)
        p.flush()
        chunks = []
        while True:
            b = p.read(65536)
            if not b:
                break
            chunks.append(b)
    return b"".join(chunks)


def request(method: str, path: str, body: str | None = None, retries: int = 5) -> tuple[int, str]:
    raw = _build_raw(method, path, body)

    # Build the transport preference list.
    transports = []
    if CONTROLLER and ":" in CONTROLLER:
        host, _, port = CONTROLLER.rpartition(":")
        host = host or "127.0.0.1"
        try:
            transports.append(("tcp", host, int(port)))
        except ValueError:
            pass
    if sys.platform == "win32":
        transports.append(("pipe", None, None))

    last_err: Exception | None = None
    for _ in range(retries):
        for kind, host, port in transports:
            try:
                if kind == "tcp":
                    data = _via_tcp(raw, host, port)
                else:
                    data = _via_pipe(raw)
                return _parse(data)
            except OSError as e:
                last_err = e
                continue
        time.sleep(0.3)
    raise ControllerUnreachable(
        f"controller request failed (transports={transports}): {last_err}"
    )


def _dechunk(body: bytes) -> bytes:
    out = bytearray()
    while body:
        size_line, _, rest = body.partition(b"\r\n")
        try:
            size = int(size_line.strip(), 16)
        except ValueError:
            break
        if size == 0:
            break
        out += rest[:size]
        body = rest[size + 2:]
    return bytes(out)


def get_json(path: str) -> dict:
    status, body = request("GET", path)
    if status != 200:
        raise ControllerError(f"GET {path} -> {status}: {body[:200]}")
    return json.loads(body)


if __name__ == "__main__":
    print("controller:", CONTROLLER, "secret:", SECRET[:4] + "..." if SECRET else "(none)")
    print(request("GET", "/version"))
