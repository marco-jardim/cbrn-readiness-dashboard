# SPDX-License-Identifier: GPL-3.0-or-later
"""Test doubles and helpers shared by the UI tests: ``FakePrompts``, database and folder helpers."""

from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QWidget

from cbrn_dashboard import __version__
from cbrn_dashboard.app import AppHandle
from cbrn_dashboard.paths import DATABASE_FILE_NAME
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate


@dataclass(frozen=True)
class PromptCall:
    """One recorded call: the method name, the parent widget and the other arguments."""

    method: str
    parent: QWidget | None
    args: tuple[object, ...]

    @property
    def title(self) -> str:
        return str(self.args[0])

    @property
    def text(self) -> str:
        """The message text (second argument) of ``info``, ``warning``, ``error``, ``confirm``."""
        return str(self.args[1])


class FakePrompts:
    """Records every call; answers are scripted per method.

    Defaults: ``confirm`` -> ``False``, the file and folder pickers and ``text_input`` -> ``None``.
    ``script("confirm", True, False)`` queues answers; once the queue is empty the default applies.
    """

    def __init__(self) -> None:
        self.calls: list[PromptCall] = []
        self._answers: defaultdict[str, deque[object]] = defaultdict(deque)

    def script(self, method: str, *answers: object) -> None:
        self._answers[method].extend(answers)

    def calls_of(self, method: str) -> list[PromptCall]:
        return [call for call in self.calls if call.method == method]

    def _record(self, method: str, parent: QWidget | None, *args: object) -> None:
        self.calls.append(PromptCall(method, parent, args))

    def _answer(self, method: str, default: object) -> object:
        queue = self._answers[method]
        return queue.popleft() if queue else default

    def info(self, parent: QWidget | None, title: str, text: str) -> None:
        self._record("info", parent, title, text)

    def warning(self, parent: QWidget | None, title: str, text: str) -> None:
        self._record("warning", parent, title, text)

    def error(self, parent: QWidget | None, title: str, text: str) -> None:
        self._record("error", parent, title, text)

    def confirm(self, parent: QWidget | None, title: str, text: str) -> bool:
        self._record("confirm", parent, title, text)
        return bool(self._answer("confirm", False))

    def open_file(self, parent: QWidget | None, title: str, file_filter: str) -> Path | None:
        self._record("open_file", parent, title, file_filter)
        answer = self._answer("open_file", None)
        return answer if isinstance(answer, Path) else None

    def save_file(
        self, parent: QWidget | None, title: str, suggested_name: str, file_filter: str
    ) -> Path | None:
        self._record("save_file", parent, title, suggested_name, file_filter)
        answer = self._answer("save_file", None)
        return answer if isinstance(answer, Path) else None

    def choose_folder(self, parent: QWidget | None, title: str) -> Path | None:
        self._record("choose_folder", parent, title)
        answer = self._answer("choose_folder", None)
        return answer if isinstance(answer, Path) else None

    def text_input(
        self, parent: QWidget | None, title: str, label: str, *, password: bool = False
    ) -> str | None:
        self._record("text_input", parent, title, label, password)
        answer = self._answer("text_input", None)
        return answer if isinstance(answer, str) else None


def expect_handle(result: AppHandle | int) -> AppHandle:
    """The handle of a start that must have succeeded."""
    assert isinstance(result, AppHandle), f"start-up failed with exit code {result}"
    return result


def create_database(data_dir: Path, *, is_demo: bool = False) -> Path:
    """A migrated real-location database ``<data_dir>/cbrn-dashboard.sqlite3`` (then closed)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / DATABASE_FILE_NAME
    conn: DatabaseConnection = open_and_migrate(
        path, data_dir=data_dir, identity=DatabaseIdentity.REAL
    )
    try:
        app_meta.initialise(conn, is_demo=is_demo, created_with=__version__)
    finally:
        conn.close()
    return path


def snapshot(folder: Path) -> dict[str, tuple[int, bytes | None]]:
    """Every path below ``folder`` with its modification time and (for files) its bytes."""
    found: dict[str, tuple[int, bytes | None]] = {}
    for path in sorted(folder.rglob("*")):
        content = path.read_bytes() if path.is_file() else None
        found[path.relative_to(folder).as_posix()] = (path.stat().st_mtime_ns, content)
    return found
