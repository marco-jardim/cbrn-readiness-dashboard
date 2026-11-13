# SPDX-License-Identifier: GPL-3.0-or-later
"""CSV files of the module data: the export half (PLAN.md T8.3, D04, D15, D25).

Qt-free; standard-library ``csv`` only. The format does not depend on the locale of the machine:

* encoding UTF-8 WITH a byte order mark (:data:`ENCODING`), ``;`` as the delimiter, ``"`` as the
  quote character (``csv.QUOTE_MINIMAL``) and ``\\r\\n`` after every record (RFC 4180). Line breaks
  inside a quoted field are written and read back exactly as they are;
* dates as ``YYYY-MM-DD``, the decimal point is ``.``, booleans are ``0``/``1``, integers are plain
  digits, and NULL is an EMPTY cell;
* REAL values are written with ``repr``: the shortest text that reads back as the very same float,
  with no locale and no thousands separator. ``repr`` is positional for ``1e-4 <= |x| < 1e16`` and
  switches to the scientific form (``1e-05``, ``1.5e+16``) outside that range; the reader accepts
  both. NaN and infinity cannot be written;
* money is written in MAJOR units (``1234.56``), converted exactly from integer minor units with
  the decimal places of the currency (``domain.budget``), never through a float; the currency is in
  its own column;
* a TEXT or CODE cell that starts with ``=``, ``+``, ``-``, ``@``, a tab or a carriage return gets a
  single quote ``'`` in front, so a spreadsheet does not run it as a formula (D04). The guard is
  exactly reversible (:func:`guard_cell`, :func:`unguard_cell`).

Every entity is declared as data (:class:`EntitySpec`, :data:`ENTITIES`): stable English column
codes and the natural key that identifies a row. Rows refer to their parents by natural key, never
by internal id; ids are not exported. The entities are listed in IMPORT ORDER: list entities first,
then the entities that refer to them.

Rows handed to :func:`write_entity` are mappings from column code to value; the value of a MONEY
column is an integer number of minor units. :func:`read_entity` is the strict reader for files that
THIS exporter wrote and returns the same shape: DATE cells as ISO text, MONEY cells as minor units.
An empty TEXT/CODE cell is NULL (``None``) unless the column is ``required`` (NOT NULL in the
database), where it is the empty string; so a nullable text column cannot tell ``''`` from NULL.
"""

from __future__ import annotations

import contextlib
import csv
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from cbrn_dashboard.domain.budget import (
    InvalidAmountError,
    InvalidCurrencyError,
    TooManyDecimalsError,
    decimal_to_minor,
    minor_to_decimal,
)
from cbrn_dashboard.domain.dates import InvalidDateError, format_iso_date, parse_iso_date

__all__ = [
    "DELIMITER",
    "DEMO_PREFIX",
    "ENCODING",
    "ENTITIES",
    "GUARD_PREFIX",
    "GUARD_TRIGGERS",
    "LINE_TERMINATOR",
    "QUOTE_CHAR",
    "ColumnKind",
    "ColumnSpec",
    "CsvFormatError",
    "EntitySpec",
    "entity_spec",
    "export_file_name",
    "guard_cell",
    "read_entity",
    "unguard_cell",
    "write_entity",
]

#: UTF-8 with a byte order mark: spreadsheets recognise the file as UTF-8. Reading accepts a file
#: with or without the mark.
ENCODING = "utf-8-sig"
DELIMITER = ";"
QUOTE_CHAR = '"'
LINE_TERMINATOR = "\r\n"
#: Prefix of the file name of every export made from a demo database (D25).
DEMO_PREFIX = "DEMO-"
#: The single quote put in front of a cell that a spreadsheet could take for a formula.
GUARD_PREFIX = "'"
#: First characters that trigger the guard (the guard prefix itself is guarded as well).
GUARD_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")

_TEMP_SUFFIX = ".part"


class CsvFormatError(ValueError):
    """A file or a value does not follow the format; ``code`` is stable, the text has no values.

    ``line`` is the physical line where the offending record ends and ``column`` the column code,
    when they are known.
    """

    def __init__(self, code: str, *, line: int | None = None, column: str | None = None) -> None:
        super().__init__(code, line, column)
        self.code = code
        self.line = line
        self.column = column

    def __str__(self) -> str:
        parts = [self.code]
        if self.line is not None:
            parts.append(f"line {self.line}")
        if self.column is not None:
            parts.append(f"column {self.column}")
        return " / ".join(parts)


# --------------------------------------------------------------------------- the entity catalogue


class ColumnKind(StrEnum):
    """How the cells of a column are written and read."""

    TEXT = "TEXT"
    CODE = "CODE"  # identifiers, tags, codes: always text, leading zeros kept
    INTEGER = "INTEGER"
    REAL = "REAL"
    DATE = "DATE"
    BOOL = "BOOL"
    MONEY = "MONEY"  # major units in the file, integer minor units in memory
    CURRENCY = "CURRENCY"


@dataclass(frozen=True)
class ColumnSpec:
    """One column: its stable English code, its kind and whether the database requires a value."""

    code: str
    kind: ColumnKind
    required: bool = False


@dataclass(frozen=True)
class EntitySpec:
    """One CSV file: entity name, file stem, ordered columns and the natural key (column codes)."""

    name: str
    file_stem: str
    columns: tuple[ColumnSpec, ...]
    natural_key: tuple[str, ...]

    @property
    def column_codes(self) -> tuple[str, ...]:
        return tuple(column.code for column in self.columns)


def _text(code: str, *, required: bool = False) -> ColumnSpec:
    return ColumnSpec(code, ColumnKind.TEXT, required)


def _code(code: str, *, required: bool = False) -> ColumnSpec:
    return ColumnSpec(code, ColumnKind.CODE, required)


def _int(code: str, *, required: bool = False) -> ColumnSpec:
    return ColumnSpec(code, ColumnKind.INTEGER, required)


def _real(code: str, *, required: bool = False) -> ColumnSpec:
    return ColumnSpec(code, ColumnKind.REAL, required)


def _date(code: str, *, required: bool = False) -> ColumnSpec:
    return ColumnSpec(code, ColumnKind.DATE, required)


def _bool(code: str) -> ColumnSpec:
    return ColumnSpec(code, ColumnKind.BOOL, True)


def _money(code: str, *, required: bool = False) -> ColumnSpec:
    return ColumnSpec(code, ColumnKind.MONEY, required)


def _labels() -> tuple[ColumnSpec, ...]:
    return (_text("label_pt_br"), _text("label_en_us"), _text("label_es_es"))


_ENTRY_KEY_COLUMNS = (
    _int("fiscal_year", required=True),
    _code("source_code", required=True),
    ColumnSpec("currency", ColumnKind.CURRENCY, True),
    _text("description", required=True),
)

#: Every entity, in import order (list entities first).
ENTITIES: tuple[EntitySpec, ...] = (
    EntitySpec(
        "training_course",
        "training_course",
        (_code("code", required=True), *_labels(), _bool("active")),
        ("code",),
    ),
    EntitySpec(
        "asset_type",
        "asset_type",
        (
            _code("code", required=True),
            _bool("built_in"),
            *_labels(),
            _int("default_maintenance_interval_days"),
            _bool("active"),
        ),
        ("code",),
    ),
    EntitySpec(
        "evaluation_metric",
        "evaluation_metric",
        (
            _code("code", required=True),
            *_labels(),
            _text("unit"),
            _real("scale_min"),
            _real("scale_max"),
            _bool("higher_is_better"),
            _bool("active"),
        ),
        ("code",),
    ),
    EntitySpec(
        "funding_source",
        "funding_source",
        (_code("code", required=True), _bool("built_in"), *_labels(), _bool("active")),
        ("code",),
    ),
    EntitySpec(
        "staff_member",
        "staff_member",
        (
            _code("identifier", required=True),
            _text("label"),
            _text("category"),
            _date("active_from", required=True),
            _date("active_until"),
        ),
        ("identifier",),
    ),
    EntitySpec(
        "ppe_certification",
        "ppe_certification",
        (
            _code("staff_identifier", required=True),
            _code("ppe_level", required=True),
            _date("issued_on", required=True),
            _date("valid_until", required=True),
            _date("no_renewal_from"),
            _code("no_renewal_reason"),
            _text("reference"),
        ),
        ("staff_identifier", "ppe_level", "issued_on"),
    ),
    EntitySpec(
        "training_record",
        "training_record",
        (
            _code("staff_identifier", required=True),
            _code("course_code", required=True),
            _date("completed_on", required=True),
            _real("hours"),
        ),
        ("staff_identifier", "course_code", "completed_on"),
    ),
    EntitySpec(
        "academic_degree",
        "academic_degree",
        (
            _code("staff_identifier", required=True),
            _code("level", required=True),
            _code("status", required=True),
            _int("year"),
            _text("field"),
        ),
        ("staff_identifier", "level", "field", "year"),
    ),
    EntitySpec(
        "asset",
        "asset",
        (
            _code("tag", required=True),
            _code("type_code", required=True),
            _text("description"),
            _text("location"),
            _date("in_service_from", required=True),
            _date("in_service_until"),
            _int("maintenance_interval_days"),
            _text("notes"),
        ),
        ("tag",),
    ),
    EntitySpec(
        "asset_status_event",
        "asset_status_event",
        (
            _code("asset_tag", required=True),
            _date("effective_on", required=True),
            _code("status", required=True),
            _text("note"),
        ),
        ("asset_tag", "effective_on"),
    ),
    EntitySpec(
        "maintenance_event",
        "maintenance_event",
        (
            _code("asset_tag", required=True),
            _date("performed_on", required=True),
            _code("kind", required=True),
            _date("next_due_on"),
            _text("note"),
        ),
        ("asset_tag", "performed_on", "kind"),
    ),
    EntitySpec(
        "exercise_edition",
        "exercise_edition",
        (
            _code("code", required=True),
            _code("kind", required=True),
            _text("title"),
            _date("start_on", required=True),
            _date("end_on", required=True),
            _int("participants"),
            _text("notes"),
        ),
        ("code",),
    ),
    EntitySpec(
        "exercise_country",
        "exercise_country",
        (_code("edition_code", required=True), _code("country_code", required=True)),
        ("edition_code", "country_code"),
    ),
    EntitySpec(
        "evaluation_result",
        "evaluation_result",
        (
            _code("edition_code", required=True),
            _code("metric_code", required=True),
            _real("value", required=True),
            _int("respondents"),
            _text("note"),
        ),
        ("edition_code", "metric_code"),
    ),
    EntitySpec(
        "budget_entry",
        "budget_entry",
        (*_ENTRY_KEY_COLUMNS, _money("allocated"), _text("notes")),
        ("fiscal_year", "source_code", "currency", "description"),
    ),
    EntitySpec(
        "budget_execution",
        "budget_execution",
        (
            *_ENTRY_KEY_COLUMNS,
            _date("executed_on", required=True),
            _money("amount", required=True),
            _text("note"),
        ),
        ("fiscal_year", "source_code", "currency", "description", "executed_on", "amount"),
    ),
)

_ENTITIES_BY_NAME = {spec.name: spec for spec in ENTITIES}


def entity_spec(name: str) -> EntitySpec | None:
    """The entity called ``name``, or ``None`` when there is no such entity."""
    return _ENTITIES_BY_NAME.get(name)


def export_file_name(spec: EntitySpec, *, is_demo: bool) -> str:
    """``<file_stem>.csv``, prefixed with ``DEMO-`` for a demo database (D25)."""
    name = f"{spec.file_stem}.csv"
    return f"{DEMO_PREFIX}{name}" if is_demo else name


# --------------------------------------------------------------------------- formula guard


def guard_cell(text: str) -> str:
    """Prefix ``'`` to a cell that starts with a formula trigger or with ``'`` itself.

    Prefixing a cell that already starts with ``'`` keeps the guard exactly reversible.
    """
    if text and (text[0] in GUARD_TRIGGERS or text[0] == GUARD_PREFIX):
        return GUARD_PREFIX + text
    return text


def unguard_cell(text: str) -> str:
    """Strip exactly one leading ``'`` when what follows starts with a trigger or with ``'``.

    ``unguard_cell(guard_cell(s)) == s`` for every string ``s``.
    """
    if len(text) >= 2 and text[0] == GUARD_PREFIX:
        following = text[1]
        if following in GUARD_TRIGGERS or following == GUARD_PREFIX:
            return text[1:]
    return text


# --------------------------------------------------------------------------- cells: writing

_INTEGER_RE = re.compile(r"-?[0-9]+")
_REAL_RE = re.compile(r"-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_MONEY_RE = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
_CURRENCY_RE = re.compile(r"[A-Z]{3}")


def _format_cell(column: ColumnSpec, value: object, currency: object) -> str:
    """The text of one cell; ``None`` is the empty cell."""
    if value is None:
        return ""
    kind = column.kind
    if kind in (ColumnKind.TEXT, ColumnKind.CODE):
        if isinstance(value, str):
            return guard_cell(value)
    elif kind is ColumnKind.CURRENCY:
        if isinstance(value, str) and _CURRENCY_RE.fullmatch(value):
            return value
    elif kind is ColumnKind.INTEGER:
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
    elif kind is ColumnKind.REAL:
        if isinstance(value, int | float) and not isinstance(value, bool):
            number = float(value)
            if math.isfinite(number):
                return repr(number)
    elif kind is ColumnKind.DATE:
        if isinstance(value, str):
            try:
                return format_iso_date(parse_iso_date(value))
            except InvalidDateError:
                raise CsvFormatError("INVALID_DATE", column=column.code) from None
        if isinstance(value, date) and not isinstance(value, datetime):
            return format_iso_date(value)
    elif kind is ColumnKind.BOOL:
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, int) and value in (0, 1):
            return str(value)
    elif kind is ColumnKind.MONEY and isinstance(value, int) and not isinstance(value, bool):
        if not isinstance(currency, str):
            raise CsvFormatError("INVALID_CURRENCY", column=column.code)
        try:
            return format(minor_to_decimal(value, currency), "f")
        except InvalidCurrencyError:
            raise CsvFormatError("INVALID_CURRENCY", column=column.code) from None
    raise CsvFormatError("INVALID_VALUE", column=column.code)


def _sort_key(spec: EntitySpec, row: Mapping[str, object]) -> tuple[tuple[bool, int | str], ...]:
    """The natural key as a sortable tuple: NULL first, text by code point, numbers by value."""
    kinds = {column.code: column.kind for column in spec.columns}
    parts: list[tuple[bool, int | str]] = []
    for code in spec.natural_key:
        value = row.get(code)
        numeric = kinds[code] in (ColumnKind.INTEGER, ColumnKind.MONEY)
        if value is None:
            parts.append((False, 0 if numeric else ""))
        elif numeric and isinstance(value, int):
            parts.append((True, value))
        else:
            parts.append((True, str(value)))
    return tuple(parts)


def _format_row(spec: EntitySpec, row: Mapping[str, object]) -> list[str]:
    known = set(spec.column_codes)
    for code in row:
        if code not in known:
            raise CsvFormatError("UNKNOWN_COLUMN", column=code)
    currency = row.get("currency")
    return [_format_cell(column, row.get(column.code), currency) for column in spec.columns]


def write_entity(path: Path, spec: EntitySpec, rows: Iterable[Mapping[str, object]]) -> int:
    """Write ``rows`` to ``path`` (header row = the column codes); returns the number of rows.

    The rows are written in a deterministic order (sorted by the natural key). The file is written
    under a temporary name beside ``path`` and renamed when complete, so a failure never leaves a
    half-written file under the final name; the temporary file is removed on every error.
    """
    prepared = sorted((_sort_key(spec, row), _format_row(spec, row)) for row in rows)
    temp = path.with_name(path.name + _TEMP_SUFFIX)
    try:
        with temp.open("w", encoding=ENCODING, newline="") as handle:
            writer = csv.writer(
                handle,
                delimiter=DELIMITER,
                quotechar=QUOTE_CHAR,
                quoting=csv.QUOTE_MINIMAL,
                lineterminator=LINE_TERMINATOR,
            )
            writer.writerow(spec.column_codes)
            for _key, cells in prepared:
                writer.writerow(cells)
        temp.replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            temp.unlink(missing_ok=True)
        raise
    return len(prepared)


# --------------------------------------------------------------------------- cells: reading


def _parse_cell(column: ColumnSpec, text: str, line: int) -> object:
    """The typed value of one cell, except MONEY (parsed once the currency is known)."""
    if text == "":
        if column.required and column.kind in (ColumnKind.TEXT, ColumnKind.CODE):
            return ""
        if column.required:
            raise CsvFormatError("REQUIRED", line=line, column=column.code)
        return None
    kind = column.kind
    if kind in (ColumnKind.TEXT, ColumnKind.CODE):
        return unguard_cell(text)
    if kind is ColumnKind.INTEGER and _INTEGER_RE.fullmatch(text):
        return int(text)
    if kind is ColumnKind.REAL and _REAL_RE.fullmatch(text):
        number = float(text)
        if math.isfinite(number):
            return number
    elif kind is ColumnKind.DATE:
        try:
            return format_iso_date(parse_iso_date(text))
        except InvalidDateError:
            raise CsvFormatError("INVALID_DATE", line=line, column=column.code) from None
    elif kind is ColumnKind.BOOL and text in ("0", "1"):
        return text == "1"
    elif (kind is ColumnKind.CURRENCY and _CURRENCY_RE.fullmatch(text)) or (
        kind is ColumnKind.MONEY and _MONEY_RE.fullmatch(text)
    ):
        return text
    raise CsvFormatError("INVALID_VALUE", line=line, column=column.code)


def _money_to_minor(column: ColumnSpec, text: str, currency: object, line: int) -> int:
    if not isinstance(currency, str):
        raise CsvFormatError("INVALID_CURRENCY", line=line, column=column.code)
    try:
        return decimal_to_minor(Decimal(text), currency)
    except (InvalidCurrencyError, TooManyDecimalsError, InvalidAmountError) as exc:
        raise CsvFormatError(exc.code, line=line, column=column.code) from None


def _parse_record(spec: EntitySpec, record: list[str], line: int) -> dict[str, object]:
    if len(record) != len(spec.columns):
        raise CsvFormatError("WRONG_COLUMN_COUNT", line=line)
    row: dict[str, object] = {
        column.code: _parse_cell(column, text, line)
        for column, text in zip(spec.columns, record, strict=True)
    }
    for column in spec.columns:
        if column.kind is ColumnKind.MONEY:
            pending = row[column.code]
            if isinstance(pending, str):
                row[column.code] = _money_to_minor(column, pending, row.get("currency"), line)
    return row


def read_entity(path: Path, spec: EntitySpec) -> list[dict[str, object]]:
    """Read a file written by :func:`write_entity`, strictly, typed per column kind.

    The header must be exactly the column codes. Raises :class:`CsvFormatError` (``NOT_UTF8``,
    ``MALFORMED_CSV``, ``HEADER_MISMATCH``, ``WRONG_COLUMN_COUNT``, ``REQUIRED``, ``INVALID_VALUE``,
    ``INVALID_DATE``, ``INVALID_CURRENCY``, ``TOO_MANY_DECIMALS``).
    """
    records: list[tuple[int, list[str]]] = []
    with path.open("r", encoding=ENCODING, newline="") as handle:
        reader = csv.reader(handle, delimiter=DELIMITER, quotechar=QUOTE_CHAR, strict=True)
        try:
            for record in reader:
                records.append((reader.line_num, record))
        except UnicodeDecodeError:
            raise CsvFormatError("NOT_UTF8") from None
        except csv.Error:
            raise CsvFormatError("MALFORMED_CSV", line=reader.line_num) from None
    if not records or tuple(records[0][1]) != spec.column_codes:
        raise CsvFormatError("HEADER_MISMATCH", line=1)
    return [_parse_record(spec, record, line) for line, record in records[1:] if record]
