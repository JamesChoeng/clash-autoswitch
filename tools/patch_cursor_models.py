"""Fetch full model catalog from Cursor API and patch state.vscdb in place.

Can run while Cursor is open — then Reload Window (or restart Cursor).
Proxy must be up on 7890.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

STATE_DB = Path(
    r"C:\Users\james\AppData\Roaming\Cursor\User\globalStorage\state.vscdb"
)
APP_USER_KEY = (
    "src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl"
    ".persistentStorage.applicationUser"
)
API_URL = "https://api2.cursor.sh/aiserver.v1.AiService/AvailableModels"
PROXY = "http://127.0.0.1:7890"

USER_MODELS = [
    "claude-opus-4-8",
    "gpt-5.5",
    "default",
    "composer-2.5",
]


def get_token(con: sqlite3.Connection) -> str:
    row = con.execute(
        "SELECT value FROM ItemTable WHERE key='cursorAuth/accessToken'"
    ).fetchone()
    if not row:
        raise SystemExit("no cursorAuth/accessToken")
    val = row[0]
    return val.decode("utf-8") if isinstance(val, bytes) else val


def fetch_models(token: str) -> list[dict]:
    proxy_handler = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(
        API_URL,
        data=b"{}",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
        },
    )
    with opener.open(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data["models"]


def cursor_running() -> bool:
    import subprocess

    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Cursor.exe", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    )
    return "Cursor.exe" in out.stdout


def patch_catalog(*, require_quit: bool = True) -> int:
    """Write the full model catalog from Cursor API into state.vscdb."""
    if not STATE_DB.exists():
        raise SystemExit(f"missing {STATE_DB}")

    if require_quit and cursor_running():
        print(
            "ERROR: Cursor.exe is running — it will overwrite this patch immediately.",
            file=sys.stderr,
        )
        print("Fully quit Cursor first, then rerun this script.", file=sys.stderr)
        return 2

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup = STATE_DB.with_name(f"state.vscdb.pre-patch-{stamp}")
    shutil.copy2(STATE_DB, backup)
    print(f"backup -> {backup}")

    con = sqlite3.connect(STATE_DB)
    token = get_token(con)
    models = fetch_models(token)
    print(f"API returned {len(models)} models")

    names = [m["name"] for m in models]
    for want in USER_MODELS:
        found = want in names or any(
            want in (m.get("legacySlugs") or []) for m in models if m.get("name") == want
        )
        print(f"  {'OK' if found else 'MISSING':7} {want}")

    row = con.execute(
        "SELECT value FROM ItemTable WHERE key=?", (APP_USER_KEY,)
    ).fetchone()
    raw = row[0]
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)

    before = data.get("availableDefaultModels2") or []
    print(f"\ncached catalog had {len(before)} models")

    data["availableDefaultModels2"] = models

    ai = data.setdefault("aiSettings", {})
    ai["userAddedModels"] = list(
        dict.fromkeys(USER_MODELS + (ai.get("userAddedModels") or []))
    )

    composer_cfg = ai.setdefault("modelConfig", {}).setdefault("composer", {})
    composer_cfg["modelName"] = "claude-opus-4-8"
    composer_cfg["maxMode"] = False
    composer_cfg["selectedModels"] = [
        {"modelId": "claude-opus-4-8", "parameters": []}
    ]

    blob = json.dumps(data, ensure_ascii=False).encode("utf-8")
    con.execute("UPDATE ItemTable SET value=? WHERE key=?", (blob, APP_USER_KEY))
    con.commit()

    verify = json.loads(
        con.execute(
            "SELECT value FROM ItemTable WHERE key=?", (APP_USER_KEY,)
        ).fetchone()[0].decode()
    )
    got = len(verify.get("availableDefaultModels2") or [])
    con.close()
    if got != len(models):
        print(f"ERROR: verify failed — wrote {len(models)} but read back {got}", file=sys.stderr)
        return 1

    print(f"\npatched catalog -> {len(models)} models")
    print("userAddedModels ->", ai["userAddedModels"])
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    rc = patch_catalog(require_quit=True)
    if rc == 0:
        print("\nNow: Ctrl+Shift+P -> Reload Window")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
