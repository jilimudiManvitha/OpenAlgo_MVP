"""Read-only review of the tracked frontend compression changes before push."""
import gzip
import json
import subprocess
import sys
from pathlib import Path

command = ['git', 'ls-files', 'frontend/dist'] if '--all' in sys.argv else ['git', 'diff', '--name-only']
paths = subprocess.check_output(command, text=True).splitlines()
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
        if '--repair' in sys.argv:
            path.write_bytes(gzip.compress(source.read_bytes(), compresslevel=9, mtime=0))
print(json.dumps({'checked_gzip': len(checked), 'deleted_gzip': len(deleted),
                  'missing_source_count': len(missing_source), 'mismatches': mismatches,
                  'other_changes_count': sum(not p.endswith('.gz') for p in paths)}, indent=2))
if mismatches and '--repair' not in sys.argv:
    raise SystemExit(1)
