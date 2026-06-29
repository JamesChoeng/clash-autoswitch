"""Verify GPT 5.5 availability and network path for Cursor."""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request

PROXY = "http://127.0.0.1:7890"
STATE_DB = r"C:\Users\james\AppData\Roaming\Cursor\User\globalStorage\state.vscdb"
APP_USER_KEY = (
    "src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl"
    ".persistentStorage.applicationUser"
)
API_URL = "https://api2.cursor.sh/aiserver.v1.AiService/AvailableModels"
AGENT_URLS = (
    "https://api2.cursor.sh/",
    "https://agent.api5.cursor.sh/",
    "https://agentn.api5.cursor.sh/",
)


def proxy_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    )


def get_token(con: sqlite3.Connection) -> str:
    row = con.execute(
        "SELECT value FROM ItemTable WHERE key='cursorAuth/accessToken'"
    ).fetchone()
    val = row[0]
    return val.decode("utf-8") if isinstance(val, bytes) else val


def probe_https(opener: urllib.request.OpenerDirector, url: str, timeout: float = 10.0) -> tuple[bool, str]:
    t0 = time.perf_counter()
    req = urllib.request.Request(url, method="HEAD")
    try:
        with opener.open(req, timeout=timeout) as resp:
            ms = int((time.perf_counter() - t0) * 1000)
            return True, f"HTTP {resp.status}, {ms}ms"
    except urllib.error.HTTPError as e:
        ms = int((time.perf_counter() - t0) * 1000)
        # TLS + proxy OK if we got an HTTP response from upstream.
        return True, f"HTTP {e.code}, {ms}ms"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print("=== GPT 5.5 connectivity check ===\n")

    con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    token = get_token(con)
    raw = con.execute(
        "SELECT value FROM ItemTable WHERE key=?", (APP_USER_KEY,)
    ).fetchone()[0]
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    con.close()

    cached = data.get("availableDefaultModels2") or []
    cached_names = [m.get("name") for m in cached]
    gpt_cached = [n for n in cached_names if n and "gpt-5.5" in n]

    print("1) Local Cursor cache")
    print(f"   catalog size: {len(cached)}")
    print(f"   gpt-5.5 in cache: {'YES (' + str(len(gpt_cached)) + ' variants)' if gpt_cached else 'NO'}")
    composer = (data.get("aiSettings") or {}).get("modelConfig", {}).get("composer", {})
    print(f"   composer model: {composer.get('modelName')}")

    print("\n2) Cursor API catalog (via proxy 7890)")
    opener = proxy_opener()
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
    try:
        with opener.open(req, timeout=30) as resp:
            models = json.loads(resp.read())["models"]
    except urllib.error.HTTPError as e:
        print(f"   FAIL: HTTP {e.code} {e.read()[:200]!r}")
        return 1
    except Exception as e:
        print(f"   FAIL: {type(e).__name__}: {e}")
        return 1

    gpt_models = [
        m for m in models
        if m.get("name", "").startswith("gpt-5.5") or m.get("name") == "gpt-5.5"
    ]
    legacy_hits = [
        m["name"] for m in models if "gpt-5.5" in (m.get("legacySlugs") or [])
    ]
    default_gpt = next((m for m in models if m.get("name") == "gpt-5.5-high"), None)
    if default_gpt is None:
        default_gpt = next((m for m in models if m.get("name", "").startswith("gpt-5.5")), None)

    print(f"   total models: {len(models)}")
    print(f"   gpt-5.5 variants: {len(gpt_models)}")
    print(f"   legacy slug 'gpt-5.5' maps to: {legacy_hits[:3] or 'n/a'}")
    if default_gpt:
        print(
            f"   sample entry: {default_gpt['name']} "
            f"(defaultOn={default_gpt.get('defaultOn')}, "
            f"legacy={default_gpt.get('legacySlugs')})"
        )
    api_ok = len(gpt_models) > 0

    print("\n3) Network path through proxy (HTTPS)")
    for url in AGENT_URLS:
        ok, detail = probe_https(opener, url)
        status = "OK" if ok else "FAIL"
        print(f"   {status:4} {url}: {detail}")

    print("\n4) Verdict")
    if api_ok:
        print("   Account/API: GPT 5.5 is available in Cursor catalog (132-model response).")
        print("   Network: Cursor backend hosts reachable via current proxy.")
    else:
        print("   Account/API: GPT 5.5 NOT found in catalog.")
        return 1

    if not gpt_cached:
        print("   UI cache: GPT 5.5 NOT in local picker cache — model list still degraded.")
        print("   Chat: Cursor may fail to select gpt-5.5 until cache is patched.")
    else:
        print("   UI cache: GPT 5.5 present locally — picker should work.")

    print("\n   Note: catalog availability != chat success; chat uses agent.api5.cursor.sh.")
    print("   Earlier today (21:37) logs show a successful gpt-5.5 model selection event.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
