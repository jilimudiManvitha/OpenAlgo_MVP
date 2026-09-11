"""Read-only review of the tracked frontend compression changes before push."""
import gzip
import json
import subprocess
from pathlib import Path

paths = subprocess.check_output(['git', 'diff', '--name-only'], text=True).splitlines()
checked, missing_source, mismatches, deleted = [], [], [], []
for name in paths:
    if not name.endswith('.gz'):
        continue
    path = Path(name)
    if not path.exists():
        deleted.append(name)
        continue
    source = Path(name[:-3])
    if not source.exists():
        missing_source.append(name)
        continue
    checked.append(name)
    if gzip.decompress(path.read_bytes()) != source.read_bytes():
        mismatches.append(name)
print(json.dumps({'checked_gzip': len(checked), 'deleted_gzip': len(deleted),
                  'missing_source': missing_source, 'mismatches': mismatches,
                  'other_changes': [p for p in paths if not p.endswith('.gz')]}, indent=2))
if mismatches:
    raise SystemExit(1)
