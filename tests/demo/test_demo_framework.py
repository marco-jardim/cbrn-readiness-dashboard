# SPDX-License-Identifier: GPL-3.0-or-later
"""Demo-data framework and ``--demo`` mode (T1.7): separate database, D25 rules, determinism."""

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Protocol

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

import cbrn_dashboard
from cbrn_dashboard import demo as demo_module
from cbrn_dashboard.app import AppHandle, main, start
from cbrn_dashboard.cli import CliOptions
from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.demo import (
    DEFAULT_SEED,
    DEMO_SEED_KEY,
    GENERATORS,
    NOT_A_DEMO_DATABASE,
    NOT_DEMO_IDENTIFIER,
    DemoContext,
    DemoDataError,
    DemoGenerator,
    assert_demo_identifier,
    demo_database_path,
    demo_identifier,
    generate,
    is_demo_identifier,
    open_demo_database,
)
from cbrn_dashboard.paths import DATABASE_FILE_NAME, DataLocation, LocationSource
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import DatabaseConnection, open_database
from cbrn_dashboard.storage.migrate import (
    DatabaseIdentity,
    backup_before_migration,
    open_and_migrate,
)
from tests.ui._fakes import FakePrompts, expect_handle

CLOCK = FixedClock.at("2026-03-05T12:00:00Z")

type Rows = list[tuple[object, ...]]


# --------------------------------------------------------------------------- helpers


class Connections:
    """Opens and tracks connections so every one is closed at teardown."""

    def __init__(self) -> None:
        self._open: list[DatabaseConnection] = []

    def track(self, conn: DatabaseConnection) -> DatabaseConnection:
        self._open.append(conn)
        return conn

    def demo(
        self,
        data_dir: Path,
        generators: Sequence[DemoGenerator] | None = None,
        *,
        seed: int = DEFAULT_SEED,
    ) -> DatabaseConnection:
        return self.track(open_demo_database(data_dir, CLOCK, seed=seed, generators=generators))

    def plain(self, path: Path, *, is_demo: bool | None) -> DatabaseConnection:
        """A migrated database; ``app_meta`` is initialised unless ``is_demo`` is ``None``."""
        conn = self.track(
            open_and_migrate(path, data_dir=path.parent, identity=DatabaseIdentity.REAL)
        )
        if is_demo is not None:
            app_meta.initialise(conn, is_demo=is_demo, created_with="0.0.1")
        return conn

    def close_all(self) -> None:
        for conn in self._open:
            conn.close()


@pytest.fixture
def connections() -> Iterator[Connections]:
    registry = Connections()
    yield registry
    registry.close_all()


def _items(name: str = "items", kind: str = "P", count: int = 5) -> DemoGenerator:
    """A fake generator: fills the fictitious table ``fake_item`` with values from ``ctx.rng``."""

    def run(ctx: DemoContext) -> None:
        ctx.conn.execute(
            "CREATE TABLE IF NOT EXISTS fake_item (id INTEGER PRIMARY KEY, generator TEXT NOT NULL,"
            " code TEXT NOT NULL, value INTEGER NOT NULL, day TEXT NOT NULL) STRICT"
        )
        day = ctx.today.isoformat()
        for number in range(1, count + 1):
            ctx.conn.execute(
                "INSERT INTO fake_item (generator, code, value, day) VALUES (?, ?, ?, ?)",
                (name, demo_identifier(kind, number), ctx.rng.randrange(10**9), day),
            )

    return DemoGenerator(name, run)


def _rows(conn: DatabaseConnection, generator: str | None = None) -> Rows:
    sql = "SELECT generator, code, value, day FROM fake_item"
    params: tuple[str, ...] = ()
    if generator is not None:
        sql += " WHERE generator = ?"
        params = (generator,)
    return [tuple(row) for row in conn.execute(sql + " ORDER BY id", params).fetchall()]


def _count(conn: DatabaseConnection, table: str) -> int:
    value: object = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    assert isinstance(value, int)
    return value


# --------------------------------------------------------------------------- separate database


def test_demo_database_is_created_and_the_real_one_is_not(
    tmp_path: Path, connections: Connections
) -> None:
    connections.demo(tmp_path)
    assert demo_database_path(tmp_path) == tmp_path / "demo" / "demo.sqlite3"
    assert demo_database_path(tmp_path).is_file()
    assert not (tmp_path / DATABASE_FILE_NAME).exists()
    assert {entry.name for entry in tmp_path.iterdir()} == {"demo"}
    assert {entry.name for entry in (tmp_path / "demo").iterdir()} == {"demo.sqlite3"}


def test_an_existing_real_database_is_left_alone(tmp_path: Path, connections: Connections) -> None:
    real = tmp_path / DATABASE_FILE_NAME
    real.write_bytes(b"fictitious real database \x00\x01\x02" * 50)
    before_bytes = real.read_bytes()
    before_mtime = real.stat().st_mtime_ns

    connections.demo(tmp_path, [_items()])

    assert real.read_bytes() == before_bytes
    assert real.stat().st_mtime_ns == before_mtime
    assert {entry.name for entry in tmp_path.iterdir()} == {DATABASE_FILE_NAME, "demo"}
    assert not (tmp_path / "backups").exists()


# --------------------------------------------------------------------------- app_meta


def test_demo_database_is_marked_as_demo(tmp_path: Path, connections: Connections) -> None:
    conn = connections.demo(tmp_path)
    assert app_meta.get(conn, app_meta.IS_DEMO) == "1"
    assert app_meta.get(conn, app_meta.CREATED_WITH) == cbrn_dashboard.__version__
    assert app_meta.read_is_demo(conn) is True


def test_app_meta_rows_are_not_written_to_the_change_log(
    tmp_path: Path, connections: Connections
) -> None:
    conn = connections.demo(tmp_path, [_items()])
    assert _count(conn, "change_log") == 0


def test_initialise_with_false_reads_false_and_is_never_flipped(
    tmp_path: Path, connections: Connections
) -> None:
    conn = connections.plain(tmp_path / "real.sqlite3", is_demo=False)
    assert app_meta.read_is_demo(conn) is False
    app_meta.initialise(conn, is_demo=True, created_with="9.9.9")
    assert app_meta.read_is_demo(conn) is False
    assert app_meta.get(conn, app_meta.IS_DEMO) == "0"
    assert app_meta.get(conn, app_meta.CREATED_WITH) == "0.0.1"


def test_initialise_twice_keeps_a_demo_database_a_demo_database(
    tmp_path: Path, connections: Connections
) -> None:
    conn = connections.plain(tmp_path / "d.sqlite3", is_demo=True)
    app_meta.initialise(conn, is_demo=False, created_with="9.9.9")
    assert app_meta.read_is_demo(conn) is True
    assert _count(conn, "app_meta") == 2


def test_a_missing_row_reads_false(tmp_path: Path, connections: Connections) -> None:
    conn = connections.plain(tmp_path / "bare.sqlite3", is_demo=None)
    assert app_meta.get(conn, app_meta.IS_DEMO) is None
    assert app_meta.read_is_demo(conn) is False


def test_only_the_exact_value_one_means_demo(tmp_path: Path, connections: Connections) -> None:
    conn = connections.plain(tmp_path / "odd.sqlite3", is_demo=None)
    for value in ("0", "true", "yes", "", "01", "1 "):
        app_meta.set_value(conn, app_meta.IS_DEMO, value)
        assert app_meta.read_is_demo(conn) is False
    app_meta.set_value(conn, app_meta.IS_DEMO, "1")
    assert app_meta.read_is_demo(conn) is True


# --------------------------------------------------------------------------- backups


def test_open_demo_database_migrates_with_the_demo_identity(
    tmp_path: Path, connections: Connections, monkeypatch: pytest.MonkeyPatch
) -> None:
    identities: list[DatabaseIdentity] = []
    data_dirs: list[Path] = []

    def spy(
        path: Path,
        *,
        data_dir: Path,
        identity: DatabaseIdentity,
        backup: bool = True,
        package: str | None = None,
    ) -> DatabaseConnection:
        identities.append(identity)
        data_dirs.append(data_dir)
        return open_and_migrate(
            path, data_dir=data_dir, identity=identity, backup=backup, package=package
        )

    monkeypatch.setattr(demo_module, "open_and_migrate", spy)
    connections.demo(tmp_path)
    assert identities == [DatabaseIdentity.DEMO]
    assert data_dirs == [tmp_path]


def test_pre_migration_backup_of_the_demo_database_goes_to_demo_backups(
    tmp_path: Path, connections: Connections
) -> None:
    conn = connections.demo(tmp_path, [_items()])
    backup = backup_before_migration(
        conn, data_dir=tmp_path, identity=DatabaseIdentity.DEMO, from_version=1
    )
    assert backup is not None
    assert backup.parent == tmp_path / "demo" / "backups"
    assert backup.is_file()
    assert not (tmp_path / "backups").exists()
    copy = connections.track(open_database(backup, read_only=True))
    assert _rows(copy) == _rows(conn)


# --------------------------------------------------------------------------- determinism


def test_same_seed_gives_identical_rows(tmp_path: Path, connections: Connections) -> None:
    first = connections.demo(tmp_path / "a", [_items()], seed=7)
    second = connections.demo(tmp_path / "b", [_items()], seed=7)
    assert _rows(first) == _rows(second)
    assert len(_rows(first)) == 5


def test_different_seed_gives_different_rows(tmp_path: Path, connections: Connections) -> None:
    first = connections.demo(tmp_path / "a", [_items()], seed=7)
    second = connections.demo(tmp_path / "b", [_items()], seed=8)
    assert _rows(first) != _rows(second)


def test_default_seed_is_used_and_recorded(tmp_path: Path, connections: Connections) -> None:
    conn = connections.demo(tmp_path, [_items()])
    assert app_meta.get(conn, DEMO_SEED_KEY) == str(DEFAULT_SEED)
    assert DEFAULT_SEED == 20260101


def test_adding_a_generator_does_not_change_another_generators_rows(
    tmp_path: Path, connections: Connections
) -> None:
    alone = connections.demo(tmp_path / "a", [_items("items")])
    after = connections.demo(tmp_path / "b", [_items("items"), _items("extra", kind="A")])
    before = connections.demo(tmp_path / "c", [_items("extra", kind="A"), _items("items")])
    expected = _rows(alone, "items")
    assert _rows(after, "items") == expected
    assert _rows(before, "items") == expected
    extra_values = [row[2] for row in _rows(after, "extra")]
    assert len(extra_values) == 5
    assert extra_values != [row[2] for row in expected]  # each generator has its own stream


def test_generators_place_data_relative_to_the_clock(
    tmp_path: Path, connections: Connections
) -> None:
    conn = connections.demo(tmp_path, [_items()])
    assert {row[3] for row in _rows(conn)} == {"2026-03-05"}


def test_generate_can_be_called_directly_on_two_fresh_databases(
    tmp_path: Path, connections: Connections
) -> None:
    first = connections.plain(tmp_path / "one.sqlite3", is_demo=True)
    second = connections.plain(tmp_path / "two.sqlite3", is_demo=True)
    assert generate(first, CLOCK, seed=3, generators=[_items()]) is True
    assert generate(second, CLOCK, seed=3, generators=[_items()]) is True
    assert _rows(first) == _rows(second)
    assert generate(first, CLOCK, seed=3, generators=[_items()]) is False
    assert len(_rows(first)) == 5


def test_reopening_does_not_regenerate_or_duplicate(
    tmp_path: Path, connections: Connections
) -> None:
    first = connections.demo(tmp_path, [_items()], seed=11)
    rows = _rows(first)
    first.close()

    again = connections.demo(tmp_path, [_items()], seed=11)
    assert _rows(again) == rows
    again.close()

    other_seed = connections.demo(tmp_path, [_items(), _items("more", kind="A")], seed=12)
    assert _rows(other_seed) == rows
    assert app_meta.get(other_seed, DEMO_SEED_KEY) == "11"


def test_duplicate_generator_names_are_rejected(tmp_path: Path, connections: Connections) -> None:
    conn = connections.plain(tmp_path / "x.sqlite3", is_demo=True)
    with pytest.raises(ValueError, match="unique"):
        generate(conn, CLOCK, generators=[_items("same"), _items("same")])


# --------------------------------------------------------------------------- identifiers


def test_generated_identifiers_start_with_demo(tmp_path: Path, connections: Connections) -> None:
    conn = connections.demo(tmp_path, [_items(), _items("extra", kind="A")])
    codes = [str(row[1]) for row in _rows(conn)]
    assert len(codes) == 10
    assert all(is_demo_identifier(code) for code in codes)
    for code in codes:
        assert_demo_identifier(code)


def test_identifier_helpers() -> None:
    assert demo_identifier("P", 1) == "DEMO-P001"
    assert demo_identifier("A", 12) == "DEMO-A012"
    assert demo_identifier("EX-", 1, width=2) == "DEMO-EX-01"
    assert is_demo_identifier("DEMO-P001")
    assert not is_demo_identifier("P001")
    assert not is_demo_identifier("demo-P001")
    assert_demo_identifier("DEMO-EX-01")


def test_a_non_demo_identifier_is_refused() -> None:
    with pytest.raises(DemoDataError) as excinfo:
        assert_demo_identifier("P001")
    assert excinfo.value.code == NOT_DEMO_IDENTIFIER == "NOT_DEMO_IDENTIFIER"
    assert "P001" not in str(excinfo.value)


# --------------------------------------------------------------------------- registry


def test_registry_is_a_tuple_of_named_generators() -> None:
    assert isinstance(GENERATORS, tuple)
    assert all(isinstance(generator, DemoGenerator) for generator in GENERATORS)
    names = [generator.name for generator in GENERATORS]
    assert len(names) == len(set(names))


def test_default_registry_opens_and_seeds_once(tmp_path: Path, connections: Connections) -> None:
    conn = connections.demo(tmp_path)
    assert app_meta.get(conn, DEMO_SEED_KEY) == str(DEFAULT_SEED)
    assert app_meta.read_is_demo(conn) is True
    conn.close()
    again = connections.demo(tmp_path)
    assert app_meta.get(again, DEMO_SEED_KEY) == str(DEFAULT_SEED)


# --------------------------------------------------------------------------- failures


def test_a_failing_generator_leaves_no_marker_and_no_partial_rows(
    tmp_path: Path, connections: Connections
) -> None:
    def boom(_ctx: DemoContext) -> None:
        msg = "generator failed"
        raise RuntimeError(msg)

    failing = [_items(), DemoGenerator("boom", boom)]
    with pytest.raises(RuntimeError, match="generator failed"):
        open_demo_database(tmp_path, CLOCK, generators=failing)

    probe = connections.track(open_database(demo_database_path(tmp_path), read_only=True))
    assert app_meta.get(probe, DEMO_SEED_KEY) is None
    tables = probe.execute("SELECT name FROM sqlite_master WHERE name = 'fake_item'").fetchall()
    assert tables == []
    probe.close()

    # The database is still a usable demo database: the next open seeds it.
    conn = connections.demo(tmp_path, [_items()])
    assert len(_rows(conn)) == 5


@pytest.mark.parametrize("kind", ["real", "no_is_demo_row", "garbage"])
def test_a_non_demo_database_at_the_demo_path_is_refused_untouched(
    tmp_path: Path, connections: Connections, kind: str
) -> None:
    path = demo_database_path(tmp_path)
    path.parent.mkdir(parents=True)
    if kind == "garbage":
        path.write_bytes(b"this is not a database" * 100)
    else:
        conn = connections.plain(path, is_demo=False if kind == "real" else None)
        conn.close()
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    with pytest.raises(DemoDataError) as excinfo:
        open_demo_database(tmp_path, CLOCK, generators=[_items()])

    assert excinfo.value.code == NOT_A_DEMO_DATABASE == "NOT_A_DEMO_DATABASE"
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime
    assert not (tmp_path / "demo" / "backups").exists()
    assert not (tmp_path / "backups").exists()
    assert {entry.name for entry in path.parent.iterdir()} == {"demo.sqlite3"}


# --------------------------------------------------------------------------- application wiring


class MakeApp(Protocol):
    """Starts the application like ``main`` does (without ``exec``)."""

    def __call__(self, data_dir: Path, *, demo: bool) -> AppHandle: ...


@pytest.fixture
def make_app(qapp: QApplication, qm_dir: Path, qtbot: QtBot) -> Iterator[MakeApp]:
    handles: list[AppHandle] = []

    def make(data_dir: Path, *, demo: bool) -> AppHandle:
        data_dir.mkdir(parents=True, exist_ok=True)  # the real resolver creates the folder
        location = DataLocation(path=data_dir, source=LocationSource.CLI, writable=True)
        options = CliOptions(data_dir=str(data_dir), lang="en-US", demo=demo)
        result = start(
            options,
            location,
            clock=CLOCK,
            prompts=FakePrompts(),
            qm_dir=qm_dir,
            hooks=(),
        )
        handle = expect_handle(result)
        qtbot.addWidget(handle.window)
        handles.append(handle)
        return handle

    yield make
    for handle in reversed(handles):
        handle.close()


@pytest.mark.ui
def test_demo_option_opens_the_demo_database(tmp_path: Path, make_app: MakeApp) -> None:
    handle = make_app(tmp_path, demo=True)
    assert handle.database is not None
    assert handle.is_demo is True
    assert demo_database_path(tmp_path).is_file()
    assert not (tmp_path / DATABASE_FILE_NAME).exists()  # --demo never creates the real database
    assert not (tmp_path / "backups").exists()


@pytest.mark.ui
def test_without_demo_the_real_database_is_opened_and_no_demo_folder_appears(
    tmp_path: Path, make_app: MakeApp
) -> None:
    # T1.9 opens the real database at start-up; --demo is the only way to the demo database.
    handle = make_app(tmp_path, demo=False)
    assert handle.database is not None
    assert handle.is_demo is False
    assert (tmp_path / DATABASE_FILE_NAME).is_file()
    assert list(tmp_path.rglob("*.sqlite3")) == [tmp_path / DATABASE_FILE_NAME]
    assert not (tmp_path / "demo").exists()


@pytest.mark.ui
def test_is_demo_follows_app_meta_not_the_flag(
    tmp_path: Path, make_app: MakeApp, connections: Connections
) -> None:
    handle = make_app(tmp_path / "flagged", demo=True)
    assert handle.is_demo is True
    handle.close_database()

    handle.database = connections.plain(tmp_path / "real.sqlite3", is_demo=False)
    assert handle.is_demo is False  # the command-line flag said demo, the database says real

    plain = make_app(tmp_path / "plain", demo=False)
    plain.database = connections.plain(tmp_path / "demo-like.sqlite3", is_demo=True)
    assert plain.is_demo is True  # no flag, but the database says demo


@pytest.mark.ui
def test_close_database_closes_the_connection(tmp_path: Path, make_app: MakeApp) -> None:
    handle = make_app(tmp_path, demo=True)
    handle.close_database()
    assert handle.database is None
    assert handle.is_demo is False


@pytest.mark.ui
def test_demo_with_an_unwritable_data_folder_returns_one(
    qapp: QApplication, qm_dir: Path, tmp_path: Path
) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("a file, not a folder", encoding="utf-8")
    prompts = FakePrompts()
    argv = ["--demo", "--lang", "en-US", "--data-dir", str(blocked)]
    assert main(argv, qm_dir=qm_dir, prompts=prompts) == 1
    [call] = prompts.calls_of("error")  # one translated explanation instead of a silent exit
    assert call.title == "Cannot start"
    assert call.text == (
        "The data folder is not writable and has no database, so nothing can be opened."
    )
    assert blocked.read_text(encoding="utf-8") == "a file, not a folder"
    assert [entry.name for entry in tmp_path.iterdir()] == ["blocked"]


@pytest.mark.ui
def test_self_test_ignores_demo(qapp: QApplication, qm_dir: Path, tmp_path: Path) -> None:
    data = tmp_path / "data"
    assert main(["--self-test", "--demo", "--data-dir", str(data)], qm_dir=qm_dir) == 0
    assert not (data / "demo").exists()
    assert list(data.rglob("*.sqlite3")) == []
