# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for ``cbrn_dashboard.logging_setup`` (PLAN T1.8, D22).

Everything happens under ``tmp_path``. The distinctive fictitious identifier and label used below
must never reach a log file, a log line kept in memory or a crash report.
"""

from __future__ import annotations

import dataclasses
import logging
import logging.handlers
import re
import sys
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from types import TracebackType

import pytest

from cbrn_dashboard import logging_setup
from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.logging_setup import (
    BACKUP_COUNT,
    LOG_DIR_NAME,
    LOG_FILE_NAME,
    LOGGER_NAME,
    MAX_BYTES,
    MEMORY_LINES,
    CrashReport,
    LoggingHandle,
    SafeFormatter,
    configure_logging,
    crash_code,
    display_path,
    install_exception_hook,
    log_event,
    log_exception,
)
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate
from cbrn_dashboard.storage.repository import (
    ConstraintViolationError,
    WriteContext,
    insert,
    update,
)

IDENTIFIER = "DEMO-ZEBRA-7731"
LABEL = "Fictitious Label QX"
SECRET_MESSAGE = f"secret {IDENTIFIER} in message"
CHAIN_MESSAGE = "DEMO-LEMUR-42"
NEEDLES = (IDENTIFIER, LABEL, "ZEBRA", "LEMUR", "Fictitious", "DEMO-", "in message")

TIMESTAMP = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"

type ExcInfo = tuple[type[BaseException], BaseException, TracebackType | None]


# --------------------------------------------------------------------------- helpers


class _Opened:
    """Opens logging handles and closes every one of them at the end of the test."""

    def __init__(self) -> None:
        self.handles: list[LoggingHandle] = []

    def __call__(self, data_dir: Path, *, read_only: bool = False) -> LoggingHandle:
        handle = configure_logging(data_dir, read_only=read_only)
        self.handles.append(handle)
        return handle

    def close(self) -> None:
        for handle in self.handles:
            handle.close()


@pytest.fixture
def configure() -> Iterator[_Opened]:
    opened = _Opened()
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture(autouse=True)
def _restore_hooks() -> Iterator[None]:
    excepthook = sys.excepthook
    thread_hook = threading.excepthook
    try:
        yield
    finally:
        sys.excepthook = excepthook
        threading.excepthook = thread_hook


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "data"
    folder.mkdir()
    return folder


def _own_handlers(logger: logging.Logger) -> list[logging.Handler]:
    """The logger's handlers without pytest's own capture handlers (``_pytest`` classes).

    pytest attaches ``LogCaptureHandler`` objects directly to a logger that does not propagate.
    """
    return [h for h in logger.handlers if not type(h).__module__.startswith("_pytest")]


def _all_log_text(folder: Path) -> str:
    """Text of ``app.log`` and every rotated file."""
    logs = folder / LOG_DIR_NAME
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(logs.iterdir()) if path.is_file()
    )


def _log_text(folder: Path) -> str:
    return (folder / LOG_DIR_NAME / LOG_FILE_NAME).read_text(encoding="utf-8")


def _assert_no_needles(text: str) -> None:
    for needle in NEEDLES:
        assert needle not in text


def _raise_secret(message: str = SECRET_MESSAGE) -> None:
    local_value = "DEMO-LOCAL-VALUE-9"
    raise ValueError(message + local_value)


def _raise_chained() -> None:
    try:
        _raise_secret()
    except ValueError as inner:
        raise RuntimeError(CHAIN_MESSAGE) from inner


def _crash_site_a(message: str) -> None:
    raise ValueError(message)


def _crash_site_b(message: str) -> None:
    raise ValueError(message)


def _capture(raiser: Callable[[str], None], message: str = SECRET_MESSAGE) -> ExcInfo:
    try:
        raiser(message)
    except BaseException as exc:
        return type(exc), exc, exc.__traceback__
    msg = "the call did not raise"
    raise AssertionError(msg)


def _call_hook(info: ExcInfo) -> None:
    sys.excepthook(info[0], info[1], info[2])


# --------------------------------------------------------------------------- file and rotation


def test_rotating_log_is_kept_in_the_data_folder(data_dir: Path, configure: _Opened) -> None:
    handle = configure(data_dir)
    expected = data_dir / "logs" / "app.log"

    assert (LOGGER_NAME, LOG_DIR_NAME, LOG_FILE_NAME) == ("cbrn_dashboard", "logs", "app.log")
    assert handle.path == expected
    assert not handle.in_memory
    assert handle.memory_lines() == ()
    assert isinstance(handle.handler, logging.handlers.RotatingFileHandler)
    assert handle.handler.maxBytes == 1_000_000 == MAX_BYTES
    assert handle.handler.backupCount == 3 == BACKUP_COUNT
    assert handle.handler.baseFilename == str(expected)
    assert isinstance(handle.handler.formatter, SafeFormatter)

    log_event("APP.START")
    assert re.fullmatch(rf"{TIMESTAMP} INFO APP\.START\n", _log_text(data_dir))


def test_log_folder_is_created_when_missing(tmp_path: Path, configure: _Opened) -> None:
    folder = tmp_path / "not" / "yet"
    handle = configure(folder)
    log_event("APP.START")
    assert handle.path == folder / "logs" / "app.log"
    assert handle.path is not None
    assert handle.path.is_file()


def test_rotation_keeps_at_most_three_backups(
    data_dir: Path, configure: _Opened, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(logging_setup, "MAX_BYTES", 400)
    handle = configure(data_dir)
    assert isinstance(handle.handler, logging.handlers.RotatingFileHandler)
    assert handle.handler.maxBytes == 400

    for number in range(150):
        log_event("ROLLOVER.TEST", count=number)

    logs = data_dir / "logs"
    assert (logs / "app.log.1").is_file()
    names = {path.name for path in logs.iterdir()}
    assert names == {"app.log", "app.log.1", "app.log.2", "app.log.3"}
    assert not (logs / "app.log.4").exists()
    assert "count=149" in (logs / "app.log").read_text(encoding="utf-8")


def test_line_format(data_dir: Path, configure: _Opened) -> None:
    configure(data_dir)
    log_event("APP.START", count=1, duration_ms=20)
    log_event("BACKUP.DAILY_DONE", level=logging.WARNING)
    first, second = _log_text(data_dir).splitlines()
    assert re.fullmatch(rf"{TIMESTAMP} INFO APP\.START count=1 duration_ms=20", first)
    assert re.fullmatch(rf"{TIMESTAMP} WARNING BACKUP\.DAILY_DONE", second)


def test_timestamp_comes_from_the_record_in_utc() -> None:
    record = logging.LogRecord("x", logging.INFO, "f.py", 1, "APP.START", None, None)
    record.created = 1_700_000_000.9  # 2023-11-14T22:13:20Z
    assert SafeFormatter().format(record) == "2023-11-14T22:13:20Z INFO APP.START"


# --------------------------------------------------------------------------- read-only / memory


def test_read_only_keeps_the_log_in_memory_and_writes_nothing(
    data_dir: Path, configure: _Opened
) -> None:
    handle = configure(data_dir, read_only=True)
    log_event("APP.START")
    log_event("DB.MIGRATED", count=2)

    assert handle.in_memory
    assert handle.path is None
    assert not isinstance(handle.handler, logging.FileHandler)
    assert list(data_dir.iterdir()) == []  # no logs folder, no file
    lines = handle.memory_lines()
    assert len(lines) == 2
    assert lines[0].endswith("INFO APP.START")
    assert lines[1].endswith("INFO DB.MIGRATED count=2")


def test_read_only_does_not_create_a_missing_data_folder(
    tmp_path: Path, configure: _Opened
) -> None:
    missing = tmp_path / "missing"
    handle = configure(missing, read_only=True)
    log_event("APP.START")
    assert handle.in_memory
    assert not missing.exists()


def test_memory_log_is_bounded(data_dir: Path, configure: _Opened) -> None:
    handle = configure(data_dir, read_only=True)
    for number in range(600):
        log_event("LOAD.TEST", count=number)

    lines = handle.memory_lines()
    assert MEMORY_LINES == 500
    assert len(lines) == 500
    assert lines[0].endswith("count=100")
    assert lines[-1].endswith("count=599")


def test_memory_log_holds_exceptions_without_their_message(
    data_dir: Path, configure: _Opened
) -> None:
    handle = configure(data_dir, read_only=True)
    try:
        _raise_secret()
    except ValueError as exc:
        log_exception("TEST.FAILED", exc)
    (entry,) = handle.memory_lines()
    assert "exc=ValueError" in entry
    assert "in _raise_secret" in entry
    _assert_no_needles(entry)


def test_unusable_log_folder_falls_back_to_memory(data_dir: Path, configure: _Opened) -> None:
    (data_dir / "logs").write_text("a file where the folder should be", encoding="utf-8")
    handle = configure(data_dir)
    log_event("APP.START")

    assert handle.in_memory
    assert handle.path is None
    assert len(handle.memory_lines()) == 1
    assert [path.name for path in data_dir.iterdir()] == ["logs"]
    assert (data_dir / "logs").is_file()


# --------------------------------------------------------------------------- exceptions


def test_exception_type_and_frames_are_written_but_never_the_message(
    data_dir: Path, configure: _Opened
) -> None:
    configure(data_dir)
    try:
        _raise_secret()
    except ValueError as exc:
        log_exception("TEST.FAILED", exc)

    text = _log_text(data_dir)
    first, *frames = text.splitlines()
    assert re.fullmatch(rf"{TIMESTAMP} ERROR TEST\.FAILED exc=ValueError", first)
    assert any(re.fullmatch(r"  at test_logging\.py:\d+ in _raise_secret", f) for f in frames)
    assert any(" in test_exception_type_and_frames" in f for f in frames)
    _assert_no_needles(text)
    assert "DEMO-LOCAL-VALUE-9" not in text  # local variables
    assert "raise ValueError" not in text  # source lines


def test_log_exception_without_an_argument_uses_the_handled_exception(
    data_dir: Path, configure: _Opened
) -> None:
    configure(data_dir)
    try:
        _raise_secret()
    except ValueError:
        log_exception("TEST.FAILED")
    text = _log_text(data_dir)
    assert "exc=ValueError" in text
    _assert_no_needles(text)


def test_chained_exceptions_write_both_types_and_neither_message(
    data_dir: Path, configure: _Opened
) -> None:
    configure(data_dir)
    try:
        _raise_chained()
    except RuntimeError as exc:
        log_exception("TEST.FAILED", exc)

    text = _log_text(data_dir)
    lines = text.splitlines()
    assert lines[0].endswith("TEST.FAILED exc=RuntimeError")
    assert "  cause=ValueError" in lines
    assert any("in _raise_chained" in line for line in lines)
    assert any("in _raise_secret" in line for line in lines[lines.index("  cause=ValueError") :])
    _assert_no_needles(text)


def test_implicit_context_is_followed_too(data_dir: Path, configure: _Opened) -> None:
    configure(data_dir)
    try:
        try:
            _raise_secret()
        except ValueError:
            _crash_site_a(CHAIN_MESSAGE)
    except ValueError as exc:
        log_exception("TEST.FAILED", exc)
    text = _log_text(data_dir)
    assert "exc=ValueError" in text
    assert "  cause=ValueError" in text
    _assert_no_needles(text)


def test_an_exception_without_a_traceback_has_no_frames(data_dir: Path, configure: _Opened) -> None:
    configure(data_dir)
    log_exception("TEST.FAILED", ValueError(SECRET_MESSAGE))  # never raised: no frames
    text = _log_text(data_dir)
    assert text.splitlines()[0].endswith("TEST.FAILED exc=ValueError")
    assert len(text.splitlines()) == 1
    _assert_no_needles(text)


# --------------------------------------------------------------------------- record content


def test_record_content_never_reaches_the_log(
    tmp_path: Path, data_dir: Path, configure: _Opened
) -> None:
    configure(data_dir)
    conn = open_and_migrate(
        tmp_path / "records.sqlite3",
        data_dir=tmp_path,
        identity=DatabaseIdentity.REAL,
        backup=False,
    )
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS staff_member ("
            " id INTEGER PRIMARY KEY,"
            " identifier TEXT NOT NULL UNIQUE,"
            " label TEXT,"
            " category TEXT,"
            " active_from TEXT NOT NULL,"
            " active_until TEXT) STRICT"
        )
        ctx = WriteContext(conn, FixedClock.at("2026-03-05T12:00:00Z"), "operator-1")
        values = {
            "identifier": IDENTIFIER,
            "label": LABEL,
            "category": "alpha",
            "active_from": "2026-01-01",
        }
        staff = insert(ctx, "staff_member", values)
        assert staff is not None
        assert update(ctx, "staff_member", staff, {"label": LABEL + " 2"})
        log_event("PERSONNEL.STAFF_ADDED", count=1)

        with pytest.raises(ConstraintViolationError) as caught:
            insert(ctx, "staff_member", values)  # same identifier: UNIQUE constraint
        log_exception("PERSONNEL.WRITE_FAILED", caught.value)
        log_event("PERSONNEL.DONE")
    finally:
        conn.close()

    text = _all_log_text(data_dir)
    assert IDENTIFIER not in text
    assert LABEL not in text
    _assert_no_needles(text)
    assert "PERSONNEL.STAFF_ADDED count=1" in text
    assert "ERROR PERSONNEL.WRITE_FAILED exc=ConstraintViolationError" in text
    assert "  cause=IntegrityError" in text
    assert re.search(r"  at cbrn_dashboard/storage/repository\.py:\d+ in insert", text)


# --------------------------------------------------------------------------- free text


def test_free_text_cannot_get_into_the_log(data_dir: Path, configure: _Opened) -> None:
    configure(data_dir)
    logger = logging.getLogger(LOGGER_NAME)
    logger.info("user %s saved", IDENTIFIER)
    logger.info(IDENTIFIER)
    logger.warning(f"saved {IDENTIFIER}")
    logger.error(12345)
    logging.getLogger(LOGGER_NAME + ".child").info("free text from a library: %s", IDENTIFIER)
    logger.info("APP.START\nFORGED INFO APP.START")  # no way to forge a second line

    lines = _log_text(data_dir).splitlines()
    assert len(lines) == 6
    codes = [line.split(" ", 2)[2] for line in lines]
    assert codes == ["LOG.INVALID_MESSAGE"] * 6
    _assert_no_needles("\n".join(lines))
    assert "FORGED" not in "\n".join(lines)


def test_percent_arguments_are_ignored_even_when_they_do_not_match(
    data_dir: Path, configure: _Opened
) -> None:
    # Built by hand and given to our handler only: pytest's own capture handler on the logger
    # would try ``msg % args`` and fail on the mismatch.
    handle = configure(data_dir)
    free_text = logging.LogRecord(
        name=LOGGER_NAME,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="saved %s",
        args=(IDENTIFIER, "extra"),
        exc_info=None,
    )
    valid_code = logging.LogRecord(
        name=LOGGER_NAME,
        level=logging.INFO,
        pathname=__file__,
        lineno=2,
        msg="APP.START",
        args=(IDENTIFIER, "extra"),
        exc_info=None,
    )

    formatted = SafeFormatter().format(free_text)
    assert "LOG.INVALID_MESSAGE" in formatted
    assert IDENTIFIER not in formatted
    assert SafeFormatter().format(valid_code).endswith("INFO APP.START")

    handle.handler.handle(free_text)
    handle.handler.handle(valid_code)
    lines = _log_text(data_dir).splitlines()
    assert [line.split(" ", 2)[2] for line in lines] == ["LOG.INVALID_MESSAGE", "APP.START"]
    _assert_no_needles("\n".join(lines))


def test_log_event_with_a_bad_code_is_written_as_invalid_message(
    data_dir: Path, configure: _Opened
) -> None:
    configure(data_dir)
    log_event("not a code")
    log_event("lower.case")
    log_event("TRAILING.NEWLINE\n")
    log_event("")
    lines = _log_text(data_dir).splitlines()
    assert [line.split(" ", 2)[2] for line in lines] == ["LOG.INVALID_MESSAGE"] * 4


def test_log_event_accepts_integers_only(data_dir: Path, configure: _Opened) -> None:
    configure(data_dir)
    with pytest.raises(TypeError):
        log_event("X.Y", count="3")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        log_event("X.Y", count=True)
    with pytest.raises(TypeError):
        log_event("X.Y", duration_ms=1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        log_event("X.Y", duration_ms=IDENTIFIER)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        log_event("X.Y", other=IDENTIFIER)  # type: ignore[call-arg]
    assert _log_text(data_dir) == ""
    log_event("X.Y", count=0, duration_ms=0)
    assert _log_text(data_dir).rstrip().endswith("INFO X.Y count=0 duration_ms=0")


def test_extra_attributes_set_by_a_caller_are_not_written(
    data_dir: Path, configure: _Opened
) -> None:
    configure(data_dir)
    logging.getLogger(LOGGER_NAME).info(
        "APP.START", extra={"cbrn_count": IDENTIFIER, "cbrn_duration_ms": True, "label": LABEL}
    )
    text = _log_text(data_dir)
    assert text.rstrip().endswith("INFO APP.START")
    _assert_no_needles(text)


# --------------------------------------------------------------------------- crash handling


def test_unhandled_exception_is_reported_as_a_code_without_the_message(
    data_dir: Path, configure: _Opened
) -> None:
    configure(data_dir)
    reports: list[CrashReport] = []
    install_exception_hook(reports.append)

    _call_hook(_capture(_crash_site_a))

    (report,) = reports
    assert re.fullmatch(r"E-[0-9a-f]{8}", report.code)
    assert report.exception_type == "ValueError"
    for text in (report.code, report.exception_type, repr(report), str(report)):
        _assert_no_needles(text)
    assert set(dataclasses.asdict(report)) == {"code", "exception_type"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.code = "E-00000000"  # type: ignore[misc]

    text = _log_text(data_dir)
    lines = text.splitlines()
    assert re.fullmatch(rf"{TIMESTAMP} ERROR APP\.UNHANDLED_EXCEPTION exc=ValueError", lines[0])
    assert any(line.endswith(" in _crash_site_a") for line in lines)
    _assert_no_needles(text)


def test_crash_code_depends_on_the_site_only(data_dir: Path, configure: _Opened) -> None:
    configure(data_dir)
    reports: list[CrashReport] = []
    install_exception_hook(reports.append)

    _call_hook(_capture(_crash_site_a, "first message"))
    _call_hook(_capture(_crash_site_a, "a completely different message"))
    _call_hook(_capture(_crash_site_b))

    first, again, other = reports
    assert first.code == again.code
    assert first.code != other.code
    assert first.code == crash_code(ValueError, _capture(_crash_site_a)[2])


def test_the_code_depends_on_the_exception_type() -> None:
    def raise_value() -> None:
        raise ValueError

    def raise_key() -> None:
        raise KeyError

    def traceback_of(raiser: Callable[[], None]) -> TracebackType | None:
        try:
            raiser()
        except Exception as exc:
            return exc.__traceback__
        return None

    assert crash_code(ValueError, traceback_of(raise_value)) != crash_code(
        KeyError, traceback_of(raise_key)
    )
    assert re.fullmatch(r"E-[0-9a-f]{8}", crash_code(ValueError, None))
    assert crash_code(ValueError, None) == crash_code(ValueError, None)


def test_a_failing_callback_does_not_propagate(data_dir: Path, configure: _Opened) -> None:
    configure(data_dir)

    def failing(_report: CrashReport) -> None:
        raise RuntimeError(CHAIN_MESSAGE)

    install_exception_hook(failing)
    _call_hook(_capture(_crash_site_a))  # must not raise

    text = _log_text(data_dir)
    assert "APP.UNHANDLED_EXCEPTION" in text
    assert "APP.CRASH_CALLBACK_FAILED exc=RuntimeError" in text
    _assert_no_needles(text)


def test_the_hook_works_without_a_callback(data_dir: Path, configure: _Opened) -> None:
    configure(data_dir)
    install_exception_hook()
    _call_hook(_capture(_crash_site_a))
    assert "APP.UNHANDLED_EXCEPTION" in _log_text(data_dir)


def test_uninstall_restores_the_previous_hooks() -> None:
    previous = sys.excepthook
    previous_thread = threading.excepthook

    uninstall = install_exception_hook()
    assert sys.excepthook is not previous
    assert threading.excepthook is not previous_thread

    uninstall()
    assert sys.excepthook is previous
    assert threading.excepthook is previous_thread


def test_keyboard_interrupt_goes_to_the_previous_hook(data_dir: Path, configure: _Opened) -> None:
    configure(data_dir)
    seen: list[type[BaseException]] = []

    def previous(
        exc_type: type[BaseException], _value: BaseException, _tb: TracebackType | None
    ) -> None:
        seen.append(exc_type)

    sys.excepthook = previous
    reports: list[CrashReport] = []
    install_exception_hook(reports.append)

    sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)

    assert seen == [KeyboardInterrupt]
    assert reports == []
    assert _log_text(data_dir) == ""


def test_exceptions_in_threads_are_logged_but_never_reach_the_main_callback(
    data_dir: Path, configure: _Opened
) -> None:
    configure(data_dir)
    reports: list[CrashReport] = []
    install_exception_hook(reports.append)

    worker = threading.Thread(target=_crash_site_a, args=(SECRET_MESSAGE,))
    worker.start()
    worker.join()

    assert reports == []  # the GUI callback must never run on a worker thread
    text = _log_text(data_dir)
    assert "APP.UNHANDLED_EXCEPTION exc=ValueError" in text
    assert any(line.endswith(" in _crash_site_a") for line in text.splitlines())
    _assert_no_needles(text)


def test_the_thread_callback_receives_the_report_of_a_worker_exception(
    data_dir: Path, configure: _Opened
) -> None:
    configure(data_dir)
    main_reports: list[CrashReport] = []
    thread_reports: list[CrashReport] = []
    install_exception_hook(main_reports.append, thread_reports.append)

    worker = threading.Thread(target=_crash_site_a, args=(SECRET_MESSAGE,))
    worker.start()
    worker.join()

    assert main_reports == []
    (report,) = thread_reports
    assert report.exception_type == "ValueError"
    assert re.fullmatch(r"E-[0-9a-f]{8}", report.code)
    text = _log_text(data_dir)
    assert "APP.UNHANDLED_EXCEPTION exc=ValueError" in text
    _assert_no_needles(text)


def test_the_callback_is_not_entered_again_while_it_runs(
    data_dir: Path, configure: _Opened
) -> None:
    configure(data_dir)
    entered: list[CrashReport] = []

    def callback(report: CrashReport) -> None:
        entered.append(report)
        if len(entered) == 1:
            _call_hook(_capture(_crash_site_b, CHAIN_MESSAGE))  # an exception during the dialog

    install_exception_hook(callback)

    _call_hook(_capture(_crash_site_a))

    assert len(entered) == 1
    text = _log_text(data_dir)
    assert text.count("APP.UNHANDLED_EXCEPTION exc=ValueError") == 2
    assert " in _crash_site_a" in text
    assert " in _crash_site_b" in text
    _assert_no_needles(text)

    _call_hook(_capture(_crash_site_a))  # the guard was reset: the callback runs again
    assert len(entered) == 2
    assert _log_text(data_dir).count("APP.UNHANDLED_EXCEPTION") == 3


def test_the_guard_is_reset_when_the_callback_fails(data_dir: Path, configure: _Opened) -> None:
    configure(data_dir)
    calls: list[int] = []

    def failing(_report: CrashReport) -> None:
        calls.append(1)
        raise RuntimeError(CHAIN_MESSAGE)

    install_exception_hook(failing)
    _call_hook(_capture(_crash_site_a))
    _call_hook(_capture(_crash_site_a))
    assert len(calls) == 2


# --------------------------------------------------------------------------- configuration


def test_repeated_configuration_does_not_duplicate_handlers(
    data_dir: Path, configure: _Opened
) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    root = logging.getLogger()
    root_handlers = list(root.handlers)
    root_level = root.level

    first = configure(data_dir)
    second = configure(data_dir)
    third = configure(data_dir, read_only=True)

    assert _own_handlers(logger) == [third.handler]
    assert first.handler not in logger.handlers
    assert second.handler not in logger.handlers
    assert logger.propagate is False
    assert root.handlers == root_handlers
    assert root.level == root_level

    first.close()  # closing a replaced handle is harmless
    log_event("APP.START")
    assert len(third.memory_lines()) == 1

    third.close()
    assert _own_handlers(logger) == []
    third.close()  # idempotent


def test_a_single_file_handler_writes_each_event_once(data_dir: Path, configure: _Opened) -> None:
    configure(data_dir)
    configure(data_dir)
    log_event("APP.START")
    assert len(_log_text(data_dir).splitlines()) == 1


def test_handle_is_a_context_manager(data_dir: Path) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    with configure_logging(data_dir) as handle:
        assert _own_handlers(logger) == [handle.handler]
    assert _own_handlers(logger) == []


def test_log_files_can_be_deleted_after_close(tmp_path: Path) -> None:
    folder = tmp_path / "deletable"
    handle = configure_logging(folder)
    log_event("APP.START")
    handle.close()
    (folder / "logs" / "app.log").unlink()
    (folder / "logs").rmdir()


# --------------------------------------------------------------------------- paths


def test_frame_paths_are_never_absolute(tmp_path: Path, data_dir: Path, configure: _Opened) -> None:
    configure(data_dir)
    try:
        _raise_chained()
    except RuntimeError as exc:
        log_exception("TEST.FAILED", exc)
    text = _log_text(data_dir)

    assert str(tmp_path) not in text
    assert str(tmp_path.parent) not in text
    assert not re.search(r"[A-Za-z]:[\\/]", text)  # no drive letter
    assert "\\" not in text
    assert "Users" not in text
    for line in text.splitlines()[1:]:
        assert re.fullmatch(r"  (at [\w./<>-]+:\d+ in [\w<>.-]+|cause=\w+)", line), line


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("C:\\Users\\Someone\\proj\\mod.py", "mod.py"),
        ("c:/Users/Someone/proj/mod.py", "mod.py"),
        ("C:\\py\\Lib\\site-packages\\pkg\\mod.py", "pkg/mod.py"),
        ("C:\\py\\Lib\\Site-Packages\\pkg\\sub\\mod.py", "pkg/sub/mod.py"),
        ("/home/someone/.venv/lib/python3/site-packages/pkg/mod.py", "pkg/mod.py"),
        ("/home/someone/proj/mod.py", "mod.py"),
        ("\\\\server\\share\\dir\\mod.py", "mod.py"),
        ("<frozen importlib._bootstrap>", "<frozen?importlib._bootstrap>"),
        ("<string>", "<string>"),
        ("src/mod.py", "src/mod.py"),
        ("mod.py", "mod.py"),
        ("C:\\Users\\Some one\\x\ny.py", "x?y.py"),  # a control character is replaced
    ],
)
def test_display_path(filename: str, expected: str) -> None:
    assert display_path(filename) == expected


def test_display_path_makes_package_files_relative_to_the_package() -> None:
    assert display_path(logging_setup.__file__) == "cbrn_dashboard/logging_setup.py"
    package_dir = Path(logging_setup.__file__).parent
    nested = package_dir / "storage" / "repository.py"
    assert display_path(str(nested)) == "cbrn_dashboard/storage/repository.py"


# --------------------------------------------------------------------------- formatter


def test_formatter_never_calls_get_message_or_reads_args() -> None:
    class Exploding:
        def __str__(self) -> str:
            raise AssertionError(IDENTIFIER)

    record = logging.LogRecord("x", logging.INFO, "f.py", 1, "SOME.CODE %s", (Exploding(),), None)
    assert SafeFormatter().format(record).endswith("INFO LOG.INVALID_MESSAGE")


def test_formatter_ignores_exc_text_and_stack_info() -> None:
    record = logging.LogRecord("x", logging.INFO, "f.py", 1, "APP.START", None, None)
    record.exc_text = f"Traceback ... ValueError: {IDENTIFIER}"
    record.stack_info = f"Stack ... {IDENTIFIER}"
    formatter = SafeFormatter()
    assert formatter.format(record).endswith("INFO APP.START")
    assert formatter.formatException((ValueError, ValueError(IDENTIFIER), None)) == ""
    assert formatter.formatStack(IDENTIFIER) == ""


def test_formatter_handles_an_exception_without_type_information() -> None:
    record = logging.LogRecord(
        "x", logging.ERROR, "f.py", 1, "TEST.FAILED", None, (None, None, None)
    )
    assert SafeFormatter().format(record).endswith("ERROR TEST.FAILED")


def test_very_deep_tracebacks_are_truncated() -> None:
    def recurse(depth: int) -> None:
        if depth == 0:
            raise ValueError(IDENTIFIER)
        recurse(depth - 1)

    info = _capture(lambda _message: recurse(100))
    record = logging.LogRecord("x", logging.ERROR, "f.py", 1, "TEST.FAILED", None, info)
    lines = SafeFormatter().format(record).splitlines()
    assert len(lines) <= 1 + 1 + 40
    assert any(line.startswith("  omitted=") for line in lines)
    _assert_no_needles("\n".join(lines))
