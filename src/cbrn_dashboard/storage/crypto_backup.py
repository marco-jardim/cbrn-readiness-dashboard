# SPDX-License-Identifier: GPL-3.0-or-later
"""The encrypted backup container, ``.cbrnbak`` (PLAN.md D04, D03, risk K06, task T7.2).

The manual backup is the copy meant to leave the machine (removable media), so it is encrypted
with a passphrase. Only well-known building blocks are used: ``hashlib.scrypt`` for the key
derivation, ``cryptography.fernet`` (AES-128-CBC + HMAC-SHA256) for the encryption, ``hmac`` and
``hashlib.sha256`` for the two checksums. Nothing here is a home-made cipher. No Qt, no wall clock,
no logging; no passphrase, salt or content ever appears in an error message.

Byte layout (all integers little-endian, every variable field length-prefixed)::

    HEADER
      magic                 8 bytes   b"CBRNBAK1"
      format version        u16       1
      scrypt log2(n)        u8        17 for the default parameters (n = 2**17)
      scrypt r              u32       8
      scrypt p              u32       1
      salt length           u8        16
      salt                  <len>     random, new for every file
      app version length    u8
      app version           <len>     UTF-8
      schema version        u32       PRAGMA user_version of the copy (informational)
    HEADER HMAC             32 bytes  HMAC-SHA256 over the HEADER bytes, keyed with key bytes 32..63
    token length            u64
    token                   <len>     the Fernet token that holds the database bytes
    TRAILER                 32 bytes  unkeyed SHA-256 of every byte before it

Key derivation: ``hashlib.scrypt(passphrase, salt=salt, n, r, p, maxmem, dklen=64)``. The first 32
bytes (url-safe base64) are the Fernet key, the last 32 bytes are the HMAC key of the header. The
passphrase is normalised with Unicode NFC and encoded as UTF-8 (so the same text typed with
composed or decomposed accents gives the same key); it is not trimmed. ``maxmem`` is explicit: the
derivation needs ``128 * n * r`` bytes (128 MiB for the default), plus a fixed headroom.

Reading checks, in this order, and stops at the first failure:

1. file too short, wrong magic, wrong trailer checksum, or a structure that cannot be parsed:
   :class:`CorruptBackupError` (``CORRUPT_BACKUP``);
2. format version other than 1: :class:`BackupTooNewError` (``BACKUP_TOO_NEW``); this is decided
   right after the magic and the trailer, before the rest of the header is interpreted;
3. scrypt parameters outside the allow-list: :class:`CorruptBackupError`, BEFORE any key
   derivation, so a crafted header cannot force a long or huge derivation;
4. header HMAC mismatch (``hmac.compare_digest``): :class:`WrongPassphraseError`
   (``WRONG_PASSPHRASE``): the file is intact (the trailer matched) but the key is not the right one
   (or the salt in the header was altered);
5. a Fernet failure after that (``InvalidToken``): :class:`CorruptBackupError`.

Only the READER enforces the allow-list; the writer accepts any valid :class:`ScryptParams` (tests
use a cheap set).

Notes: the whole file is held in memory (fine at this size). The Fernet token exposes its creation
time. The trailer is not a secret and not a signature: it only detects accidental damage. The
schema version that drives migration when a backup is restored is the restored database's own
``user_version``; the copy in the header is informational. A forgotten passphrase means the backup
cannot be recovered (the UI warns, T7.4).
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import os
import secrets
import sqlite3
import struct
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from cbrn_dashboard.storage.db import DatabaseConnection

__all__ = [
    "ALLOWED_PARAMS",
    "DEFAULT_PARAMS",
    "FILE_EXTENSION",
    "FORMAT_VERSION",
    "MAGIC",
    "SALT_BYTES",
    "SCRYPT_MAXMEM",
    "BackupFileError",
    "BackupHeader",
    "BackupTooNewError",
    "CorruptBackupError",
    "DecryptedBackup",
    "ScryptParams",
    "WrongPassphraseError",
    "database_snapshot_bytes",
    "derive_keys",
    "read_backup",
    "read_header",
    "scrypt_maxmem",
    "write_backup",
]

MAGIC = b"CBRNBAK1"
FORMAT_VERSION = 1
FILE_EXTENSION = ".cbrnbak"
SALT_BYTES = 16

#: Suffix of the temporary name a file has until it is complete.
PARTIAL_SUFFIX = ".partial"

#: Length of the header HMAC and of the trailing checksum (both SHA-256).
DIGEST_BYTES = 32
#: scrypt output: 32 bytes for Fernet and 32 for the header HMAC.
KEY_MATERIAL_BYTES = 64
_KEY_BYTES = 32

#: Extra memory allowed to scrypt on top of the ``128 * n * r`` it needs.
SCRYPT_MAXMEM_HEADROOM = 64 * 1024 * 1024

_U8 = struct.Struct("<B")
_U16 = struct.Struct("<H")
_U32 = struct.Struct("<I")
_U64 = struct.Struct("<Q")

_MAX_U8 = 255
_MAX_U32 = 2**32 - 1

_CORRUPT_MESSAGE = "The backup file is damaged or is not a backup file."
_TOO_NEW_MESSAGE = "The backup file was written by a newer version of the program."
_WRONG_PASSPHRASE_MESSAGE = "The passphrase is wrong, or the backup header was changed."


# --------------------------------------------------------------------------- errors


class BackupFileError(Exception):
    """Base class of the backup file errors; ``code`` is stable and translated by the UI."""

    code: str = "BACKUP_FILE_ERROR"


class CorruptBackupError(BackupFileError):
    """The file is not an intact backup (or uses parameters this program does not accept)."""

    code = "CORRUPT_BACKUP"

    def __init__(self, message: str = _CORRUPT_MESSAGE) -> None:
        super().__init__(message)


class BackupTooNewError(BackupFileError):
    """The format version of the file is not known to this program."""

    code = "BACKUP_TOO_NEW"

    def __init__(self, message: str = _TOO_NEW_MESSAGE) -> None:
        super().__init__(message)


class WrongPassphraseError(BackupFileError):
    """The header HMAC does not match: wrong passphrase (the file itself is intact)."""

    code = "WRONG_PASSPHRASE"

    def __init__(self, message: str = _WRONG_PASSPHRASE_MESSAGE) -> None:
        super().__init__(message)


# --------------------------------------------------------------------------- types


@dataclass(frozen=True)
class ScryptParams:
    """scrypt cost parameters; ``n`` is a power of two."""

    n: int
    r: int
    p: int

    def __post_init__(self) -> None:
        if self.n < 2 or self.n & (self.n - 1) != 0:
            msg = "scrypt n must be a power of two of at least 2"
            raise ValueError(msg)
        if not 1 <= self.r <= _MAX_U32 or not 1 <= self.p <= _MAX_U32:
            msg = "scrypt r and p must be between 1 and 2**32 - 1"
            raise ValueError(msg)

    @property
    def log2_n(self) -> int:
        """The exponent stored in the header."""
        return self.n.bit_length() - 1


#: The parameters of every new backup (n = 2**17 needs 128 MiB).
DEFAULT_PARAMS = ScryptParams(n=2**17, r=8, p=1)
#: The only parameter sets the reader accepts by default.
ALLOWED_PARAMS: frozenset[ScryptParams] = frozenset({DEFAULT_PARAMS})


def scrypt_maxmem(params: ScryptParams) -> int:
    """The explicit ``maxmem`` for ``params``: ``128 * n * r`` plus a fixed headroom."""
    return 128 * params.n * params.r + SCRYPT_MAXMEM_HEADROOM


#: ``maxmem`` of the default parameters (192 MiB).
SCRYPT_MAXMEM = scrypt_maxmem(DEFAULT_PARAMS)


@dataclass(frozen=True)
class BackupHeader:
    """The readable (not secret) header of a backup file."""

    format_version: int
    params: ScryptParams
    salt: bytes
    app_version: str
    schema_version: int


@dataclass(frozen=True)
class DecryptedBackup:
    """A decrypted backup: its header and the database bytes."""

    header: BackupHeader
    database_bytes: bytes


@dataclass(frozen=True)
class _Parsed:
    """A structurally valid file: header, the header bytes, the stored HMAC and the Fernet token."""

    header: BackupHeader
    header_bytes: bytes
    header_mac: bytes
    token: bytes


# --------------------------------------------------------------------------- key derivation


def _passphrase_bytes(passphrase: str) -> bytes:
    """NFC-normalised UTF-8 bytes of the passphrase (no trimming)."""
    return unicodedata.normalize("NFC", passphrase).encode("utf-8")


def derive_keys(passphrase: str, salt: bytes, params: ScryptParams) -> tuple[bytes, bytes]:
    """The Fernet key (url-safe base64) and the 32-byte header HMAC key for ``passphrase``."""
    material = hashlib.scrypt(
        _passphrase_bytes(passphrase),
        salt=salt,
        n=params.n,
        r=params.r,
        p=params.p,
        maxmem=scrypt_maxmem(params),
        dklen=KEY_MATERIAL_BYTES,
    )
    return base64.urlsafe_b64encode(material[:_KEY_BYTES]), material[_KEY_BYTES:]


def _header_mac(hmac_key: bytes, header_bytes: bytes) -> bytes:
    return hmac.new(hmac_key, header_bytes, hashlib.sha256).digest()


# --------------------------------------------------------------------------- writing


def _encode_header(header: BackupHeader) -> bytes:
    app = header.app_version.encode("utf-8")
    if len(header.salt) > _MAX_U8 or len(app) > _MAX_U8:
        msg = "The salt and the app version must each be at most 255 bytes."
        raise ValueError(msg)
    if not 0 <= header.schema_version <= _MAX_U32:
        msg = "The schema version must fit in 32 bits."
        raise ValueError(msg)
    return b"".join(
        (
            MAGIC,
            _U16.pack(header.format_version),
            _U8.pack(header.params.log2_n),
            _U32.pack(header.params.r),
            _U32.pack(header.params.p),
            _U8.pack(len(header.salt)),
            header.salt,
            _U8.pack(len(app)),
            app,
            _U32.pack(header.schema_version),
        )
    )


def _remove(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def write_backup(
    dest: Path,
    database_bytes: bytes,
    passphrase: str,
    *,
    app_version: str,
    schema_version: int,
    params: ScryptParams = DEFAULT_PARAMS,
    salt: bytes | None = None,
) -> BackupHeader:
    """Encrypt ``database_bytes`` into the container file ``dest`` and return its header.

    A fresh random salt is drawn for every file (``salt`` is injectable for tests only). The file
    is written under ``<dest>.partial`` and renamed into place when complete, so a partial
    ``.cbrnbak`` is never visible; on any failure the temporary file is removed and an existing
    ``dest`` is left as it was. The writer accepts any valid ``params``; only the reader checks the
    allow-list.
    """
    header = BackupHeader(
        format_version=FORMAT_VERSION,
        params=params,
        salt=secrets.token_bytes(SALT_BYTES) if salt is None else salt,
        app_version=app_version,
        schema_version=schema_version,
    )
    header_bytes = _encode_header(header)
    fernet_key, hmac_key = derive_keys(passphrase, header.salt, params)
    token = Fernet(fernet_key).encrypt(database_bytes)
    body = b"".join(
        (header_bytes, _header_mac(hmac_key, header_bytes), _U64.pack(len(token)), token)
    )
    content = body + hashlib.sha256(body).digest()

    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(dest.name + PARTIAL_SUFFIX)
    try:
        with temporary.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(dest)
    except BaseException:
        _remove(temporary)
        raise
    return header


# --------------------------------------------------------------------------- reading


class _Reader:
    """Bounds-checked cursor over the bytes of a file; any overrun is a corrupt file."""

    def __init__(self, data: bytes, offset: int) -> None:
        self._data = data
        self.offset = offset

    @property
    def remaining(self) -> int:
        return len(self._data) - self.offset

    def take(self, count: int) -> bytes:
        end = self.offset + count
        if count < 0 or end > len(self._data):
            raise CorruptBackupError
        chunk = self._data[self.offset : end]
        self.offset = end
        return chunk

    def number(self, layout: struct.Struct) -> int:
        value: int = layout.unpack(self.take(layout.size))[0]
        return value


def _parse(data: bytes, allowed_params: frozenset[ScryptParams]) -> _Parsed:
    """Checks 1 to 3 of the module docstring; no key is derived here."""
    if len(data) < len(MAGIC) + DIGEST_BYTES or data[: len(MAGIC)] != MAGIC:
        raise CorruptBackupError
    body = data[:-DIGEST_BYTES]
    if not hmac.compare_digest(hashlib.sha256(body).digest(), data[-DIGEST_BYTES:]):
        raise CorruptBackupError

    reader = _Reader(body, len(MAGIC))
    version = reader.number(_U16)
    if version != FORMAT_VERSION:
        raise BackupTooNewError

    log2_n = reader.number(_U8)
    r = reader.number(_U32)
    p = reader.number(_U32)
    salt = reader.take(reader.number(_U8))
    try:
        app_version = reader.take(reader.number(_U8)).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptBackupError from exc
    schema_version = reader.number(_U32)
    header_end = reader.offset
    header_mac = reader.take(DIGEST_BYTES)
    token = reader.take(reader.number(_U64))
    if reader.remaining != 0:
        raise CorruptBackupError

    try:
        params = ScryptParams(n=1 << log2_n, r=r, p=p)
    except ValueError as exc:
        raise CorruptBackupError from exc
    if params not in allowed_params:
        raise CorruptBackupError
    header = BackupHeader(version, params, salt, app_version, schema_version)
    return _Parsed(header, body[:header_end], header_mac, token)


def read_header(
    path: Path, *, allowed_params: frozenset[ScryptParams] = ALLOWED_PARAMS
) -> BackupHeader:
    """The header of a backup file, without a passphrase.

    Runs checks 1 to 3 (damage, format version, allow-listed parameters) but cannot authenticate
    the header: that needs the passphrase. An unreadable file raises ``OSError``.
    """
    return _parse(path.read_bytes(), allowed_params).header


def read_backup(
    path: Path, passphrase: str, *, allowed_params: frozenset[ScryptParams] = ALLOWED_PARAMS
) -> DecryptedBackup:
    """Decrypt a backup file; the errors and their order are listed in the module docstring.

    The decrypted bytes stay in memory: the caller decides where they go. An unreadable file
    raises ``OSError``.
    """
    parsed = _parse(path.read_bytes(), allowed_params)
    header = parsed.header
    fernet_key, hmac_key = derive_keys(passphrase, header.salt, header.params)
    if not hmac.compare_digest(_header_mac(hmac_key, parsed.header_bytes), parsed.header_mac):
        raise WrongPassphraseError
    try:
        database_bytes = Fernet(fernet_key).decrypt(parsed.token)
    except InvalidToken as exc:
        raise CorruptBackupError from exc
    return DecryptedBackup(header, database_bytes)


# --------------------------------------------------------------------------- the snapshot


def database_snapshot_bytes(conn: DatabaseConnection) -> tuple[bytes, int]:
    """A CONSISTENT copy of the open database as bytes, plus its ``user_version``.

    Uses SQLite's online backup API into an in-memory database and ``serialize()``. That copies
    the last committed state, works for a read-only connection and writes nothing to the data
    folder. The in-memory connection is closed before returning.
    """
    memory = sqlite3.connect(":memory:")
    try:
        conn.backup(memory)
        version: object = memory.execute("PRAGMA user_version").fetchone()[0]
        if not isinstance(version, int):
            msg = "Unexpected value for PRAGMA user_version."
            raise sqlite3.DatabaseError(msg)
        return memory.serialize(), version
    finally:
        memory.close()
