# SPDX-License-Identifier: GPL-3.0-or-later
"""The error vocabulary shared by all module services (PLAN.md section 5.1, D16, T4.4).

Services raise :class:`ServiceError` with a stable ``code`` (and, when it helps, the name of the
input ``field``). The UI translates the code; services never produce display text and the error
text never contains record values.
"""

from __future__ import annotations

import re

from cbrn_dashboard.storage.db import ReadOnlyDatabaseError
from cbrn_dashboard.storage.repository import RowNotFoundError

__all__ = [
    "CODE_IMMUTABLE",
    "INVALID_CODE",
    "INVALID_DATE",
    "LABEL_PT_BR_REQUIRED",
    "LIST_CODE_PATTERN",
    "NOT_FOUND",
    "READ_ONLY",
    "REQUIRED",
    "ServiceError",
    "require",
    "translate_storage_error",
]

#: The database (or the connection) is read-only: nothing was written.
READ_ONLY = "READ_ONLY"
#: The addressed record does not exist.
NOT_FOUND = "NOT_FOUND"
#: A required field is missing or blank.
REQUIRED = "REQUIRED"
#: A date is not a strict ISO ``YYYY-MM-DD`` date.
INVALID_DATE = "INVALID_DATE"
#: D16: only the pt-BR label is mandatory for user-defined list entries.
LABEL_PT_BR_REQUIRED = "LABEL_PT_BR_REQUIRED"
#: Section 5.1: the code of a list entry cannot change once a row uses it.
CODE_IMMUTABLE = "CODE_IMMUTABLE"
#: A code does not match :data:`LIST_CODE_PATTERN`.
INVALID_CODE = "INVALID_CODE"

#: Codes are ``^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`` (matched with ``fullmatch``).
LIST_CODE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


class ServiceError(Exception):
    """A service refused an operation; ``code`` is stable and ``field`` names the input field."""

    def __init__(self, code: str, field: str | None = None) -> None:
        super().__init__(code, field)
        self.code = code
        self.field = field

    def __str__(self) -> str:
        return self.code if self.field is None else f"{self.code} (field: {self.field})"

    def __repr__(self) -> str:
        return f"ServiceError({self.code!r}, field={self.field!r})"


def require(condition: bool, code: str, field: str | None = None) -> None:
    """Raise ``ServiceError(code, field)`` unless ``condition`` holds."""
    if not condition:
        raise ServiceError(code, field)


def translate_storage_error(exc: Exception) -> ServiceError:
    """The service error for a storage error: ``READ_ONLY`` or ``NOT_FOUND``.

    Any other exception is re-raised unchanged: unexpected storage errors must not be swallowed.
    """
    if isinstance(exc, ReadOnlyDatabaseError):
        return ServiceError(READ_ONLY)
    if isinstance(exc, RowNotFoundError):
        return ServiceError(NOT_FOUND)
    raise exc
