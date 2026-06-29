"""Probe whether Cursor's model endpoint returns a degraded subset under
different network/auth conditions, to confirm the root cause.

Tests:
  A. normal request through proxy (baseline)
  B. request with no auth token
  C. request with empty body / wrong content-type
  D. request directly (no proxy) — simulates proxy down
  E. request through proxy with a geo/region header stripped
"""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

STATE_DB = r"C:\Users\james\AppData\Roaming\Cursor\User\globalStorage\state.vscdb"
API_URL = "https://api2.cursor.sh/aiserver.v1.AiService/AvailableModels"
PROXY = "http://127.0.0.1:7890"


def get_token() -> str:
    con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    row = con.execute(
        "SELECT value FROM ItemTable WHERE key='cursorAuth/accessToken'"
    ).fetchone()
    con.close()
    val = row[0]
    return val.decode("utf-8") if isinstance(val, bytes) else val


def fetch(label: str, *, use_proxy: bool, token: str | None, body: bytes = b"{}",
          extra_headers: dict | None = None) -> None:
    print(f"\n=== {label} ===")
    handlers = []
    if use_proxy:
        handlers.append(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    opener = urllib.request.build_opener(*handlers)
    headers = {"Content-Type": "application/json", "Connect-Protocol-Version": "1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(API_URL, data=body, method="POST", headers=headers)
    try:
        with opener.open(req, timeout=15) as resp:
            data = json.loads(resp.read())
        models = data.get("models") or []
        names = [m["name"] for m in models]
        print(f"  count: {len(models)}")
        # check the 6 degraded ones
        degraded = {"default", "composer-2.5", "grok-build-0.1", "grok-4.3", "kimi-k2.5", "glm-5.2"}
        match = degraded & set(names)
        print(f"  matches degraded-6: {sorted(match)}")
        has_opus = any("claude-opus-4-8" in n for n in names)
        has_gpt55 = any(n.startswith("gpt-5.5") for n in names)
        print(f"  has opus-4-8: {has_opus}, has gpt-5.5: {has_gpt55}")
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read()[:300]}")
    except Exception as e:
        print(f"  error: {type(e).__name__}: {e}")


def main() -> int:
    token = get_token()
    print(f"token len: {len(token)}")

    fetch("A. baseline (proxy + auth)", use_proxy=True, token=token)
    fetch("B. no auth token", use_proxy=True, token=None)
    fetch("C. empty body", use_proxy=True, token=token, body=b"")
    fetch("D. no proxy (simulates proxy down)", use_proxy=False, token=token)

    # the 6 degraded models — try to see if any single endpoint returns exactly them
    # also check a connect-stream style request
    fetch("E. wrong content-type", use_proxy=True, token=token,
          extra_headers={"Content-Type": "application/proto"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
