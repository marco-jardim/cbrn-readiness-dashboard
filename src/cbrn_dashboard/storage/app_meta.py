# SPDX-License-Identifier: GPL-3.0-or-later
"""Helper for the ``app_meta`` key/value table (PLAN.md section 5.2, D25, task T1.7).

``app_meta`` holds facts about the database file itself: ``is_demo`` (``"0"`` or ``"1"``) and
``created_with`` (the application version that created the file). These rows are structural
metadata written when a database is created. They are not record data and are therefore NOT written
to ``change_log``.

``initialise`` is idempotent and never changes an existing value, so reopening a database can never
flip it between real and demo. The application's demo flag is always read from here
(:func:`read_is_demo`), never from the command line.

Qt-free; plain SQL through :class:`~cbrn_dashboard.storage.db.DatabaseConnection`.
"""

from __future__ import annotations

import sqlite3

from cbrn_dashboard.storage.db import DatabaseError, transaction

__all__ = [
    "CREATED_WITH",
    "IS_DEMO",
    "get",
    "initialise",
    "read_is_demo",
    "set_value",
]

IS_DEMO = "is_demo"
CREATED_WITH = "created_with"

_INSERT_IF_ABSENT = "INSERT INTO app_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO NOTHING"


def initialise(conn: sqlite3.Connection, *, is_demo: bool, created_with: str) -> None:
    """Write ``is_demo`` and ``created_with`` when they are absent; never overwrite them."""
    with transaction(conn):
        conn.execute(_INSERT_IF_ABSENT, (IS_DEMO, "1" if is_demo else "0"))
        conn.execute(_INSERT_IF_ABSENT, (CREATED_WITH, created_with))


def get(conn: sqlite3.Connection, key: str) -> str | None:
    """The value stored for ``key``, or ``None`` when there is no such row."""
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    value: object = row[0]
    if not isinstance(value, str):
        msg = "Unexpected value type in app_meta."
        raise DatabaseError(msg)
    return value


def set_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Insert or replace the row ``key``."""
    with transaction(conn):
        conn.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def read_is_demo(conn: sqlite3.Connection) -> bool:
    """``True`` only when ``is_demo`` is stored as exactly ``"1"``; a missing row is ``False``."""
    return get(conn, IS_DEMO) == "1"
