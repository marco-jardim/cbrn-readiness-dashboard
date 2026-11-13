# SPDX-License-Identifier: GPL-3.0-or-later
"""The Budget page and its settings section (PLAN.md T5.4, A08, P08, D15, D16, D27).

The page shows the summary of a fiscal year per source and currency (allocated, executed as of the
as-of date, execution rate; currencies on separate rows, never added), the entries of the year and
the dated execution rows of the selected entry. The settings section holds the funding-source
editor, the default currency (A08) and the pro-rating switch (P08). Both read and write ONLY through
``context.services.budget`` and ``context.services.config``; dialogs are opened non-modally with
``open()``. The module-level factories are what the registries of the shell call.
"""

from datetime import date
from typing import Any

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from cbrn_dashboard.domain.budget import CURRENCY_DECIMALS, fiscal_year_of
from cbrn_dashboard.services.budget import EntryView, ExecutionView, SourceView
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.ui.budget.dialogs import (
    EntryDialog,
    ExecutionDialog,
    SourceDialog,
    configured_currency,
)
from cbrn_dashboard.ui.budget.labels import error_label, fill_placeholders, source_name
from cbrn_dashboard.ui.budget.models import (
    EntriesModel,
    ExecutionsModel,
    SourcesModel,
    SummaryModel,
    money_text,
)
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import format_date
from cbrn_dashboard.ui.shell.widgets import (
    EditAction,
    action_row,
    apply_change,
    current_language,
    follow_language,
    make_edit_action,
    make_table_view,
    mark_data,
)

__all__ = [
    "BudgetPage",
    "BudgetSettingsSection",
    "create_page",
    "create_settings_section",
    "demo_entry_dialog",
    "demo_execution_dialog",
    "demo_source_dialog",
    "page_title",
    "settings_section_title",
]

_MIN_YEAR = 1900
_MAX_YEAR = 2200


def _open(dialog: QDialog) -> None:
    """Show ``dialog`` window-modally without blocking; it deletes itself when closed."""
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.open()


# --------------------------------------------------------------------------- the page


class BudgetPage(QWidget):
    """Year selector, summary per source and currency, entries and their execution rows."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("budget_page")
        self.context = context
        self._user_year = False
        self._syncing = False
        self.summary_model = SummaryModel(self)
        self.entries_model = EntriesModel(self)
        self.executions_model = ExecutionsModel(self)
        self.year_caption = QLabel(self)
        self.year_spin = QSpinBox(self)
        self.year_spin.setObjectName("year_spin")
        self.year_spin.setRange(_MIN_YEAR, _MAX_YEAR)
        self.year_spin.setValue(fiscal_year_of(context.as_of))
        self.summary_caption = QLabel(self)
        self.summary_view = make_table_view(self.summary_model, self)
        self.summary_view.setObjectName("summary_view")
        self.entries_caption = QLabel(self)
        self.entries_view = make_table_view(self.entries_model, self)
        self.entries_view.setObjectName("entries_view")
        self.executions_caption = QLabel(self)
        self.executions_view = make_table_view(self.executions_model, self)
        self.executions_view.setObjectName("executions_view")

        self.add_entry_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Budget", "Add entry"),
            self.add_entry,
        )
        self.edit_entry_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Budget", "Edit entry"),
            self.edit_entry,
        )
        self.delete_entry_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Budget", "Delete entry"),
            self.delete_entry,
        )
        self.add_execution_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Budget", "Add execution"),
            self.add_execution,
        )
        self.edit_execution_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Budget", "Edit execution"),
            self.edit_execution,
        )
        self.delete_execution_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Budget", "Delete execution"),
            self.delete_execution,
        )
        self._actions: tuple[EditAction, ...] = (
            self.add_entry_action,
            self.edit_entry_action,
            self.delete_entry_action,
            self.add_execution_action,
            self.edit_execution_action,
            self.delete_execution_action,
        )

        year_row = QHBoxLayout()
        year_row.addWidget(self.year_caption)
        year_row.addWidget(self.year_spin)
        year_row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(year_row)
        layout.addWidget(self.summary_caption)
        layout.addWidget(self.summary_view, 1)
        layout.addWidget(self.entries_caption)
        layout.addWidget(self.entries_view, 1)
        layout.addLayout(
            action_row(
                (self.add_entry_action, self.edit_entry_action, self.delete_entry_action), self
            )
        )
        layout.addWidget(self.executions_caption)
        layout.addWidget(self.executions_view, 1)
        layout.addLayout(
            action_row(
                (
                    self.add_execution_action,
                    self.edit_execution_action,
                    self.delete_execution_action,
                ),
                self,
            )
        )

        self.year_spin.valueChanged.connect(self._year_changed)
        selection = self.entries_view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._entry_selected)
        selection = self.executions_view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._update_actions)
        context.as_of_changed.connect(self._as_of_changed)
        context.data_changed.connect(self.refresh)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    # ----- texts

    def retranslate(self) -> None:
        """Re-apply every text of the page in the current language."""
        self.year_caption.setText(QCoreApplication.translate("Budget", "Fiscal year"))
        self.summary_caption.setText(
            QCoreApplication.translate("Budget", "Summary by source and currency")
        )
        self.entries_caption.setText(QCoreApplication.translate("Budget", "Entries of the year"))
        self.executions_caption.setText(
            QCoreApplication.translate("Budget", "Execution rows of the selected entry")
        )
        for action in self._actions:
            action.retranslate()
        lang = current_language(self.context)
        self.summary_model.set_language(lang)
        self.entries_model.set_language(lang)
        self.executions_model.set_language(lang)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    # ----- year and as-of date

    def year(self) -> int:
        return self.year_spin.value()

    def _set_year(self, year: int) -> None:
        self._syncing = True
        try:
            self.year_spin.setValue(year)
        finally:
            self._syncing = False

    def _year_changed(self, year: int) -> None:
        if self._syncing:
            return
        # Picking the year of the as-of date means "follow the as-of date" again.
        self._user_year = year != fiscal_year_of(self.context.as_of)
        self.refresh()

    def _as_of_changed(self, _value: object) -> None:
        if not self._user_year:
            self._set_year(fiscal_year_of(self.context.as_of))
        self.refresh()

    # ----- data

    def selected_entry(self) -> EntryView | None:
        row = self.entries_model.selected_row(self.entries_view)
        return None if row is None else row.entry

    def selected_execution(self) -> ExecutionView | None:
        row = self.executions_model.selected_row(self.executions_view)
        return None if row is None else row.execution

    def refresh(self) -> None:
        """Read the summary, the entries (and the execution rows of the selected one) again."""
        service = self.context.services.budget
        if service is None:
            self.summary_model.set_rows([])
            self.entries_model.set_rows([])
        else:
            sources = {s.code: s for s in service.list_sources(include_inactive=True)}
            year = self.year()
            totals = service.totals_for_year(year, self.context.as_of)
            self.summary_model.set_totals(totals, sources)
            previous = self.selected_entry()
            entries = service.list_entries(year)
            self.entries_model.set_entries(entries, sources)
            if previous is not None:
                for row, entry in enumerate(entries):
                    if entry.id == previous.id:
                        self.entries_view.selectRow(row)
        self._refresh_executions()

    def _refresh_executions(self) -> None:
        previous = self.selected_execution()
        entry = self.selected_entry()
        if entry is None:
            self.executions_model.set_executions((), "")
        else:
            self.executions_model.set_executions(entry.executions, entry.currency)
            if previous is not None:
                for row, execution in enumerate(entry.executions):
                    if execution.id == previous.id:
                        self.executions_view.selectRow(row)
        self._update_actions()

    def _entry_selected(self, *_args: object) -> None:
        self._refresh_executions()

    def _update_actions(self, *_args: object) -> None:
        has_service = self.context.services.budget is not None
        entry = self.selected_entry() is not None
        execution = self.selected_execution() is not None
        enable = self.context.set_edit_enabled
        enable(self.add_entry_action, has_service)
        enable(self.edit_entry_action, has_service and entry)
        enable(self.delete_entry_action, has_service and entry)
        enable(self.add_execution_action, has_service and entry)
        enable(self.edit_execution_action, has_service and execution)
        enable(self.delete_execution_action, has_service and execution)

    # ----- entries

    def add_entry(self) -> None:
        _open(EntryDialog(self.context, self, None, self.year()))

    def edit_entry(self) -> None:
        entry = self.selected_entry()
        if entry is not None:
            _open(EntryDialog(self.context, self, entry))

    def delete_entry(self) -> None:
        entry = self.selected_entry()
        service = self.context.services.budget
        if entry is None or service is None:
            return
        lang = current_language(self.context)
        sources = {s.code: s for s in service.list_sources(include_inactive=True)}
        source = source_name(entry.source_code, lang, sources)
        title = QCoreApplication.translate("Budget", "Delete entry")
        if entry.description:
            question = fill_placeholders(
                QCoreApplication.translate(
                    "Budget", "Delete the entry of %1 in %2 (%3) together with its execution rows?"
                ),
                source,
                entry.currency,
                entry.description,
            )
        else:
            question = fill_placeholders(
                QCoreApplication.translate(
                    "Budget", "Delete the entry of %1 in %2 together with its execution rows?"
                ),
                source,
                entry.currency,
            )
        if self.context.prompts.confirm(self, title, question):
            apply_change(self.context, self, error_label, lambda: service.delete_entry(entry.id))

    # ----- execution rows

    def add_execution(self) -> None:
        entry = self.selected_entry()
        if entry is not None:
            _open(ExecutionDialog(self.context, self, entry))

    def edit_execution(self) -> None:
        entry = self.selected_entry()
        execution = self.selected_execution()
        if entry is not None and execution is not None:
            _open(ExecutionDialog(self.context, self, entry, execution))

    def delete_execution(self) -> None:
        entry = self.selected_entry()
        execution = self.selected_execution()
        service = self.context.services.budget
        if entry is None or execution is None or service is None:
            return
        lang = current_language(self.context)
        title = QCoreApplication.translate("Budget", "Delete execution")
        question = fill_placeholders(
            QCoreApplication.translate("Budget", "Delete the execution row of %1 for %2?"),
            format_date(execution.executed_on, lang),
            money_text(execution.amount_minor, entry.currency, lang),
        )
        if self.context.prompts.confirm(self, title, question):
            apply_change(
                self.context, self, error_label, lambda: service.delete_execution(execution.id)
            )


# --------------------------------------------------------------------------- settings section


def _config(context: AppContext) -> Any:
    """The configuration service (``None`` while it is absent, e.g. without a database)."""
    return getattr(context.services, "config", None)


class BudgetSettingsSection(QWidget):
    """Settings -> Budget: funding sources (D16), default currency (A08), pro-rating (P08)."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("budget_section")
        self.context = context
        self._syncing = False
        self._currency_placeholder: str | None = None
        self._prorate_placeholder: str | None = None
        self._config_error: str | None = None
        self.model = SourcesModel(self)
        self.view = make_table_view(self.model, self)
        self.view.setObjectName("sources_view")
        self.sources_caption = QLabel(self)
        self.add_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Budget", "Add funding source"),
            self.add_source,
        )
        self.edit_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Budget", "Edit funding source"),
            self.edit_source,
        )
        self.deactivate_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Budget", "Deactivate funding source"),
            self.deactivate_source,
        )
        self.delete_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Budget", "Delete funding source"),
            self.delete_source,
        )
        self._actions: tuple[EditAction, ...] = (
            self.add_action,
            self.edit_action,
            self.deactivate_action,
            self.delete_action,
        )

        self.config_error_label = QLabel(self)
        self.config_error_label.setObjectName("config_error_label")
        self.config_error_label.setWordWrap(True)
        self.config_error_label.setVisible(False)
        self.currency_caption = QLabel(self)
        self.currency_combo = QComboBox(self)
        self.currency_combo.setObjectName("default_currency_combo")
        mark_data(self.currency_combo)
        for code in CURRENCY_DECIMALS:
            self.currency_combo.addItem(code, code)
        self.currency_badge = QLabel(self)
        self.currency_badge.setObjectName("currency_badge")
        self.currency_confirm = QPushButton(self)
        self.currency_confirm.setObjectName("currency_confirm")
        self.prorate_check = QCheckBox(self)
        self.prorate_check.setObjectName("prorate_check")
        self.prorate_badge = QLabel(self)
        self.prorate_badge.setObjectName("prorate_badge")
        self.prorate_confirm = QPushButton(self)
        self.prorate_confirm.setObjectName("prorate_confirm")
        for widget in (
            self.currency_badge,
            self.currency_confirm,
            self.prorate_badge,
            self.prorate_confirm,
        ):
            widget.setVisible(False)
        # Read-only mode disables every control that changes data.
        for target in (
            self.currency_combo,
            self.currency_confirm,
            self.prorate_check,
            self.prorate_confirm,
        ):
            context.register_edit_action(target)

        currency_row = QHBoxLayout()
        currency_row.addWidget(self.currency_caption)
        currency_row.addWidget(self.currency_combo)
        currency_row.addWidget(self.currency_badge)
        currency_row.addWidget(self.currency_confirm)
        currency_row.addStretch(1)
        prorate_row = QHBoxLayout()
        prorate_row.addWidget(self.prorate_check)
        prorate_row.addWidget(self.prorate_badge)
        prorate_row.addWidget(self.prorate_confirm)
        prorate_row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.sources_caption)
        layout.addWidget(self.view, 1)
        layout.addLayout(action_row(self._actions, self))
        layout.addWidget(self.config_error_label)
        layout.addLayout(currency_row)
        layout.addLayout(prorate_row)

        selection = self.view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._update_actions)
        self.currency_combo.currentIndexChanged.connect(self._currency_picked)
        self.prorate_check.toggled.connect(self._prorate_toggled)
        self.currency_confirm.clicked.connect(self._confirm_currency)
        self.prorate_confirm.clicked.connect(self._confirm_prorate)
        context.data_changed.connect(self.refresh)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    # ----- texts

    def retranslate(self) -> None:
        self.sources_caption.setText(QCoreApplication.translate("Budget", "Funding sources"))
        self.currency_caption.setText(QCoreApplication.translate("Budget", "Default currency"))
        self.prorate_check.setText(
            QCoreApplication.translate(
                "Budget", "Pro-rate the execution target over the fiscal year"
            )
        )
        badge = QCoreApplication.translate("Budget", "Placeholder - to be confirmed")
        confirm = QCoreApplication.translate("Budget", "Confirm")
        self.currency_badge.setText(badge)
        self.prorate_badge.setText(badge)
        self.currency_confirm.setText(confirm)
        self.prorate_confirm.setText(confirm)
        for action in self._actions:
            action.retranslate()
        self._show_config_error()
        self.model.set_language(current_language(self.context))

    def _show_config_error(self) -> None:
        """Show why the settings controls are off (a configuration that cannot be read)."""
        code = self._config_error
        self.config_error_label.setVisible(code is not None)
        self.config_error_label.setText("" if code is None else error_label(code))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    # ----- data

    def selected_source(self) -> SourceView | None:
        row = self.model.selected_row(self.view)
        return row if isinstance(row, SourceView) else None

    def refresh(self) -> None:
        service = self.context.services.budget
        previous = self.selected_source()
        sources = [] if service is None else service.list_sources(include_inactive=True)
        self.model.set_rows(sources)
        if previous is not None:
            for row, source in enumerate(sources):
                if source.id == previous.id:
                    self.view.selectRow(row)
        self._refresh_settings()
        self._update_actions()

    def _refresh_settings(self) -> None:
        """Show the stored default currency and pro-rating switch with their badges."""
        config = _config(self.context)
        currency = configured_currency(self.context)
        prorate = True
        self._currency_placeholder = None
        self._prorate_placeholder = None
        self._config_error = None
        if config is not None:
            try:
                prorate = bool(config.load().budget_prorate_target)
                self._currency_placeholder = config.badge_for_field("default_currency")
                self._prorate_placeholder = config.badge_for_field("budget_prorate_target")
            except ServiceError as error:
                self._config_error = error.code
                config = None
        self._show_config_error()
        self._syncing = True
        try:
            self.currency_combo.setCurrentIndex(max(0, self.currency_combo.findData(currency)))
            self.prorate_check.setChecked(prorate)
        finally:
            self._syncing = False
        self.currency_badge.setVisible(self._currency_placeholder is not None)
        self.currency_confirm.setVisible(self._currency_placeholder is not None)
        self.prorate_badge.setVisible(self._prorate_placeholder is not None)
        self.prorate_confirm.setVisible(self._prorate_placeholder is not None)
        enable = self.context.set_edit_enabled
        enable(self.currency_combo, config is not None)
        enable(self.prorate_check, config is not None)
        enable(self.currency_confirm, config is not None)
        enable(self.prorate_confirm, config is not None)

    def _update_actions(self, *_args: object) -> None:
        has_service = self.context.services.budget is not None
        source = self.selected_source()
        enable = self.context.set_edit_enabled
        enable(self.add_action, has_service)
        enable(self.edit_action, has_service and source is not None)
        enable(self.deactivate_action, has_service and source is not None and source.active)
        enable(self.delete_action, has_service and source is not None)

    # ----- default currency and pro-rating

    def _currency_picked(self, _index: int) -> None:
        config = _config(self.context)
        if self._syncing or config is None:
            return
        code = str(self.currency_combo.currentData())

        def save() -> object:
            return config.save(config.load().with_changes(default_currency=code))

        if not apply_change(self.context, self, error_label, save):
            self.refresh()

    def _prorate_toggled(self, checked: bool) -> None:
        config = _config(self.context)
        if self._syncing or config is None:
            return

        def save() -> object:
            return config.save(config.load().with_changes(budget_prorate_target=checked))

        if not apply_change(self.context, self, error_label, save):
            self.refresh()

    def _confirm_currency(self) -> None:
        self._confirm(self._currency_placeholder)

    def _confirm_prorate(self) -> None:
        self._confirm(self._prorate_placeholder)

    def _confirm(self, placeholder: str | None) -> None:
        config = _config(self.context)
        if config is None or placeholder is None:
            return
        apply_change(self.context, self, error_label, lambda: config.confirm(placeholder))

    # ----- funding sources

    def add_source(self) -> None:
        _open(SourceDialog(self.context, self))

    def edit_source(self) -> None:
        source = self.selected_source()
        if source is not None:
            _open(SourceDialog(self.context, self, source))

    def deactivate_source(self) -> None:
        source = self.selected_source()
        service = self.context.services.budget
        if source is not None and service is not None:
            apply_change(
                self.context, self, error_label, lambda: service.deactivate_source(source.id)
            )

    def delete_source(self) -> None:
        source = self.selected_source()
        service = self.context.services.budget
        if source is None or service is None:
            return
        name = source_name(source.code, current_language(self.context), {source.code: source})
        title = QCoreApplication.translate("Budget", "Delete funding source")
        question = fill_placeholders(
            QCoreApplication.translate("Budget", "Delete funding source %1?"), name
        )
        if self.context.prompts.confirm(self, title, question):
            apply_change(self.context, self, error_label, lambda: service.delete_source(source.id))


# --------------------------------------------------------------------------- registry factories


def page_title() -> str:
    return QCoreApplication.translate("Budget", "Budget")


def create_page(context: AppContext) -> QWidget:
    return BudgetPage(context)


def settings_section_title() -> str:
    return QCoreApplication.translate("Budget", "Funding sources and budget rules")


def create_settings_section(context: AppContext) -> QWidget:
    return BudgetSettingsSection(context)


def _demo_entry() -> EntryView:
    return EntryView(
        id=0,
        fiscal_year=2026,
        source_id=0,
        source_code="DIRSA",
        currency="BRL",
        allocated_minor=123456,
        description="Demo entry",
        notes=None,
        executions=(),
    )


def demo_entry_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """An entry dialog filled with a fictitious entry (it writes nothing unless accepted)."""
    return EntryDialog(context, parent, _demo_entry())


def demo_execution_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """An execution dialog filled with a fictitious execution row."""
    execution = ExecutionView(
        id=0, entry_id=0, executed_on=date(2026, 3, 2), amount_minor=50000, note=None
    )
    return ExecutionDialog(context, parent, _demo_entry(), execution)


def demo_source_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """A funding-source dialog filled with a fictitious source."""
    source = SourceView(
        id=0,
        code="DEMO",
        built_in=False,
        label_pt_br="Fonte de demonstracao",
        label_en_us="Demo source",
        label_es_es=None,
        active=True,
    )
    return SourceDialog(context, parent, source)
