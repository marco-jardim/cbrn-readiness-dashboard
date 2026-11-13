# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures shared by the module service tests; nothing here is module-specific."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.storage.db import DatabaseConnection, open_database
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate

type ChangeLogRows = Callable[[DatabaseConnection], list[dict[str, object]]]


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "services.sqlite3"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[DatabaseConnection]:
    """A fresh, fully migrated read-write database."""
    conn = open_and_migrate(
        _db_path(tmp_path),
        data_dir=tmp_path,
        identity=DatabaseIdentity.REAL,
        backup=False,
    )
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def clock() -> FixedClock:
    """A fixed clock; every change_log row of a test is stamped with this instant."""
    return FixedClock.at("2026-03-05T12:00:00Z")


@pytest.fixture
def change_log_rows() -> ChangeLogRows:
    """A function returning every ``change_log`` row, oldest first, as dicts."""

    def read(conn: DatabaseConnection) -> list[dict[str, object]]:
        cursor = conn.execute("SELECT * FROM change_log ORDER BY id")
        return [dict(row) for row in cursor.fetchall()]

    return read


@pytest.fixture
def read_only_db(db: DatabaseConnection, tmp_path: Path) -> Iterator[DatabaseConnection]:
    """The migrated database file reopened read-only (``db`` stays open beside it)."""
    conn = open_database(_db_path(tmp_path), read_only=True)
    try:
        yield conn
    finally:
        conn.close()
