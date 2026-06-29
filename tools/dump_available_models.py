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

models = data.get("availableDefaultModels2") or []
print(f"availableDefaultModels2 count: {len(models)}")
for m in models:
    name = m.get("name")
    default = m.get("defaultOn")
    variants = m.get("variants") or []
    vnames = [v.get("displayName") or v.get("variantStringRepresentation") for v in variants[:3]]
    print(f"  - {name} defaultOn={default} variants={vnames}")

ai = data.get("aiSettings") or {}
print("\nuserAddedModels:", ai.get("userAddedModels"))
print("modelOverrideEnabled:", ai.get("modelOverrideEnabled"))
print("modelOverrideDisabled:", ai.get("modelOverrideDisabled"))
print("composer selected:", ai.get("modelConfig", {}).get("composer"))

# search other keys for enabled picker models
for k, v in data.items():
    if "picker" in k.lower() or "addedmodel" in k.lower() or "enabledmodel" in k.lower():
        print(f"\n{k}:", json.dumps(v, ensure_ascii=False)[:2000])
