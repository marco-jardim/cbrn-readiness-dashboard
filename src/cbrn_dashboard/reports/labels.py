# SPDX-License-Identifier: GPL-3.0-or-later
"""The texts of a PDF report in the language chosen for it (PLAN.md T8.6, section 6).

A report is written in the language the user picks for THAT report, which may differ from the
language of the user interface. So this module never uses the translators installed in the
application: :class:`ReportTexts` loads its own :class:`QTranslator` objects for one language and
asks them directly. Nothing is installed, removed or changed in the application, and the default
locale is not touched.

Texts that belong to the report are literal ``texts.translate("Reports", "<English>")`` calls (the
catalogues ``reports_<lang>.ts`` hold them). Texts shared with the UI (the preliminary notice, the
certificate statuses, the built-in asset types and funding sources, the degree levels) are looked
up through :mod:`cbrn_dashboard.reports.message_keys` in the catalogues of the UI. A code that has
no label is shown as itself, never as an error.
"""

import re
from pathlib import Path
from typing import Final

from PySide6.QtCore import QTranslator

from cbrn_dashboard import i18n
from cbrn_dashboard.reports.message_keys import (
    ASSET_TYPE_KEYS,
    CERT_STATUS_KEYS,
    DEGREE_LEVEL_KEYS,
    DEGREE_STATUS_KEYS,
    EXERCISE_KIND_KEYS,
    FUNDING_SOURCE_KEYS,
    PRELIMINARY_KEY,
    SHARED_AREAS,
    MessageKey,
)

__all__ = [
    "CHART_KEYS",
    "CHART_SERIES_KEYS",
    "DIMENSION_KEYS",
    "INDICATOR_CODES",
    "REPORT_AREA",
    "ReportTexts",
    "fill",
]

#: The translation area of the report's own texts.
REPORT_AREA: Final = "reports"

#: Every indicator code the dashboard can put in a report.
INDICATOR_CODES: Final[tuple[str, ...]] = (
    "PERS_CERT_VALID",
    "PERS_CERT_EXPIRING",
    "PERS_RETRAINING_NEEDED",
    "PERS_DEGREE",
    "INFRA_AVAILABLE",
    "INFRA_MAINT_OVERDUE",
    "EX_LAST_PARTICIPANTS",
    "EX_LAST_COUNTRIES",
    "EX_DAYS_SINCE_LAST",
    "BUD_EXEC_RATE",
)

#: The keys of the fixed charts (a budget chart is ``budget_<currency>``).
CHART_KEYS: Final[tuple[str, ...]] = (
    "personnel_valid_by_level",
    "infrastructure_availability",
    "exercises_by_edition",
)

#: The series keys of the charts.
CHART_SERIES_KEYS: Final[tuple[str, ...]] = (
    "valid",
    "available",
    "in_service",
    "participants",
    "countries",
    "allocated",
    "executed",
)

#: The names of the dimension parts of an indicator row.
DIMENSION_KEYS: Final[tuple[str, ...]] = (
    "level",
    "kind",
    "status",
    "type",
    "source",
    "currency",
    "fiscal_year",
)

_BUDGET_CHART_PREFIX = "budget_"
_PLACEHOLDER = re.compile(r"%([1-9])")

# Looked up through the class so that data-driven keys need no literal at the call site; the source
# texts are the literals of the catalogues. (Referencing the unbound method is not a translate
# call for the guard of ``tests/i18n``.)
_LOOKUP = QTranslator.translate


def fill(template: str, *values: str) -> str:
    """Replace ``%1``..``%9`` in ``template`` by ``values``, in one pass."""

    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1)) - 1
        return values[index] if index < len(values) else match.group(0)

    return _PLACEHOLDER.sub(replace, template)


def _load(path: Path) -> QTranslator | None:
    if not path.is_file():  # never load a missing file: Qt would log a warning
        return None
    translator = QTranslator()
    return translator if translator.load(str(path)) else None


class ReportTexts:
    """The report's texts in one language; independent of the installed translators."""

    def __init__(self, language: str, qm_dir: Path | None = None) -> None:
        self.language: str = i18n.to_catalogue_code(language)
        folder = i18n.qm_dir() if qm_dir is None else qm_dir
        self._translators: list[QTranslator] = []
        missing: list[str] = []
        for area in (REPORT_AREA, *SHARED_AREAS):
            translator = _load(folder / f"{area}_{self.language}.qm")
            if translator is None:
                missing.append(area)
            else:
                self._translators.append(translator)
        #: Areas whose compiled catalogue was not found; their texts appear in English.
        self.missing_catalogues: tuple[str, ...] = tuple(missing)
        self._modules = self._build_modules()
        self._statuses = self._build_statuses()
        self._severities = self._build_severities()
        self._indicators = self._build_indicators()
        self._dimensions = self._build_dimensions()
        self._series = self._build_series()

    # ------------------------------------------------------------------ lookup

    def translate(
        self, context: str, source: str, disambiguation: str | None = None, n: int = -1
    ) -> str:
        """The text of ``source`` in the report language (the English source when not found).

        With ``n`` >= 0 the source is a plural pattern: ``%n`` becomes the count and the plural
        form of the language is chosen.
        """
        return self._find(context, source, disambiguation, n)

    def lookup(self, key: MessageKey) -> str:
        """The text of a shared message key."""
        return self._find(key[0], key[1])

    def _find(
        self, context: str, source: str, disambiguation: str | None = None, n: int = -1
    ) -> str:
        for translator in self._translators:
            found = _LOOKUP(translator, context, source, disambiguation, n)
            if found:
                # A translator only picks the plural form; the count is put in here.
                return found if n < 0 else found.replace("%n", str(n))
        return source if n < 0 else source.replace("%n", str(n))

    # ------------------------------------------------------------------ tables

    def _build_modules(self) -> dict[str, str]:
        return {
            "PERSONNEL": self.translate("Reports", "Personnel"),
            "INFRASTRUCTURE": self.translate("Reports", "Infrastructure"),
            "EXERCISES": self.translate("Reports", "Exercises"),
            "BUDGET": self.translate("Reports", "Budget"),
        }

    def _build_statuses(self) -> dict[str, str]:
        return {
            "OK": self.translate("Reports", "On target"),
            "WARNING": self.translate("Reports", "Warning"),
            "CRITICAL": self.translate("Reports", "Critical"),
            "NO_TARGET": self.translate("Reports", "No target"),
            "NO_DATA": self.translate("Reports", "No data"),
        }

    def _build_severities(self) -> dict[str, str]:
        return {
            "CRITICAL": self.translate("Reports", "Critical"),
            "WARNING": self.translate("Reports", "Warning"),
            "INFO": self.translate("Reports", "Information"),
        }

    def _build_indicators(self) -> dict[str, str]:
        return {
            "PERS_CERT_VALID": self.translate("Reports", "Valid qualifications"),
            "PERS_CERT_EXPIRING": self.translate("Reports", "Qualifications expiring"),
            "PERS_RETRAINING_NEEDED": self.translate("Reports", "Staff needing retraining"),
            "PERS_DEGREE": self.translate("Reports", "Postgraduate degrees"),
            "INFRA_AVAILABLE": self.translate("Reports", "Assets available"),
            "INFRA_MAINT_OVERDUE": self.translate("Reports", "Assets with overdue maintenance"),
            "EX_LAST_PARTICIPANTS": self.translate("Reports", "Participants in the last exercise"),
            "EX_LAST_COUNTRIES": self.translate("Reports", "Countries in the last exercise"),
            "EX_DAYS_SINCE_LAST": self.translate("Reports", "Days since the last exercise"),
            "BUD_EXEC_RATE": self.translate("Reports", "Budget execution rate"),
        }

    def _build_dimensions(self) -> dict[str, str]:
        return {
            "level": self.translate("Reports", "Level"),
            "kind": self.translate("Reports", "Kind"),
            "status": self.translate("Reports", "Status"),
            "type": self.translate("Reports", "Asset type"),
            "source": self.translate("Reports", "Funding source"),
            "currency": self.translate("Reports", "Currency"),
            "fiscal_year": self.translate("Reports", "Fiscal year"),
        }

    def _build_series(self) -> dict[str, str]:
        return {
            "valid": self.translate("Reports", "Valid qualifications"),
            "available": self.translate("Reports", "Available"),
            "in_service": self.translate("Reports", "In service"),
            "participants": self.translate("Reports", "Participants"),
            "countries": self.translate("Reports", "Countries"),
            "allocated": self.translate("Reports", "Allocated"),
            "executed": self.translate("Reports", "Executed"),
        }

    # ------------------------------------------------------------------ codes

    def module(self, code: str) -> str:
        """The name of a module (``Module`` value)."""
        return self._modules.get(code, code)

    def indicator_status(self, code: str) -> str:
        """The label of an ``IndicatorStatus``."""
        return self._statuses.get(code, code)

    def severity(self, code: str) -> str:
        """The label of an alert ``Severity``."""
        return self._severities.get(code, code)

    def indicator(self, code: str) -> str:
        """The name of an indicator code."""
        return self._indicators.get(code, code)

    def dimension_name(self, code: str) -> str:
        """The name of a dimension part (``level``, ``kind`` ...)."""
        return self._dimensions.get(code, code)

    def series_name(self, code: str) -> str:
        """The name of a chart series."""
        return self._series.get(code, code)

    def level(self, code: str) -> str:
        """A protection level, e.g. ``Level A``."""
        return fill(self.translate("Reports", "Level %1"), code)

    def cert_status(self, code: str) -> str:
        """The label of a certificate status (shared with the personnel page)."""
        key = CERT_STATUS_KEYS.get(code)
        return code if key is None else self.lookup(key)

    def degree_level(self, code: str) -> str:
        """The label of a degree level (shared with the personnel page)."""
        key = DEGREE_LEVEL_KEYS.get(code)
        return code if key is None else self.lookup(key)

    def degree_status(self, code: str) -> str:
        """The label of a degree status (shared with the personnel page)."""
        key = DEGREE_STATUS_KEYS.get(code)
        return code if key is None else self.lookup(key)

    def exercise_kind(self, code: str) -> str:
        """The label of an exercise kind (``CBRAMED`` and ``EXBRAMED`` are names, shown as is)."""
        key = EXERCISE_KIND_KEYS.get(code)
        return code if key is None else self.lookup(key)

    def alert_source(self, code: str) -> str:
        """The label of the source of an alert count (``AlertSource`` value)."""
        if code == "ALL":
            return self.translate("Reports", "All sources")
        if code in {"PERSONNEL", "INFRASTRUCTURE"}:
            return self.module(code)
        if code == "INDICATORS":
            return self.translate("Reports", "Indicators")
        return code

    def asset_type(self, code: str) -> str:
        """The name of a built-in asset type; any other code is shown as itself."""
        key = ASSET_TYPE_KEYS.get(code)
        return code if key is None else self.lookup(key)

    def funding_source(self, code: str) -> str:
        """The name of a funding source; ``DIRSA`` and user-defined codes are shown as they are."""
        key = FUNDING_SOURCE_KEYS.get(code)
        return code if key is None else self.lookup(key)

    def preliminary_notice(self, code: str) -> str:
        """The preliminary-version notice (I06, P07); another code is shown as itself."""
        return self.lookup(PRELIMINARY_KEY) if code == "PRELIMINARY" else code

    # ------------------------------------------------------------------ figures and charts

    def cell_label(self, key: str) -> str:
        """The label of a key figure (``Cell.key``); an unknown key is shown as itself."""
        parts = key.split(":")
        if parts[0] != "kf" or len(parts) < 3:
            return key
        module, name = parts[1], parts[2]
        argument = parts[3] if len(parts) > 3 else ""
        if module == "PERSONNEL":
            return self._personnel_cell(key, name, argument)
        if module == "INFRASTRUCTURE":
            if name == "overdue":
                return self.translate("Reports", "Assets with overdue maintenance")
            if name == "due_soon":
                return self.translate("Reports", "Assets with maintenance due soon")
        elif module == "EXERCISES":
            if name == "days_since_last":
                return self.translate("Reports", "Days since the last exercise")
            if name == "last_participants":
                return self.translate("Reports", "Participants in the last exercise")
            if name == "last_countries":
                return self.translate("Reports", "Countries in the last exercise")
        elif module == "BUDGET" and argument:
            return fill(self.translate("Reports", "%1 (%2)"), self.series_name(name), argument)
        return key

    def _personnel_cell(self, key: str, name: str, argument: str) -> str:
        if name == "active_staff":
            return self.translate("Reports", "Active staff")
        if name == "valid":
            return fill(self.translate("Reports", "Valid qualifications, level %1"), argument)
        if name == "expiring":
            return fill(self.translate("Reports", "Qualifications expiring, level %1"), argument)
        if name == "expired":
            return fill(self.translate("Reports", "Qualifications expired, level %1"), argument)
        if name == "retraining":
            return fill(self.translate("Reports", "Staff needing retraining, level %1"), argument)
        if name == "degree_completed":
            return fill(
                self.translate("Reports", "Completed degrees, %1"), self.degree_level(argument)
            )
        if name == "degree_completed_total":
            return self.translate("Reports", "Completed degrees, total")
        return key

    def chart_title(self, key: str, parameters: dict[str, str]) -> str:
        """The title of a report chart; a budget chart names its currency and fiscal year."""
        if key == "personnel_valid_by_level":
            return self.translate("Reports", "Valid qualifications by protection level")
        if key == "infrastructure_availability":
            return self.translate("Reports", "Assets available and in service by type")
        if key == "exercises_by_edition":
            return self.translate("Reports", "Participants and countries by edition")
        if key.startswith(_BUDGET_CHART_PREFIX):
            currency = parameters.get("currency", key.removeprefix(_BUDGET_CHART_PREFIX))
            year = parameters.get("fiscal_year", "")
            text = fill(self.translate("Reports", "Budget by funding source (%1)"), currency)
            return fill(self.translate("Reports", "%1, %2"), text, year) if year else text
        return key

    def chart_category(self, chart_key: str, category: str) -> str:
        """The label of one category of a chart."""
        if chart_key == "personnel_valid_by_level":
            return self.level(category)
        if chart_key == "infrastructure_availability":
            return self.asset_type(category)
        if chart_key.startswith(_BUDGET_CHART_PREFIX):
            return self.funding_source(category)
        return category
