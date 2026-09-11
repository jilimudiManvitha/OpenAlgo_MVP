"""Load only the isolated scanner modules; original application trees stay intact."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
for name in ('services', 'blueprints'):
    module = __import__(name)
    module.__path__ = [str(HERE / name), *module.__path__]
