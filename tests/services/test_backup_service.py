# SPDX-License-Identifier: GPL-3.0-or-later
"""The encrypted-backup use case of ``BackupService`` (PLAN.md D04, P05, P09, K06, task T7.2)."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from cbrn_dashboard import __version__
from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.services import backup as backup_service
from cbrn_dashboard.services.backup import (
    BACKUP_VERIFY_FAILED,
    BACKUP_WRITE_FAILED,
    LAST_ENCRYPTED_KEY,
    MIN_DISTINCT_CHARACTERS,
    PASSPHRASE_BLOCKLISTED,
    PASSPHRASE_MISMATCH,
    PASSPHRASE_TOO_FEW_DISTINCT,
    PASSPHRASE_TOO_SHORT,
    BackupService,
    check_passphrase,
)
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.storage.backup import DatabaseIdentity
from cbrn_dashboard.storage.crypto_backup import (
    FILE_EXTENSION,
    DecryptedBackup,
    ScryptParams,
    WrongPassphraseError,
    read_backup,
)
from cbrn_dashboard.storage.db import DatabaseConnection, open_database

#: Cheap scrypt parameters for the tests; the reader's allow-list is widened by KEYWORD
#: (``allowed_params``), never by patching ``ALLOWED_PARAMS``.
CHEAP = ScryptParams(n=2**12, r=8, p=1)
CHEAP_ALLOWED = frozenset({CHEAP})
PASSPHRASE = "Zq7-distinctive-passphrase-\u00e9"
_ROWS_SQL = "SELECT key, value_json FROM setting ORDER BY key"
_SETTING_LOG_SQL = "SELECT operator, entity FROM change_log WHERE entity = 'setting'"


@pytest.fixture
def out_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A folder OUTSIDE the data folder (``tmp_path``) for the backup files."""
    return tmp_path_factory.mktemp("out")


@pytest.fixture
def service(db: DatabaseConnection, clock: FixedClock, tmp_path: Path) -> BackupService:
    return BackupService(db, clock, data_dir=tmp_path, identity=DatabaseIdentity.REAL)


def _add_rows(conn: DatabaseConnection, count: int = 12) -> None:
    for index in range(count):
        conn.execute(
            "INSERT INTO setting (key, value_json) VALUES (?, ?)",
            (f"test.row{index:02d}", f'{{"n":{index}}}'),
        )


def _set_config(conn: DatabaseConnection, name: str, value: int) -> None:
    conn.execute(
        "INSERT INTO setting (key, value_json) VALUES (?, ?)", (f"config.{name}", str(value))
    )


def _tree(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` with its bytes."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _rows_of(restored: DecryptedBackup, scratch: Path) -> list[tuple[object, ...]]:
    copy = scratch / "restored.sqlite3"
    copy.write_bytes(restored.database_bytes)
    conn = open_database(copy, read_only=True)
    try:
        return [tuple(row) for row in conn.execute(_ROWS_SQL)]
    finally:
        conn.close()


def _stored_rows(conn: DatabaseConnection) -> list[tuple[object, ...]]:
    return [tuple(row) for row in conn.execute(_ROWS_SQL)]


def _decrypt(path: Path, passphrase: str = PASSPHRASE) -> DecryptedBackup:
    return read_backup(path, passphrase, allowed_params=CHEAP_ALLOWED)


# --------------------------------------------------------------------------- the passphrase rule


def _code(passphrase: str, confirmation: str | None = None, min_length: int = 12) -> str | None:
    try:
        check_passphrase(passphrase, confirmation, min_length=min_length)
    except ServiceError as exc:
        return exc.code
    return None


def test_an_acceptable_passphrase_passes() -> None:
    assert _code("correct horse battery staple") is None
    assert _code("correct horse battery staple", "correct horse battery staple") is None


@pytest.mark.parametrize(
    ("passphrase", "code"),
    [
        ("", PASSPHRASE_TOO_SHORT),
        ("Short-pass1", PASSPHRASE_TOO_SHORT),  # 11 characters
        ("aabbccaabbcc", PASSPHRASE_TOO_FEW_DISTINCT),  # 3 different characters
        ("abcdeabcdeab", PASSPHRASE_TOO_FEW_DISTINCT),  # 5 different characters
        ("            ", PASSPHRASE_TOO_FEW_DISTINCT),
        ("Password1234", PASSPHRASE_BLOCKLISTED),
        ("PASSWORD1234!", PASSPHRASE_BLOCKLISTED),
        ("password", PASSPHRASE_TOO_SHORT),
        ("123456789012", PASSPHRASE_BLOCKLISTED),
        ("qwertyuiopas", PASSPHRASE_BLOCKLISTED),
        ("cbrndashboard", PASSPHRASE_BLOCKLISTED),
        ("senha1234567", PASSPHRASE_BLOCKLISTED),
        ("Contrasena123", PASSPHRASE_BLOCKLISTED),
        ("2026-Senha-2026", PASSPHRASE_BLOCKLISTED),
        ("CBRN Readiness Dashboard", PASSPHRASE_BLOCKLISTED),
        ("CBRN Readiness Dashboard 2026!", PASSPHRASE_BLOCKLISTED),
        ("ReadinessDashboard2026", PASSPHRASE_BLOCKLISTED),
    ],
)
def test_unacceptable_passphrases_get_their_code(passphrase: str, code: str) -> None:
    assert _code(passphrase) == code


def test_the_boundaries_of_the_rules() -> None:
    assert MIN_DISTINCT_CHARACTERS == 6
    assert _code("abcdefabcdef") is None  # exactly 6 different characters, exactly 12 long
    assert _code("abcdefabcde") == PASSPHRASE_TOO_SHORT
    assert _code("not Password1234 at all") is None  # the blocklist matches whole words only


def test_a_mismatching_confirmation_is_refused_first() -> None:
    assert _code("correct horse battery staple", "correct horse battery stapl") == (
        PASSPHRASE_MISMATCH
    )
    assert _code("short", "other") == PASSPHRASE_MISMATCH
    assert _code("short", None) == PASSPHRASE_TOO_SHORT
    assert _code("correct horse battery staple", "") == PASSPHRASE_MISMATCH


def test_the_length_never_goes_below_the_hard_floor_of_12() -> None:
    assert _code("elevenchars", min_length=3) == PASSPHRASE_TOO_SHORT
    assert _code("elevenchars", min_length=0) == PASSPHRASE_TOO_SHORT
    assert _code("twelve chars", min_length=3) is None


def test_a_longer_minimum_is_honoured() -> None:
    assert _code("fifteen chars!!", min_length=16) == PASSPHRASE_TOO_SHORT
    assert _code("sixteen chars!!!", min_length=16) is None


def test_the_length_is_counted_after_nfc_normalisation() -> None:
    decomposed = "cafe\u0301-au-lai"  # 12 code points, but 11 characters once composed
    assert len(decomposed) == 12
    assert _code(decomposed) == PASSPHRASE_TOO_SHORT
    assert _code("cafe\u0301-au-lait") is None
    assert _code("cafe\u0301-au-lait", "caf\u00e9-au-lait") is None  # same text, either form


def test_the_errors_never_contain_the_passphrase() -> None:
    secret = "Secret-1234-Secret"
    for confirmation, min_length in (("another", 12), (None, 40)):
        with pytest.raises(ServiceError) as caught:
            check_passphrase(secret, confirmation, min_length=min_length)
        assert secret not in f"{caught.value!s} {caught.value!r} {caught.value.args!r}"


# --------------------------------------------------------------------------- the backup


def test_a_backup_is_written_and_decrypts_to_the_same_rows(
    service: BackupService, db: DatabaseConnection, out_dir: Path
) -> None:
    _add_rows(db)
    dest = out_dir / "weekly.cbrnbak"
    expected = _stored_rows(db)  # before the backup records its own time
    result = service.create_encrypted_backup(dest, PASSPHRASE, PASSPHRASE, params=CHEAP)
    assert result.path == dest
    assert dest.is_file()
    assert result.schema_version > 0
    restored = _decrypt(dest)
    assert restored.header.app_version == __version__
    assert restored.header.schema_version == result.schema_version
    assert restored.header.params == CHEAP
    scratch = out_dir / "scratch"
    scratch.mkdir()
    assert _rows_of(restored, scratch) == expected
    assert len(expected) >= 12
    assert sorted(path.name for path in out_dir.iterdir()) == ["scratch", "weekly.cbrnbak"]


def test_the_extension_is_appended_when_missing(service: BackupService, out_dir: Path) -> None:
    result = service.create_encrypted_backup(out_dir / "stick-backup", PASSPHRASE, params=CHEAP)
    assert result.path == out_dir / f"stick-backup{FILE_EXTENSION}"
    assert result.path.is_file()
    assert not (out_dir / "stick-backup").exists()
    other = service.create_encrypted_backup(out_dir / "v1.2", PASSPHRASE, params=CHEAP)
    assert other.path.name == "v1.2.cbrnbak"


def test_an_existing_extension_is_kept(service: BackupService, out_dir: Path) -> None:
    for name in ("a.cbrnbak", "b.CBRNBAK"):
        result = service.create_encrypted_backup(out_dir / name, PASSPHRASE, params=CHEAP)
        assert result.path.name == name
    assert sorted(path.name for path in out_dir.iterdir()) == ["a.cbrnbak", "b.CBRNBAK"]


@pytest.mark.parametrize(
    ("passphrase", "confirmation", "code"),
    [
        ("Short-pass1", None, PASSPHRASE_TOO_SHORT),
        ("Password1234", None, PASSPHRASE_BLOCKLISTED),
        ("aabbccaabbcc", None, PASSPHRASE_TOO_FEW_DISTINCT),
        ("correct horse battery staple", "correct horse battery stapel", PASSPHRASE_MISMATCH),
    ],
)
def test_a_refused_passphrase_writes_no_file(
    service: BackupService,
    out_dir: Path,
    tmp_path: Path,
    passphrase: str,
    confirmation: str | None,
    code: str,
) -> None:
    before = _tree(tmp_path)
    with pytest.raises(ServiceError) as caught:
        service.create_encrypted_backup(
            out_dir / "refused.cbrnbak", passphrase, confirmation, params=CHEAP
        )
    assert caught.value.code == code
    assert list(out_dir.iterdir()) == []
    assert _tree(tmp_path) == before
    assert service.last_encrypted_backup() is None


def test_the_hard_floor_holds_whatever_is_stored(
    service: BackupService, db: DatabaseConnection, out_dir: Path
) -> None:
    _set_config(db, "min_passphrase_length", 4)  # below the floor, written behind the validation
    with pytest.raises(ServiceError) as caught:
        service.create_encrypted_backup(out_dir / "floor.cbrnbak", "elevenchars", params=CHEAP)
    assert caught.value.code == PASSPHRASE_TOO_SHORT
    assert list(out_dir.iterdir()) == []
    service.create_encrypted_backup(out_dir / "floor.cbrnbak", "twelve chars", params=CHEAP)
    assert (out_dir / "floor.cbrnbak").is_file()


def test_a_longer_stored_minimum_is_honoured(
    service: BackupService, db: DatabaseConnection, out_dir: Path
) -> None:
    _set_config(db, "min_passphrase_length", 16)
    with pytest.raises(ServiceError) as caught:
        service.create_encrypted_backup(out_dir / "p05.cbrnbak", "fifteen chars!!", params=CHEAP)
    assert caught.value.code == PASSPHRASE_TOO_SHORT
    service.create_encrypted_backup(out_dir / "p05.cbrnbak", "sixteen chars!!!", params=CHEAP)
    assert (out_dir / "p05.cbrnbak").is_file()


def test_the_passphrase_is_stored_nowhere(
    service: BackupService, db: DatabaseConnection, out_dir: Path, tmp_path: Path
) -> None:
    _add_rows(db)
    dest = out_dir / "secret.cbrnbak"
    service.create_encrypted_backup(dest, PASSPHRASE, PASSPHRASE, params=CHEAP)
    needles = [
        PASSPHRASE.encode("utf-8"),
        PASSPHRASE.encode("utf-16"),
        PASSPHRASE.encode("utf-16-le"),
        PASSPHRASE.encode("utf-16-be"),
        b"distinctive",
    ]
    files = _tree(tmp_path)
    assert "services.sqlite3" in files
    for name, content in [*files.items(), (dest.name, dest.read_bytes())]:
        for needle in needles:
            assert needle not in content, name
    # change_log and the other tables, as text
    dump = "\n".join(
        str(tuple(row))
        for sql in (
            "SELECT * FROM change_log",
            "SELECT * FROM setting",
            "SELECT * FROM app_meta",
        )
        for row in db.execute(sql)
    )
    assert "distinctive" not in dump
    assert any(entity == "setting" for (entity,) in db.execute("SELECT entity FROM change_log"))


def test_only_event_codes_are_logged(
    service: BackupService, out_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[str, dict[str, object]]] = []

    def record(code: str, **fields: object) -> None:
        events.append((code, fields))

    monkeypatch.setattr(backup_service, "log_event", record)
    service.create_encrypted_backup(out_dir / "log.cbrnbak", PASSPHRASE, params=CHEAP)
    assert [code for code, _ in events] == ["BACKUP.ENCRYPTED_DONE"]
    assert all(fields == {} for _, fields in events)


# --------------------------------------------------------------------------- the reminder


def test_the_time_of_the_last_backup_is_recorded(
    service: BackupService, db: DatabaseConnection, clock: FixedClock, out_dir: Path
) -> None:
    assert service.last_encrypted_backup() is None
    service.create_encrypted_backup(out_dir / "t.cbrnbak", PASSPHRASE, params=CHEAP)
    assert service.last_encrypted_backup() == clock.utc_now()
    row = db.execute(
        "SELECT value_json FROM setting WHERE key = ?", (LAST_ENCRYPTED_KEY,)
    ).fetchone()
    assert row[0] == '"2026-03-05T12:00:00Z"'


def test_the_reminder_follows_p09(
    service: BackupService,
    db: DatabaseConnection,
    clock: FixedClock,
    tmp_path: Path,
    out_dir: Path,
) -> None:
    assert service.encrypted_backup_reminder_due() is True  # never backed up
    service.create_encrypted_backup(out_dir / "r.cbrnbak", PASSPHRASE, params=CHEAP)
    assert service.encrypted_backup_reminder_due() is False

    def later(days: int) -> BackupService:
        return BackupService(
            db,
            clock.advanced(timedelta(days=days)),
            data_dir=tmp_path,
            identity=DatabaseIdentity.REAL,
        )

    assert later(29).encrypted_backup_reminder_due() is False
    assert later(30).encrypted_backup_reminder_due() is False
    assert later(31).encrypted_backup_reminder_due() is True


def test_the_reminder_uses_the_stored_p09(
    service: BackupService,
    db: DatabaseConnection,
    clock: FixedClock,
    tmp_path: Path,
    out_dir: Path,
) -> None:
    _set_config(db, "backup_reminder_days", 7)
    service.create_encrypted_backup(out_dir / "r.cbrnbak", PASSPHRASE, params=CHEAP)

    def later(days: int) -> BackupService:
        return BackupService(
            db,
            clock.advanced(timedelta(days=days)),
            data_dir=tmp_path,
            identity=DatabaseIdentity.REAL,
        )

    assert later(7).encrypted_backup_reminder_due() is False
    assert later(8).encrypted_backup_reminder_due() is True


def test_the_reminder_compares_local_calendar_dates(
    service: BackupService,
    db: DatabaseConnection,
    tmp_path: Path,
    out_dir: Path,
) -> None:
    service.create_encrypted_backup(out_dir / "l.cbrnbak", PASSPHRASE, params=CHEAP)  # 5 Mar, UTC
    # 5 April 02:00 UTC is still 4 April for a workstation at UTC-3: 30 local days, not yet due.
    western = FixedClock.at("2026-04-05T02:00:00Z", utc_offset_hours=-3)
    assert (
        BackupService(
            db, western, data_dir=tmp_path, identity=DatabaseIdentity.REAL
        ).encrypted_backup_reminder_due()
        is False
    )
    utc = FixedClock.at("2026-04-05T02:00:00Z")
    assert (
        BackupService(
            db, utc, data_dir=tmp_path, identity=DatabaseIdentity.REAL
        ).encrypted_backup_reminder_due()
        is True
    )


@pytest.mark.parametrize("stored", ["not a timestamp", "2026-03-05", "12345", ""])
def test_an_unreadable_stored_time_means_a_reminder_is_due(
    service: BackupService, db: DatabaseConnection, stored: str
) -> None:
    db.execute(
        "INSERT INTO setting (key, value_json) VALUES (?, ?)",
        (LAST_ENCRYPTED_KEY, json.dumps(stored)),
    )
    assert service.last_encrypted_backup() is None
    assert service.encrypted_backup_reminder_due() is True


def test_a_refused_backup_does_not_reset_the_reminder(
    service: BackupService, out_dir: Path
) -> None:
    with pytest.raises(ServiceError):
        service.create_encrypted_backup(out_dir / "x.cbrnbak", "short", params=CHEAP)
    assert service.last_encrypted_backup() is None
    assert service.encrypted_backup_reminder_due() is True


def test_the_operator_label_goes_to_the_change_log(
    db: DatabaseConnection, clock: FixedClock, tmp_path: Path, out_dir: Path
) -> None:
    named = BackupService(
        db, clock, data_dir=tmp_path, identity=DatabaseIdentity.REAL, operator=lambda: "ana"
    )
    named.create_encrypted_backup(out_dir / "o.cbrnbak", PASSPHRASE, params=CHEAP)
    rows = db.execute(_SETTING_LOG_SQL).fetchall()
    assert [tuple(row) for row in rows] == [("ana", "setting")]


def test_without_an_operator_the_label_is_empty(
    service: BackupService, db: DatabaseConnection, out_dir: Path
) -> None:
    service.create_encrypted_backup(out_dir / "o.cbrnbak", PASSPHRASE, params=CHEAP)
    rows = db.execute(_SETTING_LOG_SQL).fetchall()
    assert [tuple(row) for row in rows] == [("", "setting")]


# --------------------------------------------------------------------------- read-only mode


def test_a_read_only_connection_still_backs_up_and_writes_nothing(
    read_only_db: DatabaseConnection,
    db: DatabaseConnection,
    clock: FixedClock,
    tmp_path: Path,
    out_dir: Path,
) -> None:
    _add_rows(db)
    readonly_service = BackupService(
        read_only_db, clock, data_dir=tmp_path, identity=DatabaseIdentity.REAL
    )
    before = _tree(tmp_path)
    result = readonly_service.create_encrypted_backup(
        out_dir / "ro.cbrnbak", PASSPHRASE, PASSPHRASE, params=CHEAP
    )
    assert _tree(tmp_path) == before  # database, journal and data folder byte-identical
    assert result.path.is_file()
    assert readonly_service.last_encrypted_backup() is None
    assert readonly_service.encrypted_backup_reminder_due() is True
    assert db.execute(_SETTING_LOG_SQL).fetchall() == []
    scratch = out_dir / "scratch"
    scratch.mkdir()
    assert _rows_of(_decrypt(result.path), scratch) == _stored_rows(db)


# --------------------------------------------------------------------------- failures


def test_a_write_failure_leaves_no_file_and_records_nothing(
    service: BackupService, out_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    monkeypatch.setattr(backup_service, "log_event", lambda code, **fields: events.append(code))

    def refuse(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(backup_service, "write_backup", refuse)
    with pytest.raises(ServiceError) as caught:
        service.create_encrypted_backup(out_dir / "f.cbrnbak", PASSPHRASE, params=CHEAP)
    assert caught.value.code == BACKUP_WRITE_FAILED
    assert list(out_dir.iterdir()) == []
    assert service.last_encrypted_backup() is None
    assert events == ["BACKUP.ENCRYPTED_FAILED"]


def test_a_real_write_failure_leaves_nothing(service: BackupService, out_dir: Path) -> None:
    blocker = out_dir / "not-a-folder"
    blocker.write_bytes(b"a file where a folder is needed")
    with pytest.raises(ServiceError) as caught:
        service.create_encrypted_backup(blocker / "f.cbrnbak", PASSPHRASE, params=CHEAP)
    assert caught.value.code == BACKUP_WRITE_FAILED
    assert [path.name for path in out_dir.iterdir()] == ["not-a-folder"]
    assert service.last_encrypted_backup() is None


def test_a_failed_rename_leaves_no_partial_file(
    service: BackupService, out_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self: Path, target: object) -> Path:
        raise OSError("rename refused")

    monkeypatch.setattr(Path, "replace", refuse)
    with pytest.raises(ServiceError) as caught:
        service.create_encrypted_backup(out_dir / "g.cbrnbak", PASSPHRASE, params=CHEAP)
    assert caught.value.code == BACKUP_WRITE_FAILED
    assert list(out_dir.iterdir()) == []
    assert service.last_encrypted_backup() is None


def test_a_file_that_does_not_read_back_is_deleted_and_not_recorded(
    service: BackupService, out_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    monkeypatch.setattr(backup_service, "log_event", lambda code, **fields: events.append(code))
    real_read = read_backup

    def differs(path: Path, passphrase: str, **kwargs: object) -> DecryptedBackup:
        good = real_read(path, passphrase, allowed_params=CHEAP_ALLOWED)
        return DecryptedBackup(good.header, good.database_bytes + b"!")

    monkeypatch.setattr(backup_service, "read_backup", differs)
    with pytest.raises(ServiceError) as caught:
        service.create_encrypted_backup(out_dir / "v.cbrnbak", PASSPHRASE, params=CHEAP)
    assert caught.value.code == BACKUP_VERIFY_FAILED
    assert list(out_dir.iterdir()) == []
    assert service.last_encrypted_backup() is None
    assert events == ["BACKUP.ENCRYPTED_FAILED"]


def test_a_file_that_cannot_be_decrypted_is_deleted_and_not_recorded(
    service: BackupService, out_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(path: Path, passphrase: str, **kwargs: object) -> DecryptedBackup:
        raise WrongPassphraseError

    monkeypatch.setattr(backup_service, "read_backup", broken)
    with pytest.raises(ServiceError) as caught:
        service.create_encrypted_backup(out_dir / "w.cbrnbak", PASSPHRASE, params=CHEAP)
    assert caught.value.code == BACKUP_VERIFY_FAILED
    assert list(out_dir.iterdir()) == []
    assert service.last_encrypted_backup() is None


def test_the_daily_backup_is_unchanged_by_the_new_keyword(
    db: DatabaseConnection, clock: FixedClock, tmp_path: Path
) -> None:
    plain = BackupService(db, clock, data_dir=tmp_path, identity=DatabaseIdentity.REAL)
    result = plain.run_daily_backup()
    assert result is not None
    assert result.verified is True
