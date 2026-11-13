# SPDX-License-Identifier: GPL-3.0-or-later
"""Single-instance lock on the data folder (PLAN.md T1.9, D02, K05, K14). Qt-free.

``InstanceLock`` takes an EXCLUSIVE operating-system lock on ``<data>/cbrn-dashboard.lock``. The
operating system releases the lock when the process ends, however it ends, so a crash leaves no
stale lock. The lock FILE may stay behind after ``release()``: it holds no data and its existence
means nothing, only the OS lock on it does.

* Windows: ``msvcrt.locking(fd, LK_NBLCK, 1)`` (non-blocking, one byte at offset 0).
* Elsewhere: ``fcntl.flock(fd, LOCK_EX | LOCK_NB)``.

Another process, or another handle in the same process, that holds the lock makes ``acquire()``
return ``False`` with ``reason == LockReason.LOCKED``. Any other failure (a folder that cannot be
written, for example) also returns ``False`` with ``reason == LockReason.UNAVAILABLE``. ``acquire``
never raises for an operating-system error.
"""

from __future__ import annotations

import contextlib
import errno
import os
import sys
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Self

__all__ = ["LOCK_FILE_NAME", "InstanceLock", "LockReason"]

LOCK_FILE_NAME = "cbrn-dashboard.lock"

#: ``errno`` values that mean "somebody else holds the lock" (``EDEADLK`` is 36 on Windows).
_LOCKED_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN, errno.EDEADLK})


class LockReason(StrEnum):
    """Why ``acquire()`` returned ``False``."""

    LOCKED = "LOCKED"
    UNAVAILABLE = "UNAVAILABLE"


def _lock_descriptor(descriptor: int) -> None:
    """Take the exclusive non-blocking lock; raises ``OSError`` when it cannot be taken."""
    if sys.platform == "win32":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_descriptor(descriptor: int) -> None:
    """Release the lock taken by :func:`_lock_descriptor` (closing the descriptor does it too)."""
    if sys.platform == "win32":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)


class InstanceLock:
    """An exclusive lock on the data folder; also a context manager (acquires on entry)."""

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / LOCK_FILE_NAME
        self._descriptor: int | None = None
        self._reason: LockReason | None = None

    @property
    def path(self) -> Path:
        """The lock file (it may exist without being locked)."""
        return self._path

    @property
    def held(self) -> bool:
        """Whether this object currently holds the lock."""
        return self._descriptor is not None

    @property
    def reason(self) -> LockReason | None:
        """Why the last ``acquire()`` failed; ``None`` after a success or before any attempt."""
        return self._reason

    def acquire(self) -> bool:
        """Try to take the lock without waiting; ``True`` when this object now holds it."""
        if self._descriptor is not None:
            return True
        try:
            descriptor = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError:
            self._reason = LockReason.UNAVAILABLE
            return False
        try:
            _lock_descriptor(descriptor)
        except OSError as exc:
            os.close(descriptor)
            locked = exc.errno in _LOCKED_ERRNOS
            self._reason = LockReason.LOCKED if locked else LockReason.UNAVAILABLE
            return False
        self._descriptor = descriptor
        self._reason = None
        return True

    def release(self) -> None:
        """Unlock and close; harmless when the lock is not held. The lock file stays."""
        descriptor = self._descriptor
        if descriptor is None:
            return
        self._descriptor = None
        with contextlib.suppress(OSError):  # closing the descriptor releases the lock anyway
            _unlock_descriptor(descriptor)
        with contextlib.suppress(OSError):
            os.close(descriptor)

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
