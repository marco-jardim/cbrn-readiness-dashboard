# SPDX-License-Identifier: GPL-3.0-or-later
"""Consistent local backups and rotation (T7.1): every Accept bullet of the task."""

from __future__ import annotations

import itertools
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from cbrn_dashboard.clock import Clock, FixedClock
from cbrn_dashboard.logging_setup import configure_logging
from cbrn_dashboard.paths import DATABASE_FILE_NAME, DataLocation, LocationSource
from cbrn_dashboard.services.backup import (
    BackupService,
    daily_backup_hook,
    daily_backup_startup,
)
from cbrn_dashboard.storage import backup as backup_module
from cbrn_dashboard.storage import migrate as migrate_module
from cbrn_dashboard.storage.backup import (
    BEFORE_RESTORE_KEEP,
    MIN_KEEP,
    PRE_MIGRATION_KEEP,
    BackupInfo,
    BackupKind,
    DatabaseIdentity,
    backup_before_migration,
    backups_dir,
    copy_database,
    create_backup,
    database_path,
    list_backups,
    parse_backup_name,
    rotate,
    verify_backup,
)
from cbrn_dashboard.storage.db import DatabaseConnection, open_database, transaction
from cbrn_dashboard.storage.migrate import open_and_migrate
from cbrn_dashboard.storage.repository import WriteContext
from cbrn_dashboard.storage.settings_repo import load_config, save_config

REAL = DatabaseIdentity.REAL
DEMO = DatabaseIdentity.DEMO
START = FixedClock.at("2026-03-01T12:00:00Z")
_package_numbers = itertools.count(1)


# --------------------------------------------------------------------------- helpers


def day(index: int) -> FixedClock:
    """The clock ``index`` days after ``START`` (UTC offset 0)."""
    return START.advanced(timedelta(days=index))


def hour(index: int) -> FixedClock:
    return START.advanced(timedelta(hours=index))


def stamp(clock: FixedClock) -> str:
    return clock.utc_now().strftime("%Y%m%dT%H%M%SZ")


def make_db(data: Path, *, identity: DatabaseIdentity = REAL) -> DatabaseConnection:
    """A migrated database at the standard place of ``identity``, plus table ``note`` (1, 2, 3)."""
    path = database_path(data, identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = open_and_migrate(path, data_dir=data, identity=identity, backup=False)
    conn.execute("CREATE TABLE note (x INTEGER) STRICT")
    with transaction(conn):
        conn.executemany("INSERT INTO note VALUES (?)", [(1,), (2,), (3,)])
    return conn


def note_values(conn: sqlite3.Connection) -> list[int]:
    return [int(row[0]) for row in conn.execute("SELECT x FROM note ORDER BY x")]


def integrity(conn: sqlite3.Connection) -> list[str]:
    return [str(row[0]) for row in conn.execute("PRAGMA integrity_check")]


def user_version(conn: sqlite3.Connection) -> int:
    value: int = conn.execute("PRAGMA user_version").fetchone()[0]
    return value


def names(folder: Path) -> list[str]:
    return sorted(entry.name for entry in folder.iterdir()) if folder.is_dir() else []


def daily(
    conn: DatabaseConnection,
    data: Path,
    clock: Clock,
    *,
    identity: DatabaseIdentity = REAL,
    rotate_pool: bool = True,
    ok: bool = True,
) -> backup_module.BackupResult | None:
    """One application start on the day of ``clock`` (``ok=False``: the integrity check fails)."""
    service = BackupService(
        conn,
        clock,
        data_dir=data,
        identity=identity,
        quick_check=verify_backup if ok else (lambda _path: False),
    )
    return service.run_daily_backup(rotate=rotate_pool)


def make_copy(
    conn: DatabaseConnection, data: Path, kind: BackupKind, clock: Clock
) -> backup_module.BackupResult:
    """``create_backup`` for the real database with the default integrity check."""
    return create_backup(conn, data_dir=data, identity=REAL, kind=kind, clock=clock)


def set_keep(conn: DatabaseConnection, keep: int) -> None:
    config = load_config(conn).with_changes(daily_backups_kept=keep)
    save_config(WriteContext(conn, START), config)


def daily_times(data: Path, identity: DatabaseIdentity = REAL) -> list[datetime]:
    """UTC instants of the daily pool, oldest first."""
    infos = list_backups(data, identity, BackupKind.DAILY)
    return sorted(info.created_utc for info in infos)


def make_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, files: dict[str, str]) -> str:
    name = f"t71_migrations_{next(_package_numbers)}"
    folder = tmp_path / "packages" / name
    folder.mkdir(parents=True)
    (folder / "__init__.py").write_text("", encoding="utf-8")
    for file_name, sql in files.items():
        (folder / file_name).write_text(sql, encoding="utf-8")
    monkeypatch.syspath_prepend(str(folder.parent))
    return name


@pytest.fixture
def data(tmp_path: Path) -> Path:
    folder = tmp_path / "data"
    folder.mkdir()
    return folder


# --------------------------------------------------------------------------- consistent copy


def test_copy_while_another_connection_holds_a_write_transaction(data: Path) -> None:
    with (
        closing(make_db(data)) as conn,
        closing(open_database(database_path(data, REAL))) as writer,
    ):
        writer.execute("BEGIN IMMEDIATE")
        writer.executemany("INSERT INTO note VALUES (?)", [(100,), (101,)])
        assert writer.in_transaction

        result = make_copy(conn, data, BackupKind.DAILY, START)
        assert result.verified
        with closing(open_database(result.path, read_only=True)) as copy:
            assert integrity(copy) == ["ok"]
            assert note_values(copy) == [1, 2, 3]  # only committed rows

        writer.execute("COMMIT")  # the writer was not disturbed
        assert note_values(conn) == [1, 2, 3, 100, 101]


def test_copy_database_writes_a_complete_file_and_no_leftovers(data: Path) -> None:
    dest = data / "out" / "copy.sqlite3"
    with closing(make_db(data)) as conn:
        copy_database(conn, dest)
        assert user_version(conn) > 0
    assert names(dest.parent) == ["copy.sqlite3"]
    with closing(open_database(dest, read_only=True)) as copy:
        assert integrity(copy) == ["ok"]
        assert note_values(copy) == [1, 2, 3]


@dataclass
class _Spy:
    """Stands in for the source connection: records the folder while the copy is in flight."""

    real: sqlite3.Connection
    folder: Path
    seen: tuple[str, ...] = ()

    def backup(self, target: sqlite3.Connection) -> None:
        self.real.backup(target)
        self.seen = tuple(names(self.folder))


class _Failing:
    def backup(self, target: sqlite3.Connection) -> None:
        msg = "boom"
        raise sqlite3.OperationalError(msg)


def test_a_copy_has_a_temporary_name_until_complete(data: Path) -> None:
    dest = data / "out" / "copy.sqlite3"
    with closing(make_db(data)) as conn:
        spy = _Spy(conn, dest.parent)
        copy_database(cast("sqlite3.Connection", spy), dest)
    assert spy.seen == ("copy.sqlite3.partial",)
    assert names(dest.parent) == ["copy.sqlite3"]


def test_a_failed_copy_leaves_nothing_behind(data: Path) -> None:
    dest = data / "out" / "copy.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        copy_database(cast("sqlite3.Connection", _Failing()), dest)
    assert names(dest.parent) == []


def test_partial_files_are_never_listed_as_backups(data: Path) -> None:
    folder = backups_dir(data, REAL)
    folder.mkdir(parents=True)
    (folder / "daily-20260301T120000Z-v0001.sqlite3.partial").write_bytes(b"half")
    assert list_backups(data, REAL) == []


# --------------------------------------------------------------------------- verify_backup


def test_verify_backup_accepts_a_good_copy_and_rejects_damage(data: Path) -> None:
    good = data / "good.sqlite3"
    with closing(make_db(data)) as conn:
        conn.execute("CREATE TABLE bulk (b BLOB) STRICT")
        conn.execute(
            "WITH RECURSIVE c(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM c WHERE i < 300) "
            "INSERT INTO bulk SELECT randomblob(1000) FROM c"
        )
        copy_database(conn, good)
    assert verify_backup(good) is True

    truncated = data / "truncated.sqlite3"
    content = good.read_bytes()
    truncated.write_bytes(content[: len(content) // 2])
    assert verify_backup(truncated) is False

    garbage = data / "garbage.sqlite3"
    garbage.write_bytes(b"this is not a database file" * 200)
    assert verify_backup(garbage) is False

    empty = data / "empty.sqlite3"
    empty.write_bytes(b"")
    assert verify_backup(empty) is False
    assert verify_backup(data / "missing.sqlite3") is False


# --------------------------------------------------------------------------- places and names


def test_backup_folders_follow_the_explicit_identity(tmp_path: Path) -> None:
    assert backups_dir(tmp_path, REAL) == tmp_path / "backups"
    assert backups_dir(tmp_path, DEMO) == tmp_path / "demo" / "backups"
    assert database_path(tmp_path, REAL) == tmp_path / DATABASE_FILE_NAME


def test_names_carry_the_utc_timestamp_and_the_schema_version(data: Path) -> None:
    clock = FixedClock.at("2026-03-05T20:15:30Z", -3)  # local time is 17:15; the name says UTC
    plain = data / "plain.sqlite3"
    with closing(open_database(plain)) as conn:
        conn.execute("CREATE TABLE t (x INTEGER) STRICT")
        conn.execute("PRAGMA user_version = 12")
        daily_result = create_backup(
            conn, data_dir=data, identity=REAL, kind=BackupKind.DAILY, clock=clock
        )
        pre_result = create_backup(
            conn, data_dir=data, identity=REAL, kind=BackupKind.PRE_MIGRATION, clock=clock
        )
        restore_result = create_backup(
            conn,
            data_dir=data,
            identity=REAL,
            kind=BackupKind.BEFORE_RESTORE,
            clock=clock,
            database=plain,
        )
    assert daily_result.path == data / "backups" / "daily-20260305T201530Z-v0012.sqlite3"
    assert pre_result.path == data / "backups" / "pre-migration-20260305T201530Z-v0012.sqlite3"
    assert restore_result.path == data / "plain.sqlite3.before-restore-20260305T201530Z"
    assert daily_result.schema_version == 12
    assert daily_result.kind is BackupKind.DAILY
    assert all(r.verified for r in (daily_result, pre_result, restore_result))


def test_parse_backup_name_reads_every_part() -> None:
    assert parse_backup_name("daily-20260305T201530Z-v0012.sqlite3") == BackupInfo(
        path=Path("daily-20260305T201530Z-v0012.sqlite3"),
        kind=BackupKind.DAILY,
        created_utc=datetime(2026, 3, 5, 20, 15, 30, tzinfo=UTC),
        schema_version=12,
        sequence=1,
    )
    pre = parse_backup_name("pre-migration-20260305T201530Z-v0003-4.sqlite3")
    assert pre is not None
    assert (pre.kind, pre.schema_version, pre.sequence) == (BackupKind.PRE_MIGRATION, 3, 4)
    restore = parse_backup_name("db.sqlite3.before-restore-20260305T201530Z-2")
    assert restore is not None
    assert (restore.kind, restore.schema_version, restore.sequence) == (
        BackupKind.BEFORE_RESTORE,
        None,
        2,
    )
    assert restore.created_utc.tzinfo is UTC


@pytest.mark.parametrize(
    "name",
    [
        "",
        "notes.txt",
        "daily-garbage.sqlite3",
        "pre-migration-v0001-001.sqlite3",  # the name scheme of T1.3
        "daily-20260305T201530Z-v0012-1.sqlite3",  # a suffix starts at 2
        "daily-20261305T201530Z-v0012.sqlite3",  # month 13
        "daily-20260305T201530Z-v0012.sqlite3.partial",
        "weekly-20260305T201530Z-v0012.sqlite3",
        "db.sqlite3.before-restore-2026-03-05",
    ],
)
def test_parse_backup_name_rejects_other_names(name: str) -> None:
    assert parse_backup_name(name) is None


def test_two_backups_in_the_same_second_do_not_overwrite_each_other(data: Path) -> None:
    with closing(make_db(data)) as conn:
        paths = [
            create_backup(conn, data_dir=data, identity=REAL, kind=BackupKind.DAILY, clock=START)
            for _ in range(3)
        ]
        version = user_version(conn)
    base = f"daily-20260301T120000Z-v{version:04d}"
    assert [p.path.name for p in paths] == [
        f"{base}.sqlite3",
        f"{base}-2.sqlite3",
        f"{base}-3.sqlite3",
    ]
    assert len({p.path for p in paths}) == 3
    assert all(p.path.is_file() for p in paths)
    listed = list_backups(data, REAL, BackupKind.DAILY)
    assert [info.sequence for info in listed] == [3, 2, 1]  # newest first


# --------------------------------------------------------------------------- daily backup


def test_daily_backup_is_made_once_per_local_day(data: Path) -> None:
    with closing(make_db(data)) as conn:
        service = BackupService(conn, START, data_dir=data, identity=REAL)
        assert service.daily_backup_due()
        first = service.run_daily_backup()
        assert first is not None
        assert first.verified
        assert first.kind is BackupKind.DAILY
        files = names(backups_dir(data, REAL))
        assert len(files) == 1

        # however many times it runs, and from a new start of the program later the same day
        assert not service.daily_backup_due()
        assert service.run_daily_backup() is None
        later = hour(5)
        assert daily(conn, data, later) is None
        assert names(backups_dir(data, REAL)) == files

        # the next local day makes another one
        second = daily(conn, data, day(1))
        assert second is not None
        assert second.verified
        assert len(names(backups_dir(data, REAL))) == 2


def test_the_local_date_decides_not_the_utc_date(data: Path) -> None:
    with closing(make_db(data)) as conn:
        # UTC-3: 20:00Z on 5 March is 17:00 local on 5 March ...
        made = daily(conn, data, FixedClock.at("2026-03-05T20:00:00Z", -3))
        assert made is not None
        # ... and 02:30Z on 6 March is 23:30 local on 5 March: the same local day, not due
        early = FixedClock.at("2026-03-06T02:30:00Z", -3)
        assert not BackupService(conn, early, data_dir=data, identity=REAL).daily_backup_due()
        assert daily(conn, data, early) is None
        assert len(names(backups_dir(data, REAL))) == 1
        # 04:00Z on 6 March is 01:00 local on 6 March: a new local day
        assert daily(conn, data, FixedClock.at("2026-03-06T04:00:00Z", -3)) is not None
        assert len(names(backups_dir(data, REAL))) == 2


def test_a_copy_made_just_after_utc_midnight_belongs_to_the_previous_local_day(
    data: Path,
) -> None:
    with closing(make_db(data)) as conn:
        # 02:30Z on 5 March is 23:30 local on 4 March
        assert daily(conn, data, FixedClock.at("2026-03-05T02:30:00Z", -3)) is not None
        # 04:00Z on 5 March is 01:00 local on 5 March: due although the UTC date is the same
        later = FixedClock.at("2026-03-05T04:00:00Z", -3)
        assert BackupService(conn, later, data_dir=data, identity=REAL).daily_backup_due()
        assert daily(conn, data, later) is not None
        assert len(names(backups_dir(data, REAL))) == 2


def test_read_only_connection_writes_nothing(data: Path) -> None:
    with closing(make_db(data)):
        pass
    before = sorted(entry.name for entry in data.rglob("*"))
    with closing(open_database(database_path(data, REAL), read_only=True)) as conn:
        service = BackupService(conn, START, data_dir=data, identity=REAL)
        assert service.run_daily_backup() is None
        daily_backup_hook(conn, START, data_dir=data, identity=REAL, clock_suspect=False)
    assert sorted(entry.name for entry in data.rglob("*")) == before


@dataclass
class _Context:
    """The few attributes of the application context that the start-up hook reads."""

    conn: DatabaseConnection | None
    clock: Clock
    location: DataLocation
    clock_suspect: bool = False


def test_startup_callable_backs_up_the_real_database(data: Path) -> None:
    location = DataLocation(path=data, source=LocationSource.DEFAULT, writable=True)
    daily_backup_startup(_Context(None, START, location))
    assert not backups_dir(data, REAL).exists()
    with closing(make_db(data)) as conn:
        daily_backup_startup(_Context(conn, START, location))
    assert len(names(backups_dir(data, REAL))) == 1
    assert not (data / "demo").exists()


# --------------------------------------------------------------------------- pre-migration


def test_pre_migration_backup_goes_through_the_shared_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data: Path
) -> None:
    create_a = "CREATE TABLE a (x INTEGER) STRICT;\n"
    create_b = "CREATE TABLE b (x INTEGER) STRICT;\n"
    one = make_package(tmp_path, monkeypatch, {"0001_a.sql": create_a})
    two = make_package(tmp_path, monkeypatch, {"0001_a.sql": create_a, "0002_b.sql": create_b})
    path = database_path(data, REAL)
    with closing(open_and_migrate(path, data_dir=data, identity=REAL, package=one)) as conn:
        conn.execute("INSERT INTO a VALUES (42)")
    with closing(
        open_and_migrate(path, data_dir=data, identity=REAL, package=two, clock=START)
    ) as conn:
        assert user_version(conn) == 2

    assert names(backups_dir(data, REAL)) == ["pre-migration-20260301T120000Z-v0001.sqlite3"]
    info = list_backups(data, REAL, BackupKind.PRE_MIGRATION)[0]
    assert (info.kind, info.schema_version) == (BackupKind.PRE_MIGRATION, 1)
    with closing(open_database(info.path, read_only=True)) as old:
        assert integrity(old) == ["ok"]
        assert user_version(old) == 1
        assert [int(row[0]) for row in old.execute("SELECT x FROM a")] == [42]
    assert migrate_module.backup_before_migration is backup_before_migration
    assert migrate_module.DatabaseIdentity is DatabaseIdentity


def test_backup_before_migration_writes_nothing_when_disabled(data: Path) -> None:
    with closing(make_db(data)) as conn:
        assert (
            backup_before_migration(
                conn,
                data_dir=data,
                identity=REAL,
                from_version=1,
                enabled=False,
                clock=START,
            )
            is None
        )
    assert not backups_dir(data, REAL).exists()


# --------------------------------------------------------------------------- rotation


def test_ten_daily_backups_keep_the_newest_seven(data: Path) -> None:
    with closing(make_db(data)) as conn:
        for index in range(10):
            result = daily(conn, data, day(index))
            assert result is not None
            assert result.verified
        assert daily_times(data) == [day(i).utc_now() for i in range(3, 10)]
        assert all(parse_backup_name(n) for n in names(backups_dir(data, REAL)))

        # P06 changed to 2 (the floor): two remain after the next backup
        set_keep(conn, 2)
        assert daily(conn, data, day(10)) is not None
        assert daily_times(data) == [day(9).utc_now(), day(10).utc_now()]


def test_daily_backups_never_remove_pre_migration_copies(data: Path) -> None:
    with closing(make_db(data)) as conn:
        for index in range(PRE_MIGRATION_KEEP):
            result = make_copy(conn, data, BackupKind.PRE_MIGRATION, hour(index))
            assert result.verified
        pre = [n for n in names(backups_dir(data, REAL)) if n.startswith("pre-migration-")]
        assert len(pre) == 3
        for index in range(10):
            assert daily(conn, data, day(index + 1)) is not None
        after = names(backups_dir(data, REAL))
        assert [n for n in after if n.startswith("pre-migration-")] == pre
        assert len([n for n in after if n.startswith("daily-")]) == 7


def test_pre_migration_pool_keeps_the_last_three_of_five(data: Path) -> None:
    with closing(make_db(data)) as conn:
        for index in range(5):
            made = backup_before_migration(
                conn, data_dir=data, identity=REAL, from_version=1, clock=hour(index)
            )
            assert made is not None
            assert made.name == f"pre-migration-{stamp(hour(index))}-v0001.sqlite3"
        assert daily(conn, data, day(0)) is not None
    pool = list_backups(data, REAL, BackupKind.PRE_MIGRATION)
    assert sorted(info.created_utc for info in pool) == [hour(i).utc_now() for i in (2, 3, 4)]
    assert len(list_backups(data, REAL, BackupKind.DAILY)) == 1


def test_before_restore_pool_keeps_two_of_four_beside_the_database(data: Path) -> None:
    other = data / "other.sqlite3.before-restore-20260301T120000Z"
    other.write_bytes(b"belongs to another database")
    with closing(make_db(data)) as conn:
        for index in range(4):
            result = make_copy(conn, data, BackupKind.BEFORE_RESTORE, hour(index))
            assert result.verified
            expected = f"{DATABASE_FILE_NAME}.before-restore-{stamp(hour(index))}"
            assert result.path == data / expected
            rotate(data, REAL, BackupKind.BEFORE_RESTORE, BEFORE_RESTORE_KEEP, protect=result.path)
    pool = list_backups(data, REAL, BackupKind.BEFORE_RESTORE)
    assert sorted(info.created_utc for info in pool) == [hour(2).utc_now(), hour(3).utc_now()]
    assert other.exists()  # another database's safety copy is not ours to delete
    assert database_path(data, REAL).exists()
    assert not backups_dir(data, REAL).exists()


def test_rotation_with_an_explicit_database_file(data: Path) -> None:
    plain = data / "special.sqlite3"
    with closing(open_database(plain)) as conn:
        conn.execute("CREATE TABLE t (x INTEGER) STRICT")
        for index in range(4):
            create_backup(
                conn,
                data_dir=data,
                identity=REAL,
                kind=BackupKind.BEFORE_RESTORE,
                clock=hour(index),
                database=plain,
            )
    result = rotate(data, REAL, BackupKind.BEFORE_RESTORE, 2, database=plain)
    assert len(result.deleted) == 2
    assert len(list_backups(data, REAL, BackupKind.BEFORE_RESTORE, database=plain)) == 2


def _four_daily(data: Path, conn: DatabaseConnection) -> list[BackupInfo]:
    for index in range(4):
        result = create_backup(
            conn, data_dir=data, identity=REAL, kind=BackupKind.DAILY, clock=day(index)
        )
        assert result.verified
    return list_backups(data, REAL, BackupKind.DAILY)  # newest first


def test_keep_is_clamped_to_the_floor(data: Path) -> None:
    with closing(make_db(data)) as conn:
        _four_daily(data, conn)
    for requested in (0, 1):
        result = rotate(data, REAL, BackupKind.DAILY, requested)
        assert result.keep == MIN_KEEP == 2
        assert result.clamped
        assert len(list_backups(data, REAL, BackupKind.DAILY)) == 2
    assert not rotate(data, REAL, BackupKind.DAILY, 2).clamped


def test_the_protected_copy_is_never_deleted(data: Path) -> None:
    with closing(make_db(data)) as conn:
        newest_first = _four_daily(data, conn)
    oldest = newest_first[-1]
    result = rotate(data, REAL, BackupKind.DAILY, 2, protect=oldest.path)
    assert result.deleted == (newest_first[2].path,)
    assert oldest.path.exists()
    assert newest_first[0].path.exists()
    assert newest_first[1].path.exists()


def test_the_only_remaining_copy_is_never_deleted(data: Path) -> None:
    with closing(make_db(data)) as conn:
        only = make_copy(conn, data, BackupKind.DAILY, START)
    assert rotate(data, REAL, BackupKind.DAILY, 0).deleted == ()
    assert only.path.exists()


def test_files_that_are_not_recognised_copies_survive_rotation(data: Path) -> None:
    with closing(make_db(data)) as conn:
        _four_daily(data, conn)
        create_backup(
            conn, data_dir=data, identity=REAL, kind=BackupKind.PRE_MIGRATION, clock=START
        )
    folder = backups_dir(data, REAL)
    keepers = [
        "notes.txt",
        "daily-garbage.sqlite3",
        "pre-migration-v0001-001.sqlite3",
        "daily-20250101T000000Z-v0001.sqlite3.partial",
        "daily-20260301T000000Z-v0001-1.sqlite3",
    ]
    for name in keepers:
        (folder / name).write_bytes(b"x")
    (folder / "daily-20240101T000000Z-v0001.sqlite3").mkdir()  # a folder, not a regular file

    result = rotate(data, REAL, BackupKind.DAILY, 2)
    assert len(result.deleted) == 2
    after = names(folder)
    for name in keepers:
        assert name in after
    assert "daily-20240101T000000Z-v0001.sqlite3" in after
    assert len([n for n in after if n.startswith("pre-migration-2026")]) == 1
    assert len(list_backups(data, REAL, BackupKind.DAILY)) == 2


def test_a_deletion_error_is_reported_not_raised(
    data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with closing(make_db(data)) as conn:
        newest_first = _four_daily(data, conn)
    locked = newest_first[-1].path
    original = Path.unlink

    def flaky(self: Path, missing_ok: bool = False) -> None:
        if self == locked:
            msg = "denied"
            raise PermissionError(msg)
        original(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", flaky)
    result = rotate(data, REAL, BackupKind.DAILY, 2)
    assert result.failed == (locked,)
    assert result.deleted == (newest_first[2].path,)
    assert locked.exists()


# --------------------------------------------------------------------------- failed checks


def test_a_copy_that_fails_the_check_is_removed_and_reported(data: Path) -> None:
    with closing(make_db(data)) as conn:
        result = create_backup(
            conn,
            data_dir=data,
            identity=REAL,
            kind=BackupKind.DAILY,
            clock=START,
            quick_check=lambda _path: False,
        )
    assert not result.verified
    assert not result.path.exists()
    assert names(backups_dir(data, REAL)) == []


def test_a_failed_copy_is_not_counted_and_deletes_nothing(data: Path) -> None:
    with closing(make_db(data)) as conn:
        for index in range(7):
            assert daily(conn, data, day(index)) is not None
        before = names(backups_dir(data, REAL))
        assert len(before) == 7

        failed = daily(conn, data, day(7), ok=False)
        assert failed is not None
        assert not failed.verified
        assert not failed.path.exists()
        assert names(backups_dir(data, REAL)) == before  # the pool is intact

        # the failed copy did not count as the backup of that day: the next try is made
        again = daily(conn, data, day(7))
        assert again is not None
        assert again.verified
    assert len(names(backups_dir(data, REAL))) == 7
    assert day(0).utc_now() not in daily_times(data)


def test_the_newest_verified_copy_survives_a_failing_newer_one(data: Path) -> None:
    with closing(make_db(data)) as conn:
        set_keep(conn, 2)
        for index in range(3):
            assert daily(conn, data, day(index)) is not None
        before = names(backups_dir(data, REAL))
        assert len(before) == 2
        newest = list_backups(data, REAL, BackupKind.DAILY)[0].path

        failed = daily(conn, data, day(3), ok=False)
        assert failed is not None
        assert not failed.verified
    assert names(backups_dir(data, REAL)) == before
    assert verify_backup(newest)


def test_no_rotation_when_the_clock_is_suspect(data: Path) -> None:
    with closing(make_db(data)) as conn:
        set_keep(conn, 2)
        for index in range(4):
            daily_backup_hook(conn, day(index), data_dir=data, identity=REAL, clock_suspect=True)
        assert len(daily_times(data)) == 4  # the backups are made, nothing is deleted
        assert daily(conn, data, day(4), rotate_pool=False) is not None
        assert len(daily_times(data)) == 5

        daily_backup_hook(conn, day(5), data_dir=data, identity=REAL, clock_suspect=False)
        assert daily_times(data) == [day(4).utc_now(), day(5).utc_now()]


# --------------------------------------------------------------------------- demo and location


def test_demo_backups_appear_only_under_demo_backups(data: Path) -> None:
    with closing(make_db(data, identity=DEMO)) as conn:
        made = daily(conn, data, START, identity=DEMO)
        assert made is not None
        assert made.path.parent == data / "demo" / "backups"
        pre = backup_before_migration(
            conn, data_dir=data, identity=DEMO, from_version=1, clock=START
        )
        assert pre is not None
        assert pre.parent == data / "demo" / "backups"
        restore = create_backup(
            conn, data_dir=data, identity=DEMO, kind=BackupKind.BEFORE_RESTORE, clock=START
        )
        assert restore.path.parent == data / "demo"
    assert not (data / "backups").exists()
    assert list_backups(data, REAL) == []
    assert len(list_backups(data, DEMO)) == 3
    assert sorted(entry.name for entry in data.iterdir()) == ["demo"]


def test_real_and_demo_pools_are_separate(data: Path) -> None:
    with closing(make_db(data)) as real, closing(make_db(data, identity=DEMO)) as demo:
        assert daily(real, data, START) is not None
        assert daily(demo, data, START, identity=DEMO) is not None
        assert len(names(backups_dir(data, REAL))) == 1
        assert len(names(backups_dir(data, DEMO))) == 1


def test_nothing_is_written_outside_the_data_folder(tmp_path: Path, data: Path) -> None:
    (tmp_path / "outside.txt").write_text("keep", encoding="utf-8")

    def outside() -> list[str]:
        return sorted(
            str(entry.relative_to(tmp_path))
            for entry in tmp_path.rglob("*")
            if entry != data and data not in entry.parents
        )

    before = outside()
    with closing(make_db(data)) as conn, closing(make_db(data, identity=DEMO)) as demo:
        for index in range(9):
            daily(conn, data, day(index))
        daily(demo, data, START, identity=DEMO)
        backup_before_migration(conn, data_dir=data, identity=REAL, from_version=1, clock=START)
        for index in range(4):
            made = make_copy(conn, data, BackupKind.BEFORE_RESTORE, hour(index))
            rotate(data, REAL, BackupKind.BEFORE_RESTORE, 2, protect=made.path)
    assert outside() == before
    assert (data / "backups").is_dir()


# --------------------------------------------------------------------------- listing and logging


def test_service_lists_backups_newest_first(data: Path) -> None:
    with closing(make_db(data)) as conn:
        service = BackupService(conn, START, data_dir=data, identity=REAL)
        create_backup(conn, data_dir=data, identity=REAL, kind=BackupKind.DAILY, clock=hour(0))
        create_backup(
            conn, data_dir=data, identity=REAL, kind=BackupKind.PRE_MIGRATION, clock=hour(1)
        )
        create_backup(
            conn, data_dir=data, identity=REAL, kind=BackupKind.BEFORE_RESTORE, clock=hour(2)
        )
        assert [info.kind for info in service.list_backups()] == [
            BackupKind.BEFORE_RESTORE,
            BackupKind.PRE_MIGRATION,
            BackupKind.DAILY,
        ]
        only = service.list_backups(BackupKind.DAILY)
        assert [info.kind for info in only] == [BackupKind.DAILY]


def test_log_lines_hold_event_codes_and_counts_only(tmp_path: Path, data: Path) -> None:
    with configure_logging(tmp_path / "unused", read_only=True) as handle:
        with closing(make_db(data)) as conn:
            set_keep(conn, 2)
            for index in range(3):
                daily(conn, data, day(index))
            daily(conn, data, day(3), ok=False)
        lines = handle.memory_lines()
    assert any(line.endswith(" BACKUP.DAILY_DONE") for line in lines)
    assert any(line.endswith(" BACKUP.ROTATED count=1") for line in lines)
    assert any(line.endswith(" BACKUP.DAILY_FAILED") for line in lines)
    assert not any("daily-" in line or str(data) in line for line in lines)
