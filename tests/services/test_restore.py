# SPDX-License-Identifier: GPL-3.0-or-later
"""The restore service and the tmp clean-up (PLAN.md D04, D25, K05, task T7.3).

Everything happens under ``tmp_path``; the OS temp folder is redirected to a watched folder there.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.services import restore as restore_module
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.services.restore import (
    TMP_DIR_NAME,
    RestoreService,
    clean_tmp,
    tmp_cleanup_startup,
)
from cbrn_dashboard.storage.app_meta import initialise
from cbrn_dashboard.storage.backup import (
    BackupKind,
    DatabaseIdentity,
    database_path,
    list_backups,
)
from cbrn_dashboard.storage.crypto_backup import (
    ScryptParams,
    database_snapshot_bytes,
    write_backup,
)
from cbrn_dashboard.storage.db import DatabaseConnection, open_connections, open_database
from cbrn_dashboard.storage.migrate import load_migrations, migrate, open_and_migrate

#: Cheap scrypt parameters; the reader's allow-list is widened by KEYWORD, never by patching.
CHEAP = ScryptParams(n=2**12, r=8, p=1)
ALLOWED = frozenset({CHEAP})
PASSPHRASE = "Zq7-distinctive-passphrase-\u00e9"
_ROWS_SQL = "SELECT key, value_json FROM setting ORDER BY key"


# --------------------------------------------------------------------------- helpers


@dataclass
class Env:
    """A data folder with an open, migrated live database and a service for it."""

    root: Path
    data: Path
    clock: FixedClock
    identity: DatabaseIdentity
    live: DatabaseConnection
    service: RestoreService

    @property
    def live_path(self) -> Path:
        return database_path(self.data, self.identity)

    @property
    def tmp_dir(self) -> Path:
        return self.data / TMP_DIR_NAME

    @property
    def os_temp(self) -> Path:
        return self.root / "ostemp"

    def restore(self, backup: Path, passphrase: str = PASSPHRASE) -> restore_module.RestoreResult:
        return self.service.restore(self.live, backup, passphrase, allowed_params=ALLOWED)


def _open_live(data: Path, identity: DatabaseIdentity) -> DatabaseConnection:
    path = database_path(data, identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = open_and_migrate(path, data_dir=data, identity=identity, backup=False)
    initialise(conn, is_demo=identity is DatabaseIdentity.DEMO, created_with="test")
    return conn


@pytest.fixture
def make_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[[DatabaseIdentity], Env]]:
    """A factory of environments; the OS temp folder is a watched folder under ``tmp_path``."""
    os_temp = tmp_path / "ostemp"
    os_temp.mkdir()
    for name in ("TMP", "TEMP", "TMPDIR"):
        monkeypatch.setenv(name, str(os_temp))
    monkeypatch.setattr(tempfile, "tempdir", None)
    opened: list[DatabaseConnection] = []

    def build(identity: DatabaseIdentity) -> Env:
        data = tmp_path / "data"
        data.mkdir(exist_ok=True)
        clock = FixedClock.at("2026-03-05T12:00:00Z")
        live = _open_live(data, identity)
        opened.append(live)
        service = RestoreService(data_dir=data, identity=identity, clock=clock)
        return Env(tmp_path, data, clock, identity, live, service)

    try:
        yield build
    finally:
        for conn in opened:
            conn.close()


@pytest.fixture
def env(make_env: Callable[[DatabaseIdentity], Env]) -> Env:
    return make_env(DatabaseIdentity.REAL)


def _put(conn: sqlite3.Connection, keys: tuple[str, ...]) -> None:
    for key in keys:
        conn.execute("INSERT INTO setting (key, value_json) VALUES (?, ?)", (key, '{"n":1}'))


def _rows(conn: sqlite3.Connection) -> list[tuple[object, ...]]:
    return [tuple(row) for row in conn.execute(_ROWS_SQL)]


def _content(conn: sqlite3.Connection) -> dict[str, list[tuple[object, ...]]]:
    """Schema and every row of every table, in a comparable form."""
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]
    content: dict[str, list[tuple[object, ...]]] = {
        name: sorted((tuple(row) for row in conn.execute(f'SELECT * FROM "{name}"')), key=repr)
        for name in tables
    }
    content["#schema"] = sorted(
        (tuple(row) for row in conn.execute("SELECT type, name, sql FROM sqlite_master")),
        key=repr,
    )
    return content


def _tree(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` with its bytes."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _leftovers(data: Path) -> list[Path]:
    folder = data / TMP_DIR_NAME
    return sorted(folder.rglob("*")) if folder.exists() else []


def _encrypt(conn: DatabaseConnection, dest: Path, passphrase: str = PASSPHRASE) -> Path:
    snapshot, version = database_snapshot_bytes(conn)
    write_backup(
        dest,
        snapshot,
        passphrase,
        app_version="test",
        schema_version=version,
        params=CHEAP,
    )
    return dest


def _make_backup(
    root: Path,
    name: str,
    *,
    keys: tuple[str, ...] = ("a.one", "a.two"),
    is_demo: bool = False,
    older: bool = False,
    user_version: int | None = None,
    app_meta: bool = True,
) -> Path:
    """Build a separate database, put ``keys`` in it and write its encrypted backup."""
    folder = root / "src" / name
    folder.mkdir(parents=True)
    conn = open_database(folder / "source.sqlite3")
    try:
        if app_meta:
            migrate(conn, migrations=load_migrations()[:-1] if older else None)
            initialise(conn, is_demo=is_demo, created_with="test")
            _put(conn, keys)
            if user_version is not None:
                conn.execute(f"PRAGMA user_version = {user_version}")
        else:
            conn.execute("CREATE TABLE plain (x INTEGER)")
        return _encrypt(conn, root / "out" / f"{name}.cbrnbak")
    finally:
        conn.close()


def _newest() -> int:
    return load_migrations()[-1].number


def _expect_refused(
    env: Env,
    backup: Path,
    code: str,
    passphrase: str = PASSPHRASE,
    *,
    read_live: bool = True,
) -> None:
    """The restore fails with ``code``; nothing at all changed on disk and ``tmp`` is empty.

    ``read_live`` is false when reading the live database from the test would itself disturb the
    situation (a fake journal file beside it).
    """
    before = _tree(env.root)
    content = _content(env.live) if read_live else {}
    with pytest.raises(ServiceError) as caught:
        env.restore(backup, passphrase)
    assert caught.value.code == code
    assert _tree(env.root) == before  # byte-identical database, no safety copy, nothing new
    if read_live:
        assert _content(env.live) == content
    assert _leftovers(env.data) == []
    assert list(env.os_temp.iterdir()) == []
    assert not env.live.in_transaction


# --------------------------------------------------------------------------- the round trip


def test_a_restore_puts_the_backed_up_rows_into_the_live_connection(env: Env) -> None:
    _put(env.live, ("a.one", "a.two"))
    backup = _encrypt(env.live, env.root / "out" / "live.cbrnbak")
    expected = _rows(env.live)
    env.live.execute("DELETE FROM setting WHERE key LIKE 'a.%'")
    _put(env.live, ("b.one",))
    changed = _rows(env.live)
    assert changed != expected
    before = _tree(env.root)

    result = env.restore(backup)

    assert _rows(env.live) == expected  # the same handle sees the restored rows
    assert result.migrated_from is None
    assert result.restored_schema_version == _newest()
    assert not env.live.in_transaction
    assert env.live.execute("PRAGMA integrity_check").fetchall()[0][0] == "ok"
    assert env.live.execute("PRAGMA user_version").fetchone()[0] == _newest()

    safety = result.safety_copy  # beside the database, holds the pre-restore data
    assert safety.parent == env.live_path.parent
    assert safety.name.startswith(env.live_path.name + ".before-restore-")
    copy = open_database(safety, read_only=True)
    try:
        assert _rows(copy) == changed
        assert copy.execute("PRAGMA quick_check").fetchall()[0][0] == "ok"
    finally:
        copy.close()

    log = env.live.execute(
        "SELECT entity, after_json FROM change_log WHERE action = 'restore'"
    ).fetchall()
    assert len(log) == 1
    assert log[0]["entity"] == "database"
    logged = json.loads(log[0]["after_json"])
    assert logged["safety_copy"] == safety.name  # the file name only, no path
    assert logged["schema_version"] == _newest()
    assert logged["migrated_from"] is None

    after = _tree(env.root)
    assert set(after) - set(before) == {safety.relative_to(env.root).as_posix()}
    assert _leftovers(env.data) == []
    assert list(env.os_temp.iterdir()) == []


def test_a_restore_is_a_copy_into_the_same_database_file(env: Env) -> None:
    _put(env.live, ("a.one",))
    backup = _encrypt(env.live, env.root / "out" / "live.cbrnbak")
    env.live.execute("DELETE FROM setting WHERE key = 'a.one'")
    before = env.live_path.stat()
    env.restore(backup)
    after = env.live_path.stat()
    assert env.live_path.exists()
    assert open_connections(env.live_path) == 1
    assert after.st_ino == before.st_ino or after.st_ino == 0  # same file, not swapped (Windows: 0)


def test_an_older_backup_is_migrated_without_a_pre_migration_backup(env: Env) -> None:
    backup = _make_backup(env.root, "older", older=True)
    env.live.execute("DELETE FROM setting WHERE key LIKE 'a.%'")
    _put(env.live, ("b.one",))

    result = env.restore(backup)

    assert result.migrated_from == _newest() - 1
    assert result.restored_schema_version == _newest()
    assert env.live.execute("PRAGMA user_version").fetchone()[0] == _newest()
    assert [row[0] for row in _rows(env.live) if str(row[0]).startswith("a.")] == [
        "a.one",
        "a.two",
    ]
    assert not [p for p in env.root.rglob("*") if p.name.startswith("pre-migration-")]
    assert not (env.data / "backups").exists() or not list((env.data / "backups").iterdir())
    assert _leftovers(env.data) == []
    log = env.live.execute("SELECT after_json FROM change_log WHERE action = 'restore'").fetchall()
    assert len(log) == 1
    assert json.loads(log[0]["after_json"])["migrated_from"] == _newest() - 1


# --------------------------------------------------------------------------- refusals


def test_a_wrong_passphrase_changes_nothing(env: Env) -> None:
    backup = _make_backup(env.root, "wrong")
    _expect_refused(env, backup, "WRONG_PASSPHRASE", passphrase=PASSPHRASE + "x")


def test_a_corrupt_file_changes_nothing(env: Env) -> None:
    backup = _make_backup(env.root, "corrupt")
    data = bytearray(backup.read_bytes())
    data[len(data) // 2] ^= 0xFF
    backup.write_bytes(bytes(data))
    _expect_refused(env, backup, "CORRUPT_BACKUP")


def test_a_missing_file_changes_nothing(env: Env) -> None:
    _expect_refused(env, env.root / "out" / "missing.cbrnbak", "BACKUP_UNREADABLE")


def test_a_failed_integrity_check_changes_nothing(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup = _make_backup(env.root, "integrity")
    monkeypatch.setattr(restore_module, "_integrity_ok", lambda conn: False)
    _expect_refused(env, backup, "INTEGRITY_FAILED")


def test_a_restored_database_newer_than_the_program_is_refused(env: Env) -> None:
    backup = _make_backup(env.root, "newer", user_version=_newest() + 5)
    _expect_refused(env, backup, "BACKUP_TOO_NEW")


def test_a_demo_backup_is_not_restored_into_a_real_database(env: Env) -> None:
    backup = _make_backup(env.root, "demo", is_demo=True)
    _expect_refused(env, backup, "DEMO_MISMATCH")


def test_a_real_backup_is_not_restored_into_a_demo_database(
    make_env: Callable[[DatabaseIdentity], Env],
) -> None:
    demo = make_env(DatabaseIdentity.DEMO)
    backup = _make_backup(demo.root, "real", is_demo=False)
    _expect_refused(demo, backup, "DEMO_MISMATCH")


def test_a_database_without_app_meta_is_refused(env: Env) -> None:
    backup = _make_backup(env.root, "plain", app_meta=False)
    _expect_refused(env, backup, "NOT_AN_APPLICATION_DATABASE")


def test_a_read_only_connection_is_refused(env: Env) -> None:
    backup = _make_backup(env.root, "readonly")
    reader = open_database(env.live_path, read_only=True)
    try:
        before = _tree(env.root)
        with pytest.raises(ServiceError) as caught:
            env.service.restore(reader, backup, PASSPHRASE, allowed_params=ALLOWED)
        assert caught.value.code == "READ_ONLY"
        assert _tree(env.root) == before
    finally:
        reader.close()
    assert _leftovers(env.data) == []


# --------------------------------------------------------------------------- quiescence


def test_a_leftover_journal_file_is_refused(env: Env) -> None:
    backup = _make_backup(env.root, "journal")
    journal = env.live_path.with_name(env.live_path.name + "-journal")
    journal.write_bytes(b"not a real journal, but not empty either" * 8)
    try:
        _expect_refused(env, backup, "JOURNAL_PRESENT", read_live=False)
    finally:
        journal.unlink(missing_ok=True)


def test_a_second_connection_on_the_live_file_is_refused(env: Env) -> None:
    backup = _make_backup(env.root, "second")
    other = open_database(env.live_path)
    try:
        assert open_connections(env.live_path) == 2
        _expect_refused(env, backup, "OTHER_CONNECTIONS_OPEN")
    finally:
        other.close()


def test_a_read_only_second_connection_is_refused_too(env: Env) -> None:
    backup = _make_backup(env.root, "second-ro")
    other = open_database(env.live_path, read_only=True)
    try:
        _expect_refused(env, backup, "OTHER_CONNECTIONS_OPEN")
    finally:
        other.close()


def test_an_open_transaction_is_refused(env: Env) -> None:
    backup = _make_backup(env.root, "transaction")
    env.live.execute("BEGIN IMMEDIATE")
    try:
        before = _tree(env.root)
        with pytest.raises(ServiceError) as caught:
            env.restore(backup)
        assert caught.value.code == "TRANSACTION_OPEN"
        assert _tree(env.root) == before
        assert env.live.in_transaction  # the caller's transaction is left alone
    finally:
        env.live.execute("ROLLBACK")
    assert _leftovers(env.data) == []


# --------------------------------------------------------------------------- the copy step


def test_a_failure_during_the_copy_puts_the_safety_copy_back(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    _put(env.live, ("a.one",))
    backup = _encrypt(env.live, env.root / "out" / "live.cbrnbak")
    env.live.execute("DELETE FROM setting WHERE key LIKE 'a.%'")
    _put(env.live, ("b.one", "b.two"))
    content = _content(env.live)

    def damage_then_fail(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
        target.execute("DELETE FROM setting")  # a half-done copy
        msg = "injected failure"
        raise sqlite3.OperationalError(msg)

    monkeypatch.setattr(restore_module, "_copy_into", damage_then_fail)

    with pytest.raises(ServiceError) as caught:
        env.restore(backup)

    assert caught.value.code == "RESTORE_COPY_FAILED"
    assert _content(env.live) == content  # the pre-restore content is back
    assert env.live.execute("PRAGMA integrity_check").fetchall()[0][0] == "ok"
    assert not env.live.in_transaction
    assert len(list_backups(env.data, env.identity, BackupKind.BEFORE_RESTORE)) == 1
    assert _leftovers(env.data) == []
    assert list(env.os_temp.iterdir()) == []


def test_a_failure_when_logging_the_restore_puts_the_safety_copy_back(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    _put(env.live, ("a.one",))
    backup = _encrypt(env.live, env.root / "out" / "live.cbrnbak")
    env.live.execute("DELETE FROM setting WHERE key LIKE 'a.%'")
    content = _content(env.live)

    def refuse(*args: Any, **kwargs: Any) -> None:
        msg = "injected failure"
        raise sqlite3.OperationalError(msg)

    monkeypatch.setattr(restore_module.repository, "log_event", refuse)
    with pytest.raises(ServiceError) as caught:
        env.restore(backup)
    assert caught.value.code == "RESTORE_COPY_FAILED"
    assert _content(env.live) == content


def test_a_failed_safety_copy_writes_nothing_to_the_live_database(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup = _make_backup(env.root, "safety")

    def failing(*args: Any, **kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(restore_module, "create_backup", failing)
    _expect_refused(env, backup, "SAFETY_COPY_FAILED")


def test_the_before_restore_pool_keeps_the_newest_two(env: Env) -> None:
    backup = _make_backup(env.root, "rotate")
    results = [env.restore(backup) for _ in range(3)]
    kept = {info.path for info in list_backups(env.data, env.identity, BackupKind.BEFORE_RESTORE)}
    assert kept == {results[1].safety_copy, results[2].safety_copy}
    assert not results[0].safety_copy.exists()
    assert all(path.exists() for path in kept)


@pytest.mark.parametrize("how", ["safety copy unreadable", "put-back fails its integrity check"])
def test_a_failed_put_back_has_its_own_code_and_the_good_safety_copy_survives(
    env: Env, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    _put(env.live, ("a.one",))
    backup = _encrypt(env.live, env.root / "out" / "live.cbrnbak")
    env.live.execute("DELETE FROM setting WHERE key LIKE 'a.%'")
    _put(env.live, ("b.one", "b.two"))
    original = _rows(env.live)
    broken = {"on": False}

    def damage_then_fail(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
        broken["on"] = True  # from here on the live database fails its own integrity check
        target.execute("DELETE FROM setting")  # a half-done copy
        msg = "injected failure"
        raise sqlite3.OperationalError(msg)

    real_integrity = restore_module._integrity_ok
    real_open = restore_module.open_database

    def integrity(conn: sqlite3.Connection) -> bool:
        if broken["on"] and conn is env.live:
            return False
        return real_integrity(conn)

    def refuse_read_only(path: Path, *, read_only: bool = False) -> DatabaseConnection:
        if read_only:
            msg = "injected failure"
            raise sqlite3.OperationalError(msg)
        return real_open(path, read_only=read_only)

    monkeypatch.setattr(restore_module, "_copy_into", damage_then_fail)
    monkeypatch.setattr(restore_module, "_integrity_ok", integrity)
    if how == "safety copy unreadable":
        monkeypatch.setattr(restore_module, "open_database", refuse_read_only)

    with pytest.raises(restore_module.RollbackFailedError) as caught:
        env.restore(backup)

    (good,) = list_backups(env.data, env.identity, BackupKind.BEFORE_RESTORE)
    assert caught.value.code == "RESTORE_ROLLBACK_FAILED"
    assert caught.value.code != "RESTORE_COPY_FAILED"
    assert caught.value.safety_copy_name == good.path.name  # the name only, never a path
    assert "\\" not in caught.value.safety_copy_name
    assert "/" not in caught.value.safety_copy_name

    for _ in range(2):  # two more attempts on the damaged database
        with pytest.raises(restore_module.RollbackFailedError):
            env.restore(backup)

    assert good.path.exists()  # the pool would have kept only 2: the good copy must not be rotated
    assert len(list_backups(env.data, env.identity, BackupKind.BEFORE_RESTORE)) == 3
    copy = open_database(good.path, read_only=True)
    try:
        assert _rows(copy) == original
    finally:
        copy.close()
    assert _leftovers(env.data) == []
    assert list(env.os_temp.iterdir()) == []


def test_a_suspect_clock_skips_the_rotation_of_the_before_restore_pool(env: Env) -> None:
    backup = _make_backup(env.root, "suspect")
    service = RestoreService(
        data_dir=env.data, identity=env.identity, clock=env.clock, clock_suspect=lambda: True
    )
    for _ in range(3):
        service.restore(env.live, backup, PASSPHRASE, allowed_params=ALLOWED)
    assert len(list_backups(env.data, env.identity, BackupKind.BEFORE_RESTORE)) == 3


def test_a_sqlite_error_while_reading_the_live_demo_flag_is_a_coded_error(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup = _make_backup(env.root, "unreadable")
    real = restore_module.read_is_demo

    def failing_on_live(conn: sqlite3.Connection) -> bool:
        if conn is env.live:
            msg = "injected failure"
            raise sqlite3.OperationalError(msg)
        return real(conn)

    monkeypatch.setattr(restore_module, "read_is_demo", failing_on_live)
    _expect_refused(env, backup, "LIVE_UNREADABLE")


# --------------------------------------------------------------------------- the temporary file


def test_the_decrypted_file_exists_only_in_the_tmp_folder_and_is_always_removed(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup = _make_backup(env.root, "spy")
    created: list[Path] = []
    real = tempfile.mkstemp

    def spy(*args: Any, **kwargs: Any) -> tuple[int, str]:
        handle, name = real(*args, **kwargs)
        created.append(Path(name))
        return handle, name

    monkeypatch.setattr(tempfile, "mkstemp", spy)
    before = _tree(env.root)

    result = env.restore(backup)  # success
    monkeypatch.setattr(restore_module, "_integrity_ok", lambda conn: False)
    with pytest.raises(ServiceError):  # failure after the file was written
        env.restore(backup)

    assert len(created) == 2
    for path in created:
        assert path.parent == env.tmp_dir
        assert path.name.startswith("restore-")
        assert path.suffix == ".sqlite3"
        assert not path.exists()
    assert _leftovers(env.data) == []
    assert list(env.os_temp.iterdir()) == []
    # No plaintext copy anywhere: the only new file is the safety copy of the successful restore.
    new_files = set(_tree(env.root)) - set(before)
    assert new_files == {result.safety_copy.relative_to(env.root).as_posix()}


def test_a_failed_migration_removes_the_temporary_file(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup = _make_backup(env.root, "migfail", older=True)

    def failing(*args: Any, **kwargs: Any) -> None:
        msg = "injected failure"
        raise sqlite3.OperationalError(msg)

    monkeypatch.setattr(restore_module, "migrate", failing)
    _expect_refused(env, backup, "MIGRATION_FAILED")


def test_only_the_decrypted_connection_keeps_sqlite_temp_data_in_memory(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup = _make_backup(env.root, "tempstore")
    default = env.live.execute("PRAGMA temp_store").fetchone()[0]
    seen: dict[str, object] = {}
    real = restore_module._integrity_ok

    def spy(conn: sqlite3.Connection) -> bool:
        seen.setdefault(
            "live" if conn is env.live else "temporary",
            conn.execute("PRAGMA temp_store").fetchone()[0],
        )
        return real(conn)

    monkeypatch.setattr(restore_module, "_integrity_ok", spy)
    env.restore(backup)
    assert seen["temporary"] == 2  # MEMORY: no plaintext spill into the OS temp folder
    assert seen["live"] == default != 2


def test_a_tmp_folder_that_is_a_link_is_refused(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    backup = _make_backup(env.root, "linked")
    monkeypatch.setattr(restore_module, "_is_link", lambda path: path.name == TMP_DIR_NAME)
    _expect_refused(env, backup, "TEMP_FILE_FAILED")
    assert not env.tmp_dir.exists()  # nothing was created through the link


# --------------------------------------------------------------------------- clean-up


def test_clean_tmp_removes_files_and_folders_and_keeps_the_folder(tmp_path: Path) -> None:
    folder = tmp_path / TMP_DIR_NAME
    (folder / "sub" / "deeper").mkdir(parents=True)
    (folder / "restore-abc.sqlite3").write_bytes(b"plaintext")
    (folder / "sub" / "deeper" / "x.bin").write_bytes(b"x")
    (folder / "restore-abc.sqlite3-journal").write_bytes(b"j")

    assert clean_tmp(tmp_path) == 3
    assert folder.is_dir()
    assert list(folder.iterdir()) == []


def test_clean_tmp_tolerates_a_missing_folder(tmp_path: Path) -> None:
    assert clean_tmp(tmp_path) == 0
    assert not (tmp_path / TMP_DIR_NAME).exists()


def test_clean_tmp_does_not_follow_a_link_out_of_the_folder(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    folder = tmp_path / TMP_DIR_NAME
    folder.mkdir()
    try:
        (folder / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here")

    assert clean_tmp(tmp_path) == 1
    assert list(folder.iterdir()) == []
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_clean_tmp_carries_on_after_an_entry_that_cannot_be_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / TMP_DIR_NAME
    folder.mkdir()
    for name in ("a.bin", "b.bin", "c.bin"):
        (folder / name).write_bytes(b"x")
    real = restore_module._remove_entry

    def flaky(path: Path) -> None:
        if path.name == "b.bin":
            raise PermissionError
        real(path)

    monkeypatch.setattr(restore_module, "_remove_entry", flaky)
    assert clean_tmp(tmp_path) == 2
    assert [p.name for p in folder.iterdir()] == ["b.bin"]


@dataclass
class _Location:
    path: Path


@dataclass
class _Context:
    location: _Location


def test_the_startup_hook_cleans_the_data_folder_of_its_context(tmp_path: Path) -> None:
    folder = tmp_path / TMP_DIR_NAME
    folder.mkdir()
    (folder / "restore-left.sqlite3").write_bytes(b"plaintext")
    tmp_cleanup_startup(_Context(_Location(tmp_path)))
    assert list(folder.iterdir()) == []


def test_the_startup_hook_is_harmless_without_a_tmp_folder(tmp_path: Path) -> None:
    tmp_cleanup_startup(_Context(_Location(tmp_path)))
    assert list(tmp_path.iterdir()) == []
