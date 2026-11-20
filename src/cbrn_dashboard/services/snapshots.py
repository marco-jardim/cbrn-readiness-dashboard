# SPDX-License-Identifier: GPL-3.0-or-later
"""Readiness snapshots: the only record of what was known and configured at the time
(PLAN.md T8.1, D13, D21, P04, K13, R31).

Qt-free. A snapshot stores, for every (indicator code, dimension) of
:meth:`~cbrn_dashboard.services.indicators.IndicatorService.evaluate`, the value, the status and
the targets in force (the thresholds on the reading), together with the application version, the
configuration hash and the hashed configuration itself. Time comes only from the injected clock.

Origin rule (K13). The caller passes ``manual``, ``monthly`` or ``report``; the SERVICE decides what
is stored: when the LOCAL date on which the snapshot is taken is after ``as_of`` the origin is
``retroactive`` whatever was passed. Passing ``retroactive`` is accepted only when it is true
(``ORIGIN_NOT_ALLOWED`` otherwise) and an ``as_of`` in the future is refused (``AS_OF_IN_FUTURE``).

Configuration hash. :func:`hashed_config` builds the canonical structure of EXACTLY these fields:
P01 ``cert_warning_days``, P02 ``maintenance_warning_days``, P03 every stored target (with its
``enabled`` flag), P04 ``snapshot_monthly`` and ``snapshot_on_report``, P08
``budget_prorate_target``,
A02 ``ppe_hierarchy_enabled`` and ``ppe_hierarchy``, A04 ``ppe_validity_months``, A05
``degraded_counts_as_available``, A06 the default maintenance interval of every asset type
(inactive types included), P11 ``stock_expiry_warning_days`` and P12
``stock_item_type_minimum_quantity`` (the minimum of every stock item type, by type code; ``null``
when none is set). The two stock fields were added in 1.1.0, so the hash changes once on upgrade
(K21); a snapshot taken before then has no ``STOCK_*`` value, which reads as "no data", never as
zero. Nothing else is hashed: not the operator label, the institution and unit
names, the handling notice, P05, P06, P09, the default currency or the small-count threshold.
``config_json`` is that structure serialised by :func:`canonical_json` and ``config_hash`` is the
SHA-256 hex digest of that exact text, so the hash can always be re-derived from the stored JSON.

A snapshot is NEVER updated or deleted (the migration's triggers refuse both and this service has no
such method). :meth:`SnapshotService.withdraw` appends a ``snapshot_withdrawal`` row (with a
mandatory reason) through the repository helper, so a ``change_log`` row is written. Withdrawn
snapshots stay stored with their values and are ignored by lists unless asked for.

Monthly snapshot (P04). The start-up registry of ``app.py`` registers the hook once, in ONE line::

    StartupHook(
        "monthly-snapshot", monthly_snapshot_startup,
        runs_read_only=False, runs_in_demo=False, needs_trusted_clock=True,
    )

It is skipped in read-only mode, in demo mode and, for the session, when the clock sanity check
failed. Several starts in one LOCAL calendar month produce exactly one monthly snapshot.

Log lines carry event codes only (``SNAPSHOT.RECORDED``, ``SNAPSHOT.WITHDRAWN``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol

from cbrn_dashboard import __version__
from cbrn_dashboard.clock import Clock
from cbrn_dashboard.domain.config import ReadinessConfig
from cbrn_dashboard.domain.dates import (
    format_utc_timestamp,
    is_same_month,
    parse_utc_timestamp,
)
from cbrn_dashboard.domain.indicators import IndicatorStatus
from cbrn_dashboard.logging_setup import log_event
from cbrn_dashboard.services.errors import (
    INVALID_DATE,
    NOT_FOUND,
    READ_ONLY,
    ServiceError,
    require,
    translate_storage_error,
)
from cbrn_dashboard.services.indicators import IndicatorService, TargetView
from cbrn_dashboard.services.infrastructure import AssetTypeView, InfrastructureService
from cbrn_dashboard.services.stock import StockService, StockTypeView
from cbrn_dashboard.storage import snapshots_repo as repo
from cbrn_dashboard.storage.db import DatabaseConnection, ReadOnlyDatabaseError, transaction
from cbrn_dashboard.storage.repository import RowNotFoundError, WriteContext
from cbrn_dashboard.storage.settings_repo import load_config
from cbrn_dashboard.storage.snapshots_repo import SnapshotRow, SnapshotValueRow

__all__ = [
    "ALREADY_WITHDRAWN",
    "AS_OF_IN_FUTURE",
    "HASHED_FIELDS",
    "ORIGIN_NOT_ALLOWED",
    "REASON_REQUIRED",
    "SnapshotDetail",
    "SnapshotOrigin",
    "SnapshotService",
    "SnapshotValue",
    "SnapshotView",
    "StartupContext",
    "canonical_json",
    "config_hash",
    "hashed_config",
    "monthly_snapshot_startup",
]

# Error codes of this service (the shared ones are in services/errors.py).
#: The as-of date is after the local date of today: a reading cannot be recorded in advance.
AS_OF_IN_FUTURE = "AS_OF_IN_FUTURE"
#: The origin cannot be stored: ``retroactive`` was requested for a snapshot taken on its as-of
#: day, or the origin is not one of the four known ones.
ORIGIN_NOT_ALLOWED = "ORIGIN_NOT_ALLOWED"
#: A withdrawal needs a non-blank reason.
REASON_REQUIRED = "REASON_REQUIRED"
#: The snapshot has already been withdrawn.
ALREADY_WITHDRAWN = "ALREADY_WITHDRAWN"

#: The top-level keys of the hashed structure (and so of ``config_json``), sorted.
HASHED_FIELDS: tuple[str, ...] = (
    "asset_type_default_maintenance_interval_days",
    "budget_prorate_target",
    "cert_warning_days",
    "degraded_counts_as_available",
    "maintenance_warning_days",
    "ppe_hierarchy",
    "ppe_hierarchy_enabled",
    "ppe_validity_months",
    "snapshot_monthly",
    "snapshot_on_report",
    "stock_expiry_warning_days",
    "stock_item_type_minimum_quantity",
    "targets",
)


class SnapshotOrigin(StrEnum):
    """Why a snapshot was taken (the CHECK constraint of migration 0007)."""

    MANUAL = "manual"
    MONTHLY = "monthly"
    REPORT = "report"
    RETROACTIVE = "retroactive"


# --------------------------------------------------------------------------- configuration hash


def hashed_config(
    config: ReadinessConfig,
    targets: Iterable[TargetView],
    asset_types: Iterable[AssetTypeView],
    stock_types: Iterable[StockTypeView] = (),
) -> dict[str, object]:
    """The canonical structure that is hashed: exactly the fields of the module docstring.

    Targets are sorted by code and then dimension, the ``ppe_hierarchy`` lists are sorted, and the
    asset-type intervals and the stock minimums are keyed by type code (``None`` = no minimum).
    Key order is made canonical by :func:`canonical_json`.
    """
    return {
        "cert_warning_days": config.cert_warning_days,
        "maintenance_warning_days": config.maintenance_warning_days,
        "targets": [
            {
                "indicator_code": target.indicator_code,
                "dimension": target.dimension,
                "warning_value": target.warning_value,
                "critical_value": target.critical_value,
                "enabled": bool(target.enabled),
            }
            for target in sorted(targets, key=lambda t: (t.indicator_code, t.dimension))
        ],
        "snapshot_monthly": config.snapshot_monthly,
        "snapshot_on_report": config.snapshot_on_report,
        "budget_prorate_target": config.budget_prorate_target,
        "ppe_hierarchy_enabled": config.ppe_hierarchy_enabled,
        "ppe_hierarchy": {str(level): sorted(also) for level, also in config.ppe_hierarchy.items()},
        "ppe_validity_months": {
            str(level): months for level, months in config.ppe_validity_months.items()
        },
        "degraded_counts_as_available": config.degraded_counts_as_available,
        "asset_type_default_maintenance_interval_days": {
            asset_type.code: asset_type.default_maintenance_interval_days
            for asset_type in sorted(asset_types, key=lambda t: t.code)
        },
        "stock_expiry_warning_days": config.stock_expiry_warning_days,
        "stock_item_type_minimum_quantity": {
            item.code: item.minimum_quantity for item in sorted(stock_types, key=lambda t: t.code)
        },
    }


def canonical_json(structure: dict[str, object]) -> str:
    """The exact text that is stored as ``config_json`` and hashed."""
    return json.dumps(structure, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def config_hash(config_json: str) -> str:
    """SHA-256 hex digest of ``config_json`` (UTF-8)."""
    return hashlib.sha256(config_json.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- views


@dataclass(frozen=True)
class SnapshotView:
    """The header of a stored snapshot; the ``withdrawn_*`` fields are set when it is withdrawn."""

    id: int
    taken_at_utc: str
    as_of: date
    origin: SnapshotOrigin
    app_version: str
    config_hash: str
    note: str | None
    withdrawn: bool
    withdrawn_at_utc: str | None
    withdrawal_reason: str | None


@dataclass(frozen=True)
class SnapshotValue:
    """One stored reading: value, status and the targets in force."""

    indicator_code: str
    dimension: str
    value: float | None
    status: IndicatorStatus
    warning_value: float | None
    critical_value: float | None


@dataclass(frozen=True)
class SnapshotDetail:
    """A snapshot with its configuration text and all its values."""

    snapshot: SnapshotView
    config_json: str
    values: tuple[SnapshotValue, ...]


def _view(row: SnapshotRow) -> SnapshotView:
    return SnapshotView(
        id=row.id,
        taken_at_utc=row.taken_at_utc,
        as_of=date.fromisoformat(row.as_of),
        origin=SnapshotOrigin(row.origin),
        app_version=row.app_version,
        config_hash=row.config_hash,
        note=row.note,
        withdrawn=row.withdrawn,
        withdrawn_at_utc=row.withdrawn_at_utc,
        withdrawal_reason=row.withdrawal_reason,
    )


def _value(row: SnapshotValueRow) -> SnapshotValue:
    return SnapshotValue(
        indicator_code=row.indicator_code,
        dimension=row.dimension,
        value=row.value,
        status=IndicatorStatus(row.status),
        warning_value=row.warning_value,
        critical_value=row.critical_value,
    )


@contextmanager
def _translated() -> Iterator[None]:
    """Turn the storage errors with a service meaning into service errors; re-raise the rest."""
    try:
        yield
    except (ReadOnlyDatabaseError, RowNotFoundError) as exc:
        raise translate_storage_error(exc) from exc


# --------------------------------------------------------------------------- the service


class SnapshotService:
    """Record, list and withdraw readiness snapshots; take the monthly one (P04)."""

    def __init__(
        self,
        conn: DatabaseConnection,
        clock: Clock,
        operator: Callable[[], str] = lambda: "",
        *,
        indicators: IndicatorService,
        infrastructure: InfrastructureService,
        app_version: str | None = None,
        stock: StockService | None = None,
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._operator = operator
        self._indicators = indicators
        self._infrastructure = infrastructure
        self._stock = stock
        self._app_version = __version__ if app_version is None else app_version

    # ----- plumbing

    def _ctx(self) -> WriteContext:
        return WriteContext(self._conn, self._clock, self._operator())

    def _require_writable(self) -> None:
        require(not self._conn.read_only, READ_ONLY)

    def _row(self, snapshot_id: int) -> SnapshotRow:
        row = repo.get_snapshot(self._conn, snapshot_id)
        if row is None:
            raise ServiceError(NOT_FOUND)
        return row

    # ----- configuration

    def current_config(self) -> tuple[str, str]:
        """``(config_json, config_hash)`` of the configuration in force now."""
        structure = hashed_config(
            load_config(self._conn),
            self._indicators.list_targets(),
            self._infrastructure.list_types(include_inactive=True),
            stock_types=(
                () if self._stock is None else self._stock.list_types(include_inactive=True)
            ),
        )
        text = canonical_json(structure)
        return text, config_hash(text)

    # ----- recording

    def _stored_origin(self, as_of: date, origin: SnapshotOrigin) -> SnapshotOrigin:
        """The origin the service stores (K13); the caller cannot override it."""
        today = self._clock.local_date()
        require(as_of <= today, AS_OF_IN_FUTURE, "as_of")
        if as_of < today:
            return SnapshotOrigin.RETROACTIVE
        # Taken on its as-of day: a retroactive origin would be untrue.
        require(origin is not SnapshotOrigin.RETROACTIVE, ORIGIN_NOT_ALLOWED, "origin")
        return origin

    def record(
        self, as_of: date, *, origin: SnapshotOrigin, note: str | None = None
    ) -> SnapshotView:
        """Record a snapshot of every indicator for ``as_of`` in ONE transaction.

        Refusals (nothing is written): ``READ_ONLY`` (checked first), ``INVALID_DATE``,
        ``AS_OF_IN_FUTURE`` and ``ORIGIN_NOT_ALLOWED``. The stored origin is decided here, see the
        module docstring.
        """
        self._require_writable()
        require(isinstance(as_of, date) and not isinstance(as_of, datetime), INVALID_DATE, "as_of")
        try:
            requested = SnapshotOrigin(origin)
        except ValueError:
            raise ServiceError(ORIGIN_NOT_ALLOWED, "origin") from None
        stored_origin = self._stored_origin(as_of, requested)
        with _translated(), transaction(self._conn):
            readings = self._indicators.evaluate(as_of)
            config_json, digest = self.current_config()
            ctx = self._ctx()
            snapshot_id = repo.insert_snapshot(
                ctx,
                taken_at_utc=format_utc_timestamp(self._clock.utc_now()),
                as_of=as_of.isoformat(),
                origin=stored_origin.value,
                app_version=self._app_version,
                config_hash=digest,
                config_json=config_json,
                note=note,
            )
            repo.insert_values(
                ctx,
                snapshot_id,
                [
                    SnapshotValueRow(
                        snapshot_id=snapshot_id,
                        indicator_code=reading.code,
                        dimension=reading.dimension,
                        value=reading.value,
                        status=reading.status.value,
                        warning_value=reading.warning_value,
                        critical_value=reading.critical_value,
                    )
                    for reading in readings
                ],
            )
            count = len(readings)
            view = _view(self._row(snapshot_id))
        log_event("SNAPSHOT.RECORDED", count=count)
        return view

    # ----- withdrawing

    def withdraw(self, snapshot_id: int, reason: str) -> None:
        """Withdraw a snapshot by appending a ``snapshot_withdrawal`` row; nothing is deleted.

        Refusals: ``READ_ONLY`` (first), ``REASON_REQUIRED`` (blank reason), ``NOT_FOUND`` and
        ``ALREADY_WITHDRAWN``. The operator label and the time are recorded with the reason.
        """
        self._require_writable()
        require(isinstance(reason, str) and bool(reason.strip()), REASON_REQUIRED, "reason")
        with _translated(), transaction(self._conn):
            row = self._row(snapshot_id)
            require(not row.withdrawn, ALREADY_WITHDRAWN)
            repo.insert_withdrawal(
                self._ctx(),
                snapshot_id,
                withdrawn_at_utc=format_utc_timestamp(self._clock.utc_now()),
                reason=reason.strip(),
                operator=self._operator(),
            )
        log_event("SNAPSHOT.WITHDRAWN")

    # ----- reads

    def list_snapshots(self, *, include_withdrawn: bool = False) -> list[SnapshotView]:
        """The snapshots, newest first; withdrawn ones only when asked for (and then flagged)."""
        rows = repo.list_snapshots(self._conn, include_withdrawn=include_withdrawn)
        return [_view(row) for row in rows]

    def get(self, snapshot_id: int) -> SnapshotDetail:
        """A snapshot (withdrawn or not) with its configuration text and values; ``NOT_FOUND``."""
        row = self._row(snapshot_id)
        return SnapshotDetail(
            snapshot=_view(row),
            config_json=row.config_json,
            values=tuple(_value(item) for item in repo.list_values(self._conn, snapshot_id)),
        )

    def values(self, snapshot_id: int) -> list[SnapshotValue]:
        """The stored readings of a snapshot, by code and dimension; ``NOT_FOUND``."""
        self._row(snapshot_id)
        return [_value(item) for item in repo.list_values(self._conn, snapshot_id)]

    # ----- monthly snapshot (P04)

    def monthly_due(self) -> bool:
        """Whether a monthly snapshot is due: P04 is on and no snapshot of origin ``monthly``, a
        withdrawn one included, was taken in the current LOCAL calendar month."""
        if not load_config(self._conn).snapshot_monthly:
            return False
        today = self._clock.local_date()
        return not any(
            is_same_month(self._clock.local_date_of(parse_utc_timestamp(taken_at)), today)
            for taken_at in repo.monthly_taken_times(self._conn)
        )

    def record_monthly_if_due(self) -> SnapshotView | None:
        """Record the monthly snapshot for today when :meth:`monthly_due`; else return ``None``.

        ``READ_ONLY`` is raised first on a read-only connection.
        """
        self._require_writable()
        if not self.monthly_due():
            return None
        return self.record(self._clock.local_date(), origin=SnapshotOrigin.MONTHLY)


# --------------------------------------------------------------------------- start-up hook


class _ServicesLike(Protocol):
    """The part of the shell's services the hook needs (either may still be ``None``)."""

    @property
    def indicators(self) -> IndicatorService | None: ...

    @property
    def infrastructure(self) -> InfrastructureService | None: ...

    # ``stock`` is read with ``getattr``: a services object without it (older callers, fakes)
    # still works and then hashes no stock minimums.


class StartupContext(Protocol):
    """The part of the application context the hook reads (``ui.shell.context.AppContext``)."""

    @property
    def conn(self) -> DatabaseConnection | None: ...

    @property
    def clock(self) -> Clock: ...

    @property
    def services(self) -> _ServicesLike: ...


def monthly_snapshot_startup(context: StartupContext) -> None:
    """``StartupHook.run`` callable: record the monthly snapshot of P04 when it is due.

    Does nothing when there is no open database or a needed service is missing. The registration
    (module docstring) declares that the hook does not run in read-only mode, in demo mode or
    when the clock is suspect. The snapshot carries no operator label: the program took it.
    """
    conn = context.conn
    if conn is None:
        return
    services = context.services
    indicators = services.indicators
    infrastructure = services.infrastructure
    if indicators is None or infrastructure is None:
        return
    # A hook run must hash the same configuration as a manual snapshot: stock included (T11.7).
    stock: StockService | None = getattr(services, "stock", None)
    SnapshotService(
        conn, context.clock, indicators=indicators, infrastructure=infrastructure, stock=stock
    ).record_monthly_if_due()
