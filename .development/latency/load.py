"""Load isolated replacements explicitly; production imports are untouched."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LANE = Path(__file__).resolve().parent


def module(name):
    path = LANE / "overlays" / (name.replace(".", "/") + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
