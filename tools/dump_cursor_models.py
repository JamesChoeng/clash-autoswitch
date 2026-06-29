import json
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

p = r"C:\Users\james\AppData\Roaming\Cursor\User\globalStorage\state.vscdb"
con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
key = "src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl.persistentStorage.applicationUser"
val = con.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()[0]
data = json.loads(val.decode("utf-8") if isinstance(val, bytes) else val)
con.close()

for section in ("composerState", "aiSettings", "modelConfig", "cppConfig", "modelPickerState"):
    if section in data:
        print(f"=== {section} ===")
        print(json.dumps(data[section], ensure_ascii=False, indent=2)[:8000])

# common nested paths
cs = data.get("composerState") or {}
for k in sorted(cs.keys()):
    if "model" in k.lower() or "Model" in k:
        print(f"=== composerState.{k} ===")
        print(json.dumps(cs[k], ensure_ascii=False, indent=2)[:4000])

print("=== top-level keys with model ===")
for k, v in data.items():
    if "model" in k.lower():
        print(k, "=>", json.dumps(v, ensure_ascii=False)[:500])
