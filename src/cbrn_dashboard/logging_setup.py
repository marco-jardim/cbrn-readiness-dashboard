# SPDX-License-Identifier: GPL-3.0-or-later
"""Logging and crash handling without record contents (PLAN.md D22, task T1.8).

Log files hold **event codes, exception types and stack frames only**. They never hold record
contents, and never exception *messages* either: a message such as ``UNIQUE constraint failed ...``
or a ``ValueError`` built from an identifier can carry record data. The rules are enforced in one
place, :class:`SafeFormatter`, which is the only formatter this module installs:

* the log message of a record **is** the event code and must match :data:`EVENT_CODE_PATTERN`
  (``APP.START``, ``DB.MIGRATED``, ``BACKUP.DAILY_DONE``); anything else (free text from a careless
  caller or from a library) is written as the fixed code ``LOG.INVALID_MESSAGE`` and the original
  text is dropped; ``%``-style arguments are ignored entirely;
* the only extra fields are two integers, ``count`` and ``duration_ms``, set through
  :func:`log_event`;
* an exception is written as its type name and one line per stack frame (module path, line number,
  function name), followed by the same for the ``__cause__``/``__context__`` chain. ``str(exc)``,
  ``exc.args``, source lines and local variables are never read. Frame paths are relative to the
  package or to ``site-packages``, else the bare file name, so no user name leaks.

Files: ``<data>/logs/app.log``, rotated at 1 MB with 3 backups. In read-only mode (or when the log
folder cannot be created) nothing is written to the data folder: the last 500 records are kept in
memory instead.

Crash handling: :func:`install_exception_hook` replaces ``sys.excepthook`` and
``threading.excepthook``. An unhandled exception is logged as ``APP.UNHANDLED_EXCEPTION`` and handed
to an injectable callback as a :class:`CrashReport` (a short stable code and the exception type,
never the message). Nothing is uploaded or sent anywhere.

This module is Qt-free; the start-up sequence (T1.9) wires the callback to a translated dialog.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import logging.handlers
import re
import sys
import threading
import traceback
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from types import TracebackType
from typing import Self, cast

__all__ = [
    "BACKUP_COUNT",
    "EVENT_CODE_PATTERN",
    "INVALID_MESSAGE_CODE",
    "LOGGER_NAME",
    "LOG_DIR_NAME",
    "LOG_FILE_NAME",
    "MAX_BYTES",
    "MEMORY_LINES",
    "CrashReport",
    "LoggingHandle",
    "SafeFormatter",
    "configure_logging",
    "crash_code",
    "display_path",
    "install_exception_hook",
    "is_event_code",
    "log_event",
    "log_exception",
]

LOGGER_NAME = "cbrn_dashboard"
LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "app.log"
#: Size at which ``app.log`` is rotated (1 MB) and the number of rotated files kept.
MAX_BYTES = 1_000_000
BACKUP_COUNT = 3
#: Records kept in memory when no log file may be written.
MEMORY_LINES = 500

#: Written instead of any log message that is not a valid event code.
INVALID_MESSAGE_CODE = "LOG.INVALID_MESSAGE"
#: ``^[A-Z][A-Z0-9_]*(\.[A-Z0-9_]+)*$`` (matched with ``fullmatch``, so no trailing newline).
EVENT_CODE_PATTERN = r"[A-Z][A-Z0-9_]*(?:\.[A-Z0-9_]+)*"

#: Names of the ``LogRecord`` attributes that carry the two permitted integer fields.
_COUNT_ATTR = "cbrn_count"
_DURATION_ATTR = "cbrn_duration_ms"

#: At most this many frames per exception are written (the innermost ones), and this many chained
#: exceptions are followed.
_MAX_FRAMES = 40
_MAX_CHAIN = 8

_EVENT_CODE = re.compile(EVENT_CODE_PATTERN)
_UNSAFE_CHARACTERS = re.compile(r"[^\w.<>/\-]")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PACKAGE_NAME = "cbrn_dashboard"

#: Handlers installed by :func:`configure_logging`, so repeated calls can remove exactly those.
_INSTALLED: list[logging.Handler] = []


def is_event_code(text: object) -> bool:
    """Whether ``text`` is a valid event code (see :data:`EVENT_CODE_PATTERN`)."""
    return isinstance(text, str) and _EVENT_CODE.fullmatch(text) is not None


# --------------------------------------------------------------------------- frame descriptions


def _clean(text: str) -> str:
    """Replace everything but word characters and ``. < > / -`` (so no control characters)."""
    return _UNSAFE_CHARACTERS.sub("?", text)


def _folded(parts: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(part.casefold() for part in parts)


def _package_roots() -> tuple[tuple[str, ...], ...]:
    """Folded path parts of the package folder, as imported and fully resolved."""
    roots: list[tuple[str, ...]] = []
    candidates = [Path(__file__).absolute().parent]
    with contextlib.suppress(OSError, RuntimeError):
        candidates.append(Path(__file__).resolve().parent)
    for candidate in candidates:
        parts = _folded(PureWindowsPath(str(candidate)).parts)
        if parts not in roots:
            roots.append(parts)
    return tuple(roots)


_PACKAGE_ROOTS = _package_roots()


def display_path(filename: str) -> str:
    """The form of a source file name that may be written to the log.

    Inside the package: ``cbrn_dashboard/<sub>/<file>.py``; inside ``site-packages``: the path below
    it; any other absolute path: the bare file name. Relative names and ``<frozen ...>`` pseudo
    names are kept (cleaned). Never an absolute path, so no user name or drive letter.
    """
    if not filename or filename.startswith("<"):
        return _clean(filename)
    windows = PureWindowsPath(filename)
    if not windows.anchor:
        return _clean(windows.as_posix())
    parts = windows.parts
    folded = _folded(parts)
    for root in _PACKAGE_ROOTS:
        if root and folded[: len(root)] == root and len(parts) > len(root):
            return _clean("/".join((_PACKAGE_NAME, *parts[len(root) :])))
    for index in range(len(folded) - 1, -1, -1):
        if folded[index] == "site-packages" and index + 1 < len(parts):
            return _clean("/".join(parts[index + 1 :]))
    return _clean(parts[-1])


type _Frame = tuple[str, int, str]  # (display path, line number, function name)


def _frames(tb: TracebackType | None) -> list[_Frame]:
    """Frames of a traceback, oldest first; reads no source lines and no local variables."""
    return [
        (display_path(frame.f_code.co_filename), lineno, _clean(frame.f_code.co_name))
        for frame, lineno in traceback.walk_tb(tb)
    ]


def _type_name(exc_type: type[BaseException] | None) -> str:
    name = "UnknownError" if exc_type is None else exc_type.__name__
    return name if _IDENTIFIER.fullmatch(name) else "UnknownError"


def _chain(start: BaseException | None) -> Iterator[BaseException]:
    """The ``__cause__``/``__context__`` chain of ``start`` (without ``start``), cycle-safe."""
    if start is None:
        return
    seen = {id(start)}
    current = start
    for _ in range(_MAX_CHAIN):
        following = current.__cause__
        if following is None and not current.__suppress_context__:
            following = current.__context__
        if following is None or id(following) in seen:
            return
        seen.add(id(following))
        yield following
        current = following


def _frame_lines(tb: TracebackType | None) -> list[str]:
    frames = _frames(tb)
    lines: list[str] = []
    if len(frames) > _MAX_FRAMES:
        lines.append(f"  omitted={len(frames) - _MAX_FRAMES}")
        frames = frames[-_MAX_FRAMES:]
    lines.extend(f"  at {path}:{lineno} in {function}" for path, lineno, function in frames)
    return lines


def crash_code(exc_type: type[BaseException] | None, tb: TracebackType | None) -> str:
    """Short stable reference ``E-<8 hex>`` for an exception *site*.

    Derived from the exception type name and the innermost frame (module path, function, line) by
    SHA-256; the message is never an input, so the code is identical for the same site on any
    machine and carries no record data.
    """
    frames = _frames(tb)
    innermost = "{}|{}|{}".format(*frames[-1]) if frames else "no-frame"
    material = f"{_type_name(exc_type)}|{innermost}".encode()
    return f"E-{hashlib.sha256(material).hexdigest()[:8]}"


# --------------------------------------------------------------------------- formatter


def _plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class SafeFormatter(logging.Formatter):
    """The only formatter used: event code, level, UTC time, two integers, exception type + frames.

    Line: ``<UTC time> <LEVEL> <CODE>[ count=<n>][ duration_ms=<n>][ exc=<Type>]``; then one
    ``  at <path>:<line> in <function>`` per frame and ``  cause=<Type>`` plus frames for every
    chained exception. See the module docstring for what is never written.
    """

    def format(self, record: logging.LogRecord) -> str:
        code = record.msg if is_event_code(record.msg) else INVALID_MESSAGE_CODE
        stamp = datetime.fromtimestamp(record.created, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        head = f"{stamp} {_clean(record.levelname)} {code}"
        count: object = getattr(record, _COUNT_ATTR, None)
        if _plain_int(count):
            head += f" count={count}"
        duration: object = getattr(record, _DURATION_ATTR, None)
        if _plain_int(duration):
            head += f" duration_ms={duration}"

        info = record.exc_info
        if info is None or info[0] is None:
            return head
        exc_type, exc_value, exc_tb = info
        lines = [f"{head} exc={_type_name(exc_type)}", *_frame_lines(exc_tb)]
        for cause in _chain(exc_value):
            lines.append(f"  cause={_type_name(type(cause))}")
            lines.extend(_frame_lines(cause.__traceback__))
        return "\n".join(lines)

    def formatException(self, ei: object) -> str:  # noqa: N802 - name fixed by logging.Formatter
        return ""  # defence in depth: the base class would write the message

    def formatStack(self, stack_info: str) -> str:  # noqa: N802 - name fixed by logging.Formatter
        return ""


# --------------------------------------------------------------------------- handlers and handle


class _MemoryHandler(logging.Handler):
    """Keeps the last ``capacity`` formatted records (one entry per record)."""

    def __init__(self, capacity: int) -> None:
        super().__init__()
        self._entries: deque[str] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._entries.append(self.format(record))
        except Exception:
            self.handleError(record)

    def entries(self) -> tuple[str, ...]:
        self.acquire()
        try:
            return tuple(self._entries)
        finally:
            self.release()


class LoggingHandle:
    """What :func:`configure_logging` returns: where the log goes and how to stop it."""

    __slots__ = ("_handler", "_logger", "_memory", "_path")

    def __init__(
        self,
        logger: logging.Logger,
        handler: logging.Handler,
        path: Path | None,
        memory: _MemoryHandler | None,
    ) -> None:
        self._logger = logger
        self._handler = handler
        self._path = path
        self._memory = memory

    @property
    def path(self) -> Path | None:
        """The log file, or ``None`` when the log is kept in memory."""
        return self._path

    @property
    def in_memory(self) -> bool:
        return self._memory is not None

    @property
    def handler(self) -> logging.Handler:
        """The installed handler (a ``RotatingFileHandler`` or the in-memory one)."""
        return self._handler

    def memory_lines(self) -> tuple[str, ...]:
        """The retained records (at most :data:`MEMORY_LINES`), oldest first; empty for a file."""
        return () if self._memory is None else self._memory.entries()

    def close(self) -> None:
        """Flush, close and detach the handler (needed on Windows before files can be deleted)."""
        self._handler.flush()
        self._logger.removeHandler(self._handler)
        self._handler.close()
        if self._handler in _INSTALLED:
            _INSTALLED.remove(self._handler)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _file_handler(data_dir: Path) -> tuple[logging.Handler, Path] | None:
    """The rotating file handler, or ``None`` when the folder or file cannot be created."""
    folder = data_dir / LOG_DIR_NAME
    path = folder / LOG_FILE_NAME
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with path.open("ab"):  # fail now, not on the first event
            pass
        handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
            delay=True,
        )
    except OSError:
        return None
    return handler, path


def configure_logging(data_dir: Path, *, read_only: bool = False) -> LoggingHandle:
    """Configure the ``cbrn_dashboard`` logger (and only that one); safe to call repeatedly.

    Writable: ``<data_dir>/logs/app.log`` rotating at 1 MB with 3 backups. Read-only, or when the
    folder or file cannot be created: nothing is written to disk and the last 500 records are kept
    in memory (``handle.in_memory``). Handlers installed by an earlier call are removed first. The
    root logger is never touched and the logger does not propagate to it.
    """
    logger = logging.getLogger(LOGGER_NAME)
    for old in _INSTALLED[:]:
        logger.removeHandler(old)
        old.close()
    _INSTALLED.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False

    handler: logging.Handler | None = None
    path: Path | None = None
    if not read_only:
        created = _file_handler(data_dir)
        if created is not None:
            handler, path = created
    memory: _MemoryHandler | None = None
    if handler is None:
        memory = _MemoryHandler(MEMORY_LINES)
        handler = memory
    handler.setFormatter(SafeFormatter())
    logger.addHandler(handler)
    _INSTALLED.append(handler)
    return LoggingHandle(logger, handler, path, memory)


# --------------------------------------------------------------------------- convenience API


def log_event(
    code: str,
    *,
    level: int = logging.INFO,
    count: int | None = None,
    duration_ms: int | None = None,
) -> None:
    """Log one event: the code plus, optionally, a count and a duration (integers only).

    A ``code`` that is not a valid event code is written as ``LOG.INVALID_MESSAGE``. A ``count`` or
    ``duration_ms`` that is not an integer raises ``TypeError`` and nothing is logged.
    """
    extra: dict[str, int] = {}
    for attribute, name, value in (
        (_COUNT_ATTR, "count", count),
        (_DURATION_ATTR, "duration_ms", duration_ms),
    ):
        if value is None:
            continue
        if not _plain_int(value):
            msg = f"{name} must be an integer"
            raise TypeError(msg)
        extra[attribute] = value
    logging.getLogger(LOGGER_NAME).log(level, code, extra=extra or None)


def log_exception(code: str, exc: BaseException | None = None) -> None:
    """Log ``code`` at ERROR with the exception's type and frames (never its message).

    Without ``exc`` the exception being handled is used.
    """
    logging.getLogger(LOGGER_NAME).error(code, exc_info=True if exc is None else exc)


# --------------------------------------------------------------------------- crash handling


@dataclass(frozen=True)
class CrashReport:
    """What the UI may show about an unhandled exception: a reference code and the type name."""

    code: str
    exception_type: str


def _report_crash(
    exc_type: type[BaseException],
    exc_value: BaseException | None,
    tb: TracebackType | None,
    callback: Callable[[CrashReport], None] | None,
) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    # ``exc_value`` is only ``None`` for a thread hook without a value; the formatter copes.
    info = cast(
        "tuple[type[BaseException], BaseException, TracebackType | None]",
        (exc_type, exc_value, tb),
    )
    logger.error("APP.UNHANDLED_EXCEPTION", exc_info=info)
    if callback is None:
        return
    report = CrashReport(code=crash_code(exc_type, tb), exception_type=_type_name(exc_type))
    try:
        callback(report)
    except Exception as failure:
        # Deliberate swallow: the exception hook is the last line of defence, so a failing
        # callback (for example a dialog that cannot be shown) must not raise out of it. The
        # failure is logged as type and frames only and then dropped.
        logger.error("APP.CRASH_CALLBACK_FAILED", exc_info=failure)


def install_exception_hook(
    callback: Callable[[CrashReport], None] | None = None,
) -> Callable[[], None]:
    """Install ``sys.excepthook`` and ``threading.excepthook``; return the ``uninstall`` function.

    An unhandled exception is logged as ``APP.UNHANDLED_EXCEPTION`` (type and frames, no message)
    and ``callback`` receives a :class:`CrashReport`. The hooks never raise. ``KeyboardInterrupt``
    (and ``SystemExit`` in a thread) goes untouched to the previous hook. Nothing is sent anywhere.
    """
    previous_hook = sys.excepthook
    previous_thread_hook = threading.excepthook

    def hook(
        exc_type: type[BaseException], exc_value: BaseException, tb: TracebackType | None
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            previous_hook(exc_type, exc_value, tb)
            return
        _report_crash(exc_type, exc_value, tb, callback)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, KeyboardInterrupt | SystemExit):
            previous_thread_hook(args)
            return
        _report_crash(args.exc_type, args.exc_value, args.exc_traceback, callback)

    sys.excepthook = hook
    threading.excepthook = thread_hook

    def uninstall() -> None:
        sys.excepthook = previous_hook
        threading.excepthook = previous_thread_hook

    return uninstall
