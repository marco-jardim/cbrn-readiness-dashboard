# SPDX-License-Identifier: GPL-3.0-or-later
"""Budget service: funding sources, budget entries and dated execution rows (PLAN.md T5.3).

Qt-free. The rules about *values* (totals, rates, fiscal year, pro-rating, the indicator) live in
``domain/budget.py`` and are only called from here. The rules about *input* live here and are
reported as :class:`~cbrn_dashboard.services.errors.ServiceError` with a stable code and the name
of the offending field; the UI maps codes to texts. Every mutating method

* first refuses a read-only connection (``READ_ONLY``),
* validates everything it needs inside ONE transaction, so a refusal (or any later failure) leaves
  neither data rows nor ``change_log`` rows behind,
* writes only through ``storage/budget_repo.py``, whose writes use the repository helpers (one
  ``change_log`` row per affected row, stamped with the injected clock and the current operator).

Money (D15, D27): the service works in MINOR UNITS ONLY. Amounts are whole ``int`` numbers (``bool``
and ``float`` are refused), never negative, and at most ``MAX_MINOR`` (2**53 - 1);
parsing what users type into minor units is the UI's job. Currencies are never converted or added.
The currency must be in the allow-list of ``domain/budget.py``; a new entry created without one gets
the configured default currency (A08). Corrections are made by editing a row (every edit is in
``change_log``), not by negative amounts.

Funding sources are list entries (D16): only the pt-BR label is mandatory, and only for
USER-DEFINED sources. The built-in sources (``DIRSA``, ``COMAER``) keep empty labels (their
names come from the UI), can be deactivated but never deleted, and their code cannot change.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime

from cbrn_dashboard.clock import Clock
from cbrn_dashboard.domain import budget as rules
from cbrn_dashboard.domain.budget import (
    BudgetEntry,
    BudgetExecution,
    BudgetTotal,
    is_valid_currency,
)
from cbrn_dashboard.domain.config import ConfigError, ReadinessConfig
from cbrn_dashboard.domain.dates import InvalidDateError, format_iso_date, parse_iso_date
from cbrn_dashboard.domain.indicators import IndicatorValue
from cbrn_dashboard.services.config import CORRUPT_SETTING
from cbrn_dashboard.services.errors import (
    CODE_IMMUTABLE,
    INVALID_CODE,
    INVALID_DATE,
    LABEL_PT_BR_REQUIRED,
    LIST_CODE_PATTERN,
    NOT_FOUND,
    READ_ONLY,
    REQUIRED,
    ServiceError,
    require,
    translate_storage_error,
)
from cbrn_dashboard.storage import budget_repo as repo
from cbrn_dashboard.storage.budget_repo import EntryRow, ExecutionRow, SourceRow
from cbrn_dashboard.storage.db import DatabaseConnection, ReadOnlyDatabaseError, transaction
from cbrn_dashboard.storage.repository import ForeignKeyError, RowNotFoundError, WriteContext
from cbrn_dashboard.storage.settings_repo import load_config

__all__ = [
    "BUILT_IN_SOURCE",
    "CURRENCY_IN_USE",
    "DUPLICATE_CODE",
    "DUPLICATE_ENTRY",
    "DUPLICATE_EXECUTION",
    "EXECUTION_OUTSIDE_FISCAL_YEAR",
    "INVALID_AMOUNT",
    "INVALID_CURRENCY",
    "INVALID_YEAR",
    "MAX_MINOR",
    "NEGATIVE_AMOUNT",
    "ORPHAN_EXECUTION",
    "SOURCE_INACTIVE",
    "SOURCE_IN_USE",
    "BudgetService",
    "DataQualityIssue",
    "EntryInput",
    "EntryView",
    "ExecutionView",
    "SourceInput",
    "SourceView",
    "source_label",
]

# Error codes of this service (the shared ones are in services/errors.py).
DUPLICATE_CODE = "DUPLICATE_CODE"
INVALID_YEAR = "INVALID_YEAR"
INVALID_CURRENCY = "INVALID_CURRENCY"
#: D27: an allocated or executed amount below zero.
NEGATIVE_AMOUNT = "NEGATIVE_AMOUNT"
#: An amount is not a whole number of minor units (``bool``/``float``/other) or is too large.
INVALID_AMOUNT = "INVALID_AMOUNT"
DUPLICATE_ENTRY = "DUPLICATE_ENTRY"
DUPLICATE_EXECUTION = "DUPLICATE_EXECUTION"
#: A source cannot be deleted while an entry uses it.
SOURCE_IN_USE = "SOURCE_IN_USE"
#: A built-in source cannot be deleted and its code cannot change.
BUILT_IN_SOURCE = "BUILT_IN_SOURCE"
#: An inactive source cannot receive new entries.
SOURCE_INACTIVE = "SOURCE_INACTIVE"
#: The currency of an entry cannot change while it has execution rows (D15: no conversion).
CURRENCY_IN_USE = "CURRENCY_IN_USE"

#: An execution row dated outside the fiscal year of its entry. It is a refusal when a row is
#: added or changed (``executed_on``) or when the fiscal year of an entry with rows changes
#: (``fiscal_year``), and a data-quality finding (:meth:`BudgetService.data_quality`) for rows that
#: are already stored that way.
EXECUTION_OUTSIDE_FISCAL_YEAR = "EXECUTION_OUTSIDE_FISCAL_YEAR"

# Data-quality codes (non-blocking findings).
#: An execution row whose entry does not exist.
ORPHAN_EXECUTION = "ORPHAN_EXECUTION"

#: The largest amount the service stores, in minor units: 2**53 - 1, the largest integer that a
#: ``float`` holds exactly (the indicator context carries amounts as floats; the database itself
#: could hold up to 2**63 - 1).
MAX_MINOR = 2**53 - 1

_MIN_YEAR = 1900
_MAX_YEAR = 2200


# --------------------------------------------------------------------------- input and output


@dataclass(frozen=True)
class SourceInput:
    """The editable fields of a funding source; the pt-BR label is required for user sources."""

    code: str
    label_pt_br: str | None = None
    label_en_us: str | None = None
    label_es_es: str | None = None
    active: bool = True


@dataclass(frozen=True)
class EntryInput:
    """The editable fields of a budget entry; amounts in minor units.

    ``currency=None`` means the configured default currency for a new entry and "keep the current
    currency" when updating. ``allocated_minor=None`` means "not known yet".
    """

    fiscal_year: int | None
    source_id: int | None
    allocated_minor: int | None = None
    currency: str | None = None
    description: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class SourceView:
    """A stored funding source."""

    id: int
    code: str
    built_in: bool
    label_pt_br: str | None
    label_en_us: str | None
    label_es_es: str | None
    active: bool


@dataclass(frozen=True)
class ExecutionView:
    """A stored execution row."""

    id: int
    entry_id: int
    executed_on: date
    amount_minor: int
    note: str | None


@dataclass(frozen=True)
class EntryView:
    """A stored entry with its source code and its execution rows (by date, then amount)."""

    id: int
    fiscal_year: int
    source_id: int
    source_code: str
    currency: str
    allocated_minor: int | None
    description: str
    notes: str | None
    executions: tuple[ExecutionView, ...]


@dataclass(frozen=True)
class DataQualityIssue:
    """A data-quality finding about one execution row: a stable ``code`` and what it concerns."""

    code: str
    entry_id: int
    executed_on: date
    amount_minor: int


def source_label(source: SourceView, lang: str) -> str:
    """The label of ``source`` in ``lang`` (``pt_BR``/``en_US``/``es_ES``; ``-`` also accepted).

    Fallback (section 6): the language asked for, then pt-BR, then en-US, then the code. A blank
    label counts as missing. Built-in sources have no labels, so this returns their code; the UI
    replaces it with its own translated name.
    """
    labels = {
        "pt_BR": source.label_pt_br,
        "en_US": source.label_en_us,
        "es_ES": source.label_es_es,
    }
    for candidate in (lang.replace("-", "_"), "pt_BR", "en_US"):
        text = labels.get(candidate)
        if text is not None and text.strip():
            return text
    return source.code


# --------------------------------------------------------------------------- validation helpers


@dataclass(frozen=True)
class _SourceFields:
    code: str
    label_pt_br: str | None
    label_en_us: str | None
    label_es_es: str | None
    active: bool


@dataclass(frozen=True)
class _EntryFields:
    fiscal_year: int
    source: SourceRow
    currency: str
    allocated_minor: int | None
    description: str
    notes: str | None


def _clean(text: str | None) -> str | None:
    """Strip a free-text field; blank becomes ``None``."""
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


def _check_code(code: str) -> str:
    require(bool(code.strip()), REQUIRED, "code")
    require(LIST_CODE_PATTERN.fullmatch(code) is not None, INVALID_CODE, "code")
    return code


def _year(value: object) -> int:
    if value is None:
        raise ServiceError(REQUIRED, "fiscal_year")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ServiceError(INVALID_YEAR, "fiscal_year")
    require(_MIN_YEAR <= value <= _MAX_YEAR, INVALID_YEAR, "fiscal_year")
    return value


def _whole_minor(value: object, field: str) -> int:
    """A whole, non-negative number of minor units that the database can hold."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ServiceError(INVALID_AMOUNT, field)
    require(value >= 0, NEGATIVE_AMOUNT, field)
    require(value <= MAX_MINOR, INVALID_AMOUNT, field)
    return value


def _allocated(value: object) -> int | None:
    """The allocated amount; ``None`` (not known yet) is allowed."""
    return None if value is None else _whole_minor(value, "allocated_minor")


def _executed(value: object) -> int:
    """An execution amount; required."""
    if value is None:
        raise ServiceError(REQUIRED, "amount_minor")
    return _whole_minor(value, "amount_minor")


def _parse_date(value: str | date, field: str) -> date:
    if isinstance(value, datetime):
        raise ServiceError(INVALID_DATE, field)
    if isinstance(value, date):
        return value
    require(bool(value.strip()), REQUIRED, field)
    try:
        return parse_iso_date(value)
    except InvalidDateError:
        raise ServiceError(INVALID_DATE, field) from None


def _require_in_year(entry: EntryRow, day: date) -> None:
    """The date of an execution row lies in the fiscal year of its entry (A08)."""
    require(
        rules.fiscal_year_of(day) == entry.fiscal_year,
        EXECUTION_OUTSIDE_FISCAL_YEAR,
        "executed_on",
    )


@contextmanager
def _translated() -> Iterator[None]:
    """Turn the storage errors with a service meaning into service errors; re-raise the rest."""
    try:
        yield
    except (ReadOnlyDatabaseError, RowNotFoundError) as exc:
        raise translate_storage_error(exc) from exc


def _source_view(row: SourceRow) -> SourceView:
    return SourceView(
        id=row.id,
        code=row.code,
        built_in=row.built_in,
        label_pt_br=row.label_pt_br,
        label_en_us=row.label_en_us,
        label_es_es=row.label_es_es,
        active=row.active,
    )


def _execution_view(row: ExecutionRow) -> ExecutionView:
    return ExecutionView(
        id=row.id,
        entry_id=row.entry_id,
        executed_on=parse_iso_date(row.executed_on),
        amount_minor=row.amount_minor,
        note=row.note,
    )


# --------------------------------------------------------------------------- the service


class BudgetService:
    """Create, change, delete and read funding sources, entries and execution rows."""

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

    def _source_row(self, source_id: int) -> SourceRow:
        row = repo.get_source(self._conn, source_id)
        if row is None:
            raise ServiceError(NOT_FOUND, "source_id")
        return row

    def _entry_row(self, entry_id: int) -> EntryRow:
        row = repo.get_entry(self._conn, entry_id)
        if row is None:
            raise ServiceError(NOT_FOUND, "entry_id")
        return row

    def _execution_row(self, execution_id: int) -> ExecutionRow:
        row = repo.get_execution(self._conn, execution_id)
        if row is None:
            raise ServiceError(NOT_FOUND, "execution_id")
        return row

    def _config(self) -> ReadinessConfig:
        """The stored configuration; ``CORRUPT_SETTING`` when a stored value is unusable."""
        try:
            return load_config(self._conn)
        except ConfigError as exc:
            raise ServiceError(CORRUPT_SETTING, exc.field or None) from exc

    # ----- funding sources

    def _validate_source(self, data: SourceInput, source_id: int | None) -> _SourceFields:
        """Rules for USER-DEFINED sources (built-in ones are handled by ``update_source``)."""
        code = _check_code(data.code)
        label_pt_br = _clean(data.label_pt_br)
        if label_pt_br is None:
            raise ServiceError(LABEL_PT_BR_REQUIRED, "label_pt_br")
        if source_id is not None:
            current = self._source_row(source_id)
            if code != current.code:
                require(not repo.source_in_use(self._conn, source_id), CODE_IMMUTABLE, "code")
        existing = repo.get_source_by_code(self._conn, code)
        require(existing is None or existing.id == source_id, DUPLICATE_CODE, "code")
        return _SourceFields(
            code=code,
            label_pt_br=label_pt_br,
            label_en_us=_clean(data.label_en_us),
            label_es_es=_clean(data.label_es_es),
            active=data.active,
        )

    def create_source(self, data: SourceInput) -> int:
        """Create a user-defined source (never built-in); returns its id."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            fields = self._validate_source(data, None)
            source_id = repo.insert_source(
                self._ctx(),
                code=fields.code,
                built_in=False,
                label_pt_br=fields.label_pt_br,
                label_en_us=fields.label_en_us,
                label_es_es=fields.label_es_es,
                active=fields.active,
            )
        return source_id

    def update_source(self, source_id: int, data: SourceInput) -> None:
        """Change a source; its code is frozen once an entry uses it (``CODE_IMMUTABLE``).

        For a built-in source only ``active`` can change: its code must stay (``BUILT_IN_SOURCE``)
        and its labels stay empty (the UI names it), so the label fields of ``data`` are ignored.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            current = self._source_row(source_id)
            if current.built_in:
                require(data.code == current.code, BUILT_IN_SOURCE, "code")
                repo.update_source(
                    self._ctx(),
                    source_id,
                    code=current.code,
                    built_in=True,
                    label_pt_br=current.label_pt_br,
                    label_en_us=current.label_en_us,
                    label_es_es=current.label_es_es,
                    active=data.active,
                )
                return
            fields = self._validate_source(data, source_id)
            repo.update_source(
                self._ctx(),
                source_id,
                code=fields.code,
                built_in=False,
                label_pt_br=fields.label_pt_br,
                label_en_us=fields.label_en_us,
                label_es_es=fields.label_es_es,
                active=fields.active,
            )

    def deactivate_source(self, source_id: int) -> None:
        """Mark a source inactive: it keeps its entries but cannot receive new ones."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            row = self._source_row(source_id)
            repo.update_source(
                self._ctx(),
                source_id,
                code=row.code,
                built_in=row.built_in,
                label_pt_br=row.label_pt_br,
                label_en_us=row.label_en_us,
                label_es_es=row.label_es_es,
                active=False,
            )

    def delete_source(self, source_id: int) -> None:
        """Delete a user-defined source no entry uses.

        ``BUILT_IN_SOURCE`` for a built-in one, ``SOURCE_IN_USE`` when an entry uses it.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            row = self._source_row(source_id)
            require(not row.built_in, BUILT_IN_SOURCE, "source_id")
            require(not repo.source_in_use(self._conn, source_id), SOURCE_IN_USE, "source_id")
            try:
                repo.delete_source(self._ctx(), source_id)
            except ForeignKeyError:
                raise ServiceError(SOURCE_IN_USE, "source_id") from None

    def list_sources(self, include_inactive: bool = False) -> list[SourceView]:
        """The sources ordered by code; inactive ones only when asked for."""
        rows = repo.list_sources(self._conn, include_inactive=include_inactive)
        return [_source_view(row) for row in rows]

    def get_source(self, source_id: int) -> SourceView:
        """One source; ``NOT_FOUND`` when it does not exist."""
        return _source_view(self._source_row(source_id))

    def get_source_by_code(self, code: str) -> SourceView | None:
        """The source with this code (active or not), or ``None``."""
        row = repo.get_source_by_code(self._conn, code)
        return None if row is None else _source_view(row)

    # ----- entries: validation

    def _currency(self, requested: str | None, current: EntryRow | None) -> str:
        if requested is not None:
            currency = requested
        elif current is not None:
            currency = current.currency
        else:
            currency = self._config().default_currency  # A08
        valid = isinstance(currency, str) and is_valid_currency(currency)
        require(valid, INVALID_CURRENCY, "currency")
        return currency

    def _check_rows_still_fit(self, current: EntryRow, fiscal_year: int, currency: str) -> None:
        """Refuse a currency or fiscal-year change that its execution rows cannot follow.

        D15 (no conversion): another currency would reinterpret the stored minor units, so it is
        ``CURRENCY_IN_USE``. A new fiscal year must contain the date of every row.
        """
        rows = repo.list_executions(self._conn, current.id)
        if not rows:
            return
        require(currency == current.currency, CURRENCY_IN_USE, "currency")
        if fiscal_year != current.fiscal_year:
            inside = all(
                rules.fiscal_year_of(parse_iso_date(row.executed_on)) == fiscal_year for row in rows
            )
            require(inside, EXECUTION_OUTSIDE_FISCAL_YEAR, "fiscal_year")

    def _validate_entry(self, data: EntryInput, entry_id: int | None) -> _EntryFields:
        fiscal_year = _year(data.fiscal_year)
        if data.source_id is None:
            raise ServiceError(REQUIRED, "source_id")
        source = self._source_row(data.source_id)
        current = None if entry_id is None else self._entry_row(entry_id)
        currency = self._currency(data.currency, current)
        allocated_minor = _allocated(data.allocated_minor)
        if current is not None:
            self._check_rows_still_fit(current, fiscal_year, currency)
        if current is None or current.source_id != source.id:
            require(source.active, SOURCE_INACTIVE, "source_id")
        description = "" if data.description is None else data.description.strip()
        existing = repo.get_entry_by_key(
            self._conn, fiscal_year, source.code, currency, description
        )
        require(existing is None or existing.id == entry_id, DUPLICATE_ENTRY, "description")
        return _EntryFields(
            fiscal_year=fiscal_year,
            source=source,
            currency=currency,
            allocated_minor=allocated_minor,
            description=description,
            notes=_clean(data.notes),
        )

    # ----- entries: writes

    def create_entry(self, data: EntryInput) -> int:
        """Create an entry (default currency when none is given); returns its id."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            fields = self._validate_entry(data, None)
            entry_id = repo.insert_entry(
                self._ctx(),
                fiscal_year=fields.fiscal_year,
                source_id=fields.source.id,
                currency=fields.currency,
                allocated_minor=fields.allocated_minor,
                description=fields.description,
                notes=fields.notes,
            )
        return entry_id

    def update_entry(self, entry_id: int, data: EntryInput) -> None:
        """Change an entry (only differences are logged); its execution rows stay with it.

        With execution rows the currency cannot change (``CURRENCY_IN_USE``) and the fiscal year
        can only change to one that contains every row (``EXECUTION_OUTSIDE_FISCAL_YEAR``).
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._entry_row(entry_id)
            fields = self._validate_entry(data, entry_id)
            repo.update_entry(
                self._ctx(),
                entry_id,
                fiscal_year=fields.fiscal_year,
                source_id=fields.source.id,
                currency=fields.currency,
                allocated_minor=fields.allocated_minor,
                description=fields.description,
                notes=fields.notes,
            )

    def delete_entry(self, entry_id: int) -> None:
        """Delete an entry together with its execution rows (each one logged)."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._entry_row(entry_id)
            repo.delete_entry(self._ctx(), entry_id)

    # ----- entries: reads

    def _entry_views(self, rows: Sequence[EntryRow]) -> list[EntryView]:
        codes = repo.source_codes(self._conn)
        executions: dict[int, list[ExecutionView]] = {}
        for execution in repo.list_executions(self._conn):
            executions.setdefault(execution.entry_id, []).append(_execution_view(execution))
        views = [
            EntryView(
                id=row.id,
                fiscal_year=row.fiscal_year,
                source_id=row.source_id,
                source_code=codes.get(row.source_id, ""),
                currency=row.currency,
                allocated_minor=row.allocated_minor,
                description=row.description,
                notes=row.notes,
                executions=tuple(executions.get(row.id, [])),
            )
            for row in rows
        ]
        return sorted(
            views,
            key=lambda v: (v.fiscal_year, v.source_code, v.currency, v.description, v.id),
        )

    def list_entries(self, fiscal_year: int | None = None) -> list[EntryView]:
        """The entries (optionally of one fiscal year) with their execution rows."""
        return self._entry_views(repo.list_entries(self._conn, fiscal_year))

    def get_entry(self, entry_id: int) -> EntryView:
        """One entry with its execution rows; ``NOT_FOUND`` when it does not exist."""
        return self._entry_views([self._entry_row(entry_id)])[0]

    # ----- execution rows

    def add_execution(
        self, entry_id: int, executed_on: str | date, amount_minor: int, note: str | None = None
    ) -> int:
        """Add a dated execution row to an entry; returns its id.

        The date must fall in the entry's fiscal year (A08: the calendar year), else
        ``EXECUTION_OUTSIDE_FISCAL_YEAR`` on ``executed_on``.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            entry = self._entry_row(entry_id)
            day = _parse_date(executed_on, "executed_on")
            _require_in_year(entry, day)
            amount = _executed(amount_minor)
            text = format_iso_date(day)
            existing = repo.get_execution_by_key(self._conn, entry_id, text, amount)
            require(existing is None, DUPLICATE_EXECUTION, "amount_minor")
            execution_id = repo.insert_execution(
                self._ctx(),
                entry_id=entry_id,
                executed_on=text,
                amount_minor=amount,
                note=_clean(note),
            )
        return execution_id

    def update_execution(
        self,
        execution_id: int,
        executed_on: str | date,
        amount_minor: int,
        note: str | None = None,
    ) -> None:
        """Correct an execution row (the way to fix a mistake; the edit is in ``change_log``).

        The date must fall in the fiscal year of the row's entry, like when adding a row.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            current = self._execution_row(execution_id)
            day = _parse_date(executed_on, "executed_on")
            _require_in_year(self._entry_row(current.entry_id), day)
            amount = _executed(amount_minor)
            text = format_iso_date(day)
            existing = repo.get_execution_by_key(self._conn, current.entry_id, text, amount)
            require(
                existing is None or existing.id == execution_id,
                DUPLICATE_EXECUTION,
                "amount_minor",
            )
            repo.update_execution(
                self._ctx(), execution_id, executed_on=text, amount_minor=amount, note=_clean(note)
            )

    def delete_execution(self, execution_id: int) -> None:
        """Delete one execution row; ``NOT_FOUND`` when there is none."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._execution_row(execution_id)
            repo.delete_execution(self._ctx(), execution_id)

    # ----- as-of views (built with the domain functions)

    def _domain_entries(self) -> list[BudgetEntry]:
        codes = repo.source_codes(self._conn)
        return [repo.entry_to_domain(row, codes) for row in repo.list_entries(self._conn)]

    def _domain_executions(self) -> list[BudgetExecution]:
        return [repo.execution_to_domain(row) for row in repo.list_executions(self._conn)]

    def totals(self, as_of: date) -> list[BudgetTotal]:
        """Totals per (fiscal year, source code, currency) as of ``as_of`` (domain rule)."""
        return rules.totals(self._domain_entries(), self._domain_executions(), as_of)

    def totals_for_year(self, fiscal_year: int, as_of: date) -> list[BudgetTotal]:
        """:meth:`totals` restricted to one fiscal year."""
        return rules.totals_for_year(
            self._domain_entries(), self._domain_executions(), as_of, fiscal_year
        )

    def multi_year_table(self, as_of: date) -> list[BudgetTotal]:
        """The planning table over all fiscal years (domain rule)."""
        return rules.multi_year_table(self._domain_entries(), self._domain_executions(), as_of)

    def indicator_values(self, as_of: date) -> list[IndicatorValue]:
        """The ``BUD_EXEC_RATE`` values of the as-of date's fiscal year (input of T6.1)."""
        return rules.indicator_values(self._domain_entries(), self._domain_executions(), as_of)

    def target_scale(self, as_of: date) -> float:
        """The factor for the ``BUD_EXEC_RATE`` target: elapsed year fraction, or 1.0 (P08)."""
        prorate = self._config().budget_prorate_target
        return rules.target_scale(as_of, prorate=prorate)

    def data_quality(self, as_of: date) -> list[DataQualityIssue]:
        """Non-blocking findings: execution rows outside their entry's fiscal year and orphans.

        The service itself no longer writes such rows (they are refused when added or changed);
        the findings are for data that got into the database another way. They do not depend on
        the date; ``as_of`` keeps the signature uniform with the other as-of views.
        """
        del as_of
        entries = self._domain_entries()
        executions = self._domain_executions()
        year_of_entry = {entry.id: entry.fiscal_year for entry in entries}
        issues: list[DataQualityIssue] = []
        for row in rules.orphan_executions(entries, executions):
            issues.append(
                DataQualityIssue(ORPHAN_EXECUTION, row.entry_id, row.executed_on, row.amount_minor)
            )
        for row in executions:
            year = year_of_entry.get(row.entry_id)
            if year is not None and rules.fiscal_year_of(row.executed_on) != year:
                issues.append(
                    DataQualityIssue(
                        EXECUTION_OUTSIDE_FISCAL_YEAR,
                        row.entry_id,
                        row.executed_on,
                        row.amount_minor,
                    )
                )
        return issues
