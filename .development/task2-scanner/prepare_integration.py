"""Produce a reviewable patch and source hashes without changing the original app."""
import difflib
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
FILES=['app.py','blueprints/market_scanner.py','blueprints/react_app.py',
       'services/market_scanner_service.py','services/market_scanner_provider.py',
       'services/market_scanner_live.py','services/market_scanner_feed.py',
       'frontend/src/App.tsx','frontend/src/config/navigation.ts',
       'frontend/src/pages/MarketScanner.tsx','frontend/vite.config.ts']
manifest=[]
patch=[]
for name in FILES:
    source=ROOT/name
    candidate=HERE/name
    original=source.read_bytes() if source.exists() else b''
    updated=candidate.read_bytes()
    manifest.append({'path':name,'original_sha256':hashlib.sha256(original).hexdigest() if source.exists() else None,
                     'candidate_sha256':hashlib.sha256(updated).hexdigest()})
    patch.extend(difflib.unified_diff(original.decode('utf-8').replace('\r\n','\n').splitlines(True),
                                    updated.decode('utf-8').replace('\r\n','\n').splitlines(True),
                                    fromfile='a/'+name if source.exists() else '/dev/null',tofile='b/'+name))
(HERE/'artifacts'/'integration.patch').write_text(''.join(patch),encoding='utf-8')
(HERE/'artifacts'/'integration-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(f'Review patch prepared for {len(FILES)} application files; original files unchanged.')
