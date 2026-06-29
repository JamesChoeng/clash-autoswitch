"""Try to fetch Cursor model catalog via API (proxy must be up)."""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.error
import urllib.request

STATE_DB = r"C:\Users\james\AppData\Roaming\Cursor\User\globalStorage\state.vscdb"
PROXY = "http://127.0.0.1:7890"

# Common Cursor model-list endpoints (best-effort).
ENDPOINTS = [
    "https://api2.cursor.sh/aiserver.v1.AiService/AvailableModels",
    "https://api2.cursor.sh/aiserver.v1.AiService/GetDefaultModelNudgeData",
    "https://api4.cursor.sh/aiserver.v1.AiService/AvailableModels",
]


def get_access_token() -> str | None:
    con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    row = con.execute(
        "SELECT value FROM ItemTable WHERE key='cursorAuth/accessToken'"
    ).fetchone()
    con.close()
    if not row:
        return None
    val = row[0]
    return val.decode("utf-8") if isinstance(val, bytes) else val


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    token = get_access_token()
    if not token:
        print("no access token in state.vscdb", file=sys.stderr)
        return 1
    print(f"token length: {len(token)}")

    proxy_handler = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    opener = urllib.request.build_opener(proxy_handler)

    for url in ENDPOINTS:
        print(f"\n=== POST {url} ===")
        req = urllib.request.Request(
            url,
            data=b"{}",
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Connect-Protocol-Version": "1",
            },
        )
        try:
            with opener.open(req, timeout=15) as resp:
                body = resp.read()
                print(f"status: {resp.status}, bytes: {len(body)}")
                try:
                    data = json.loads(body)
                    print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])
                except json.JSONDecodeError:
                    print(body[:500])
        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code}: {e.read()[:500]}")
        except Exception as e:
            print(f"error: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
