# SPDX-License-Identifier: GPL-3.0-or-later
"""The ``.cbrnbak`` container (PLAN.md D04, task T7.2): format, check order, errors."""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Callable
from pathlib import Path

import pytest

from cbrn_dashboard.storage import crypto_backup
from cbrn_dashboard.storage.crypto_backup import (
    ALLOWED_PARAMS,
    DEFAULT_PARAMS,
    FILE_EXTENSION,
    FORMAT_VERSION,
    MAGIC,
    SALT_BYTES,
    SCRYPT_MAXMEM,
    BackupFileError,
    BackupTooNewError,
    CorruptBackupError,
    ScryptParams,
    WrongPassphraseError,
    database_snapshot_bytes,
    read_backup,
    read_header,
    scrypt_maxmem,
    write_backup,
)
from cbrn_dashboard.storage.db import open_database
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate

#: A cheap parameter set so most tests do not pay for the real 128 MiB derivation.
CHEAP = ScryptParams(n=2**12, r=8, p=1)
CHEAP_ALLOWED = frozenset({CHEAP})
PASSPHRASE = "correct horse battery staple"
APP_VERSION = "1.2.3"
SCHEMA_VERSION = 7
PAYLOAD = b"SQLite format 3\x00" + bytes(range(256)) * 20

# Offsets in a file written with the 16-byte salt and APP_VERSION above.
_VERSION_OFFSET = 8
_LOG2_N_OFFSET = 10
_SALT_LENGTH_OFFSET = 19
_SALT_OFFSET = 20
_DIGEST = 32
_ROWS_SQL = "SELECT key, value_json FROM setting ORDER BY key"


def _checksum_fixed(data: bytes | bytearray) -> bytes:
    """``data`` with its trailing SHA-256 recomputed (after a tamper of the body)."""
    body = bytes(data[:-_DIGEST])
    return body + hashlib.sha256(body).digest()


def _flip(data: bytes, index: int) -> bytes:
    changed = bytearray(data)
    changed[index] ^= 0x01
    return bytes(changed)


def _token_offset() -> int:
    header = _SALT_OFFSET + SALT_BYTES + 1 + len(APP_VERSION) + 4
    return header + _DIGEST + 8


def _write(path: Path, payload: bytes = PAYLOAD, passphrase: str = PASSPHRASE) -> bytes:
    write_backup(
        path,
        payload,
        passphrase,
        app_version=APP_VERSION,
        schema_version=SCHEMA_VERSION,
        params=CHEAP,
    )
    return path.read_bytes()


def _read(path: Path, passphrase: str = PASSPHRASE) -> bytes:
    return read_backup(path, passphrase, allowed_params=CHEAP_ALLOWED).database_bytes


@pytest.fixture
def backup_file(tmp_path: Path) -> Path:
    path = tmp_path / f"one{FILE_EXTENSION}"
    _write(path)
    return path


# --------------------------------------------------------------------------- constants


def test_format_constants() -> None:
    assert MAGIC == b"CBRNBAK1"
    assert FORMAT_VERSION == 1
    assert FILE_EXTENSION == ".cbrnbak"
    assert ScryptParams(n=2**17, r=8, p=1) == DEFAULT_PARAMS
    assert frozenset({DEFAULT_PARAMS}) == ALLOWED_PARAMS
    assert scrypt_maxmem(DEFAULT_PARAMS) == SCRYPT_MAXMEM
    assert 128 * DEFAULT_PARAMS.n * DEFAULT_PARAMS.r < SCRYPT_MAXMEM


@pytest.mark.parametrize(("n", "r", "p"), [(3, 8, 1), (1, 8, 1), (0, 8, 1), (2**12, 0, 1)])
def test_scrypt_params_are_validated(n: int, r: int, p: int) -> None:
    with pytest.raises(ValueError, match="scrypt"):
        ScryptParams(n=n, r=r, p=p)


def test_error_codes_are_stable() -> None:
    assert CorruptBackupError.code == "CORRUPT_BACKUP"
    assert BackupTooNewError.code == "BACKUP_TOO_NEW"
    assert WrongPassphraseError.code == "WRONG_PASSPHRASE"
    assert issubclass(CorruptBackupError, BackupFileError)
    assert issubclass(BackupTooNewError, BackupFileError)
    assert issubclass(WrongPassphraseError, BackupFileError)


# --------------------------------------------------------------------------- layout


def test_byte_layout(tmp_path: Path) -> None:
    salt = bytes(range(SALT_BYTES))
    path = tmp_path / "layout.cbrnbak"
    write_backup(
        path,
        PAYLOAD,
        PASSPHRASE,
        app_version=APP_VERSION,
        schema_version=SCHEMA_VERSION,
        params=CHEAP,
        salt=salt,
    )
    data = path.read_bytes()
    assert data[:8] == MAGIC
    assert struct.unpack_from("<H", data, 8) == (1,)
    assert data[10] == 12  # log2(4096)
    assert struct.unpack_from("<II", data, 11) == (8, 1)
    assert data[19] == SALT_BYTES
    assert data[20:36] == salt
    assert data[36] == len(APP_VERSION)
    assert data[37 : 37 + len(APP_VERSION)] == APP_VERSION.encode()
    schema_at = 37 + len(APP_VERSION)
    assert struct.unpack_from("<I", data, schema_at) == (SCHEMA_VERSION,)
    token_length_at = schema_at + 4 + _DIGEST
    (token_length,) = struct.unpack_from("<Q", data, token_length_at)
    assert token_length_at + 8 + token_length + _DIGEST == len(data)
    assert token_length_at + 8 == _token_offset()
    assert data[-_DIGEST:] == hashlib.sha256(data[:-_DIGEST]).digest()


def test_read_header_needs_no_passphrase(backup_file: Path) -> None:
    header = read_header(backup_file, allowed_params=CHEAP_ALLOWED)
    assert header.format_version == FORMAT_VERSION
    assert header.app_version == APP_VERSION
    assert header.schema_version == SCHEMA_VERSION
    assert header.params == CHEAP
    assert len(header.salt) == SALT_BYTES


def test_read_header_applies_the_allow_list(backup_file: Path) -> None:
    with pytest.raises(CorruptBackupError):
        read_header(backup_file)  # CHEAP is not in the default allow-list


def test_write_returns_the_header(tmp_path: Path) -> None:
    path = tmp_path / "w.cbrnbak"
    header = write_backup(
        path, PAYLOAD, PASSPHRASE, app_version=APP_VERSION, schema_version=3, params=CHEAP
    )
    assert header == read_header(path, allowed_params=CHEAP_ALLOWED)


def test_too_long_app_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "long.cbrnbak"
    with pytest.raises(ValueError, match="255"):
        write_backup(
            path, PAYLOAD, PASSPHRASE, app_version="9" * 256, schema_version=1, params=CHEAP
        )
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------- round trips


def test_round_trip_with_cheap_params(backup_file: Path) -> None:
    assert _read(backup_file) == PAYLOAD


def test_round_trip_with_the_real_defaults(tmp_path: Path) -> None:
    path = tmp_path / "real.cbrnbak"
    write_backup(path, PAYLOAD, PASSPHRASE, app_version=APP_VERSION, schema_version=SCHEMA_VERSION)
    result = read_backup(path, PASSPHRASE)
    assert result.database_bytes == PAYLOAD
    assert result.header.params == DEFAULT_PARAMS
    assert result.header.schema_version == SCHEMA_VERSION


def test_round_trip_of_a_real_migrated_database(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    conn = open_and_migrate(source, data_dir=tmp_path, identity=DatabaseIdentity.REAL, backup=False)
    try:
        for index in range(25):
            conn.execute(
                "INSERT INTO setting (key, value_json) VALUES (?, ?)",
                (f"test.row{index:02d}", f'{{"n":{index}}}'),
            )
        expected_rows = [tuple(row) for row in conn.execute(_ROWS_SQL)]
        data, version = database_snapshot_bytes(conn)
    finally:
        conn.close()
    assert version > 0
    assert any(key == "test.row24" for key, _ in expected_rows)

    container = tmp_path / "db.cbrnbak"
    write_backup(
        container, data, PASSPHRASE, app_version=APP_VERSION, schema_version=version, params=CHEAP
    )
    restored = read_backup(container, PASSPHRASE, allowed_params=CHEAP_ALLOWED)
    assert restored.database_bytes == data
    assert restored.header.schema_version == version

    copy = tmp_path / "copy.sqlite3"
    copy.write_bytes(restored.database_bytes)
    reopened = open_database(copy, read_only=True)
    try:
        rows = [tuple(row) for row in reopened.execute(_ROWS_SQL)]
        assert rows == expected_rows
        assert reopened.execute("PRAGMA user_version").fetchone()[0] == version
        assert reopened.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        reopened.close()


def test_snapshot_of_a_read_only_connection_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "ro.sqlite3"
    open_and_migrate(path, data_dir=tmp_path, identity=DatabaseIdentity.REAL, backup=False).close()
    before = {entry.name: entry.read_bytes() for entry in tmp_path.iterdir()}
    conn = open_database(path, read_only=True)
    try:
        data, version = database_snapshot_bytes(conn)
    finally:
        conn.close()
    after = {entry.name: entry.read_bytes() for entry in tmp_path.iterdir()}
    assert after == before
    assert data.startswith(b"SQLite format 3\x00")
    assert version > 0


# --------------------------------------------------------------------------- failures


def test_wrong_passphrase(backup_file: Path) -> None:
    with pytest.raises(WrongPassphraseError) as caught:
        _read(backup_file, "this is not the passphrase")
    assert caught.value.code == "WRONG_PASSPHRASE"
    assert "passphrase" in str(caught.value)
    assert "this is not" not in str(caught.value)


def test_empty_passphrase_is_wrong_not_special(backup_file: Path) -> None:
    with pytest.raises(WrongPassphraseError):
        _read(backup_file, "")


def test_a_flipped_byte_in_the_body_is_corrupt(backup_file: Path) -> None:
    data = backup_file.read_bytes()
    backup_file.write_bytes(_flip(data, _token_offset() + 40))
    with pytest.raises(CorruptBackupError) as caught:
        _read(backup_file)
    assert caught.value.code == "CORRUPT_BACKUP"


def test_a_flipped_trailing_checksum_byte_is_corrupt(backup_file: Path) -> None:
    backup_file.write_bytes(_flip(backup_file.read_bytes(), -1))
    with pytest.raises(CorruptBackupError):
        _read(backup_file)


def test_a_flipped_token_byte_with_the_checksum_recomputed_fails_at_the_fernet_step(
    backup_file: Path,
) -> None:
    data = backup_file.read_bytes()
    tampered = _checksum_fixed(_flip(data, _token_offset() + 40))
    assert tampered != data
    backup_file.write_bytes(tampered)
    with pytest.raises(CorruptBackupError):
        _read(backup_file)


@pytest.mark.parametrize("keep", [0, 5, 8, 20, 60, 120, -1, -33, -34])
def test_a_truncated_file_is_corrupt(backup_file: Path, keep: int) -> None:
    data = backup_file.read_bytes()
    backup_file.write_bytes(data[:keep])
    with pytest.raises(CorruptBackupError):
        _read(backup_file)


def test_a_truncated_file_with_a_recomputed_checksum_is_corrupt(backup_file: Path) -> None:
    data = backup_file.read_bytes()
    cut = data[:-_DIGEST][:-10]
    backup_file.write_bytes(cut + hashlib.sha256(cut).digest())
    with pytest.raises(CorruptBackupError):
        _read(backup_file)


def test_extra_bytes_before_the_checksum_are_corrupt(backup_file: Path) -> None:
    data = backup_file.read_bytes()
    padded = data[:-_DIGEST] + b"\x00"
    backup_file.write_bytes(padded + hashlib.sha256(padded).digest())
    with pytest.raises(CorruptBackupError):
        _read(backup_file)


@pytest.mark.parametrize("content", [b"", b"CBRNBAK1", b"not a backup at all" * 10])
def test_a_file_that_is_not_a_backup_is_corrupt(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "junk.cbrnbak"
    path.write_bytes(content)
    with pytest.raises(CorruptBackupError):
        _read(path)


def test_a_wrong_magic_is_corrupt(backup_file: Path) -> None:
    data = backup_file.read_bytes()
    backup_file.write_bytes(b"CBRNBAK2" + data[8:])
    with pytest.raises(CorruptBackupError):
        _read(backup_file)
    # Even with the checksum recomputed: the magic is checked first.
    backup_file.write_bytes(_checksum_fixed(b"XBRNBAK1" + data[8:]))
    with pytest.raises(CorruptBackupError):
        _read(backup_file)


def test_a_flipped_salt_byte_is_a_wrong_passphrase(backup_file: Path) -> None:
    data = backup_file.read_bytes()
    backup_file.write_bytes(_checksum_fixed(_flip(data, _SALT_OFFSET + 3)))
    with pytest.raises(WrongPassphraseError):
        _read(backup_file)


def test_a_flipped_salt_byte_without_the_checksum_is_corrupt(backup_file: Path) -> None:
    data = backup_file.read_bytes()
    backup_file.write_bytes(_flip(data, _SALT_OFFSET + 3))
    with pytest.raises(CorruptBackupError):
        _read(backup_file)


def test_a_changed_header_field_fails_the_header_hmac(backup_file: Path) -> None:
    data = bytearray(backup_file.read_bytes())
    data[36 + 1] ^= 0x01  # first byte of the app version
    backup_file.write_bytes(_checksum_fixed(data))
    with pytest.raises(WrongPassphraseError):
        _read(backup_file)


@pytest.mark.parametrize("version", [0, 2, 99, 65535])
def test_an_unknown_format_version_is_too_new(backup_file: Path, version: int) -> None:
    data = bytearray(backup_file.read_bytes())
    data[_VERSION_OFFSET : _VERSION_OFFSET + 2] = struct.pack("<H", version)
    backup_file.write_bytes(_checksum_fixed(data))
    with pytest.raises(BackupTooNewError) as caught:
        _read(backup_file)
    assert caught.value.code == "BACKUP_TOO_NEW"


def test_an_unknown_format_version_with_a_broken_rest_is_still_too_new(tmp_path: Path) -> None:
    # Only the magic, a future version and the trailer: the rest is not interpreted.
    body = MAGIC + struct.pack("<H", 2) + b"anything a future format puts here"
    path = tmp_path / "future.cbrnbak"
    path.write_bytes(body + hashlib.sha256(body).digest())
    with pytest.raises(BackupTooNewError):
        read_header(path)


def _set_log2_n(value: int) -> Callable[[bytearray], None]:
    def mutate(data: bytearray) -> None:
        data[_LOG2_N_OFFSET] = value

    return mutate


def _set_r(value: int) -> Callable[[bytearray], None]:
    def mutate(data: bytearray) -> None:
        data[11:15] = struct.pack("<I", value)

    return mutate


def _set_p(value: int) -> Callable[[bytearray], None]:
    def mutate(data: bytearray) -> None:
        data[15:19] = struct.pack("<I", value)

    return mutate


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(_set_log2_n(30), id="huge-n"),
        pytest.param(_set_log2_n(255), id="absurd-n"),
        pytest.param(_set_log2_n(0), id="n-of-one"),
        pytest.param(_set_r(9), id="other-r"),
        pytest.param(_set_p(2**31), id="huge-p"),
    ],
)
def test_parameters_outside_the_allow_list_are_corrupt_before_any_derivation(
    backup_file: Path, monkeypatch: pytest.MonkeyPatch, mutate: Callable[[bytearray], None]
) -> None:
    data = bytearray(backup_file.read_bytes())
    mutate(data)
    backup_file.write_bytes(_checksum_fixed(data))
    calls: list[object] = []

    def spy(*args: object, **kwargs: object) -> bytes:
        calls.append((args, kwargs))
        raise AssertionError("scrypt must not run for parameters outside the allow-list")

    monkeypatch.setattr(crypto_backup.hashlib, "scrypt", spy)
    with pytest.raises(CorruptBackupError):
        _read(backup_file)
    assert calls == []


def test_the_default_allow_list_rejects_a_cheap_file_without_deriving(
    backup_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []

    def spy(*args: object, **kwargs: object) -> bytes:
        calls.append(args)
        raise AssertionError("scrypt must not run")

    monkeypatch.setattr(crypto_backup.hashlib, "scrypt", spy)
    with pytest.raises(CorruptBackupError):
        read_backup(backup_file, PASSPHRASE)
    assert calls == []


def test_the_format_version_is_checked_before_the_parameters(
    backup_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = bytearray(backup_file.read_bytes())
    data[_VERSION_OFFSET : _VERSION_OFFSET + 2] = struct.pack("<H", 2)
    data[_LOG2_N_OFFSET] = 30
    backup_file.write_bytes(_checksum_fixed(data))

    def spy(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("scrypt must not run")

    monkeypatch.setattr(crypto_backup.hashlib, "scrypt", spy)
    with pytest.raises(BackupTooNewError):
        _read(backup_file)


def test_the_parameters_are_checked_before_the_header_hmac(backup_file: Path) -> None:
    # Right or wrong passphrase: bad parameters are corrupt either way, never a wrong passphrase.
    data = bytearray(backup_file.read_bytes())
    data[_LOG2_N_OFFSET] = 30
    backup_file.write_bytes(_checksum_fixed(data))
    for passphrase in (PASSPHRASE, "something else entirely"):
        with pytest.raises(CorruptBackupError):
            _read(backup_file, passphrase)


# --------------------------------------------------------------------------- properties


def test_two_backups_of_the_same_database_differ_and_both_decrypt(tmp_path: Path) -> None:
    first = tmp_path / "first.cbrnbak"
    second = tmp_path / "second.cbrnbak"
    first_bytes = _write(first)
    second_bytes = _write(second)
    assert first_bytes != second_bytes
    assert (
        read_header(first, allowed_params=CHEAP_ALLOWED).salt
        != read_header(second, allowed_params=CHEAP_ALLOWED).salt
    )
    assert _read(first) == PAYLOAD
    assert _read(second) == PAYLOAD


def test_the_passphrase_appears_nowhere_in_the_file(tmp_path: Path) -> None:
    passphrase = "Zq7-distinctive-passphrase-\u00e9\u00e7"
    data = _write(tmp_path / "secret.cbrnbak", passphrase=passphrase)
    for encoded in (
        passphrase.encode("utf-8"),
        passphrase.encode("utf-16"),
        passphrase.encode("utf-16-le"),
        passphrase.encode("utf-16-be"),
        passphrase.encode("latin-1"),
    ):
        assert encoded not in data
    assert b"distinctive" not in data


def test_the_payload_does_not_appear_in_the_file(tmp_path: Path) -> None:
    marker = b"PLAINTEXT-MARKER-" * 8
    data = _write(tmp_path / "enc.cbrnbak", payload=marker + PAYLOAD)
    assert marker not in data
    assert b"SQLite format 3" not in data


def test_nfc_normalisation_of_the_passphrase(tmp_path: Path) -> None:
    composed = "caf\u00e9 au lait 12345"
    decomposed = "cafe\u0301 au lait 12345"
    assert composed != decomposed
    path = tmp_path / "nfc.cbrnbak"
    _write(path, passphrase=composed)
    assert _read(path, decomposed) == PAYLOAD
    _write(path, passphrase=decomposed)
    assert _read(path, composed) == PAYLOAD


def test_the_passphrase_is_not_trimmed(tmp_path: Path) -> None:
    path = tmp_path / "trim.cbrnbak"
    _write(path, passphrase=" spaced passphrase ")
    with pytest.raises(WrongPassphraseError):
        _read(path, "spaced passphrase")
    assert _read(path, " spaced passphrase ") == PAYLOAD


def test_an_empty_database_payload_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "empty.cbrnbak"
    _write(path, payload=b"")
    assert _read(path) == b""


# --------------------------------------------------------------------------- writing safely


def test_no_partial_file_remains_after_a_failed_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "keep.cbrnbak"
    dest.write_bytes(b"the previous backup")

    def refuse(self: Path, target: object) -> Path:
        raise OSError("rename refused")

    monkeypatch.setattr(Path, "replace", refuse)
    with pytest.raises(OSError, match="rename refused"):
        _write(dest)
    assert dest.read_bytes() == b"the previous backup"
    assert [entry.name for entry in tmp_path.iterdir()] == ["keep.cbrnbak"]


def test_a_failed_first_write_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = tmp_path / "new" / "fresh.cbrnbak"

    def refuse(self: Path, target: object) -> Path:
        raise OSError("rename refused")

    monkeypatch.setattr(Path, "replace", refuse)
    with pytest.raises(OSError, match="rename refused"):
        _write(dest)
    assert not dest.exists()
    assert list(dest.parent.iterdir()) == []


def test_an_existing_destination_is_replaced_when_complete(tmp_path: Path) -> None:
    dest = tmp_path / "again.cbrnbak"
    dest.write_bytes(b"old")
    _write(dest)
    assert _read(dest) == PAYLOAD
    assert [entry.name for entry in tmp_path.iterdir()] == ["again.cbrnbak"]


def test_the_destination_folder_is_created(tmp_path: Path) -> None:
    dest = tmp_path / "a" / "b" / "deep.cbrnbak"
    _write(dest)
    assert _read(dest) == PAYLOAD


def test_errors_do_not_carry_secrets(backup_file: Path) -> None:
    secret = "a very particular wrong passphrase"
    with pytest.raises(WrongPassphraseError) as caught:
        _read(backup_file, secret)
    text = f"{caught.value!s} {caught.value!r}"
    assert secret not in text
    salt = read_header(backup_file, allowed_params=CHEAP_ALLOWED).salt
    assert salt.hex() not in text
    assert repr(salt) not in text
