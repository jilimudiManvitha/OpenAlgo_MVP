"""Create the isolated review copy; never overwrite an existing edited copy."""
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for name in ('services/market_scanner_service.py', 'services/market_scanner_provider.py',
             'blueprints/market_scanner.py', 'blueprints/react_app.py', 'app.py'):
    target = HERE / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(ROOT / name, target)
if not (HERE / 'frontend').exists():
    shutil.copytree(ROOT / 'frontend', HERE / 'frontend',
                    ignore=shutil.ignore_patterns('node_modules', 'dist', '.vite', '*.tsbuildinfo'))
print('Isolated source copy ready:', HERE)
