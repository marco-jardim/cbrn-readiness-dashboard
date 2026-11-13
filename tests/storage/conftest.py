# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared fixtures for the storage tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate


@pytest.fixture
def migrated_db(tmp_path: Path) -> Iterator[DatabaseConnection]:
    """A fresh database with every real migration applied."""
    conn = open_and_migrate(
        tmp_path / "test.sqlite3",
        data_dir=tmp_path,
        identity=DatabaseIdentity.REAL,
        backup=False,
    )
    try:
        yield conn
    finally:
        conn.close()
