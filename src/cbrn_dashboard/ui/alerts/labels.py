# SPDX-License-Identifier: GPL-3.0-or-later
"""Translated labels and messages of the alerts UI (PLAN.md section 6, T6.3).

Severities, modules and alert kinds are CODES; this module turns them into translated texts. An
unknown code is shown as itself, never as an exception. The message of an alert is built from its
kind and its parameters (subject, certificate level, days remaining, indicator value and threshold);
the day counts use ``%n`` plural forms, the other values are substituted in ONE pass so a value that
looks like a placeholder is never replaced again. Subjects (staff identifiers, asset tags,
indicator codes and dimensions) are data and are shown unchanged.
"""

import re
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle

from cbrn_dashboard.domain.alerts import Alert, AlertKind, Severity, SubjectKind
from cbrn_dashboard.domain.indicators import InvalidDimensionError, Module, decode_dimension
from cbrn_dashboard.ui.shell.formatting import FormatError, format_number
from cbrn_dashboard.ui.shell.widgets import label_for

__all__ = [
    "ALL_KIND_CODES",
    "ALL_MODULE_CODES",
    "ALL_SEVERITY_CODES",
    "alert_message",
    "kind_message",
    "module_label",
    "severity_icon",
    "severity_label",
    "subject_text",
]

#: A missing value in a message (data, not a translatable text).
NOT_RECORDED = "-"

_SEVERITY_LABELS: dict[str, Callable[[], str]] = {
    Severity.CRITICAL.value: lambda: QCoreApplication.translate("Alerts", "Critical"),
    Severity.WARNING.value: lambda: QCoreApplication.translate("Alerts", "Warning"),
    Severity.INFO.value: lambda: QCoreApplication.translate("Alerts", "Information"),
}

_MODULE_LABELS: dict[str, Callable[[], str]] = {
    Module.PERSONNEL.value: lambda: QCoreApplication.translate("Alerts", "Personnel"),
    Module.INFRASTRUCTURE.value: lambda: QCoreApplication.translate("Alerts", "Infrastructure"),
    Module.EXERCISES.value: lambda: QCoreApplication.translate("Alerts", "Exercises"),
    Module.BUDGET.value: lambda: QCoreApplication.translate("Alerts", "Budget"),
}

#: The icon of each severity: the shapes differ (never colour alone, D23).
_SEVERITY_ICONS: dict[str, QStyle.StandardPixmap] = {
    Severity.CRITICAL.value: QStyle.StandardPixmap.SP_MessageBoxCritical,
    Severity.WARNING.value: QStyle.StandardPixmap.SP_MessageBoxWarning,
    Severity.INFO.value: QStyle.StandardPixmap.SP_MessageBoxInformation,
}

#: Every severity, module and alert-kind code (for the completeness tests).
ALL_SEVERITY_CODES: tuple[str, ...] = tuple(_SEVERITY_LABELS)
ALL_MODULE_CODES: tuple[str, ...] = tuple(_MODULE_LABELS)


def severity_label(code: str) -> str:
    """The translated name of a severity code (the code itself when unknown)."""
    return label_for(_SEVERITY_LABELS, str(code))


def module_label(code: str) -> str:
    """The translated name of a module code (the code itself when unknown)."""
    return label_for(_MODULE_LABELS, str(code))


def severity_icon(code: str) -> QIcon:
    """The icon of a severity code (an empty icon when unknown); needs a ``QApplication``."""
    pixmap = _SEVERITY_ICONS.get(str(code))
    if pixmap is None:
        return QIcon()
    return QApplication.style().standardIcon(pixmap)


# --------------------------------------------------------------------------- message pieces

_PLACEHOLDER = re.compile(r"%([1-9])")


def _fill(text: str, *values: str) -> str:
    """Replace ``%1``..``%9`` by ``values`` in one pass (a translation may reorder them)."""

    def substitute(match: re.Match[str]) -> str:
        position = int(match.group(1)) - 1
        return values[position] if position < len(values) else match.group(0)

    return _PLACEHOLDER.sub(substitute, text)


def _days(alert: Alert) -> int:
    """The size of the distance to the due date, in days (0 without a date)."""
    return 0 if alert.days_remaining is None else abs(alert.days_remaining)


def _level(alert: Alert) -> str:
    """The certificate level of an alert (``level=A`` -> ``A``)."""
    try:
        parts = decode_dimension(alert.dimension)
    except InvalidDimensionError:
        return alert.dimension
    return parts.get("level", alert.dimension)


def _number(value: float | None, lang: str) -> str:
    """A value or threshold: whole numbers without decimals, else two places, locale separators."""
    if value is None:
        return NOT_RECORDED
    rounded = round(float(value), 2)
    number: float | int = int(rounded) if rounded.is_integer() else rounded
    try:
        return format_number(number, lang)
    except FormatError:
        return NOT_RECORDED


def subject_text(alert: Alert) -> str:
    """The subject of an alert: staff identifier, asset tag, or indicator code and dimension."""
    if alert.subject_kind is SubjectKind.INDICATOR and alert.dimension:
        return f"{alert.subject_ref} ({alert.dimension})"
    return alert.subject_ref


# --------------------------------------------------------------------------- messages


def _cert_expired(alert: Alert, lang: str) -> str:
    text = QCoreApplication.translate(
        "Alerts", "The level %1 certificate of %2 expired %n day(s) ago.", None, _days(alert)
    )
    return _fill(text, _level(alert), alert.subject_ref)


def _cert_expiring(alert: Alert, lang: str) -> str:
    text = QCoreApplication.translate(
        "Alerts", "The level %1 certificate of %2 expires in %n day(s).", None, _days(alert)
    )
    return _fill(text, _level(alert), alert.subject_ref)


def _maint_overdue(alert: Alert, lang: str) -> str:
    text = QCoreApplication.translate(
        "Alerts", "Maintenance of asset %1 is overdue by %n day(s).", None, _days(alert)
    )
    return _fill(text, alert.subject_ref)


def _maint_due_soon(alert: Alert, lang: str) -> str:
    text = QCoreApplication.translate(
        "Alerts", "Maintenance of asset %1 is due in %n day(s).", None, _days(alert)
    )
    return _fill(text, alert.subject_ref)


def _maint_unknown(alert: Alert, lang: str) -> str:
    text = QCoreApplication.translate("Alerts", "The maintenance schedule of asset %1 is unknown.")
    return _fill(text, alert.subject_ref)


def _indicator_values(alert: Alert, lang: str) -> tuple[str, str, str]:
    return subject_text(alert), _number(alert.value, lang), _number(alert.threshold, lang)


def _indicator_warning(alert: Alert, lang: str) -> str:
    text = QCoreApplication.translate("Alerts", "Indicator %1 is at %2 (warning threshold: %3).")
    return _fill(text, *_indicator_values(alert, lang))


def _indicator_critical(alert: Alert, lang: str) -> str:
    text = QCoreApplication.translate("Alerts", "Indicator %1 is at %2 (critical threshold: %3).")
    return _fill(text, *_indicator_values(alert, lang))


_MESSAGES: dict[str, Callable[[Alert, str], str]] = {
    AlertKind.CERT_EXPIRED.value: _cert_expired,
    AlertKind.CERT_EXPIRING.value: _cert_expiring,
    AlertKind.MAINT_OVERDUE.value: _maint_overdue,
    AlertKind.MAINT_DUE_SOON.value: _maint_due_soon,
    AlertKind.MAINT_SCHEDULE_UNKNOWN.value: _maint_unknown,
    AlertKind.INDICATOR_WARNING.value: _indicator_warning,
    AlertKind.INDICATOR_CRITICAL.value: _indicator_critical,
}

ALL_KIND_CODES: tuple[str, ...] = tuple(_MESSAGES)


def kind_message(code: str, alert: Alert, lang: str) -> str:
    """The message for the alert kind ``code``; the code itself when the kind is unknown."""
    builder = _MESSAGES.get(str(code))
    return str(code) if builder is None else builder(alert, lang)


def alert_message(alert: Alert, lang: str) -> str:
    """The localized message of ``alert``, built from its kind and parameters, for ``lang``."""
    return kind_message(alert.kind.value, alert, lang)
