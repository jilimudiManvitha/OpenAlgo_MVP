"""Cooperative, process-safe file locks for short-lived database connections."""

import errno
import os
import time
from contextlib import contextmanager

if os.name == "nt":
    import msvcrt
else:
    import fcntl


@contextmanager
def exclusive_file_lock(path, timeout=120.0):
    """Lock a stable sidecar across threads/processes, yielding while waiting.

    Keep the sidecar on disk: unlinking it could let a new caller lock a
    different inode while existing waiters still use the old one. The OS
    releases ownership when the handle closes, including on process exit.
    """
    deadline = time.monotonic() + timeout
    with open(path, "a+b") as handle:
        while True:
            try:
                if os.name == "nt":
                    handle.seek(0)
                    # Windows permits locking a byte beyond end-of-file.
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Timed out after {timeout:g}s waiting for database lock {path}"
                    ) from exc
                # Patched time.sleep yields to the eventlet hub in production.
                time.sleep(min(0.05, remaining))
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
