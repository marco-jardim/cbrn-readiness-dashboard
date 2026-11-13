# SPDX-License-Identifier: GPL-3.0-or-later
"""Alert rules (PLAN T6.2, section 5.5, A03, A06, P01, P02, D24, R25-R27).

Pure domain code: no Qt, no I/O, no clock. Alerts are computed when needed and never stored. EVERY
function takes the as-of date ``d`` explicitly, so a past date gives the alerts of THAT date. Only
codes and numbers are produced; the UI builds the localized message from the kind and the
parameters.

Nothing is re-implemented here: the certificate rule (A03, D24, P01) comes from
:mod:`cbrn_dashboard.domain.personnel` and the due-date rule (A06, P02) from
:mod:`cbrn_dashboard.domain.infrastructure`, so the alerts, the lists and the indicators can never
disagree.

Rules
-----
* Certificates: for each ACTIVE person and each level, the counting certificate (A03) gives at most
  ONE alert. No certificate or "no renewal" on ``d`` (``no_renewal_from <= d``): none. Expired
  (``valid_until < d``): ``CERT_EXPIRED``. Valid and expiring (P01): ``CERT_EXPIRING``.
* Maintenance: for each asset IN SERVICE on ``d``, at most ONE alert. Overdue: ``MAINT_OVERDUE``;
  due soon: ``MAINT_DUE_SOON``; unknown schedule: ``MAINT_SCHEDULE_UNKNOWN``. An interval of 0
  without a recorded next-due date means "no scheduled maintenance" and raises nothing (A06).
* Indicators: one alert per reading with status ``WARNING`` or ``CRITICAL``. Readings without an
  enabled target are ``NO_TARGET`` and therefore never alert.
* Order: severity (critical, warning, info), then due date ascending with undated alerts last, then
  (module, kind, subject reference, dimension) so the order is fully deterministic.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType

from cbrn_dashboard.domain.dates import days_between
from cbrn_dashboard.domain.indicators import (
    IndicatorReading,
    IndicatorRegistry,
    IndicatorStatus,
    Module,
    encode_dimension,
)
from cbrn_dashboard.domain.infrastructure import (
    Asset,
    AssetType,
    InfrastructureRules,
    MaintenanceEvent,
    ScheduleBasis,
    StatusEvent,
    asset_rows,
)
from cbrn_dashboard.domain.personnel import (
    Certificate,
    PersonnelRules,
    PpeLevel,
    StaffMember,
    counting_certificate,
    is_active,
    is_expiring,
    is_no_renewal,
    is_valid,
)

_LEVEL_KEY = "level"


# --------------------------------------------------------------------------------------------
# Types
# --------------------------------------------------------------------------------------------


class AlertKind(StrEnum):
    """Alert kinds of PLAN 5.5; the value is the stable code."""

    CERT_EXPIRED = "CERT_EXPIRED"
    CERT_EXPIRING = "CERT_EXPIRING"
    MAINT_OVERDUE = "MAINT_OVERDUE"
    MAINT_DUE_SOON = "MAINT_DUE_SOON"
    MAINT_SCHEDULE_UNKNOWN = "MAINT_SCHEDULE_UNKNOWN"
    INDICATOR_WARNING = "INDICATOR_WARNING"
    INDICATOR_CRITICAL = "INDICATOR_CRITICAL"


class Severity(StrEnum):
    """Alert severity; :attr:`rank` is 0 for the most severe (critical first)."""

    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK: Mapping[Severity, int] = MappingProxyType(
    {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
)

SEVERITY_OF: Mapping[AlertKind, Severity] = MappingProxyType(
    {
        AlertKind.CERT_EXPIRED: Severity.CRITICAL,
        AlertKind.CERT_EXPIRING: Severity.WARNING,
        AlertKind.MAINT_OVERDUE: Severity.CRITICAL,
        AlertKind.MAINT_DUE_SOON: Severity.WARNING,
        AlertKind.MAINT_SCHEDULE_UNKNOWN: Severity.INFO,
        AlertKind.INDICATOR_WARNING: Severity.WARNING,
        AlertKind.INDICATOR_CRITICAL: Severity.CRITICAL,
    }
)


class SubjectKind(StrEnum):
    """What the alert is about, so the UI can open the page of the record."""

    STAFF = "STAFF"
    ASSET = "ASSET"
    INDICATOR = "INDICATOR"


@dataclass(frozen=True)
class Alert:
    """One alert, as codes and numbers only.

    ``subject_ref`` is the staff identifier, the asset tag or the indicator code. ``subject_id`` is
    the staff or asset id for navigation (``None`` for indicators). ``dimension`` is ``level=A``
    for certificates, the indicator dimension for indicator alerts and ``""`` otherwise.
    ``days_remaining`` is signed (``days_between(d, due_on)``): negative when overdue or expired,
    ``None`` when there is no date. ``value`` and ``threshold`` are set for indicator alerts only.
    """

    kind: AlertKind
    severity: Severity
    module: Module
    subject_kind: SubjectKind
    subject_ref: str
    subject_id: int | None = None
    dimension: str = ""
    due_on: date | None = None
    days_remaining: int | None = None
    value: float | None = None
    threshold: float | None = None


# --------------------------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------------------------


def certificate_alerts(
    staff: Iterable[StaffMember],
    certs: Iterable[Certificate],
    d: date,
    rules: PersonnelRules,
) -> list[Alert]:
    """At most one alert per ACTIVE person and level, from the counting certificate (A03).

    "No renewal" on ``d`` (D24) suppresses both kinds, an expired certificate included.
    """
    pending = list(certs)
    alerts: list[Alert] = []
    for person in staff:
        if not is_active(person, d):
            continue
        for level in PpeLevel:
            counting = counting_certificate(pending, person.id, level, d, rules)
            if counting is None or is_no_renewal(counting, d):
                continue
            if not is_valid(counting, d):
                kind = AlertKind.CERT_EXPIRED
            elif is_expiring(counting, d, rules):
                kind = AlertKind.CERT_EXPIRING
            else:
                continue
            alerts.append(
                Alert(
                    kind=kind,
                    severity=SEVERITY_OF[kind],
                    module=Module.PERSONNEL,
                    subject_kind=SubjectKind.STAFF,
                    subject_ref=person.identifier,
                    subject_id=person.id,
                    dimension=encode_dimension({_LEVEL_KEY: level.value}),
                    due_on=counting.valid_until,
                    days_remaining=days_between(d, counting.valid_until),
                )
            )
    return alerts


def maintenance_alerts(
    assets: Iterable[Asset],
    types: Iterable[AssetType],
    status_events: Iterable[StatusEvent],
    maintenance: Iterable[MaintenanceEvent],
    d: date,
    rules: InfrastructureRules,
) -> list[Alert]:
    """At most one alert per asset in service on ``d``; others (retired, not yet) give none.

    Interval 0 without a recorded next-due date (no scheduled maintenance) raises nothing (A06).
    """
    alerts: list[Alert] = []
    for row in asset_rows(assets, types, status_events, maintenance, d, rules):
        if not row.in_service:
            continue
        if row.overdue:
            kind = AlertKind.MAINT_OVERDUE
        elif row.due_soon:
            kind = AlertKind.MAINT_DUE_SOON
        elif row.basis is ScheduleBasis.UNKNOWN:
            kind = AlertKind.MAINT_SCHEDULE_UNKNOWN
        else:
            continue
        alerts.append(
            Alert(
                kind=kind,
                severity=SEVERITY_OF[kind],
                module=Module.INFRASTRUCTURE,
                subject_kind=SubjectKind.ASSET,
                subject_ref=row.tag,
                subject_id=row.asset_id,
                due_on=row.due_on,
                days_remaining=None if row.due_on is None else days_between(d, row.due_on),
            )
        )
    return alerts


def indicator_alerts(
    readings: Iterable[IndicatorReading],
    registry: IndicatorRegistry,
) -> list[Alert]:
    """One alert per reading with status WARNING or CRITICAL.

    ``threshold`` is the threshold that was crossed. A code missing from ``registry`` raises
    :class:`~cbrn_dashboard.domain.indicators.UnknownIndicatorError`.
    """
    alerts: list[Alert] = []
    for reading in readings:
        definition = registry.get(reading.code)
        if reading.status is IndicatorStatus.CRITICAL:
            kind = AlertKind.INDICATOR_CRITICAL
            threshold = reading.critical_value
        elif reading.status is IndicatorStatus.WARNING:
            kind = AlertKind.INDICATOR_WARNING
            threshold = reading.warning_value
        else:
            continue
        alerts.append(
            Alert(
                kind=kind,
                severity=SEVERITY_OF[kind],
                module=definition.module,
                subject_kind=SubjectKind.INDICATOR,
                subject_ref=reading.code,
                subject_id=None,
                dimension=reading.dimension,
                value=reading.value,
                threshold=threshold,
            )
        )
    return alerts


# --------------------------------------------------------------------------------------------
# Ordering and summaries
# --------------------------------------------------------------------------------------------


def _sort_key(alert: Alert) -> tuple[int, bool, date, str, str, str, str, int]:
    return (
        alert.severity.rank,
        alert.due_on is None,
        date.min if alert.due_on is None else alert.due_on,
        alert.module.value,
        alert.kind.value,
        alert.subject_ref,
        alert.dimension,
        -1 if alert.subject_id is None else alert.subject_id,
    )


def sort_alerts(alerts: Iterable[Alert]) -> list[Alert]:
    """Severity (critical first), then due date (undated last), then a stable tie-break."""
    return sorted(alerts, key=_sort_key)


def all_alerts(
    *,
    staff: Iterable[StaffMember],
    certs: Iterable[Certificate],
    personnel_rules: PersonnelRules,
    assets: Iterable[Asset],
    asset_types: Iterable[AssetType],
    status_events: Iterable[StatusEvent],
    maintenance: Iterable[MaintenanceEvent],
    infrastructure_rules: InfrastructureRules,
    readings: Iterable[IndicatorReading],
    registry: IndicatorRegistry,
    d: date,
) -> list[Alert]:
    """Certificate, maintenance and indicator alerts as of ``d``, sorted by :func:`sort_alerts`."""
    combined = certificate_alerts(staff, certs, d, personnel_rules)
    combined.extend(
        maintenance_alerts(assets, asset_types, status_events, maintenance, d, infrastructure_rules)
    )
    combined.extend(indicator_alerts(readings, registry))
    return sort_alerts(combined)


def count_by_severity(alerts: Iterable[Alert]) -> Mapping[Severity, int]:
    """Number of alerts per severity; always has all three keys."""
    counts = dict.fromkeys(Severity, 0)
    for alert in alerts:
        counts[alert.severity] += 1
    return MappingProxyType(counts)


def has_actionable(alerts: Iterable[Alert]) -> bool:
    """True when at least one alert is WARNING or CRITICAL (info never triggers the summary)."""
    return any(alert.severity is not Severity.INFO for alert in alerts)
