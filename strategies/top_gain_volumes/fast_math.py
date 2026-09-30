"""Optional local Rust kernel; identical population variance in the fallback."""

import ctypes
import math
import sys
from pathlib import Path

_suffix = ".dylib" if sys.platform == "darwin" else ".dll" if sys.platform == "win32" else ".so"
_path = Path(__file__).with_name("native") / ("libbands" + _suffix)
_library = None
if _path.is_file():
    try:
        _library = ctypes.CDLL(str(_path))
    except OSError:
        pass  # A copied binary may target a different OS/CPU; retain the fallback.
if _library is not None:
    _library.ha_bands.argtypes = [
        ctypes.POINTER(ctypes.c_double),
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_double),
    ]
    _library.ha_bands.restype = ctypes.c_int
BACKEND = "rust" if _library is not None else "python"


def bands(values):
    values = tuple(values)
    if not values or len(values) > 20:
        raise ValueError("Bollinger window must contain 1-20 closes")
    if _library is not None:
        data = (ctypes.c_double * len(values))(*values)
        result = (ctypes.c_double * 2)()
        if not _library.ha_bands(data, len(values), result):
            raise ValueError("Non-finite HA close")
        return result[0], result[1]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Non-finite HA close")
    mean = sum(values) / len(values)
    return mean, mean + 2 * math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
