# SPDX-License-Identifier: GPL-3.0-or-later
"""Config service: the readiness configuration and the placeholder state (PLAN.md 3.5, 4.1, T6.1).

Qt-free. ``ui/`` reaches the configuration only through this service (D11); the service wraps
``storage/settings_repo.py`` and keeps the conventions of the other module services:

* every mutating method first refuses a read-only connection (``READ_ONLY``),
* every mutating call runs in ONE transaction, so a refusal leaves neither ``setting`` rows nor
  ``change_log`` rows behind,
* every write is stamped with the injected clock and the current operator label (``change_log``),
* errors are :class:`~cbrn_dashboard.services.errors.ServiceError` with a stable code (and the
  offending field); the UI translates the codes and the error text never contains values.

The codes of the domain validation (``ConfigError``) are passed through unchanged; they are listed
in :data:`CONFIG_ERROR_CODES` so that the UI label tables can be complete.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from cbrn_dashboard.clock import Clock
from cbrn_dashboard.domain.config import (
    PLACEHOLDERS,
    ConfigError,
    Placeholder,
    ReadinessConfig,
    placeholder_for_field,
)
from cbrn_dashboard.services.errors import READ_ONLY, ServiceError, require
from cbrn_dashboard.storage import settings_repo
from cbrn_dashboard.storage.db import DatabaseConnection, ReadOnlyDatabaseError, transaction
from cbrn_dashboard.storage.repository import WriteContext

__all__ = [
    "CONFIG_ERROR_CODES",
    "CORRUPT_SETTING",
    "UNKNOWN_PLACEHOLDER",
    "ConfigService",
]

#: A stored setting cannot be read (unreadable JSON or a value that no longer validates).
CORRUPT_SETTING = "CORRUPT_SETTING"
#: The placeholder id is not in the registry.
UNKNOWN_PLACEHOLDER = "UNKNOWN_PLACEHOLDER"

#: Every code ``domain.config.validate`` can raise (field-level rejections of a configuration).
CONFIG_ERROR_CODES: tuple[str, ...] = (
    "BACKUP_FLOOR",
    "INVALID_CURRENCY",
    "INVALID_PPE_LEVEL",
    "INVALID_TEXT",
    "INVALID_TYPE",
    "INVALID_VALIDITY_MONTHS",
    "NEGATIVE_DAYS",
    "PASSPHRASE_FLOOR",
    "THRESHOLD_TOO_LOW",
    "VALUE_TOO_LARGE",
)


@contextmanager
def _translated(*, loading: bool = False) -> Iterator[None]:
    """Turn ``ConfigError`` and read-only errors into service errors; re-raise the rest.

    With ``loading`` every ``ConfigError`` means that a stored value is unusable, so it becomes
    ``CORRUPT_SETTING`` (the field is the stored key or config field, never a value).
    """
    try:
        yield
    except ReadOnlyDatabaseError as exc:
        raise ServiceError(READ_ONLY) from exc
    except ConfigError as exc:
        code = CORRUPT_SETTING if loading else exc.code
        raise ServiceError(code, exc.field or None) from exc


class ConfigService:
    """Read and change the readiness configuration and the confirmed state of the placeholders."""

    def __init__(
        self,
        conn: DatabaseConnection,
        clock: Clock,
        operator: Callable[[], str] = lambda: "",
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._operator = operator

    # ----- plumbing

    def _ctx(self) -> WriteContext:
        return WriteContext(self._conn, self._clock, self._operator())

    def _require_writable(self) -> None:
        require(not self._conn.read_only, READ_ONLY)

    # ----- configuration

    def load(self) -> ReadinessConfig:
        """The stored configuration (defaults for missing keys); ``CORRUPT_SETTING`` if unusable."""
        with _translated(loading=True):
            return settings_repo.load_config(self._conn)

    def save(self, config: ReadinessConfig) -> tuple[str, ...]:
        """Validate and store ``config``; the ``config.<field>`` keys that changed.

        An invalid configuration raises ``ServiceError(code, field)`` with the domain code and
        nothing is written. Saving what is already stored writes and logs nothing.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            return settings_repo.save_config(self._ctx(), config)

    # ----- placeholders

    def placeholders(self) -> tuple[Placeholder, ...]:
        """The placeholder registry in registry order."""
        return PLACEHOLDERS

    def needs_badge(self, placeholder_id: str) -> bool:
        """Whether the "to be confirmed" badge is due: flagged in code, not confirmed here."""
        with _translated():
            return settings_repo.needs_badge(self._conn, placeholder_id)

    def badge_for_field(self, field: str) -> str | None:
        """The id of the placeholder whose badge is due for config ``field``, else ``None``."""
        item = placeholder_for_field(field)
        if item is None:
            return None
        return item.id if self.needs_badge(item.id) else None

    def confirm(self, placeholder_id: str) -> None:
        """Confirm ``placeholder_id`` on this installation and pin its current config values."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            settings_repo.confirm_placeholder(self._ctx(), placeholder_id)

    def unconfirm(self, placeholder_id: str) -> None:
        """Forget the confirmation of ``placeholder_id`` (idempotent)."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            settings_repo.unconfirm_placeholder(self._ctx(), placeholder_id)
