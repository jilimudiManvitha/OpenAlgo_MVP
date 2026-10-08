"""Exercise integrated latency API and normal frontend build with synthetic records."""
import runpy
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'.development/latency'))
import load
load.LANE=ROOT
# Loader now targets the production source tree; fixture storage remains disposable.
def integrated(name):
    import importlib
    return importlib.import_module(name)
load.module=integrated
source=(ROOT/'.development/latency/browser_server.py').read_text()
source=source.replace('PREVIEW = ROOT / ".development/latency/dist"','PREVIEW = ROOT / "frontend/dist"')
exec(compile(source,str(ROOT/'.development/latency/browser_server.py'),'exec'),{'__file__':str(ROOT/'.development/latency/browser_server.py'),'__name__':'__main__'})
