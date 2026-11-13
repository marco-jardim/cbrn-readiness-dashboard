# SPDX-License-Identifier: GPL-3.0-or-later
"""Infrastructure service: asset types, assets, status history and maintenance (PLAN.md T3.3).

Qt-free. All rules about *values* (in service, status on a date, availability, maintenance due
dates, indicators) live in ``domain/infrastructure.py`` and are only called from here; the as-of
views load rows, convert them with ``storage/infrastructure_repo.py`` and call those functions. The
rules about *input* live here and are reported as
:class:`~cbrn_dashboard.services.errors.ServiceError` with a stable code and the name of the
offending field; the UI maps codes to texts. Every mutating method

* first refuses a read-only connection (``READ_ONLY``),
* validates everything it needs and writes inside ONE transaction, so a refusal (or any later
  failure) leaves neither data rows nor ``change_log`` rows behind,
* writes only through ``storage/infrastructure_repo.py``, whose writes use the repository helpers
  (one ``change_log`` row per affected row, stamped with the injected clock and the current
  operator).

Asset types are list entries (section 5.1, D16): a user-defined type needs a pt-BR label, a
built-in type (``bed``, ``bay``, ``neg_pressure_filtration``, ``decon_tent``) keeps empty labels
(its name comes from the UI's ``labels.py``), can be deactivated and can have its default interval
edited, but is never deleted and its code never changes. No default maintenance interval is
invented (A06: not set), and no occupancy is tracked (A01).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime

from cbrn_dashboard.clock import Clock
from cbrn_dashboard.domain import infrastructure as rules
from cbrn_dashboard.domain.dates import (
    InvalidDateError,
    format_iso_date,
    parse_iso_date,
)
from cbrn_dashboard.domain.indicators import IndicatorValue, decode_dimension
from cbrn_dashboard.domain.infrastructure import AssetStatus, MaintenanceKind
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
from cbrn_dashboard.storage import infrastructure_repo as repo
from cbrn_dashboard.storage.db import DatabaseConnection, ReadOnlyDatabaseError, transaction
from cbrn_dashboard.storage.infrastructure_repo import (
    AssetRow,
    AssetTypeRow,
    MaintenanceRow,
    StatusEventRow,
)
from cbrn_dashboard.storage.repository import ForeignKeyError, RowNotFoundError, WriteContext
from cbrn_dashboard.storage.settings_repo import load_config

__all__ = [
    "BUILT_IN_TYPE",
    "DUPLICATE_CODE",
    "DUPLICATE_MAINTENANCE",
    "DUPLICATE_TAG",
    "INITIAL_STATUS_REQUIRED",
    "INVALID_INTERVAL",
    "INVALID_MAINTENANCE_KIND",
    "INVALID_STATUS",
    "IN_SERVICE_UNTIL_BEFORE_FROM",
    "NEGATIVE_INTERVAL",
    "NEXT_DUE_BEFORE_PERFORMED",
    "STATUS_DATE_TAKEN",
    "TAG_MAX_LENGTH",
    "TEXT_TOO_LONG",
    "TYPE_INACTIVE",
    "TYPE_IN_USE",
    "AssetDetail",
    "AssetHistory",
    "AssetInput",
    "AssetTypeInput",
    "AssetTypeView",
    "AssetView",
    "InfrastructureService",
    "MaintenanceView",
    "StatusEventView",
    "TypeAvailability",
    "type_label",
]

# Error codes of this service (the shared ones are in services/errors.py).
DUPLICATE_CODE = "DUPLICATE_CODE"
NEGATIVE_INTERVAL = "NEGATIVE_INTERVAL"
INVALID_INTERVAL = "INVALID_INTERVAL"
TYPE_IN_USE = "TYPE_IN_USE"
BUILT_IN_TYPE = "BUILT_IN_TYPE"
TYPE_INACTIVE = "TYPE_INACTIVE"
DUPLICATE_TAG = "DUPLICATE_TAG"
TEXT_TOO_LONG = "TEXT_TOO_LONG"
INITIAL_STATUS_REQUIRED = "INITIAL_STATUS_REQUIRED"
IN_SERVICE_UNTIL_BEFORE_FROM = "IN_SERVICE_UNTIL_BEFORE_FROM"
INVALID_STATUS = "INVALID_STATUS"
STATUS_DATE_TAKEN = "STATUS_DATE_TAKEN"
INVALID_MAINTENANCE_KIND = "INVALID_MAINTENANCE_KIND"
NEXT_DUE_BEFORE_PERFORMED = "NEXT_DUE_BEFORE_PERFORMED"
DUPLICATE_MAINTENANCE = "DUPLICATE_MAINTENANCE"

#: Longest asset tag, in characters.
TAG_MAX_LENGTH = 64

#: The statuses that may be stored; ``unknown`` is computed (D26).
_STORABLE_STATUSES = frozenset(
    {AssetStatus.OPERATIONAL.value, AssetStatus.DEGRADED.value, AssetStatus.OUT_OF_SERVICE.value}
)


# --------------------------------------------------------------------------- input and output


@dataclass(frozen=True)
class AssetTypeInput:
    """The editable fields of an asset type; only ``label_pt_br`` is required among the labels.

    ``default_maintenance_interval_days``: ``None`` = not set, ``0`` = no scheduled maintenance.
    """

    code: str
    label_pt_br: str | None
    label_en_us: str | None = None
    label_es_es: str | None = None
    default_maintenance_interval_days: int | None = None
    active: bool = True


@dataclass(frozen=True)
class AssetInput:
    """The editable fields of an asset. Dates are strict ISO text (or ``date``)."""

    tag: str
    type_id: int | None
    in_service_from: str | date | None
    in_service_until: str | date | None = None
    description: str | None = None
    location: str | None = None
    maintenance_interval_days: int | None = None
    notes: str | None = None


@dataclass(frozen=True)
class AssetTypeView:
    """A stored asset type."""

    id: int
    code: str
    built_in: bool
    label_pt_br: str | None
    label_en_us: str | None
    label_es_es: str | None
    default_maintenance_interval_days: int | None
    active: bool


@dataclass(frozen=True)
class AssetView:
    """A stored asset together with the code of its type."""

    id: int
    tag: str
    type_id: int
    type_code: str
    description: str | None
    location: str | None
    in_service_from: date
    in_service_until: date | None
    maintenance_interval_days: int | None
    notes: str | None


@dataclass(frozen=True)
class StatusEventView:
    """A stored status event."""

    id: int
    asset_id: int
    effective_on: date
    status: AssetStatus
    note: str | None


@dataclass(frozen=True)
class MaintenanceView:
    """A stored maintenance event."""

    id: int
    asset_id: int
    performed_on: date
    kind: MaintenanceKind
    next_due_on: date | None
    note: str | None


@dataclass(frozen=True)
class AssetHistory:
    """The status events and the maintenance events of an asset, oldest first."""

    status_events: tuple[StatusEventView, ...]
    maintenance_events: tuple[MaintenanceView, ...]


@dataclass(frozen=True)
class AssetDetail:
    """An asset with its status history and its maintenance log."""

    asset: AssetView
    status_events: tuple[StatusEventView, ...]
    maintenance_events: tuple[MaintenanceView, ...]


@dataclass(frozen=True)
class TypeAvailability:
    """Assets of one type in service on a date and how many of them are available (A01, A05)."""

    type_code: str
    available: int
    in_service: int


def type_label(asset_type: AssetTypeView, lang: str) -> str:
    """The label of ``asset_type`` in ``lang`` (``pt_BR``, ``en_US`` or ``es_ES``; ``-`` too).

    Fallback (section 6): the language asked for, then pt-BR, then en-US, then the code.
    A blank label counts as missing (built-in types have none: the UI names them).
    """
    labels = {
        "pt_BR": asset_type.label_pt_br,
        "en_US": asset_type.label_en_us,
        "es_ES": asset_type.label_es_es,
    }
    for candidate in (lang.replace("-", "_"), "pt_BR", "en_US"):
        text = labels.get(candidate)
        if text is not None and text.strip():
            return text
    return asset_type.code


# --------------------------------------------------------------------------- validation helpers


@dataclass(frozen=True)
class _TypeFields:
    code: str
    label_pt_br: str | None
    label_en_us: str | None
    label_es_es: str | None
    default_maintenance_interval_days: int | None
    active: bool


@dataclass(frozen=True)
class _AssetFields:
    type_id: int
    tag: str
    description: str | None
    location: str | None
    in_service_from: date
    in_service_until: date | None
    maintenance_interval_days: int | None
    notes: str | None


@dataclass(frozen=True)
class _Snapshot:
    """All rows converted to domain objects (the input of every as-of view)."""

    assets: list[rules.Asset]
    types: list[rules.AssetType]
    active_types: list[rules.AssetType]
    status_events: list[rules.StatusEvent]
    maintenance: list[rules.MaintenanceEvent]


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


def _interval(value: object, field: str) -> int | None:
    """``None`` (not set) or a whole number of days >= 0 (0 = no scheduled maintenance, A06)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ServiceError(INVALID_INTERVAL, field)
    require(value >= 0, NEGATIVE_INTERVAL, field)
    return value


def _parse_status(value: object) -> AssetStatus:
    """A storable status; ``unknown`` and anything else is ``INVALID_STATUS`` (D26)."""
    if isinstance(value, str) and value in _STORABLE_STATUSES:
        return AssetStatus(value)
    raise ServiceError(INVALID_STATUS, "status")


def _parse_kind(value: object) -> MaintenanceKind:
    if isinstance(value, str) and value in {kind.value for kind in MaintenanceKind}:
        return MaintenanceKind(value)
    raise ServiceError(INVALID_MAINTENANCE_KIND, "kind")


@contextmanager
def _translated() -> Iterator[None]:
    """Turn the storage errors with a service meaning into service errors; re-raise the rest."""
    try:
        yield
    except (ReadOnlyDatabaseError, RowNotFoundError) as exc:
        raise translate_storage_error(exc) from exc


def _type_view(row: AssetTypeRow) -> AssetTypeView:
    return AssetTypeView(
        id=row.id,
        code=row.code,
        built_in=row.built_in,
        label_pt_br=row.label_pt_br,
        label_en_us=row.label_en_us,
        label_es_es=row.label_es_es,
        default_maintenance_interval_days=row.default_maintenance_interval_days,
        active=row.active,
    )


def _asset_view(row: AssetRow, type_codes: dict[int, str]) -> AssetView:
    return AssetView(
        id=row.id,
        tag=row.tag,
        type_id=row.type_id,
        type_code=type_codes.get(row.type_id, ""),
        description=row.description,
        location=row.location,
        in_service_from=parse_iso_date(row.in_service_from),
        in_service_until=(
            None if row.in_service_until is None else parse_iso_date(row.in_service_until)
        ),
        maintenance_interval_days=row.maintenance_interval_days,
        notes=row.notes,
    )


def _status_view(row: StatusEventRow) -> StatusEventView:
    return StatusEventView(
        id=row.id,
        asset_id=row.asset_id,
        effective_on=parse_iso_date(row.effective_on),
        status=AssetStatus(row.status),
        note=row.note,
    )


def _maintenance_view(row: MaintenanceRow) -> MaintenanceView:
    return MaintenanceView(
        id=row.id,
        asset_id=row.asset_id,
        performed_on=parse_iso_date(row.performed_on),
        kind=MaintenanceKind(row.kind),
        next_due_on=None if row.next_due_on is None else parse_iso_date(row.next_due_on),
        note=row.note,
    )


# --------------------------------------------------------------------------- the service


class InfrastructureService:
    """Create, change, delete and read asset types, assets, status events and maintenance."""

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

    def _type_row(self, type_id: int | None, field: str = "type_id") -> AssetTypeRow:
        if type_id is None:
            raise ServiceError(REQUIRED, field)
        row = repo.get_type(self._conn, type_id)
        if row is None:
            raise ServiceError(NOT_FOUND, field)
        return row

    def _asset_row(self, asset_id: int) -> AssetRow:
        row = repo.get_asset(self._conn, asset_id)
        if row is None:
            raise ServiceError(NOT_FOUND, "asset_id")
        return row

    def _status_row(self, event_id: int) -> StatusEventRow:
        row = repo.get_status_event(self._conn, event_id)
        if row is None:
            raise ServiceError(NOT_FOUND, "event_id")
        return row

    def _maintenance_row(self, maintenance_id: int) -> MaintenanceRow:
        row = repo.get_maintenance(self._conn, maintenance_id)
        if row is None:
            raise ServiceError(NOT_FOUND, "maintenance_id")
        return row

    def _type_codes(self) -> dict[int, str]:
        return {row.id: row.code for row in repo.list_types(self._conn)}

    # ----- asset types: validation

    def _validate_type(self, data: AssetTypeInput, current: AssetTypeRow | None) -> _TypeFields:
        code = _check_code(data.code)
        interval = _interval(
            data.default_maintenance_interval_days, "default_maintenance_interval_days"
        )
        if current is not None and current.built_in:
            # A built-in type keeps its code, its (empty) labels and its flag.
            require(code == current.code, BUILT_IN_TYPE, "code")
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
            if current is not None and code != current.code:
                require(not repo.type_in_use(self._conn, current.id), CODE_IMMUTABLE, "code")
        existing = repo.get_type_by_code(self._conn, code)
        require(
            existing is None or (current is not None and existing.id == current.id),
            DUPLICATE_CODE,
            "code",
        )
        return _TypeFields(
            code=code,
            label_pt_br=label_pt_br,
            label_en_us=label_en_us,
            label_es_es=label_es_es,
            default_maintenance_interval_days=interval,
            active=data.active,
        )

    # ----- asset types: writes

    def create_type(self, data: AssetTypeInput) -> int:
        """Create a user-defined asset type; returns its id."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            fields = self._validate_type(data, None)
            return repo.insert_type(
                self._ctx(),
                code=fields.code,
                built_in=False,
                label_pt_br=fields.label_pt_br,
                label_en_us=fields.label_en_us,
                label_es_es=fields.label_es_es,
                default_maintenance_interval_days=fields.default_maintenance_interval_days,
                active=fields.active,
            )

    def update_type(self, type_id: int, data: AssetTypeInput) -> None:
        """Change a type.

        Built-in types: only the default interval and ``active`` change (``BUILT_IN_TYPE`` when
        the code differs). User-defined types: the code is frozen once an asset uses it
        (``CODE_IMMUTABLE``).
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            current = self._type_row(type_id)
            fields = self._validate_type(data, current)
            repo.update_type(
                self._ctx(),
                type_id,
                code=fields.code,
                label_pt_br=fields.label_pt_br,
                label_en_us=fields.label_en_us,
                label_es_es=fields.label_es_es,
                default_maintenance_interval_days=fields.default_maintenance_interval_days,
                active=fields.active,
            )

    def deactivate_type(self, type_id: int) -> None:
        """Mark a type inactive (built-in ones too): it keeps its assets but gets no new ones."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            row = self._type_row(type_id)
            repo.update_type(
                self._ctx(),
                type_id,
                code=row.code,
                label_pt_br=row.label_pt_br,
                label_en_us=row.label_en_us,
                label_es_es=row.label_es_es,
                default_maintenance_interval_days=row.default_maintenance_interval_days,
                active=False,
            )

    def delete_type(self, type_id: int) -> None:
        """Delete a user-defined type that has no assets (``BUILT_IN_TYPE``, ``TYPE_IN_USE``)."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            row = self._type_row(type_id)
            require(not row.built_in, BUILT_IN_TYPE, "type_id")
            require(not repo.type_in_use(self._conn, type_id), TYPE_IN_USE, "type_id")
            try:
                repo.delete_type(self._ctx(), type_id)
            except ForeignKeyError:
                raise ServiceError(TYPE_IN_USE, "type_id") from None

    def list_types(self, include_inactive: bool = False) -> list[AssetTypeView]:
        """The types ordered by code; inactive ones only when asked for."""
        rows = repo.list_types(self._conn, include_inactive=include_inactive)
        return [_type_view(row) for row in rows]

    def get_type(self, type_id: int) -> AssetTypeView:
        """One type; ``NOT_FOUND`` when it does not exist."""
        return _type_view(self._type_row(type_id))

    # ----- assets: validation

    def _validate_asset(self, data: AssetInput, current: AssetRow | None) -> _AssetFields:
        tag = data.tag.strip()
        require(bool(tag), REQUIRED, "tag")
        require(len(tag) <= TAG_MAX_LENGTH, TEXT_TOO_LONG, "tag")
        type_row = self._type_row(data.type_id)
        in_service_from = _parse_date(data.in_service_from, "in_service_from")
        in_service_until = _parse_optional_date(data.in_service_until, "in_service_until")
        require(
            in_service_until is None or in_service_until >= in_service_from,
            IN_SERVICE_UNTIL_BEFORE_FROM,
            "in_service_until",
        )
        interval = _interval(data.maintenance_interval_days, "maintenance_interval_days")
        if current is None or current.type_id != type_row.id:
            require(type_row.active, TYPE_INACTIVE, "type_id")
        existing = repo.get_asset_by_tag(self._conn, tag)
        require(
            existing is None or (current is not None and existing.id == current.id),
            DUPLICATE_TAG,
            "tag",
        )
        return _AssetFields(
            type_id=type_row.id,
            tag=tag,
            description=_clean(data.description),
            location=_clean(data.location),
            in_service_from=in_service_from,
            in_service_until=in_service_until,
            maintenance_interval_days=interval,
            notes=_clean(data.notes),
        )

    # ----- assets: writes

    def create_asset(self, data: AssetInput, initial_status: AssetStatus | str | None) -> int:
        """Create an asset and its initial status event (dated ``in_service_from``).

        ``INITIAL_STATUS_REQUIRED`` when no initial status is given; both rows are written in one
        transaction, so a refusal leaves nothing behind. Returns the new asset id.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            fields = self._validate_asset(data, None)
            if initial_status is None or (
                isinstance(initial_status, str) and not initial_status.strip()
            ):
                raise ServiceError(INITIAL_STATUS_REQUIRED, "initial_status")
            status = _parse_status(initial_status)
            ctx = self._ctx()
            asset_id = repo.insert_asset(
                ctx,
                type_id=fields.type_id,
                tag=fields.tag,
                description=fields.description,
                location=fields.location,
                in_service_from=format_iso_date(fields.in_service_from),
                in_service_until=_optional_iso(fields.in_service_until),
                maintenance_interval_days=fields.maintenance_interval_days,
                notes=fields.notes,
            )
            repo.insert_status_event(
                ctx,
                asset_id=asset_id,
                effective_on=format_iso_date(fields.in_service_from),
                status=status.value,
                note=None,
            )
            return asset_id

    def update_asset(self, asset_id: int, data: AssetInput) -> None:
        """Change an asset.

        The initial status event keeps its own date when ``in_service_from`` changes; an in-service
        asset left without a status on the as-of date shows up in :meth:`data_quality`.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            current = self._asset_row(asset_id)
            fields = self._validate_asset(data, current)
            repo.update_asset(
                self._ctx(),
                asset_id,
                type_id=fields.type_id,
                tag=fields.tag,
                description=fields.description,
                location=fields.location,
                in_service_from=format_iso_date(fields.in_service_from),
                in_service_until=_optional_iso(fields.in_service_until),
                maintenance_interval_days=fields.maintenance_interval_days,
                notes=fields.notes,
            )

    def retire_asset(self, asset_id: int, in_service_until: str | date) -> None:
        """Retire an asset: it stays in the database with its history, last in service that day."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            row = self._asset_row(asset_id)
            until = _parse_date(in_service_until, "in_service_until")
            require(
                until >= parse_iso_date(row.in_service_from),
                IN_SERVICE_UNTIL_BEFORE_FROM,
                "in_service_until",
            )
            repo.update_asset(
                self._ctx(),
                asset_id,
                type_id=row.type_id,
                tag=row.tag,
                description=row.description,
                location=row.location,
                in_service_from=row.in_service_from,
                in_service_until=format_iso_date(until),
                maintenance_interval_days=row.maintenance_interval_days,
                notes=row.notes,
            )

    def delete_asset(self, asset_id: int) -> None:
        """Delete an asset entered by mistake with its status and maintenance events (logged).

        Use :meth:`retire_asset` for an asset that existed.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._asset_row(asset_id)
            repo.delete_asset(self._ctx(), asset_id)

    # ----- assets: reads

    def list_assets(
        self, type_id: int | None = None, in_service_on: date | None = None
    ) -> list[AssetView]:
        """The assets by tag; optionally of one type and/or only those in service on a date."""
        type_codes = self._type_codes()
        views: list[AssetView] = []
        for row in repo.list_assets(self._conn, type_id):
            view = _asset_view(row, type_codes)
            if in_service_on is not None and not rules.is_in_service(
                repo.asset_to_domain(row, type_codes), in_service_on
            ):
                continue
            views.append(view)
        return views

    def get_asset(self, asset_id: int) -> AssetDetail:
        """One asset with its status history and maintenance log; ``NOT_FOUND`` if missing."""
        row = self._asset_row(asset_id)
        history = self._history(asset_id)
        return AssetDetail(
            asset=_asset_view(row, self._type_codes()),
            status_events=history.status_events,
            maintenance_events=history.maintenance_events,
        )

    def _history(self, asset_id: int) -> AssetHistory:
        status = sorted(
            (_status_view(row) for row in repo.list_status_events(self._conn, asset_id)),
            key=lambda event: (event.effective_on, event.id),
        )
        maintenance = sorted(
            (_maintenance_view(row) for row in repo.list_maintenance(self._conn, asset_id)),
            key=lambda event: (event.performed_on, event.kind.value, event.id),
        )
        return AssetHistory(tuple(status), tuple(maintenance))

    def asset_history(self, asset_id: int) -> AssetHistory:
        """The status events and maintenance events of an asset sorted by date."""
        self._asset_row(asset_id)
        return self._history(asset_id)

    # ----- status events

    def change_status(
        self,
        asset_id: int,
        effective_on: str | date,
        status: AssetStatus | str,
        note: str | None = None,
    ) -> int:
        """Add a status event; one event per asset and day (``STATUS_DATE_TAKEN``)."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._asset_row(asset_id)
            day = _parse_date(effective_on, "effective_on")
            parsed = _parse_status(status)
            existing = repo.get_status_event_by_date(self._conn, asset_id, format_iso_date(day))
            require(existing is None, STATUS_DATE_TAKEN, "effective_on")
            return repo.insert_status_event(
                self._ctx(),
                asset_id=asset_id,
                effective_on=format_iso_date(day),
                status=parsed.value,
                note=_clean(note),
            )

    def update_status_event(
        self,
        event_id: int,
        effective_on: str | date,
        status: AssetStatus | str,
        note: str | None = None,
    ) -> None:
        """Correct a status event (date, status and note)."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            current = self._status_row(event_id)
            day = _parse_date(effective_on, "effective_on")
            parsed = _parse_status(status)
            existing = repo.get_status_event_by_date(
                self._conn, current.asset_id, format_iso_date(day)
            )
            require(existing is None or existing.id == event_id, STATUS_DATE_TAKEN, "effective_on")
            repo.update_status_event(
                self._ctx(),
                event_id,
                effective_on=format_iso_date(day),
                status=parsed.value,
                note=_clean(note),
            )

    def delete_status_event(self, event_id: int) -> None:
        """Delete a status event (a correction)."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._status_row(event_id)
            repo.delete_status_event(self._ctx(), event_id)

    # ----- maintenance events

    def _validate_maintenance(
        self,
        asset_id: int,
        maintenance_id: int | None,
        performed_on: str | date,
        kind: MaintenanceKind | str,
        next_due_on: str | date | None,
    ) -> tuple[date, MaintenanceKind, date | None]:
        performed = _parse_date(performed_on, "performed_on")
        parsed_kind = _parse_kind(kind)
        due = _parse_optional_date(next_due_on, "next_due_on")
        require(due is None or due >= performed, NEXT_DUE_BEFORE_PERFORMED, "next_due_on")
        existing = repo.get_maintenance_by_key(
            self._conn, asset_id, format_iso_date(performed), parsed_kind.value
        )
        require(
            existing is None or existing.id == maintenance_id,
            DUPLICATE_MAINTENANCE,
            "performed_on",
        )
        return performed, parsed_kind, due

    def record_maintenance(
        self,
        asset_id: int,
        performed_on: str | date,
        kind: MaintenanceKind | str,
        next_due_on: str | date | None = None,
        note: str | None = None,
    ) -> int:
        """Add a maintenance event; returns its id."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._asset_row(asset_id)
            performed, parsed_kind, due = self._validate_maintenance(
                asset_id, None, performed_on, kind, next_due_on
            )
            return repo.insert_maintenance(
                self._ctx(),
                asset_id=asset_id,
                performed_on=format_iso_date(performed),
                kind=parsed_kind.value,
                next_due_on=_optional_iso(due),
                note=_clean(note),
            )

    def update_maintenance(
        self,
        maintenance_id: int,
        performed_on: str | date,
        kind: MaintenanceKind | str,
        next_due_on: str | date | None = None,
        note: str | None = None,
    ) -> None:
        """Correct a maintenance event."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            current = self._maintenance_row(maintenance_id)
            performed, parsed_kind, due = self._validate_maintenance(
                current.asset_id, maintenance_id, performed_on, kind, next_due_on
            )
            repo.update_maintenance(
                self._ctx(),
                maintenance_id,
                performed_on=format_iso_date(performed),
                kind=parsed_kind.value,
                next_due_on=_optional_iso(due),
                note=_clean(note),
            )

    def delete_maintenance(self, maintenance_id: int) -> None:
        """Delete a maintenance event (a correction)."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._maintenance_row(maintenance_id)
            repo.delete_maintenance(self._ctx(), maintenance_id)

    # ----- as-of views (built with the domain functions)

    def _rules(self) -> rules.InfrastructureRules:
        config = load_config(self._conn)
        return rules.InfrastructureRules(
            maintenance_warning_days=config.maintenance_warning_days,
            degraded_counts_as_available=config.degraded_counts_as_available,
        )

    def _snapshot(self) -> _Snapshot:
        type_rows = repo.list_types(self._conn)
        type_codes = {row.id: row.code for row in type_rows}
        return _Snapshot(
            assets=[repo.asset_to_domain(row, type_codes) for row in repo.list_assets(self._conn)],
            types=[repo.type_to_domain(row) for row in type_rows],
            active_types=[repo.type_to_domain(row) for row in type_rows if row.active],
            status_events=[
                repo.status_event_to_domain(row) for row in repo.list_status_events(self._conn)
            ],
            maintenance=[
                repo.maintenance_to_domain(row) for row in repo.list_maintenance(self._conn)
            ],
        )

    def asset_rows(self, as_of: date) -> list[rules.AssetRow]:
        """A row for every asset as of ``as_of`` (domain rule), sorted by type code and tag."""
        data = self._snapshot()
        return rules.asset_rows(
            data.assets, data.types, data.status_events, data.maintenance, as_of, self._rules()
        )

    def maintenance_due_lists(self, as_of: date) -> rules.MaintenanceDueLists:
        """Overdue and due-soon rows of the assets in service on ``as_of`` (domain rule)."""
        data = self._snapshot()
        return rules.maintenance_due_lists(
            data.assets, data.types, data.status_events, data.maintenance, as_of, self._rules()
        )

    def data_quality(self, as_of: date) -> list[str]:
        """Tags of the assets in service on ``as_of`` whose status is ``unknown`` (D26), sorted."""
        data = self._snapshot()
        return rules.data_quality(data.assets, data.status_events, as_of)

    def indicator_values(self, as_of: date) -> list[IndicatorValue]:
        """The infrastructure indicator values for ALL active types (input of the indicators)."""
        data = self._snapshot()
        return rules.indicator_values(
            data.assets,
            data.active_types,
            data.status_events,
            data.maintenance,
            as_of,
            self._rules(),
        )

    def availability(self, as_of: date) -> list[TypeAvailability]:
        """Per active type, by code: assets in service and available on ``as_of``.

        Taken from ``INFRA_AVAILABLE`` of :meth:`indicator_values`; "available" is not "free"
        (A01: no occupancy is tracked).
        """
        result: list[TypeAvailability] = []
        for value in self.indicator_values(as_of):
            if value.code != "INFRA_AVAILABLE":
                continue
            context = value.context or {}
            result.append(
                TypeAvailability(
                    type_code=decode_dimension(value.dimension)["type"],
                    available=int(value.value or 0.0),
                    in_service=int(context.get("in_service", 0.0)),
                )
            )
        return result
