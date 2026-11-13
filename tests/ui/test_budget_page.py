# SPDX-License-Identifier: GPL-3.0-or-later
"""The Budget page, its dialogs, the settings section and the labels (PLAN.md T5.4)."""

import decimal
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QAbstractItemModel, QCoreApplication, QDate, Qt
from PySide6.QtWidgets import QDialog, QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard.domain.config import ReadinessConfig
from cbrn_dashboard.services import budget as budget_module
from cbrn_dashboard.services import errors as errors_module
from cbrn_dashboard.services.budget import (
    BudgetService,
    EntryInput,
    SourceInput,
    SourceView,
)
from cbrn_dashboard.services.config import CONFIG_ERROR_CODES, ConfigService
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.ui.budget.dialogs import EntryDialog, ExecutionDialog, SourceDialog
from cbrn_dashboard.ui.budget.labels import (
    ALL_ERROR_CODES,
    BUILT_IN_SOURCE_CODES,
    error_label,
    source_display,
)
from cbrn_dashboard.ui.budget.page import (
    BudgetPage,
    BudgetSettingsSection,
    create_page,
    create_settings_section,
    demo_entry_dialog,
    demo_execution_dialog,
    demo_source_dialog,
    page_title,
    settings_section_title,
)
from cbrn_dashboard.ui.shell import formatting as formatting_module
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import format_amount, parse_amount
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from tests.ui._fakes import FakePrompts
from tests.ui._walk import assert_fully_translated

pytestmark = pytest.mark.ui

LANGUAGES = ("pt_BR", "en_US", "es_ES")
NBSP = "\xa0"


# --------------------------------------------------------------------------- helpers


def _service(context: AppContext) -> BudgetService:
    service = context.services.budget
    assert service is not None
    return service


def _source_id(context: AppContext, code: str = "DIRSA") -> int:
    source = _service(context).get_source_by_code(code)
    assert source is not None
    return source.id


def _add_entry(
    context: AppContext,
    *,
    year: int = 2026,
    code: str = "DIRSA",
    currency: str = "BRL",
    allocated: int | None = 1_000_000,
    description: str = "",
) -> int:
    return _service(context).create_entry(
        EntryInput(
            fiscal_year=year,
            source_id=_source_id(context, code),
            allocated_minor=allocated,
            currency=currency,
            description=description,
        )
    )


def _with_config(context: AppContext) -> ConfigService:
    """A real configuration service on the context (it may or may not be there already)."""
    assert context.conn is not None
    config = ConfigService(context.conn, context.clock, context.operator_label)
    vars(context.services)["config"] = config
    return config


class _FakeConfig:
    """The configuration service API over memory, with scripted placeholder badges."""

    def __init__(self, badges: dict[str, str]) -> None:
        self.config = ReadinessConfig()
        self.badges = dict(badges)
        self.confirmed: list[str] = []
        self.fail_with: str | None = None

    def load(self) -> ReadinessConfig:
        return self.config

    def save(self, config: ReadinessConfig) -> tuple[str, ...]:
        if self.fail_with is not None:
            raise ServiceError(self.fail_with)
        self.config = config
        return ()

    def badge_for_field(self, field: str) -> str | None:
        return self.badges.get(field)

    def confirm(self, placeholder_id: str) -> None:
        self.confirmed.append(placeholder_id)
        self.badges = {k: v for k, v in self.badges.items() if v != placeholder_id}


def _cells(model: QAbstractItemModel, row: int, columns: int) -> list[object]:
    return [model.index(row, column).data() for column in range(columns)]


def _open_dialog[D: QDialog](page: QWidget, kind: type[D]) -> D:
    shown = [dialog for dialog in page.findChildren(kind) if dialog.isVisible()]
    assert len(shown) == 1
    return shown[0]


def _warnings(prompts: FakePrompts) -> list[str]:
    return [call.text for call in prompts.calls_of("warning")]


def _pick_source(dialog: EntryDialog, context: AppContext, code: str = "DIRSA") -> None:
    index = dialog.source_combo.findData(_source_id(context, code))
    assert index >= 0
    dialog.source_combo.setCurrentIndex(index)


def _select_source(section: BudgetSettingsSection, code: str) -> None:
    for row, source in enumerate(section.model.rows()):
        if source.code == code:
            section.view.selectRow(row)
            return
    raise AssertionError(code)


@pytest.fixture
def pseudo_context(
    app_context: AppContext,
    translator_manager_factory: Callable[[Path | None], TranslatorManager],
    pseudo_qm_dir: Path,
) -> AppContext:
    """The context with every translated text wrapped in the pseudo-locale markers."""
    app_context.translator_manager.clear()
    manager = translator_manager_factory(pseudo_qm_dir)
    manager.set_language("pt_BR")
    app_context.translator_manager = manager
    return app_context


# --------------------------------------------------------------------------- typed amounts


@pytest.mark.parametrize(
    ("lang", "typed", "shown"),
    [
        ("pt_BR", "1.234,56", f"R${NBSP}1.234,56"),
        ("es_ES", "1.234,56", f"1234,56{NBSP}R$"),
        ("en_US", "1,234.56", "R$1,234.56"),
    ],
)
def test_a_typed_allocated_amount_is_stored_in_minor_units_and_shown_back(
    app_context: AppContext, qtbot: QtBot, lang: str, typed: str, shown: str
) -> None:
    app_context.translator_manager.set_language(lang)
    page = BudgetPage(app_context)
    qtbot.addWidget(page)
    dialog = EntryDialog(app_context)
    qtbot.addWidget(dialog)
    _pick_source(dialog, app_context)
    dialog.allocated_edit.setText(typed)
    dialog.accept()

    (entry,) = _service(app_context).list_entries(2026)
    assert entry.allocated_minor == 123456
    assert entry.currency == "BRL"
    assert page.entries_model.index(0, 3).data() == shown
    assert page.summary_model.index(0, 2).data() == shown

    reopened = EntryDialog(app_context, None, entry)
    qtbot.addWidget(reopened)
    assert reopened.allocated_edit.text() == format_amount(123456, "BRL", lang)
    assert parse_amount(reopened.allocated_edit.text(), "BRL", lang) == 123456


@pytest.mark.parametrize(
    ("lang", "typed", "shown"),
    [
        ("pt_BR", "1.234,56", f"R${NBSP}1.234,56"),
        ("es_ES", "1.234,56", f"1234,56{NBSP}R$"),
        ("en_US", "1,234.56", "R$1,234.56"),
    ],
)
def test_a_typed_execution_amount_is_stored_in_minor_units_and_shown_back(
    app_context: AppContext, qtbot: QtBot, lang: str, typed: str, shown: str
) -> None:
    app_context.translator_manager.set_language(lang)
    entry_id = _add_entry(app_context)
    page = BudgetPage(app_context)
    qtbot.addWidget(page)
    page.entries_view.selectRow(0)
    dialog = ExecutionDialog(app_context, None, _service(app_context).get_entry(entry_id))
    qtbot.addWidget(dialog)
    dialog.date_edit.setDate(QDate(2026, 2, 10))
    dialog.amount_edit.setText(typed)
    dialog.note_edit.setText("Course fees")
    dialog.accept()

    (execution,) = _service(app_context).get_entry(entry_id).executions
    assert execution.amount_minor == 123456
    assert execution.executed_on == date(2026, 2, 10)
    assert execution.note == "Course fees"
    assert page.executions_model.rowCount() == 1
    assert page.executions_model.index(0, 1).data() == shown
    assert page.summary_model.index(0, 3).data() == shown


def test_money_follows_a_language_switch(app_context: AppContext, qtbot: QtBot) -> None:
    entry_id = _add_entry(app_context, allocated=123456)
    _service(app_context).add_execution(entry_id, date(2026, 2, 10), 5000)
    page = BudgetPage(app_context)
    qtbot.addWidget(page)
    page.entries_view.selectRow(0)
    horizontal = Qt.Orientation.Horizontal
    expected = (
        ("en_US", "R$1,234.56", "R$50.00"),
        ("pt_BR", f"R${NBSP}1.234,56", f"R${NBSP}50,00"),
        ("es_ES", f"1234,56{NBSP}R$", f"50,00{NBSP}R$"),
    )
    for lang, allocated, executed in expected:
        app_context.translator_manager.set_language(lang)
        assert page.entries_model.index(0, 3).data() == allocated
        assert page.summary_model.index(0, 2).data() == allocated
        assert page.executions_model.index(0, 1).data() == executed
        assert page.summary_model.headerData(2, horizontal) == QCoreApplication.translate(
            "Budget", "Allocated"
        )
    assert page.add_entry_action.text() != "Add entry"


def test_a_typed_amount_is_reformatted_when_the_language_changes(
    app_context: AppContext, qtbot: QtBot
) -> None:
    dialog = EntryDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.allocated_edit.setText("1,234.56")
    app_context.translator_manager.set_language("pt_BR")
    assert dialog.allocated_edit.text() == "1.234,56"
    dialog.allocated_edit.setText("not a number")
    app_context.translator_manager.set_language("es_ES")
    assert dialog.allocated_edit.text() == "not a number"


def test_an_empty_allocated_amount_means_not_set(app_context: AppContext, qtbot: QtBot) -> None:
    page = BudgetPage(app_context)
    qtbot.addWidget(page)
    dialog = EntryDialog(app_context)
    qtbot.addWidget(dialog)
    _pick_source(dialog, app_context)
    dialog.accept()
    (entry,) = _service(app_context).list_entries(2026)
    assert entry.allocated_minor is None
    assert _cells(page.entries_model, 0, 4) == ["DIRSA", "BRL", "", "-"]
    assert _cells(page.summary_model, 0, 5) == ["DIRSA", "BRL", "-", "R$0.00", "-"]


# --------------------------------------------------------------------------- invalid amounts


@pytest.mark.parametrize(
    ("typed", "code"),
    [
        ("1,234.56", "AMBIGUOUS_NUMBER"),
        ("-5,00", "NEGATIVE_AMOUNT"),
        ("1,234", "TOO_MANY_DECIMALS"),
        ("abc", "INVALID_NUMBER"),
        ("99999999999999999999,00", "TOO_LARGE"),
    ],
)
def test_an_invalid_allocated_amount_shows_the_translated_message_and_writes_nothing(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot, typed: str, code: str
) -> None:
    app_context.translator_manager.set_language("pt_BR")
    dialog = EntryDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    _pick_source(dialog, app_context)
    dialog.allocated_edit.setText(typed)
    dialog.accept()
    (text,) = _warnings(fake_prompts)
    assert text == error_label(code)
    english = {
        "AMBIGUOUS_NUMBER": "The number uses the separators of another language.",
        "NEGATIVE_AMOUNT": "The amount cannot be negative.",
        "TOO_MANY_DECIMALS": "The amount has more decimal places than the currency allows.",
        "INVALID_NUMBER": "The number is not valid.",
        "TOO_LARGE": "The amount is too large.",
    }
    assert text != english[code]
    assert dialog.isVisible()
    assert _service(app_context).list_entries() == []


@pytest.mark.parametrize(
    ("typed", "english"),
    [
        ("1.234,56", "The number uses the separators of another language."),
        ("-1.00", "The amount cannot be negative."),
        ("1.234", "The amount has more decimal places than the currency allows."),
        ("", "A required field is empty."),
    ],
)
def test_an_invalid_execution_amount_is_refused_and_nothing_is_written(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot, typed: str, english: str
) -> None:
    entry_id = _add_entry(app_context)
    dialog = ExecutionDialog(app_context, None, _service(app_context).get_entry(entry_id))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.amount_edit.setText(typed)
    dialog.accept()
    assert _warnings(fake_prompts) == [english]
    assert fake_prompts.calls_of("warning")[0].title == "Cannot save"
    assert dialog.isVisible()
    assert _service(app_context).get_entry(entry_id).executions == ()


def test_a_service_error_is_shown_translated_and_keeps_the_dialog_open(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _add_entry(app_context, description="Same")
    app_context.translator_manager.set_language("es_ES")
    dialog = EntryDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    _pick_source(dialog, app_context)
    dialog.description_edit.setText("Same")
    dialog.accept()
    (text,) = _warnings(fake_prompts)
    assert text == error_label("DUPLICATE_ENTRY")
    assert text != "An entry for this year, source, currency and description already exists."
    assert dialog.isVisible()
    assert len(_service(app_context).list_entries()) == 1


def test_an_entry_without_a_source_is_refused(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    dialog = EntryDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.source_combo.setCurrentIndex(-1)
    dialog.accept()
    assert _warnings(fake_prompts) == ["A required field is empty."]
    assert dialog.isVisible()


# --------------------------------------------------------------------------- summary


def test_the_summary_updates_after_each_edit(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    service = _service(app_context)
    page = BudgetPage(app_context)
    qtbot.addWidget(page)
    assert page.summary_model.rowCount() == 0

    dialog = EntryDialog(app_context)
    qtbot.addWidget(dialog)
    _pick_source(dialog, app_context)
    dialog.allocated_edit.setText("10,000.00")
    dialog.description_edit.setText("Training")
    dialog.accept()
    assert _cells(page.summary_model, 0, 5) == ["DIRSA", "BRL", "R$10,000.00", "R$0.00", "0.0%"]

    page.entries_view.selectRow(0)
    entry = page.selected_entry()
    assert entry is not None
    execution_dialog = ExecutionDialog(app_context, None, entry)
    qtbot.addWidget(execution_dialog)
    execution_dialog.date_edit.setDate(QDate(2026, 2, 10))
    execution_dialog.amount_edit.setText("1,000.00")
    execution_dialog.accept()
    assert _cells(page.summary_model, 0, 5)[3:] == ["R$1,000.00", "10.0%"]
    assert page.executions_model.rowCount() == 1
    assert _cells(page.executions_model, 0, 3) == ["02/10/2026", "R$1,000.00", ""]

    page.executions_view.selectRow(0)
    page.edit_execution()
    edit_dialog = _open_dialog(page, ExecutionDialog)
    assert edit_dialog.amount_edit.text() == "1,000.00"
    edit_dialog.amount_edit.setText("2,000.00")
    edit_dialog.accept()
    assert _cells(page.summary_model, 0, 5)[3:] == ["R$2,000.00", "20.0%"]

    fake_prompts.script("confirm", True)
    page.delete_execution_action.trigger()
    assert service.list_entries(2026)[0].executions == ()
    assert _cells(page.summary_model, 0, 5)[3:] == ["R$0.00", "0.0%"]
    assert page.executions_model.rowCount() == 0

    page.edit_entry()
    entry_dialog = _open_dialog(page, EntryDialog)
    assert entry_dialog.allocated_edit.text() == "10,000.00"
    entry_dialog.allocated_edit.setText("4,000.00")
    entry_dialog.accept()
    assert _cells(page.summary_model, 0, 5)[2] == "R$4,000.00"


def test_changing_the_as_of_date_changes_the_executed_amount(
    app_context: AppContext, qtbot: QtBot
) -> None:
    service = _service(app_context)
    entry_id = _add_entry(app_context)
    service.add_execution(entry_id, date(2026, 2, 10), 100_000)
    service.add_execution(entry_id, date(2026, 4, 10), 200_000)
    page = BudgetPage(app_context)
    qtbot.addWidget(page)
    assert app_context.as_of == date(2026, 3, 5)
    assert _cells(page.summary_model, 0, 5)[3:] == ["R$1,000.00", "10.0%"]

    app_context.set_as_of(date(2026, 6, 1))
    assert _cells(page.summary_model, 0, 5)[3:] == ["R$3,000.00", "30.0%"]
    app_context.set_as_of(date(2026, 1, 1))
    assert _cells(page.summary_model, 0, 5)[3:] == ["R$0.00", "0.0%"]
    page.entries_view.selectRow(0)
    assert page.executions_model.rowCount() == 2  # the rows stay listed; only the total moves


def test_two_currencies_are_on_separate_rows_and_never_added(
    app_context: AppContext, qtbot: QtBot
) -> None:
    service = _service(app_context)
    brl = _add_entry(app_context, currency="BRL", allocated=1_000_000)
    usd = _add_entry(app_context, currency="USD", allocated=500_000)
    service.add_execution(brl, date(2026, 2, 10), 100_000)
    service.add_execution(usd, date(2026, 2, 11), 50_000)
    page = BudgetPage(app_context)
    qtbot.addWidget(page)
    assert page.summary_model.rowCount() == 2
    rows = {tuple(_cells(page.summary_model, row, 5)) for row in range(2)}
    assert rows == {
        ("DIRSA", "BRL", "R$10,000.00", "R$1,000.00", "10.0%"),
        ("DIRSA", "USD", "US$5,000.00", "US$500.00", "10.0%"),
    }
    assert page.entries_model.rowCount() == 2


def test_the_year_selector_defaults_to_the_as_of_fiscal_year_and_follows_it(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _add_entry(app_context, year=2025, allocated=100)
    _add_entry(app_context, year=2026, allocated=200)
    page = BudgetPage(app_context)
    qtbot.addWidget(page)
    assert page.year_spin.value() == 2026
    assert [row.entry.fiscal_year for row in page.entries_model.rows()] == [2026]

    page.year_spin.setValue(2025)  # the user picks another year: it stays
    assert [row.entry.fiscal_year for row in page.entries_model.rows()] == [2025]
    app_context.set_as_of(date(2027, 1, 5))
    assert page.year_spin.value() == 2025

    page.year_spin.setValue(2027)  # the year of the as-of date: it follows the date again
    assert page.entries_model.rowCount() == 0
    app_context.set_as_of(date(2028, 1, 5))
    assert page.year_spin.value() == 2028


def test_the_year_follows_the_as_of_date_while_the_user_has_not_chosen(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _add_entry(app_context, year=2026)
    page = BudgetPage(app_context)
    qtbot.addWidget(page)
    app_context.set_as_of(date(2027, 1, 5))
    assert page.year_spin.value() == 2027
    assert page.summary_model.rowCount() == 0
    app_context.set_as_of(date(2026, 12, 31))
    assert page.year_spin.value() == 2026
    assert page.summary_model.rowCount() == 1


def test_the_page_opens_its_dialogs_without_blocking(app_context: AppContext, qtbot: QtBot) -> None:
    page = BudgetPage(app_context)
    qtbot.addWidget(page)
    page.year_spin.setValue(2025)
    page.add_entry()
    dialog = _open_dialog(page, EntryDialog)
    assert dialog.year_spin.value() == 2025
    _pick_source(dialog, app_context, "OPCW_TRUST_FUND")
    dialog.allocated_edit.setText("1.00")
    dialog.currency_combo.setCurrentIndex(dialog.currency_combo.findData("EUR"))
    dialog.accept()
    (entry,) = _service(app_context).list_entries(2025)
    assert (entry.source_code, entry.currency) == ("OPCW_TRUST_FUND", "EUR")
    assert page.entries_model.index(0, 0).data() == "OPCW Trust Fund"


def test_deleting_an_entry_asks_for_confirmation(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    service = _service(app_context)
    entry_id = _add_entry(app_context, description="Courses")
    service.add_execution(entry_id, date(2026, 2, 10), 100)
    page = BudgetPage(app_context)
    qtbot.addWidget(page)
    page.entries_view.selectRow(0)
    assert page.delete_entry_action.isEnabled()

    fake_prompts.script("confirm", False)
    page.delete_entry_action.trigger()
    (call,) = fake_prompts.calls_of("confirm")
    assert "DIRSA" in call.text
    assert "Courses" in call.text
    assert call.title == "Delete entry"
    assert len(service.list_entries()) == 1

    fake_prompts.script("confirm", True)
    page.delete_entry_action.trigger()
    assert service.list_entries() == []
    assert page.entries_model.rowCount() == 0
    assert page.summary_model.rowCount() == 0
    assert not page.add_execution_action.isEnabled()


# --------------------------------------------------------------------------- currency and config


def test_a_new_entry_defaults_to_the_configured_currency(
    app_context: AppContext, qtbot: QtBot
) -> None:
    config = _with_config(app_context)
    first = EntryDialog(app_context)
    qtbot.addWidget(first)
    assert first.currency_combo.currentData() == "BRL"

    config.save(config.load().with_changes(default_currency="USD"))
    dialog = EntryDialog(app_context)
    qtbot.addWidget(dialog)
    assert dialog.currency_combo.currentData() == "USD"
    assert [dialog.currency_combo.itemData(i) for i in range(dialog.currency_combo.count())] == [
        "BRL",
        "USD",
        "EUR",
    ]
    _pick_source(dialog, app_context)
    dialog.allocated_edit.setText("100.50")
    dialog.accept()
    (entry,) = _service(app_context).list_entries(2026)
    assert (entry.currency, entry.allocated_minor) == ("USD", 10050)

    reopened = EntryDialog(app_context, None, entry)
    qtbot.addWidget(reopened)
    assert reopened.currency_combo.currentData() == "USD"


def test_without_a_configuration_service_the_default_currency_is_the_built_in_one(
    app_context: AppContext, qtbot: QtBot
) -> None:
    vars(app_context.services)["config"] = None
    dialog = EntryDialog(app_context)
    qtbot.addWidget(dialog)
    assert dialog.currency_combo.currentData() == "BRL"
    section = BudgetSettingsSection(app_context)
    qtbot.addWidget(section)
    assert not section.currency_combo.isEnabled()
    assert not section.prorate_check.isEnabled()


def test_the_settings_section_changes_the_currency_and_the_pro_rating_switch(
    app_context: AppContext, qtbot: QtBot
) -> None:
    config = _with_config(app_context)
    section = BudgetSettingsSection(app_context)
    qtbot.addWidget(section)
    assert section.currency_combo.currentData() == "BRL"
    assert section.prorate_check.isChecked() is config.load().budget_prorate_target

    section.currency_combo.setCurrentIndex(section.currency_combo.findData("EUR"))
    assert config.load().default_currency == "EUR"
    section.prorate_check.setChecked(False)
    assert config.load().budget_prorate_target is False
    assert config.load().default_currency == "EUR"
    section.prorate_check.setChecked(True)
    assert config.load().budget_prorate_target is True

    config.save(config.load().with_changes(default_currency="USD"))
    app_context.notify_data_changed()
    assert section.currency_combo.currentData() == "USD"


def test_the_placeholder_badges_and_confirm_buttons_follow_the_configuration(
    app_context: AppContext, qtbot: QtBot
) -> None:
    fake = _FakeConfig({"default_currency": "A08", "budget_prorate_target": "P08"})
    vars(app_context.services)["config"] = fake
    section = BudgetSettingsSection(app_context)
    qtbot.addWidget(section)
    assert not section.currency_badge.isHidden()
    assert not section.prorate_badge.isHidden()
    assert section.currency_badge.text() == "Placeholder - to be confirmed"
    assert section.currency_confirm.text() == "Confirm"

    section.currency_confirm.click()
    assert fake.confirmed == ["A08"]
    assert section.currency_badge.isHidden()
    assert section.currency_confirm.isHidden()
    assert not section.prorate_badge.isHidden()
    section.prorate_confirm.click()
    assert fake.confirmed == ["A08", "P08"]
    assert section.prorate_badge.isHidden()

    section.prorate_check.setChecked(False)
    assert fake.config.budget_prorate_target is False
    section.currency_combo.setCurrentIndex(section.currency_combo.findData("USD"))
    assert fake.config.default_currency == "USD"


def test_a_refused_configuration_change_shows_the_message_and_restores_the_control(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    fake = _FakeConfig({})
    fake.fail_with = "READ_ONLY"
    vars(app_context.services)["config"] = fake
    section = BudgetSettingsSection(app_context)
    qtbot.addWidget(section)
    section.currency_combo.setCurrentIndex(section.currency_combo.findData("USD"))
    assert _warnings(fake_prompts) == ["The data is read-only: nothing was saved."]
    assert fake.config.default_currency == "BRL"
    assert section.currency_combo.currentData() == "BRL"
    section.prorate_check.setChecked(False)
    assert len(_warnings(fake_prompts)) == 2
    assert section.prorate_check.isChecked()


# --------------------------------------------------------------------------- funding sources


def test_the_source_editor_adds_edits_deactivates_and_deletes(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    section = BudgetSettingsSection(app_context)
    qtbot.addWidget(section)
    assert [row.code for row in section.model.rows()] == ["DIRSA", "OPCW_TRUST_FUND"]
    assert _cells(section.model, 0, 4) == ["DIRSA", "DIRSA", "Built-in", "Active"]
    assert _cells(section.model, 1, 4) == [
        "OPCW_TRUST_FUND",
        "OPCW Trust Fund",
        "Built-in",
        "Active",
    ]

    dialog = SourceDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.code_edit.setText("FUNDX")
    dialog.label_pt_edit.setText("Fonte X")
    dialog.label_en_edit.setText("Source X")
    dialog.accept()
    assert [row.code for row in section.model.rows()] == ["DIRSA", "FUNDX", "OPCW_TRUST_FUND"]
    assert _cells(section.model, 1, 4) == ["FUNDX", "Source X", "User-defined", "Active"]

    _select_source(section, "FUNDX")
    section.edit_source()
    edit_dialog = _open_dialog(section, SourceDialog)
    assert edit_dialog.label_en_edit.text() == "Source X"
    edit_dialog.label_en_edit.setText("Source Y")
    edit_dialog.accept()
    assert section.model.index(1, 1).data() == "Source Y"
    app_context.translator_manager.set_language("es_ES")
    assert section.model.index(1, 1).data() == "Fonte X"  # no Spanish label: pt-BR first

    app_context.translator_manager.set_language("en_US")
    assert section.deactivate_action.isEnabled()
    section.deactivate_action.trigger()
    assert section.model.index(1, 3).data() == "Inactive"
    assert not section.deactivate_action.isEnabled()
    assert [s.code for s in _service(app_context).list_sources()] == ["DIRSA", "OPCW_TRUST_FUND"]

    fake_prompts.script("confirm", True)
    section.delete_action.trigger()
    assert [row.code for row in section.model.rows()] == ["DIRSA", "OPCW_TRUST_FUND"]


def test_built_in_sources_cannot_be_deleted(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    section = BudgetSettingsSection(app_context)
    qtbot.addWidget(section)
    _select_source(section, "DIRSA")
    fake_prompts.script("confirm", True)
    section.delete_action.trigger()
    assert _warnings(fake_prompts) == [
        "A built-in source cannot be deleted and its code cannot change."
    ]
    assert _service(app_context).get_source_by_code("DIRSA") is not None
    assert section.model.rowCount() == 2

    app_context.translator_manager.set_language("pt_BR")
    _select_source(section, "OPCW_TRUST_FUND")
    fake_prompts.script("confirm", True)
    section.delete_action.trigger()
    assert _warnings(fake_prompts)[-1] == error_label("BUILT_IN_SOURCE")
    assert _warnings(fake_prompts)[-1] != _warnings(fake_prompts)[0]
    assert section.model.rowCount() == 2


def test_a_source_used_by_an_entry_cannot_be_deleted(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    service = _service(app_context)
    source_id = service.create_source(SourceInput("FUNDX", label_pt_br="Fonte X"))
    service.create_entry(EntryInput(fiscal_year=2026, source_id=source_id, allocated_minor=1))
    section = BudgetSettingsSection(app_context)
    qtbot.addWidget(section)
    _select_source(section, "FUNDX")
    fake_prompts.script("confirm", True)
    section.delete_action.trigger()
    assert _warnings(fake_prompts) == [
        "The source is used by an entry and cannot be deleted. Deactivate it instead."
    ]
    assert section.model.rowCount() == 3


def test_the_dialog_of_a_built_in_source_keeps_its_code_and_labels(
    app_context: AppContext, qtbot: QtBot
) -> None:
    source = _service(app_context).get_source_by_code("OPCW_TRUST_FUND")
    assert source is not None
    dialog = SourceDialog(app_context, None, source)
    qtbot.addWidget(dialog)
    for edit in (
        dialog.code_edit,
        dialog.label_pt_edit,
        dialog.label_en_edit,
        dialog.label_es_edit,
    ):
        assert edit.isReadOnly()
    dialog.active_check.setChecked(False)
    dialog.accept()
    stored = _service(app_context).get_source_by_code("OPCW_TRUST_FUND")
    assert stored is not None
    assert not stored.active
    assert stored.label_pt_br is None


def test_a_user_source_needs_a_portuguese_label(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    dialog = SourceDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.code_edit.setText("FUNDX")
    dialog.accept()
    assert _warnings(fake_prompts) == ["The Portuguese (Brazil) label is required."]
    assert dialog.isVisible()
    assert _service(app_context).get_source_by_code("FUNDX") is None


# --------------------------------------------------------------------------- read-only, no service


def test_read_only_mode_disables_every_edit(app_context: AppContext, qtbot: QtBot) -> None:
    entry_id = _add_entry(app_context)
    _service(app_context).add_execution(entry_id, date(2026, 2, 10), 100)
    _with_config(app_context)
    app_context.read_only = True
    page = BudgetPage(app_context)
    qtbot.addWidget(page)
    section = BudgetSettingsSection(app_context)
    qtbot.addWidget(section)
    page.entries_view.selectRow(0)
    page.executions_view.selectRow(0)
    section.view.selectRow(0)
    actions = [*page._actions, *section._actions]
    assert len(actions) == 10
    targets = app_context.edit_targets()
    for action in actions:
        assert action in targets
        assert not action.isEnabled()
    for widget in (
        section.currency_combo,
        section.prorate_check,
        section.currency_confirm,
        section.prorate_confirm,
    ):
        assert widget in targets
        assert not widget.isEnabled()


def test_the_page_builds_without_a_budget_service(app_context: AppContext, qtbot: QtBot) -> None:
    app_context.services.budget = None
    vars(app_context.services)["config"] = None
    page = BudgetPage(app_context)
    qtbot.addWidget(page)
    section = BudgetSettingsSection(app_context)
    qtbot.addWidget(section)
    assert page.summary_model.rowCount() == 0
    assert page.entries_model.rowCount() == 0
    assert page.executions_model.rowCount() == 0
    assert section.model.rowCount() == 0
    assert not page.add_entry_action.isEnabled()
    assert not section.add_action.isEnabled()
    for dialog in (
        demo_entry_dialog(app_context, None),
        demo_execution_dialog(app_context, None),
        demo_source_dialog(app_context, None),
    ):
        qtbot.addWidget(dialog)
        assert dialog.windowTitle()
        dialog.show()
        dialog.accept()  # no service: nothing is written and the dialog stays open
        assert dialog.isVisible()


def test_the_actions_follow_the_selection(app_context: AppContext, qtbot: QtBot) -> None:
    entry_id = _add_entry(app_context)
    _service(app_context).add_execution(entry_id, date(2026, 2, 10), 100)
    page = BudgetPage(app_context)
    qtbot.addWidget(page)
    assert page.add_entry_action.isEnabled()
    assert not page.edit_entry_action.isEnabled()
    assert not page.add_execution_action.isEnabled()
    page.entries_view.selectRow(0)
    assert page.edit_entry_action.isEnabled()
    assert page.add_execution_action.isEnabled()
    assert not page.edit_execution_action.isEnabled()
    page.executions_view.selectRow(0)
    assert page.edit_execution_action.isEnabled()
    assert page.delete_execution_action.isEnabled()
    assert page.selected_execution() is not None


# --------------------------------------------------------------------------- pseudo-locale walk

FACTORIES: dict[str, Callable[[AppContext], QWidget]] = {
    "page": create_page,
    "settings_section": create_settings_section,
    "entry_dialog": lambda context: demo_entry_dialog(context, None),
    "execution_dialog": lambda context: demo_execution_dialog(context, None),
    "source_dialog": lambda context: demo_source_dialog(context, None),
}


@pytest.mark.parametrize("name", list(FACTORIES))
def test_everything_is_translated_in_the_pseudo_locale(
    pseudo_context: AppContext, qtbot: QtBot, name: str
) -> None:
    widget = FACTORIES[name](pseudo_context)
    qtbot.addWidget(widget)
    assert_fully_translated(widget)


@pytest.mark.parametrize("name", ["page", "settings_section"])
def test_the_pseudo_locale_walk_with_data(
    pseudo_context: AppContext, qtbot: QtBot, name: str
) -> None:
    entry_id = _add_entry(pseudo_context, description="Courses")
    _service(pseudo_context).add_execution(entry_id, date(2026, 2, 10), 100)
    _service(pseudo_context).create_source(SourceInput("FUNDX", label_pt_br="Fonte X"))
    widget = FACTORIES[name](pseudo_context)
    qtbot.addWidget(widget)
    if isinstance(widget, BudgetPage):
        widget.entries_view.selectRow(0)
        widget.executions_view.selectRow(0)
    assert_fully_translated(widget)


def test_the_pseudo_locale_walk_with_visible_badges(
    pseudo_context: AppContext, qtbot: QtBot
) -> None:
    vars(pseudo_context.services)["config"] = _FakeConfig(
        {"default_currency": "A08", "budget_prorate_target": "P08"}
    )
    section = BudgetSettingsSection(pseudo_context)
    qtbot.addWidget(section)
    assert not section.currency_badge.isHidden()
    assert_fully_translated(section)


def test_the_dialogs_with_data_are_translated_in_the_pseudo_locale(
    pseudo_context: AppContext, qtbot: QtBot
) -> None:
    entry_id = _add_entry(pseudo_context)
    entry = _service(pseudo_context).get_entry(entry_id)
    for dialog in (
        EntryDialog(pseudo_context),
        EntryDialog(pseudo_context, None, entry),
        ExecutionDialog(pseudo_context, None, entry),
        SourceDialog(pseudo_context),
    ):
        qtbot.addWidget(dialog)
        assert_fully_translated(dialog)


def test_the_titles_are_translated(pseudo_context: AppContext) -> None:
    assert page_title() == "\u27e6Budget\u27e7"
    assert settings_section_title() == "\u27e6Funding sources and budget rules\u27e7"


# --------------------------------------------------------------------------- labels


def test_every_built_in_source_and_error_code_has_a_label_in_all_languages(
    app_context: AppContext,
) -> None:
    names: dict[str, dict[str, str]] = {}
    errors: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        app_context.translator_manager.set_language(lang)
        names[lang] = {
            code: source_display(
                SourceView(0, code, True, None, None, None, True),
                lang,
            )
            for code in BUILT_IN_SOURCE_CODES
        }
        errors[lang] = {code: error_label(code) for code in ALL_ERROR_CODES}
    assert set(BUILT_IN_SOURCE_CODES) == {"DIRSA", "OPCW_TRUST_FUND"}
    for lang in LANGUAGES:
        assert all(text.strip() for text in names[lang].values())
        for code, text in errors[lang].items():
            assert text.strip(), (lang, code)
            assert text != code, (lang, code)
        assert names[lang]["DIRSA"] == "DIRSA"
    assert names["en_US"]["OPCW_TRUST_FUND"] == "OPCW Trust Fund"
    assert names["pt_BR"]["OPCW_TRUST_FUND"] == "Trust Fund da OPAQ"
    assert names["es_ES"]["OPCW_TRUST_FUND"] == "Fondo Fiduciario de la OPAQ"
    for code, english in errors["en_US"].items():
        assert errors["pt_BR"][code] != english, code
        assert errors["es_ES"][code] != english, code


def test_a_user_source_is_shown_with_its_label_and_the_fallback_order(
    app_context: AppContext,
) -> None:
    both = SourceView(1, "FUNDX", False, "Fonte X", "Source X", None, True)
    only_code = SourceView(2, "FUNDY", False, None, None, None, True)
    assert source_display(both, "pt_BR") == "Fonte X"
    assert source_display(both, "en_US") == "Source X"
    assert source_display(both, "es_ES") == "Fonte X"
    assert source_display(only_code, "en_US") == "FUNDY"


def test_an_unknown_code_is_shown_as_itself() -> None:
    assert error_label("NOT_A_CODE") == "NOT_A_CODE"


def _constants(module: object) -> set[str]:
    return {
        name
        for name, value in vars(module).items()
        if name.isupper() and isinstance(value, str) and value == name
    }


def test_all_error_codes_lists_every_code_of_the_services() -> None:
    found = _constants(budget_module) | _constants(errors_module)
    assert {"DUPLICATE_ENTRY", "BUILT_IN_SOURCE", "NEGATIVE_AMOUNT", "READ_ONLY"} <= found
    assert found <= set(ALL_ERROR_CODES), sorted(found - set(ALL_ERROR_CODES))
    assert len(set(ALL_ERROR_CODES)) == len(ALL_ERROR_CODES)


def test_all_error_codes_lists_the_format_and_configuration_codes() -> None:
    # ``formatting`` imports decimal's rounding-mode names, which are strings equal to their name.
    format_codes = _constants(formatting_module) - _constants(decimal)
    assert {"EMPTY", "AMBIGUOUS_NUMBER", "TOO_MANY_DECIMALS", "TOO_LARGE"} <= format_codes
    assert format_codes <= set(ALL_ERROR_CODES), sorted(format_codes - set(ALL_ERROR_CODES))
    assert set(CONFIG_ERROR_CODES) <= set(ALL_ERROR_CODES)
    assert {"CORRUPT_SETTING", "UNKNOWN_PLACEHOLDER"} <= set(ALL_ERROR_CODES)
