import json, sqlite3, urllib.request, sys
sys.stdout.reconfigure(encoding='utf-8')
p = r'C:\Users\james\AppData\Roaming\Cursor\User\globalStorage\state.vscdb'
con = sqlite3.connect('file:'+p+'?mode=ro', uri=True)
raw = con.execute("SELECT value FROM ItemTable WHERE key='src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl.persistentStorage.applicationUser'").fetchone()[0]
data = json.loads(raw.decode('utf-8') if isinstance(raw, bytes) else raw)
models = data.get('availableDefaultModels2') or []
print('count', len(models))
for m in models:
    n = m.get('name','')
    if 'claude-opus-4-8' in n or 'gpt-5.5' in n or n in ('claude-opus-4-8','gpt-5.5'):
        print(n, 'defaultOn=', m.get('defaultOn'))
# list gpt-5.5* and claude-opus-4-8*
print('\ngpt-5.5 variants:')
for m in models:
    if 'gpt-5.5' in m.get('name',''):
        print(' ', m['name'])
print('\nclaude-opus-4-8 variants:')
for m in models:
    if 'claude-opus-4-8' in m.get('name',''):
        print(' ', m['name'])
