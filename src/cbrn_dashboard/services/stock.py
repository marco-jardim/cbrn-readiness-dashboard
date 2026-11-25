# SPDX-License-Identifier: GPL-3.0-or-later
"""Stock service: item types, lots, movements and as-of views (PLAN.md T11.5 and T11.6).

Qt-free. The rules about *values* (quantity, validity, status, minimum) live in ``domain/stock.py``;
the rules about *input* live here and are reported as
:class:`~cbrn_dashboard.services.errors.ServiceError` with a stable code and the name of the
offending field; the UI maps codes to texts. Every mutating method

* first refuses a read-only connection (``READ_ONLY``),
* validates everything it needs and writes inside ONE transaction, so a refusal (or any later
  failure) leaves neither data rows nor ``change_log`` rows behind,
* writes only through ``storage/stock_repo.py``, whose writes use the repository helpers (one
  ``change_log`` row per affected row, stamped with the injected clock and the current operator).

Item types are list entries (D16, D32): a user-defined type needs a pt-BR label and a category; a
built-in type (the 17 seeded ones) keeps empty labels (its name comes from the UI's ``labels.py``)
and only its minimum and its ``active`` flag change; it is never deleted. The code and the category
of a type are frozen once a lot uses it. The minimum (P12) is stored in the type; setting it can
confirm the P12 placeholder in the same transaction.

A lot is created together with its initial receipt movement (D33) in one transaction. Stock is
management data only (D19, D38): there is no clinical field anywhere.

Movements (T11.6): a quantity from 1 to :data:`MAX_QUANTITY`, a note for an adjustment, no date
after the injected clock's local date, no duplicate (lot, date, kind, quantity, reference). The
balance of a lot is never negative (D33): every insert, update and delete is applied to the lot's
movements in memory first and refused with ``BALANCE_NEGATIVE`` when ``first_negative_day`` finds a
negative
day, before anything is written. The last movement of a lot cannot be deleted (``ONLY_MOVEMENT``);
a real lot is closed with a disposal or a loss. Movements on a lot of an inactive type stay allowed.

The as-of views (lot rows, type summaries, value, expiry schedule) only load the rows, convert them
and delegate to ``domain/stock.py``; ``alert_inputs`` hands the domain records to the alert and
indicator services.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime

from cbrn_dashboard.clock import Clock
from cbrn_dashboard.domain import stock as rules
from cbrn_dashboard.domain.budget import is_valid_currency
from cbrn_dashboard.domain.config import ConfigError, ReadinessConfig
from cbrn_dashboard.domain.dates import InvalidDateError, format_iso_date, parse_iso_date
from cbrn_dashboard.domain.indicators import IndicatorValue
from cbrn_dashboard.domain.stock import (
    EXPIRY_REQUIRED_CATEGORIES,
    SIGN,
    Lot,
    LotRow,
    Movement,
    MovementKind,
    ScheduleBucket,
    StockCategory,
    StockDataError,
    StockRules,
    StockType,
    StockValue,
    TypeSummary,
    first_negative_day,
    signed_quantity,
)
from cbrn_dashboard.services.budget import INVALID_AMOUNT, INVALID_CURRENCY, MAX_MINOR
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
from cbrn_dashboard.services.infrastructure import (
    BUILT_IN_TYPE,
    DUPLICATE_CODE,
    TEXT_TOO_LONG,
    TYPE_IN_USE,
    TYPE_INACTIVE,
)
from cbrn_dashboard.storage import stock_repo as repo
from cbrn_dashboard.storage.db import DatabaseConnection, ReadOnlyDatabaseError, transaction
from cbrn_dashboard.storage.repository import ForeignKeyError, RowNotFoundError, WriteContext
from cbrn_dashboard.storage.settings_repo import load_config
from cbrn_dashboard.storage.stock_repo import StockLotRow, StockMovementRow, StockTypeRow

__all__ = [
    "BALANCE_NEGATIVE",
    "BUILT_IN_TYPE",
    "CATEGORY_IMMUTABLE",
    "CODE_IMMUTABLE",
    "DATE_IN_FUTURE",
    "DUPLICATE_CODE",
    "DUPLICATE_LOT",
    "DUPLICATE_MOVEMENT",
    "EXPIRY_REQUIRED",
    "INITIAL_RECEIPT_REQUIRED",
    "INVALID_AMOUNT",
    "INVALID_CATEGORY",
    "INVALID_CURRENCY",
    "INVALID_KIND",
    "INVALID_MONTHS",
    "INVALID_QUANTITY",
    "LABEL_PT_BR_REQUIRED",
    "LOT_CODE_MAX_LENGTH",
    "MAX_MINIMUM",
    "MAX_QUANTITY",
    "NOTE_REQUIRED",
    "ONLY_MOVEMENT",
    "TEXT_TOO_LONG",
    "TYPE_IMMUTABLE",
    "TYPE_INACTIVE",
    "TYPE_IN_USE",
    "InitialReceipt",
    "LotInput",
    "LotView",
    "MovementInput",
    "MovementView",
    "StockDataQuality",
    "StockService",
    "StockTypeInput",
    "StockTypeView",
    "stock_type_label",
]

# Error codes of this service (the shared ones are in services/errors.py, budget.py and
# infrastructure.py; they are re-exported above).
#: The category of a type cannot change once a lot uses it.
CATEGORY_IMMUTABLE = "CATEGORY_IMMUTABLE"
#: The category is not one of the five of ``StockCategory``.
INVALID_CATEGORY = "INVALID_CATEGORY"
#: A quantity (initial receipt or minimum) is not a whole number in its range.
INVALID_QUANTITY = "INVALID_QUANTITY"
#: A lot is created without its initial receipt (date and quantity of at least 1).
INITIAL_RECEIPT_REQUIRED = "INITIAL_RECEIPT_REQUIRED"
#: Antidote and decontaminant lots must have an expiry date (D34).
EXPIRY_REQUIRED = "EXPIRY_REQUIRED"
#: The type already has a lot with this code.
DUPLICATE_LOT = "DUPLICATE_LOT"
#: A movement is dated after the injected clock's local date.
DATE_IN_FUTURE = "DATE_IN_FUTURE"
#: The change would make the end-of-day balance of the lot negative on some date (D33).
BALANCE_NEGATIVE = "BALANCE_NEGATIVE"
#: An adjustment (in or out) has no note.
NOTE_REQUIRED = "NOTE_REQUIRED"
#: The lot already has a movement with this date, kind, quantity and reference.
DUPLICATE_MOVEMENT = "DUPLICATE_MOVEMENT"
#: The last movement of a lot cannot be deleted: close the lot with a disposal or a loss.
ONLY_MOVEMENT = "ONLY_MOVEMENT"
#: The kind is not one of the six of ``MovementKind``.
INVALID_KIND = "INVALID_KIND"
#: The horizon of the expiry schedule is not from 1 to 60 months.
INVALID_MONTHS = "INVALID_MONTHS"
#: A lot that has movements cannot move to another item type (P11-06).
TYPE_IMMUTABLE = "TYPE_IMMUTABLE"

#: Longest lot code, in characters.
LOT_CODE_MAX_LENGTH = 64
#: Largest quantity of one movement (shared with the movements of T11.6).
MAX_QUANTITY = 1_000_000
#: Largest minimum stock of a type.
MAX_MINIMUM = 1_000_000_000


# --------------------------------------------------------------------------- input and output


@dataclass(frozen=True)
class StockTypeInput:
    """The editable fields of an item type; only ``label_pt_br`` is required among the labels.

    ``minimum_quantity``: ``None`` = not set (O04, P12), ``0`` = a minimum that is never below.
    """

    code: str
    category: StockCategory | str
    label_pt_br: str | None
    label_en_us: str | None = None
    label_es_es: str | None = None
    minimum_quantity: int | None = None
    active: bool = True


@dataclass(frozen=True)
class StockTypeView:
    """A stored item type."""

    id: int
    code: str
    built_in: bool
    category: StockCategory
    label_pt_br: str | None
    label_en_us: str | None
    label_es_es: str | None
    minimum_quantity: int | None
    active: bool


@dataclass(frozen=True)
class LotInput:
    """The editable fields of a lot. ``expires_on`` is strict ISO text (or ``date``).

    A price is a whole number of minor units; with a price and no currency the lot takes its
    current currency or the configured default (A08); without a price the lot has no currency.
    """

    type_id: int | None
    lot_code: str
    expires_on: str | date | None = None
    unit_price_minor: int | None = None
    currency: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class InitialReceipt:
    """The receipt movement that starts a lot: date, quantity (at least 1), optional reference."""

    moved_on: str | date | None
    quantity: int | None
    reference: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class LotView:
    """A stored lot together with the code of its type."""

    id: int
    type_id: int
    type_code: str
    lot_code: str
    expires_on: date | None
    unit_price_minor: int | None
    currency: str | None
    notes: str | None


@dataclass(frozen=True)
class MovementInput:
    """The editable fields of a movement: strict ISO date (or ``date``), kind, quantity 1..1e6.

    The lot of a movement never changes. An adjustment needs a ``note``; an empty ``reference``
    is stored as ``''``.
    """

    moved_on: str | date | None
    kind: MovementKind | str | None
    quantity: int | None
    reference: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class MovementView:
    """A stored movement with its signed quantity and the balance of the lot after it.

    Movements are ordered by date; inside one day the inflows come before the outflows (the order
    inside a day does not matter for the rule), then by id. So ``balance_after`` is never negative.
    """

    id: int
    lot_id: int
    moved_on: date
    kind: MovementKind
    quantity: int
    signed_quantity: int
    balance_after: int
    reference: str
    note: str | None


@dataclass(frozen=True)
class StockDataQuality:
    """Simple data-quality findings of the stock on a date (lot ids, ordered).

    ``lots_without_movements``: lots with no movement at all (a lot made through the service always
    has its receipt; this finds the ones that came from elsewhere). ``lots_without_price``: lots
    with stock on hand on ``as_of`` and no price (or no currency); their value is missing from the
    stock value, as ``StockValue.unpriced_lots`` counts.
    """

    as_of: date
    lots_without_movements: tuple[int, ...]
    lots_without_price: tuple[int, ...]


def stock_type_label(view: StockTypeView, lang: str) -> str:
    """The label of ``view`` in ``lang`` (``pt_BR``, ``en_US`` or ``es_ES``; ``-`` too).

    Fallback (section 6): the language asked for, then pt-BR, then en-US, then the code.
    A blank label counts as missing (built-in types have none: the UI names them).
    """
    labels = {
        "pt_BR": view.label_pt_br,
        "en_US": view.label_en_us,
        "es_ES": view.label_es_es,
    }
    for candidate in (lang.replace("-", "_"), "pt_BR", "en_US"):
        text = labels.get(candidate)
        if text is not None and text.strip():
            return text
    return view.code


# --------------------------------------------------------------------------- validation helpers


@dataclass(frozen=True)
class _TypeFields:
    code: str
    category: StockCategory
    label_pt_br: str | None
    label_en_us: str | None
    label_es_es: str | None
    minimum_quantity: int | None
    active: bool


@dataclass(frozen=True)
class _LotFields:
    type_id: int
    lot_code: str
    expires_on: date | None
    unit_price_minor: int | None
    currency: str | None
    notes: str | None


@dataclass(frozen=True)
class _ReceiptFields:
    moved_on: date
    quantity: int
    reference: str
    note: str | None


@dataclass(frozen=True)
class _MovementFields:
    moved_on: date
    kind: MovementKind
    quantity: int
    reference: str
    note: str | None


#: The kinds that need a note.
_ADJUSTMENTS = frozenset({MovementKind.ADJUSTMENT_IN, MovementKind.ADJUSTMENT_OUT})


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


def _parse_category(value: object) -> StockCategory:
    if isinstance(value, StockCategory):
        return value
    if isinstance(value, str) and value in {category.value for category in StockCategory}:
        return StockCategory(value)
    raise ServiceError(INVALID_CATEGORY, "category")


def _parse_kind(value: object) -> MovementKind:
    if value is None:
        raise ServiceError(REQUIRED, "kind")
    if isinstance(value, MovementKind):
        return value
    if isinstance(value, str) and value in {kind.value for kind in MovementKind}:
        return MovementKind(value)
    raise ServiceError(INVALID_KIND, "kind")


def _minimum(value: object) -> int | None:
    """``None`` (not set) or a whole number from 0 to :data:`MAX_MINIMUM`."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ServiceError(INVALID_QUANTITY, "minimum_quantity")
    require(0 <= value <= MAX_MINIMUM, INVALID_QUANTITY, "minimum_quantity")
    return value


def _quantity(value: object, field: str) -> int:
    """A whole quantity from 1 to :data:`MAX_QUANTITY`."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ServiceError(INVALID_QUANTITY, field)
    require(1 <= value <= MAX_QUANTITY, INVALID_QUANTITY, field)
    return value


def _price(value: object) -> int | None:
    """``None`` (no price) or a whole number of minor units from 0 to the budget maximum."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ServiceError(INVALID_AMOUNT, "unit_price_minor")
    require(0 <= value <= MAX_MINOR, INVALID_AMOUNT, "unit_price_minor")
    return value


def _parse_date(value: str | date | None, field: str) -> date:
    if value is None:
        raise ServiceError(REQUIRED, field)
    if isinstance(value, datetime):
        raise ServiceError(INVALID_DATE, field)
    if isinstance(value, date):
        return value
    require(bool(value.strip()), REQUIRED, field)
    try:
        return parse_iso_date(value)
    except InvalidDateError:
        raise ServiceError(INVALID_DATE, field) from None


def _parse_optional_date(value: str | date | None, field: str) -> date | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _parse_date(value, field)


def _optional_iso(value: date | None) -> str | None:
    return None if value is None else format_iso_date(value)


@contextmanager
def _translated() -> Iterator[None]:
    """Turn the storage errors with a service meaning into service errors; re-raise the rest."""
    try:
        yield
    except (ReadOnlyDatabaseError, RowNotFoundError) as exc:
        raise translate_storage_error(exc) from exc


def _type_view(row: StockTypeRow) -> StockTypeView:
    return StockTypeView(
        id=row.id,
        code=row.code,
        built_in=row.built_in,
        category=StockCategory(row.category),
        label_pt_br=row.label_pt_br,
        label_en_us=row.label_en_us,
        label_es_es=row.label_es_es,
        minimum_quantity=row.minimum_quantity,
        active=row.active,
    )


def _display_order(row: StockMovementRow) -> tuple[str, int, int]:
    """Date, inflows before outflows, id: the order of the running balance shown to the user."""
    return (row.moved_on, 0 if SIGN[MovementKind(row.kind)] > 0 else 1, row.id)


def _movement_views(rows: Iterable[StockMovementRow]) -> list[MovementView]:
    views: list[MovementView] = []
    balance = 0
    for row in sorted(rows, key=_display_order):
        movement = repo.movement_to_domain(row)
        signed = signed_quantity(movement)
        balance += signed
        views.append(
            MovementView(
                id=row.id,
                lot_id=row.lot_id,
                moved_on=movement.moved_on,
                kind=movement.kind,
                quantity=row.quantity,
                signed_quantity=signed,
                balance_after=balance,
                reference=row.reference,
                note=row.note,
            )
        )
    return views


def _lot_view(row: StockLotRow, type_codes: dict[int, str]) -> LotView:
    return LotView(
        id=row.id,
        type_id=row.type_id,
        type_code=type_codes.get(row.type_id, ""),
        lot_code=row.lot_code,
        expires_on=None if row.expires_on is None else parse_iso_date(row.expires_on),
        unit_price_minor=row.unit_price_minor,
        currency=row.currency,
        notes=row.notes,
    )


# --------------------------------------------------------------------------- the service


class StockService:
    """Create, change, delete and read stock types, lots and movements; the as-of views."""

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

    def _type_row(self, type_id: int | None, field: str = "type_id") -> StockTypeRow:
        if type_id is None:
            raise ServiceError(REQUIRED, field)
        row = repo.get_type(self._conn, type_id)
        if row is None:
            raise ServiceError(NOT_FOUND, field)
        return row

    def _lot_row(self, lot_id: int) -> StockLotRow:
        row = repo.get_lot(self._conn, lot_id)
        if row is None:
            raise ServiceError(NOT_FOUND, "lot_id")
        return row

    def _type_codes(self) -> dict[int, str]:
        return {row.id: row.code for row in repo.list_types(self._conn)}

    def _config(self) -> ReadinessConfig:
        """The stored configuration; ``CORRUPT_SETTING`` when a stored value is unusable."""
        try:
            return load_config(self._conn)
        except ConfigError as exc:
            raise ServiceError(CORRUPT_SETTING, exc.field or None) from exc

    def _write_type(self, row: StockTypeRow, *, minimum_quantity: int | None, active: bool) -> bool:
        """Write ``row`` with a new minimum and ``active`` flag; True if anything changed."""
        return repo.update_type(
            self._ctx(),
            row.id,
            code=row.code,
            category=row.category,
            label_pt_br=row.label_pt_br,
            label_en_us=row.label_en_us,
            label_es_es=row.label_es_es,
            minimum_quantity=minimum_quantity,
            active=active,
        )

    # ----- item types: validation

    def _type_is_referenced(self, row: StockTypeRow) -> bool:
        """Whether something outside the type row relies on its code and category (P11-05).

        A lot uses the type, a minimum (P12) is set for it, or its code is named by a stored
        snapshot reading (dimension ``item=<code>``) or by an indicator target.
        """
        return (
            repo.type_in_use(self._conn, row.id)
            or row.minimum_quantity is not None
            or repo.code_in_stored_dimensions(self._conn, row.code)
        )

    def _validate_type(self, data: StockTypeInput, current: StockTypeRow | None) -> _TypeFields:
        code = _check_code(data.code)
        category = _parse_category(data.category)
        minimum = _minimum(data.minimum_quantity)
        if current is not None and current.built_in:
            # A built-in type keeps its code, category and (empty) labels: only the minimum and
            # the active flag change.
            require(code == current.code, BUILT_IN_TYPE, "code")
            require(category.value == current.category, BUILT_IN_TYPE, "category")
            same_labels = (
                _clean(data.label_pt_br) == _clean(current.label_pt_br)
                and _clean(data.label_en_us) == _clean(current.label_en_us)
                and _clean(data.label_es_es) == _clean(current.label_es_es)
            )
            require(same_labels, BUILT_IN_TYPE, "label_pt_br")
            label_pt_br, label_en_us, label_es_es = (
                current.label_pt_br,
                current.label_en_us,
                current.label_es_es,
            )
        else:
            label_pt_br = _clean(data.label_pt_br)
            if label_pt_br is None:
                raise ServiceError(LABEL_PT_BR_REQUIRED, "label_pt_br")
            label_en_us = _clean(data.label_en_us)
            label_es_es = _clean(data.label_es_es)
            if current is not None and self._type_is_referenced(current):
                require(code == current.code, CODE_IMMUTABLE, "code")
                require(category.value == current.category, CATEGORY_IMMUTABLE, "category")
        existing = repo.get_type_by_code(self._conn, code)
        require(
            existing is None or (current is not None and existing.id == current.id),
            DUPLICATE_CODE,
            "code",
        )
        return _TypeFields(
            code=code,
            category=category,
            label_pt_br=label_pt_br,
            label_en_us=label_en_us,
            label_es_es=label_es_es,
            minimum_quantity=minimum,
            active=data.active,
        )

    # ----- item types: writes

    def create_type(self, data: StockTypeInput) -> int:
        """Create a user-defined item type; returns its id."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            fields = self._validate_type(data, None)
            return repo.insert_type(
                self._ctx(),
                code=fields.code,
                built_in=False,
                category=fields.category.value,
                label_pt_br=fields.label_pt_br,
                label_en_us=fields.label_en_us,
                label_es_es=fields.label_es_es,
                minimum_quantity=fields.minimum_quantity,
                active=fields.active,
            )

    def update_type(self, type_id: int, data: StockTypeInput) -> None:
        """Change a type; the ``active`` flag is changed here too.

        Built-in types: only the minimum and ``active`` change (``BUILT_IN_TYPE`` when the code,
        the category or a label differs). User-defined types: the code is frozen
        (``CODE_IMMUTABLE``) and so is the category (``CATEGORY_IMMUTABLE``) once a lot uses the
        type, a minimum is set for it, or its code is named by a stored snapshot reading or
        indicator target (dimension ``item=<code>``).
        Use :meth:`set_minimum` to confirm P12 together with a new minimum.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            current = self._type_row(type_id)
            fields = self._validate_type(data, current)
            repo.update_type(
                self._ctx(),
                type_id,
                code=fields.code,
                category=fields.category.value,
                label_pt_br=fields.label_pt_br,
                label_en_us=fields.label_en_us,
                label_es_es=fields.label_es_es,
                minimum_quantity=fields.minimum_quantity,
                active=fields.active,
            )

    def deactivate_type(self, type_id: int) -> None:
        """Mark a type inactive (built-in ones too): it keeps its lots but gets no new ones."""
        self._set_active(type_id, False)

    def activate_type(self, type_id: int) -> None:
        """Mark a type active again."""
        self._set_active(type_id, True)

    def _set_active(self, type_id: int, active: bool) -> None:
        self._require_writable()
        with _translated(), transaction(self._conn):
            row = self._type_row(type_id)
            self._write_type(row, minimum_quantity=row.minimum_quantity, active=active)

    def set_minimum(
        self,
        type_id: int,
        minimum: int | None,
    ) -> bool:
        """Set or clear the minimum stock of a type (built-in ones too); True if it changed.

        ``INVALID_QUANTITY`` when ``minimum`` is not ``None`` or a whole number from 0 to
        :data:`MAX_MINIMUM`.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            row = self._type_row(type_id)
            checked = _minimum(minimum)
            return self._write_type(row, minimum_quantity=checked, active=row.active)

    def save_type_with_minimum(
        self,
        type_id: int | None,
        data: StockTypeInput,
        minimum: int | None,
    ) -> int:
        """Create (``type_id`` ``None``) or change a type together with its minimum; returns its id.

        One transaction: the type and the minimum (``data.minimum_quantity`` is ignored). Any
        refusal, a bad minimum included, leaves nothing written: no type is created and no field is
        changed.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            checked = _minimum(minimum)
            current = None if type_id is None else self._type_row(type_id)
            fields = self._validate_type(replace(data, minimum_quantity=checked), current)
            if current is None:
                saved_id = repo.insert_type(
                    self._ctx(),
                    code=fields.code,
                    built_in=False,
                    category=fields.category.value,
                    label_pt_br=fields.label_pt_br,
                    label_en_us=fields.label_en_us,
                    label_es_es=fields.label_es_es,
                    minimum_quantity=checked,
                    active=fields.active,
                )
            else:
                saved_id = current.id
                repo.update_type(
                    self._ctx(),
                    saved_id,
                    code=fields.code,
                    category=fields.category.value,
                    label_pt_br=fields.label_pt_br,
                    label_en_us=fields.label_en_us,
                    label_es_es=fields.label_es_es,
                    minimum_quantity=checked,
                    active=fields.active,
                )
            return saved_id

    def delete_type(self, type_id: int) -> None:
        """Delete a user-defined type that has no lots (``BUILT_IN_TYPE``, ``TYPE_IN_USE``)."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            row = self._type_row(type_id)
            require(not row.built_in, BUILT_IN_TYPE, "type_id")
            require(not repo.type_in_use(self._conn, type_id), TYPE_IN_USE, "type_id")
            try:
                repo.delete_type(self._ctx(), type_id)
            except ForeignKeyError:
                raise ServiceError(TYPE_IN_USE, "type_id") from None

    # ----- item types: reads

    def list_types(self, include_inactive: bool = False) -> list[StockTypeView]:
        """The types ordered by code; inactive ones only when asked for."""
        rows = repo.list_types(self._conn, include_inactive=include_inactive)
        return [_type_view(row) for row in rows]

    def get_type(self, type_id: int) -> StockTypeView:
        """One type; ``NOT_FOUND`` when it does not exist."""
        return _type_view(self._type_row(type_id))

    def get_type_by_code(self, code: str) -> StockTypeView | None:
        """The type with this code (active or not), or ``None``."""
        row = repo.get_type_by_code(self._conn, code)
        return None if row is None else _type_view(row)

    # ----- lots: validation

    def _currency(
        self, requested: str | None, price: int | None, current: StockLotRow | None
    ) -> str | None:
        """The currency to store: none without a price, else the one asked for, kept or default."""
        if requested is not None:
            require(is_valid_currency(requested), INVALID_CURRENCY, "currency")
        if price is None:
            return None  # no price, no currency
        if requested is not None:
            return requested
        if current is not None and current.currency is not None:
            return current.currency
        return self._config().default_currency  # A08

    def _validate_lot(self, data: LotInput, current: StockLotRow | None) -> _LotFields:
        lot_code = data.lot_code.strip()
        require(bool(lot_code), REQUIRED, "lot_code")
        require(len(lot_code) <= LOT_CODE_MAX_LENGTH, TEXT_TOO_LONG, "lot_code")
        type_row = self._type_row(data.type_id)
        if current is not None and current.type_id != type_row.id:
            # the balance, the schedule and the alerts of a lot follow its type: a lot with
            # movements stays where it is (a lot entered by mistake is deleted and entered again)
            require(not repo.lot_in_use(self._conn, current.id), TYPE_IMMUTABLE, "type_id")
        expires_on = _parse_optional_date(data.expires_on, "expires_on")
        if StockCategory(type_row.category) in EXPIRY_REQUIRED_CATEGORIES:
            require(expires_on is not None, EXPIRY_REQUIRED, "expires_on")
        price = _price(data.unit_price_minor)
        currency = self._currency(data.currency, price, current)
        if current is None or current.type_id != type_row.id:
            require(type_row.active, TYPE_INACTIVE, "type_id")
        existing = repo.get_lot_by_code(self._conn, type_row.id, lot_code)
        require(
            existing is None or (current is not None and existing.id == current.id),
            DUPLICATE_LOT,
            "lot_code",
        )
        return _LotFields(
            type_id=type_row.id,
            lot_code=lot_code,
            expires_on=expires_on,
            unit_price_minor=price,
            currency=currency,
            notes=_clean(data.notes),
        )

    def _validate_receipt(self, receipt: InitialReceipt | None) -> _ReceiptFields:
        if receipt is None:
            raise ServiceError(INITIAL_RECEIPT_REQUIRED, "initial_receipt")
        if receipt.moved_on is None or (
            isinstance(receipt.moved_on, str) and not receipt.moved_on.strip()
        ):
            raise ServiceError(INITIAL_RECEIPT_REQUIRED, "moved_on")
        if receipt.quantity is None:
            raise ServiceError(INITIAL_RECEIPT_REQUIRED, "quantity")
        moved_on = _parse_date(receipt.moved_on, "moved_on")
        quantity = _quantity(receipt.quantity, "quantity")
        require(moved_on <= self._clock.local_date(), DATE_IN_FUTURE, "moved_on")
        return _ReceiptFields(
            moved_on=moved_on,
            quantity=quantity,
            reference=(receipt.reference or "").strip(),
            note=_clean(receipt.note),
        )

    # ----- lots: writes

    def create_lot(self, data: LotInput, initial_receipt: InitialReceipt | None) -> int:
        """Create a lot and its initial receipt movement; returns the lot id.

        ``INITIAL_RECEIPT_REQUIRED`` when there is no receipt (or it has no date or quantity);
        both rows are written in one transaction, so a refusal leaves nothing behind.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            fields = self._validate_lot(data, None)
            receipt = self._validate_receipt(initial_receipt)
            ctx = self._ctx()
            lot_id = repo.insert_lot(
                ctx,
                type_id=fields.type_id,
                lot_code=fields.lot_code,
                expires_on=_optional_iso(fields.expires_on),
                unit_price_minor=fields.unit_price_minor,
                currency=fields.currency,
                notes=fields.notes,
            )
            repo.insert_movement(
                ctx,
                lot_id=lot_id,
                moved_on=format_iso_date(receipt.moved_on),
                kind=MovementKind.RECEIPT.value,
                quantity=receipt.quantity,
                reference=receipt.reference,
                note=receipt.note,
            )
            return lot_id

    def update_lot(self, lot_id: int, data: LotInput) -> None:
        """Change a lot (its movements are changed with the movement methods of T11.6).

        ``TYPE_IMMUTABLE`` when the type changes and the lot already has movements.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            current = self._lot_row(lot_id)
            fields = self._validate_lot(data, current)
            repo.update_lot(
                self._ctx(),
                lot_id,
                type_id=fields.type_id,
                lot_code=fields.lot_code,
                expires_on=_optional_iso(fields.expires_on),
                unit_price_minor=fields.unit_price_minor,
                currency=fields.currency,
                notes=fields.notes,
            )

    def delete_lot(self, lot_id: int) -> None:
        """Delete a lot entered by mistake with all its movements.

        The log gets one ``delete`` row for the lot and one for each movement. A lot that existed
        is closed with a disposal or a loss (T11.6), not deleted.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._lot_row(lot_id)
            repo.delete_lot(self._ctx(), lot_id)

    # ----- lots: reads

    def list_lots(self, type_id: int | None = None) -> list[LotView]:
        """The lots by type code and lot code; optionally only those of one type."""
        type_codes = self._type_codes()
        views = [_lot_view(row, type_codes) for row in repo.list_lots(self._conn, type_id)]
        return sorted(views, key=lambda view: (view.type_code, view.lot_code, view.id))

    def get_lot(self, lot_id: int) -> LotView:
        """One lot; ``NOT_FOUND`` when it does not exist."""
        return _lot_view(self._lot_row(lot_id), self._type_codes())

    # ----- movements: validation

    def _movement_row(self, movement_id: int) -> StockMovementRow:
        row = repo.get_movement(self._conn, movement_id)
        if row is None:
            raise ServiceError(NOT_FOUND, "movement_id")
        return row

    def _validate_movement(
        self, lot_id: int, movement_id: int | None, data: MovementInput
    ) -> _MovementFields:
        """Check the input of a movement of ``lot_id``; ``movement_id`` is the one being edited."""
        moved_on = _parse_date(data.moved_on, "moved_on")
        kind = _parse_kind(data.kind)
        quantity = _quantity(data.quantity, "quantity")
        note = _clean(data.note)
        if kind in _ADJUSTMENTS:
            require(note is not None, NOTE_REQUIRED, "note")
        require(moved_on <= self._clock.local_date(), DATE_IN_FUTURE, "moved_on")
        reference = (data.reference or "").strip()
        existing = repo.get_movement_by_key(
            self._conn, lot_id, format_iso_date(moved_on), kind.value, quantity, reference
        )
        require(existing is None or existing.id == movement_id, DUPLICATE_MOVEMENT, "moved_on")
        return _MovementFields(
            moved_on=moved_on, kind=kind, quantity=quantity, reference=reference, note=note
        )

    def _require_balance(
        self,
        lot_id: int,
        field: str,
        *,
        without: int | None = None,
        added: Movement | None = None,
    ) -> None:
        """Refuse with ``BALANCE_NEGATIVE`` when the change would leave a negative balance.

        The change is the lot's stored movements with ``without`` left out and ``added`` put in,
        applied in memory only: nothing is written here.
        """
        movements = [
            repo.movement_to_domain(row)
            for row in repo.list_movements(self._conn, lot_id)
            if row.id != without
        ]
        if added is not None:
            movements.append(added)
        require(first_negative_day(movements) is None, BALANCE_NEGATIVE, field)

    # ----- movements: writes

    def record_movement(self, lot_id: int, data: MovementInput) -> int:
        """Record a movement of a lot (backdated ones too); returns its id.

        Errors: ``NOT_FOUND`` (``lot_id``), ``REQUIRED``/``INVALID_DATE``, ``INVALID_KIND``,
        ``INVALID_QUANTITY``, ``NOTE_REQUIRED`` (adjustments), ``DATE_IN_FUTURE``,
        ``DUPLICATE_MOVEMENT`` and ``BALANCE_NEGATIVE`` (field ``quantity``). Allowed for a lot of
        an inactive type. A refusal writes nothing.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._lot_row(lot_id)
            fields = self._validate_movement(lot_id, None, data)
            self._require_balance(
                lot_id,
                "quantity",
                added=Movement(
                    id=0,
                    lot_id=lot_id,
                    moved_on=fields.moved_on,
                    kind=fields.kind,
                    quantity=fields.quantity,
                ),
            )
            return repo.insert_movement(
                self._ctx(),
                lot_id=lot_id,
                moved_on=format_iso_date(fields.moved_on),
                kind=fields.kind.value,
                quantity=fields.quantity,
                reference=fields.reference,
                note=fields.note,
            )

    def update_movement(self, movement_id: int, data: MovementInput) -> None:
        """Correct a movement (date, kind, quantity, reference, note); its lot stays the same.

        The same errors as :meth:`record_movement`; ``BALANCE_NEGATIVE`` when the corrected movement
        would make the balance negative on any date (field ``quantity``).
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            current = self._movement_row(movement_id)
            fields = self._validate_movement(current.lot_id, movement_id, data)
            self._require_balance(
                current.lot_id,
                "quantity",
                without=movement_id,
                added=Movement(
                    id=movement_id,
                    lot_id=current.lot_id,
                    moved_on=fields.moved_on,
                    kind=fields.kind,
                    quantity=fields.quantity,
                ),
            )
            repo.update_movement(
                self._ctx(),
                movement_id,
                moved_on=format_iso_date(fields.moved_on),
                kind=fields.kind.value,
                quantity=fields.quantity,
                reference=fields.reference,
                note=fields.note,
            )

    def delete_movement(self, movement_id: int) -> None:
        """Delete a movement (a correction).

        ``ONLY_MOVEMENT`` for the last movement of a lot (close the lot with a disposal or a loss);
        ``BALANCE_NEGATIVE`` (field ``movement_id``) when later outflows depend on it.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            row = self._movement_row(movement_id)
            only = len(repo.list_movements(self._conn, row.lot_id)) <= 1
            require(not only, ONLY_MOVEMENT, "movement_id")
            self._require_balance(row.lot_id, "movement_id", without=movement_id)
            repo.delete_movement(self._ctx(), movement_id)

    # ----- movements: reads

    def movements(self, lot_id: int) -> list[MovementView]:
        """The movements of a lot with the balance after each; ``NOT_FOUND`` for an unknown lot."""
        self._lot_row(lot_id)
        return _movement_views(repo.list_movements(self._conn, lot_id))

    # ----- as-of views (the rules live in domain/stock.py)

    def _rules(self) -> StockRules:
        return StockRules(expiry_warning_days=self._config().stock_expiry_warning_days)

    def _domain_inputs(
        self, categories: Iterable[StockCategory | str] | None = None
    ) -> tuple[list[StockType], list[Lot], list[Movement]]:
        """Types, lots and movements as domain records, limited to ``categories`` when given.

        Types of every state (inactive ones too); a lot and its movements are kept with their type.
        """
        wanted = None if categories is None else {_parse_category(item) for item in categories}
        type_rows = [
            row
            for row in repo.list_types(self._conn)
            if wanted is None or StockCategory(row.category) in wanted
        ]
        types = [repo.type_to_domain(row) for row in type_rows]
        type_codes = {row.id: row.code for row in repo.list_types(self._conn)}
        kept_ids = {row.id for row in type_rows}
        lot_rows = [row for row in repo.list_lots(self._conn) if row.type_id in kept_ids]
        lots = [repo.lot_to_domain(row, type_codes) for row in lot_rows]
        lot_ids = {lot.id for lot in lots}
        movements = [
            repo.movement_to_domain(row)
            for row in repo.list_movements(self._conn)
            if row.lot_id in lot_ids
        ]
        return types, lots, movements

    def alert_inputs(self) -> tuple[tuple[StockType, ...], tuple[Lot, ...], tuple[Movement, ...]]:
        """Every type, lot and movement as domain records, for the alert and indicator services."""
        types, lots, movements = self._domain_inputs()
        return tuple(types), tuple(lots), tuple(movements)

    def stock_rules(self) -> StockRules:
        """The rules of the alerts and views: the P11 expiry warning window from the settings."""
        return self._rules()

    def indicator_values(self, as_of: date) -> list[IndicatorValue]:
        """The stock indicator values on ``as_of`` (input of the indicators, D35, D36).

        The emission rule lives in ``domain/stock.py``: no value for a type that is neither in use
        on the date nor has a minimum, so a database without stock gives an empty list.
        """
        types, lots, movements = self._domain_inputs()
        return rules.indicator_values(types, lots, movements, as_of, self._rules())

    def lot_rows(
        self, as_of: date, categories: Iterable[StockCategory | str] | None = None
    ) -> tuple[LotRow, ...]:
        """One row per lot as read on ``as_of`` (domain ``lot_rows``), optionally by category.

        A date before the first receipt shows the lot as ``NOT_RECEIVED``.
        """
        types, lots, movements = self._domain_inputs(categories)
        return rules.lot_rows(types, lots, movements, as_of, self._rules())

    def type_summaries(
        self, as_of: date, categories: Iterable[StockCategory | str] | None = None
    ) -> tuple[TypeSummary, ...]:
        """One summary per type as read on ``as_of`` (domain ``type_summaries``)."""
        types, lots, movements = self._domain_inputs(categories)
        return rules.type_summaries(types, lots, movements, as_of, self._rules())

    def expiry_schedule(
        self,
        as_of: date,
        months: int = 12,
        categories: Iterable[StockCategory | str] | None = None,
    ) -> tuple[ScheduleBucket, ...]:
        """The expiry schedule of the lots with stock (domain ``expiry_schedule``).

        ``INVALID_MONTHS`` (field ``months``) unless ``months`` is from 1 to 60.
        """
        rows = self.lot_rows(as_of, categories)
        try:
            return rules.expiry_schedule(rows, as_of, months)
        except StockDataError as exc:
            raise ServiceError(INVALID_MONTHS, "months") from exc

    def stock_value(
        self, as_of: date, categories: Iterable[StockCategory | str] | None = None
    ) -> StockValue:
        """The value per currency on ``as_of`` (domain ``stock_value``); currencies stay apart."""
        return rules.stock_value(self.lot_rows(as_of, categories))

    def data_quality(self, as_of: date) -> StockDataQuality:
        """Lots without any movement and lots with stock on hand and no price on ``as_of``."""
        types, lots, movements = self._domain_inputs()
        with_movements = {movement.lot_id for movement in movements}
        rows = rules.lot_rows(types, lots, movements, as_of, self._rules())
        return StockDataQuality(
            as_of=as_of,
            lots_without_movements=tuple(
                sorted(lot.id for lot in lots if lot.id not in with_movements)
            ),
            lots_without_price=tuple(
                sorted(
                    row.lot_id
                    for row in rows
                    if row.on_hand > 0 and (row.value_minor is None or row.currency is None)
                )
            ),
        )
