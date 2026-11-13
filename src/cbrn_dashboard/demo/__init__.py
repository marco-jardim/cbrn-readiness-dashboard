# SPDX-License-Identifier: GPL-3.0-or-later
"""Demo-data framework and the demo database (PLAN.md D25, I07, task T1.7).

``--demo`` works on a SEPARATE database, ``<data>/demo/demo.sqlite3``, with its own backup folder
``<data>/demo/backups/``. The real database ``<data>/cbrn-dashboard.sqlite3`` is never created,
opened or touched by anything in this module.

Seeding is deterministic. Every registered generator receives its OWN ``random.Random`` derived
from the seed and the generator's name, so adding a module's generator later does not change the
data another module generates. Time enters only through the injected
:class:`~cbrn_dashboard.clock.Clock` (``DemoContext.today`` is ``clock.local_date()``), so the
generated data sits relative to "today".

Every generated identifier starts with ``DEMO`` (``DEMO-P001``, ``DEMO-A001``, ``DEMO-EX-01``);
generators and tests enforce that with :func:`assert_demo_identifier`.

A database is seeded exactly once: the generators run inside ONE transaction (rolled back as a
whole on error) only while ``app_meta["demo_seed"]`` is absent, and the marker is written in that
same transaction. Reopening an existing demo database neither regenerates nor duplicates anything.

Module generators register with exactly one line each in :data:`GENERATORS`.

Qt-free.
"""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cbrn_dashboard import __version__
from cbrn_dashboard.clock import Clock
from cbrn_dashboard.demo import budget, exercises, infrastructure, personnel
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import (
    DatabaseConnection,
    DatabaseError,
    HotJournalError,
    open_database,
    transaction,
)
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate

__all__ = [
    "DEFAULT_SEED",
    "DEMO_DATABASE_FILE_NAME",
    "DEMO_DIR_NAME",
    "DEMO_PREFIX",
    "DEMO_SEED_KEY",
    "GENERATORS",
    "NOT_A_DEMO_DATABASE",
    "NOT_DEMO_IDENTIFIER",
    "DemoContext",
    "DemoDataError",
    "DemoGenerator",
    "assert_demo_identifier",
    "demo_database_path",
    "demo_identifier",
    "generate",
    "is_demo_identifier",
    "open_demo_database",
]

DEMO_DIR_NAME = "demo"
DEMO_DATABASE_FILE_NAME = "demo.sqlite3"
DEMO_PREFIX = "DEMO"
DEFAULT_SEED = 20260101

#: ``app_meta`` key of the marker that says the generators already ran (value: the seed as text).
DEMO_SEED_KEY = "demo_seed"

NOT_DEMO_IDENTIFIER = "NOT_DEMO_IDENTIFIER"
NOT_A_DEMO_DATABASE = "NOT_A_DEMO_DATABASE"


class DemoDataError(DatabaseError):
    """A demo-data rule was broken; ``code`` is stable and translated by the UI."""

    code = "DEMO_DATA_ERROR"

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- generators


@dataclass(frozen=True)
class DemoContext:
    """What a generator gets: the connection, the clock, its own RNG and the clock's date."""

    conn: DatabaseConnection
    clock: Clock
    rng: random.Random
    today: date


@dataclass(frozen=True)
class DemoGenerator:
    """A named demo-data generator; ``name`` also seeds its random number generator."""

    name: str
    run: Callable[[DemoContext], None]


#: The registered module generators, ONE PER LINE. Tasks T2.5, T3.5, T4.6 and T5.5 each add exactly
#: one line of the form ``DemoGenerator("<module>", <module>.generate),`` where ``generate`` has
#: the signature ``generate(ctx: DemoContext) -> None``.
GENERATORS: tuple[DemoGenerator, ...] = (
    DemoGenerator("personnel", personnel.generate),
    DemoGenerator("infrastructure", infrastructure.generate),
    DemoGenerator("exercises", exercises.generate),
    DemoGenerator("budget", budget.generate),
)


# --------------------------------------------------------------------------- identifiers


def demo_identifier(kind: str, number: int, *, width: int = 3) -> str:
    """``DEMO-<kind><number>`` with ``number`` zero-padded to ``width``, e.g. ``DEMO-P001``."""
    return f"{DEMO_PREFIX}-{kind}{number:0{width}d}"


def is_demo_identifier(value: str) -> bool:
    """Whether ``value`` carries the demo prefix."""
    return value.startswith(DEMO_PREFIX)


def assert_demo_identifier(value: str) -> None:
    """Raise :class:`DemoDataError` (``NOT_DEMO_IDENTIFIER``) unless ``value`` starts with DEMO."""
    if not is_demo_identifier(value):
        msg = f"A demo identifier must start with {DEMO_PREFIX}."
        raise DemoDataError(NOT_DEMO_IDENTIFIER, msg)


# --------------------------------------------------------------------------- seeding


def demo_database_path(data_dir: Path) -> Path:
    """``<data>/demo/demo.sqlite3``."""
    return data_dir / DEMO_DIR_NAME / DEMO_DATABASE_FILE_NAME


def _generator_rng(seed: int, name: str) -> random.Random:
    return random.Random(f"{seed}:{name}")


def generate(
    conn: DatabaseConnection,
    clock: Clock,
    *,
    seed: int = DEFAULT_SEED,
    generators: Sequence[DemoGenerator] | None = None,
) -> bool:
    """Run the generators once for this database; return whether they ran.

    Nothing happens (``False``) when ``app_meta["demo_seed"]`` is already present. Otherwise all
    generators and the marker are written in one transaction, rolled back as a whole on error.
    """
    chosen = GENERATORS if generators is None else tuple(generators)
    names = [generator.name for generator in chosen]
    if len(set(names)) != len(names):
        msg = "Demo generator names must be unique."
        raise ValueError(msg)
    today = clock.local_date()
    with transaction(conn):
        if app_meta.get(conn, DEMO_SEED_KEY) is not None:
            return False
        for generator in chosen:
            context = DemoContext(
                conn=conn, clock=clock, rng=_generator_rng(seed, generator.name), today=today
            )
            generator.run(context)
        app_meta.set_value(conn, DEMO_SEED_KEY, str(seed))
    return True


def _probe_is_demo(path: Path) -> bool:
    """Whether the existing file at ``path`` is a demo database (read-only probe)."""
    msg = "The file at the demo database location is not a demo database."
    try:
        probe = open_database(path, read_only=True)
    except HotJournalError:
        raise  # the caller recovers the journal and probes again
    except (sqlite3.DatabaseError, DatabaseError) as exc:
        raise DemoDataError(NOT_A_DEMO_DATABASE, msg) from exc
    try:
        try:
            return app_meta.read_is_demo(probe)
        except HotJournalError:
            raise
        except (sqlite3.DatabaseError, DatabaseError) as exc:
            raise DemoDataError(NOT_A_DEMO_DATABASE, msg) from exc
    finally:
        probe.close()


def _refuse_if_not_demo(path: Path) -> None:
    """Refuse an existing file that is not a demo database, without touching it.

    The one exception: a hot rollback journal (an earlier crash during a write) cannot be rolled
    back by the read-only probe, so the file is opened read-write once (the caller holds the
    instance lock) and SQLite recovers it. That is what any SQLite open does, and it is the only
    change this check may make to a file that is then refused as not a demo database.
    """
    if not path.is_file() or path.stat().st_size == 0:
        return
    try:
        is_demo = _probe_is_demo(path)
    except HotJournalError:
        open_database(path).close()
        is_demo = _probe_is_demo(path)  # still failing: the error propagates
    if not is_demo:
        msg = "The file at the demo database location is not a demo database."
        raise DemoDataError(NOT_A_DEMO_DATABASE, msg)


def open_demo_database(
    data_dir: Path,
    clock: Clock,
    *,
    seed: int = DEFAULT_SEED,
    generators: Sequence[DemoGenerator] | None = None,
) -> DatabaseConnection:
    """Open (creating and seeding it on first use) ``<data>/demo/demo.sqlite3``.

    The database is migrated with ``DatabaseIdentity.DEMO``, so its pre-migration backups go to
    ``<data>/demo/backups/``. The real database is never touched. An existing file whose
    ``app_meta.is_demo`` is not ``"1"`` is refused with ``NOT_A_DEMO_DATABASE`` and left as it is.
    """
    path = demo_database_path(data_dir)
    _refuse_if_not_demo(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = open_and_migrate(path, data_dir=data_dir, identity=DatabaseIdentity.DEMO)
    try:
        app_meta.initialise(conn, is_demo=True, created_with=__version__)
        generate(conn, clock, seed=seed, generators=generators)
    except BaseException:
        conn.close()
        raise
    return conn
