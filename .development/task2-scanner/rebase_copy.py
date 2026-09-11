"""Bring upstream edits into the isolated copy without replacing scanner additions."""
from pathlib import Path
import shutil
import subprocess

here = Path(__file__).resolve().parent
root = here.parents[1]
names = subprocess.check_output(['git','diff','--name-only','11ca386ab..HEAD','--',
    'frontend/src','frontend/package.json','frontend/package-lock.json','app.py'],text=True).splitlines()
protected = {'frontend/src/App.tsx','frontend/src/config/navigation.ts',
             'frontend/src/pages/MarketScanner.tsx'}
for name in names:
    if name in protected:
        raise RuntimeError(f'Needs scanner-aware merge: {name}')
    if (root/name).is_file():
        (here/name).parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(root/name,here/name)
app = here/'app.py'
body = app.read_text(encoding='utf-8')
anchor = '    app.register_blueprint(market_scanner_bp)'
addition = anchor+'\n    from services.market_scanner_live import coordinator\n    coordinator()  # Lease election prevents duplicate workers across reloads.'
if addition not in body:
    body = body.replace(anchor,addition,1)
app.write_text(body,encoding='utf-8')
print(f'Rebased {len(names)} files; scanner additions preserved')
