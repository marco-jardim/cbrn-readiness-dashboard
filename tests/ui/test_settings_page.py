# SPDX-License-Identifier: GPL-3.0-or-later
"""The Settings page, its own sections, the target dialog and the labels (PLAN.md T6.1)."""

import ast
import inspect
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import pytest
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QPushButton, QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard.domain.config import ReadinessConfig
from cbrn_dashboard.domain.indicators import Direction, UnitKind
from cbrn_dashboard.domain.registry import build_registry
from cbrn_dashboard.services import config as config_module
from cbrn_dashboard.services import errors as errors_module
from cbrn_dashboard.services import indicators as indicators_module
from cbrn_dashboard.services.budget import EntryInput
from cbrn_dashboard.services.config import CONFIG_ERROR_CODES, ConfigService
from cbrn_dashboard.services.indicators import IndicatorService
from cbrn_dashboard.ui.dashboard import labels as dashboard_labels
from cbrn_dashboard.ui.settings import page as page_module
from cbrn_dashboard.ui.settings.dialogs import TargetDialog
from cbrn_dashboard.ui.settings.labels import (
    ALL_ERROR_CODES,
    GROUP_CODES,
    INDICATOR_CODES,
    dimension_text,
    direction_label,
    error_label,
    group_label,
    indicator_label,
    unit_label,
)
from cbrn_dashboard.ui.settings.page import (
    SettingsPage,
    alerts_section_title,
    create_alerts_section,
    create_general_section,
    create_page,
    create_targets_section,
    demo_target_dialog,
    general_section_title,
    page_title,
    targets_section_title,
)
from cbrn_dashboard.ui.settings.sections import AlertsSection, GeneralSection, TargetsSection
from cbrn_dashboard.ui.shell import formatting as formatting_module
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.context import AppContext, Services
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from tests.ui._fakes import FakePrompts
from tests.ui._walk import assert_fully_translated, find_untranslated

pytestmark = pytest.mark.ui

LANGUAGES = ("pt_BR", "en_US", "es_ES")
EXPECTED_GROUPS = (
    "general",
    "alerts",
    "targets",
    "personnel",
    "infrastructure",
    "exercises",
    "budget",
)

OWN_SPECS = (
    registry.SettingsSectionSpec(
        "settings.general", "general", general_section_title, create_general_section
    ),
    registry.SettingsSectionSpec(
        "settings.alerts", "alerts", alerts_section_title, create_alerts_section
    ),
    registry.SettingsSectionSpec(
        "settings.targets", "targets", targets_section_title, create_targets_section
    ),
)


# --------------------------------------------------------------------------- helpers


@pytest.fixture(autouse=True)
def own_sections() -> Iterator[None]:
    """Make sure the three sections of T6.1 are registered (they are once the shell lists them)."""
    known = {spec.key for spec in registry.settings_sections()}
    missing = [spec for spec in OWN_SPECS if spec.key not in known]
    with registry.registered(*missing):
        yield


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


def _config(context: AppContext) -> ConfigService:
    service = context.services.config
    assert service is not None
    return service


def _indicators(context: AppContext) -> IndicatorService:
    service = context.services.indicators
    assert service is not None
    return service


def _warnings(prompts: FakePrompts) -> list[str]:
    return [call.text for call in prompts.calls_of("warning")]


def _log_rows(context: AppContext) -> int:
    assert context.conn is not None
    return int(context.conn.execute("SELECT count(*) FROM change_log").fetchone()[0])


def _put_target(
    context: AppContext, code: str, dimension: str, warning: float | None, critical: float | None
) -> None:
    _indicators(context).set_target(code, dimension, warning_value=warning, critical_value=critical)


def _open_dialog(parent: QWidget) -> TargetDialog:
    shown = [d for d in parent.findChildren(TargetDialog) if d.isVisible()]
    assert len(shown) == 1
    return shown[0]


def _fill(dialog: TargetDialog, code: str, dimension: str, warning: str, critical: str) -> None:
    dialog.indicator_combo.setCurrentIndex(dialog.indicator_combo.findData(code))
    dialog.dimension_combo.setEditText(dimension)
    dialog.warning_edit.setText(warning)
    dialog.critical_edit.setText(critical)


def _cells(section: TargetsSection, row: int) -> list[object]:
    return [section.model.index(row, column).data() for column in range(6)]


class _StubIndicators:
    """Only what the target dialog asks of the indicator service."""

    def __init__(self) -> None:
        self.registry = build_registry()

    def definitions(self) -> list[object]:
        return list(self.registry)

    def known_dimensions(self, as_of: object) -> dict[str, list[str]]:
        return {"PERS_CERT_VALID": ["level=A", "level=B"]}


# --------------------------------------------------------------------------- the page


def test_the_page_renders_every_registered_section_under_its_group(
    app_context: AppContext, qtbot: QtBot
) -> None:
    page = SettingsPage(app_context)
    qtbot.addWidget(page)
    assert page.groups()[: len(EXPECTED_GROUPS)] == EXPECTED_GROUPS
    assert page.section_keys("general") == ("settings.general",)
    assert page.section_keys("alerts") == ("settings.alerts",)
    assert page.section_keys("targets") == ("settings.targets",)
    assert page.section_keys("personnel") == ("personnel.rules",)
    assert page.section_keys("infrastructure") == ("infrastructure.types", "stock.types")
    assert page.section_keys("exercises") == ("exercises.metrics",)
    assert page.section_keys("budget") == ("budget.sources",)
    assert isinstance(page.section_widget("settings.general"), GeneralSection)
    assert isinstance(page.section_widget("settings.alerts"), AlertsSection)
    assert isinstance(page.section_widget("settings.targets"), TargetsSection)
    order = [registry.SETTINGS_GROUPS.index(group) for group in page.groups()]
    assert order == sorted(order)
    empty = [g for g in registry.SETTINGS_GROUPS if not registry.settings_sections(g)]
    assert not set(empty) & set(page.groups())
    assert page.section_box("settings.targets").title() == "Indicator targets"
    assert page_title() == "Settings"
    assert isinstance(create_page(app_context), SettingsPage)


def test_a_temporarily_registered_section_is_rendered_under_its_group(
    app_context: AppContext, qtbot: QtBot
) -> None:
    extra = registry.SettingsSectionSpec(
        "test.extra", "budget", lambda: "Extra box", lambda context: QLabel("Extra body")
    )
    elsewhere = registry.SettingsSectionSpec(
        "test.backup", "backup", lambda: "Backup box", lambda context: QLabel("Backup body")
    )
    before = SettingsPage(app_context)
    qtbot.addWidget(before)
    with registry.registered(extra, elsewhere):
        page = SettingsPage(app_context)
        qtbot.addWidget(page)
        assert page.section_keys("budget") == ("budget.sources", "test.extra")
        assert "backup" in page.groups()
        assert page.section_keys("backup") == ("backup.settings", "test.backup")
        assert page.section_box("test.extra").title() == "Extra box"
        body = page.section_widget("test.extra")
        assert isinstance(body, QLabel)
        assert body.text() == "Extra body"
    # The registry is read when the page is built, not at import: the earlier page is unchanged.
    assert "test.extra" not in before.section_keys("budget")
    assert "test.extra" not in registry_keys()


def registry_keys() -> set[str]:
    return {spec.key for spec in registry.settings_sections()}


def test_the_page_module_imports_the_registry_lazily() -> None:
    tree = ast.parse(inspect.getsource(page_module))
    top_level = [node for node in tree.body if isinstance(node, ast.Import | ast.ImportFrom)]
    names = [ast.unparse(node) for node in top_level]
    assert not [name for name in names if "registry" in name and "domain" not in name]


def test_titles_follow_the_language(app_context: AppContext, qtbot: QtBot) -> None:
    page = SettingsPage(app_context)
    qtbot.addWidget(page)
    index = page.groups().index("budget")
    assert page.tabs.tabText(index) == "Budget"
    assert page.section_box("settings.general").title() == "Language, operator and institution"
    app_context.translator_manager.set_language("pt_BR")
    qtbot.waitUntil(lambda: page.tabs.tabText(index) == "Orçamento")
    assert page.section_box("settings.general").title() == "Idioma, operador e instituição"
    app_context.translator_manager.set_language("es_ES")
    qtbot.waitUntil(lambda: page.tabs.tabText(index) == "Presupuesto")
    assert page.section_box("settings.alerts").title() == "Ventanas de aviso"


# --------------------------------------------------------------------------- general


def test_the_general_section_stores_the_names_and_the_operator_label(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = GeneralSection(app_context)
    qtbot.addWidget(section)
    section.operator_edit.setText("Op One")
    section.institution_edit.setText("Institute")
    section.unit_edit.setText("Unit 7")
    section.save_button.click()
    stored = _config(app_context).load()
    assert (stored.operator_label, stored.institution_name, stored.unit_name) == (
        "Op One",
        "Institute",
        "Unit 7",
    )
    assert app_context.operator_label() == "Op One"


def test_changing_only_the_operator_label_keeps_the_names(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = GeneralSection(app_context)
    qtbot.addWidget(section)
    section.operator_edit.setText("Only me")
    section.save()
    stored = _config(app_context).load()
    assert (stored.operator_label, stored.institution_name, stored.unit_name) == ("Only me", "", "")


def test_the_stored_operator_label_is_given_to_the_context(
    app_context: AppContext, qtbot: QtBot
) -> None:
    config = _config(app_context)
    config.save(config.load().with_changes(operator_label="Chief"))
    section = GeneralSection(app_context)
    qtbot.addWidget(section)
    assert section.operator_edit.text() == "Chief"
    assert app_context.operator_label() == "Chief"


def test_a_refused_general_change_is_shown_translated_and_the_form_stays(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    section = GeneralSection(app_context)
    qtbot.addWidget(section)
    rows = _log_rows(app_context)
    section.operator_edit.setText("x" * 201)
    section.save()
    assert _warnings(fake_prompts) == ["The text is not valid."]
    assert section.operator_edit.text() == "x" * 201
    assert _config(app_context).load().operator_label == ""
    assert app_context.operator_label() == ""
    assert _log_rows(app_context) == rows
    app_context.translator_manager.set_language("pt_BR")
    section.save()
    assert _warnings(fake_prompts)[-1] == error_label("INVALID_TEXT")
    assert _warnings(fake_prompts)[-1] != "The text is not valid."


def test_the_language_selector_switches_the_language(app_context: AppContext, qtbot: QtBot) -> None:
    section = GeneralSection(app_context)
    qtbot.addWidget(section)
    combo = section.language_combo
    assert combo.currentData() == "en_US"
    assert [combo.itemText(i) for i in range(3)] == [
        "Portuguese (Brazil)",
        "English (United States)",
        "Spanish (Spain)",
    ]
    combo.setCurrentIndex(combo.findData("es_ES"))
    assert app_context.translator_manager.current_language == "es_ES"
    qtbot.waitUntil(lambda: combo.itemText(2) == "Español (España)")
    assert combo.currentData() == "es_ES"
    assert [combo.itemText(i) for i in range(3)] == [
        "Portugués (Brasil)",
        "Inglés (Estados Unidos)",
        "Español (España)",
    ]
    assert section.operator_caption.text() == "Identificación del operador"
    app_context.translator_manager.set_language("pt_BR")
    qtbot.waitUntil(lambda: section.operator_caption.text() == "Identificação do operador")
    assert combo.currentData() == "pt_BR"


# --------------------------------------------------------------------------- alerts


def test_the_alert_windows_are_stored(app_context: AppContext, qtbot: QtBot) -> None:
    section = AlertsSection(app_context)
    qtbot.addWidget(section)
    assert (
        section.cert_edit.text(),
        section.maintenance_edit.text(),
        section.stock_edit.text(),
    ) == ("90", "30", "90")
    section.cert_edit.setText("120")
    section.maintenance_edit.setText("45")
    section.stock_edit.setText("60")
    section.save_button.click()
    stored = _config(app_context).load()
    assert (
        stored.cert_warning_days,
        stored.maintenance_warning_days,
        stored.stock_expiry_warning_days,
    ) == (120, 45, 60)


def test_the_stock_window_is_saved_and_read_by_the_stock_rules(
    app_context: AppContext, qtbot: QtBot
) -> None:
    stock = app_context.services.stock
    assert stock is not None
    section = AlertsSection(app_context)
    qtbot.addWidget(section)
    assert stock.stock_rules().expiry_warning_days == 90

    section.stock_edit.setText("45")
    section.save()

    assert _config(app_context).load().stock_expiry_warning_days == 45
    assert stock.stock_rules().expiry_warning_days == 45  # the next evaluation uses it
    assert section.stock_edit.text() == "45"
    assert _config(app_context).load().cert_warning_days == 90  # the other windows were not touched


@pytest.mark.parametrize(
    ("typed", "code"),
    [
        ("abc", "INVALID_NUMBER"),
        ("", "EMPTY"),
        ("-5", "NEGATIVE_DAYS"),
        ("99999", "VALUE_TOO_LARGE"),
    ],
)
def test_an_invalid_stock_window_is_refused_and_nothing_is_written(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    qtbot: QtBot,
    typed: str,
    code: str,
) -> None:
    section = AlertsSection(app_context)
    qtbot.addWidget(section)
    rows = _log_rows(app_context)
    section.stock_edit.setText(typed)

    section.save()

    assert _warnings(fake_prompts) == [error_label(code)]
    assert section.stock_edit.text() == typed
    assert _config(app_context).load().stock_expiry_warning_days == 90
    assert _log_rows(app_context) == rows


def test_the_windows_are_typed_and_shown_in_the_active_language(
    app_context: AppContext, qtbot: QtBot
) -> None:
    config = _config(app_context)
    config.save(config.load().with_changes(cert_warning_days=1500))
    section = AlertsSection(app_context)
    qtbot.addWidget(section)
    assert section.cert_edit.text() == "1,500"
    app_context.translator_manager.set_language("pt_BR")
    qtbot.waitUntil(lambda: section.cert_edit.text() == "1.500")
    app_context.translator_manager.set_language("es_ES")
    qtbot.waitUntil(lambda: section.cert_edit.text() == "1500")
    app_context.translator_manager.set_language("pt_BR")
    section.cert_edit.setText("1.200")
    section.save()
    assert config.load().cert_warning_days == 1200


@pytest.mark.parametrize(
    ("typed", "code", "english"),
    [
        ("abc", "INVALID_NUMBER", "The number is not valid."),
        ("1.5", "INVALID_NUMBER", "The number is not valid."),
        ("", "EMPTY", "Enter a value."),
        ("-5", "NEGATIVE_DAYS", "The number of days cannot be negative."),
        ("99999", "VALUE_TOO_LARGE", "The value is too large."),
    ],
)
def test_an_invalid_window_is_refused_and_nothing_is_written(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    qtbot: QtBot,
    typed: str,
    code: str,
    english: str,
) -> None:
    section = AlertsSection(app_context)
    qtbot.addWidget(section)
    rows = _log_rows(app_context)
    section.cert_edit.setText(typed)
    section.save()
    assert _warnings(fake_prompts) == [english]
    assert error_label(code) == english
    assert section.cert_edit.text() == typed
    assert _config(app_context).load().cert_warning_days == 90
    assert _log_rows(app_context) == rows


# --------------------------------------------------------------------------- targets


def test_the_dialog_stores_a_target_and_the_table_follows(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = TargetsSection(app_context)
    qtbot.addWidget(section)
    assert section.model.rowCount() == 0
    assert section.add_action.isEnabled()
    assert not section.edit_action.isEnabled()
    rows = _log_rows(app_context)

    dialog = TargetDialog(app_context)
    qtbot.addWidget(dialog)
    _fill(dialog, "PERS_CERT_VALID", "level=A", "10", "5")
    dialog.accept()

    stored = _indicators(app_context).get_target("PERS_CERT_VALID", "level=A")
    assert (stored.warning_value, stored.critical_value, stored.enabled) == (10.0, 5.0, True)
    assert _log_rows(app_context) > rows
    assert _cells(section, 0) == [
        "Staff with a valid PPE qualification",
        "Level: A",
        "Count",
        "10",
        "5",
        "Enabled",
    ]

    section.view.selectRow(0)
    assert section.edit_action.isEnabled()
    section.edit_target()
    edit = _open_dialog(section)
    assert not edit.indicator_combo.isEnabled()
    assert edit.dimension() == "level=A"
    assert (edit.warning_edit.text(), edit.critical_edit.text()) == ("10", "5")
    edit.warning_edit.setText("12")
    edit.critical_edit.setText("6")
    edit.accept()
    changed = _indicators(app_context).get_target("PERS_CERT_VALID", "level=A")
    assert (changed.warning_value, changed.critical_value) == (12.0, 6.0)
    assert _cells(section, 0)[3:5] == ["12", "6"]


@pytest.mark.parametrize(
    ("code", "dimension", "warning", "critical", "error", "english"),
    [
        (
            "PERS_CERT_VALID",
            "level=B",
            "5",
            "10",
            "TARGET_ORDER",
            "Warning and critical values are in the wrong order for this indicator.",
        ),
        (
            "PERS_CERT_EXPIRING",
            "level=A",
            "10",
            "5",
            "TARGET_ORDER",
            "Warning and critical values are in the wrong order for this indicator.",
        ),
        (
            "PERS_CERT_VALID",
            "",
            "10",
            "5",
            "INVALID_DIMENSION",
            "The dimension is not valid for this indicator.",
        ),
        (
            "PERS_CERT_VALID",
            "level=A",
            "",
            "",
            "TARGET_EMPTY",
            "Enter at least one threshold or delete the target.",
        ),
        (
            "PERS_CERT_VALID",
            "level=A",
            "abc",
            "5",
            "INVALID_NUMBER",
            "The number is not valid.",
        ),
    ],
)
def test_a_refused_target_is_shown_translated_and_nothing_is_written(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    qtbot: QtBot,
    code: str,
    dimension: str,
    warning: str,
    critical: str,
    error: str,
    english: str,
) -> None:
    dialog = TargetDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    _fill(dialog, code, dimension, warning, critical)
    rows = _log_rows(app_context)
    dialog.accept()
    assert _warnings(fake_prompts) == [english]
    assert error_label(error) == english
    assert dialog.isVisible()
    assert dialog.warning_edit.text() == warning
    assert _indicators(app_context).list_targets() == []
    assert _log_rows(app_context) == rows


def test_a_target_error_is_translated_in_the_active_language(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    app_context.translator_manager.set_language("pt_BR")
    dialog = TargetDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    _fill(dialog, "PERS_CERT_VALID", "level=B", "5", "10")
    dialog.accept()
    assert _warnings(fake_prompts) == [error_label("TARGET_ORDER")]
    assert _warnings(fake_prompts)[0] != (
        "Warning and critical values are in the wrong order for this indicator."
    )


def test_thresholds_are_typed_and_shown_in_the_active_language(
    app_context: AppContext, qtbot: QtBot
) -> None:
    app_context.translator_manager.set_language("pt_BR")
    section = TargetsSection(app_context)
    qtbot.addWidget(section)
    dialog = TargetDialog(app_context)
    qtbot.addWidget(dialog)
    # a ratio target is typed as PERCENT (90 = 90 %) and stored as a ratio
    _fill(dialog, "BUD_EXEC_RATE", "currency=BRL;source=DIRSA", "90", "70,5")
    dialog.accept()
    stored = _indicators(app_context).get_target("BUD_EXEC_RATE", "currency=BRL;source=DIRSA")
    assert (stored.warning_value, stored.critical_value) == (0.9, 0.705)
    assert _cells(section, 0) == [
        "Taxa de execução orçamentária",
        "Moeda: BRL; Fonte: DIRSA",
        "Porcentagem",
        "90,0%",
        "70,5%",
        "Ativado",
    ]
    app_context.translator_manager.set_language("en_US")
    qtbot.waitUntil(lambda: section.model.index(0, 3).data() == "90.0%")
    assert _cells(section, 0)[0] == "Budget execution rate"
    assert section.model.index(0, 4).data() == "70.5%"


def test_an_indicator_without_dimension_keys_stores_the_empty_dimension(
    app_context: AppContext, qtbot: QtBot
) -> None:
    dialog = TargetDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.indicator_combo.setCurrentIndex(dialog.indicator_combo.findData("PERS_TRAINING_12M"))
    assert not dialog.dimension_combo.isEnabled()
    assert dialog.keys_hint.text() == "This indicator has no dimension."
    dialog.warning_edit.setText("3")
    dialog.accept()
    assert _indicators(app_context).get_target("PERS_TRAINING_12M", "").warning_value == 3.0


def test_the_dialog_offers_the_dimensions_that_have_values(
    app_context: AppContext, qtbot: QtBot
) -> None:
    vars(app_context.services)["indicators"] = _StubIndicators()
    dialog = TargetDialog(app_context)
    qtbot.addWidget(dialog)
    assert dialog.selected_code() == "PERS_CERT_VALID"
    assert [dialog.dimension_combo.itemText(i) for i in range(2)] == ["level=A", "level=B"]
    assert dialog.keys_hint.text() == "Dimension keys: level"
    assert dialog.unit_value.text() == "Count"
    assert dialog.direction_value.text() == "Higher is better"


def test_a_target_can_be_switched_off_and_on_and_deleted(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _put_target(app_context, "PERS_CERT_VALID", "level=A", 10, 5)
    section = TargetsSection(app_context)
    qtbot.addWidget(section)
    section.view.selectRow(0)
    section.toggle_action.trigger()
    assert _indicators(app_context).get_target("PERS_CERT_VALID", "level=A").enabled is False
    assert _cells(section, 0)[5] == "Disabled"
    section.toggle_action.trigger()
    assert _indicators(app_context).get_target("PERS_CERT_VALID", "level=A").enabled is True

    section.delete_action.trigger()
    (call,) = fake_prompts.calls_of("confirm")
    assert call.title == "Delete target"
    assert call.text == "Delete the target of Staff with a valid PPE qualification (Level: A)?"
    assert len(_indicators(app_context).list_targets()) == 1
    fake_prompts.script("confirm", True)
    section.delete_action.trigger()
    assert _indicators(app_context).list_targets() == []
    assert section.model.rowCount() == 0
    assert not section.delete_action.isEnabled()


# --------------------------------------------------------------------------- read-only, no service


def test_read_only_mode_disables_every_edit(app_context: AppContext, qtbot: QtBot) -> None:
    _put_target(app_context, "PERS_CERT_VALID", "level=A", 10, 5)
    app_context.read_only = True
    general = GeneralSection(app_context)
    alerts = AlertsSection(app_context)
    targets = TargetsSection(app_context)
    for widget in (general, alerts, targets):
        qtbot.addWidget(widget)
    targets.view.selectRow(0)
    controls: list[QAction | QWidget] = [
        general.operator_edit,
        general.institution_edit,
        general.unit_edit,
        general.save_button,
        alerts.cert_edit,
        alerts.maintenance_edit,
        alerts.save_button,
        alerts.stock_edit,
        *targets._actions,
    ]
    registered = app_context.edit_targets()
    assert len(controls) == 12
    for control in controls:
        assert control in registered
        assert not control.isEnabled()


def test_the_sections_build_without_services(app_context: AppContext, qtbot: QtBot) -> None:
    app_context.services = Services()
    page = SettingsPage(app_context)
    qtbot.addWidget(page)
    general = page.section_widget("settings.general")
    alerts = page.section_widget("settings.alerts")
    targets = page.section_widget("settings.targets")
    assert isinstance(general, GeneralSection)
    assert isinstance(alerts, AlertsSection)
    assert isinstance(targets, TargetsSection)
    for widget in (
        general.operator_edit,
        general.save_button,
        alerts.cert_edit,
        alerts.stock_edit,
        alerts.save_button,
        targets.add_action,
    ):
        assert not widget.isEnabled()
    assert general.language_combo.isEnabled()
    assert targets.model.rowCount() == 0
    dialog = demo_target_dialog(app_context, None)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.accept()  # no service: nothing is written and the dialog stays open
    assert dialog.isVisible()


def test_the_demo_dialog_builds_without_writing(app_context: AppContext, qtbot: QtBot) -> None:
    rows = _log_rows(app_context)
    dialog = demo_target_dialog(app_context, None)
    qtbot.addWidget(dialog)
    assert isinstance(dialog, TargetDialog)
    assert dialog.windowTitle() == "Edit target"
    assert dialog.dimension() == "level=A"
    assert _indicators(app_context).list_targets() == []
    assert _log_rows(app_context) == rows


def test_a_fake_configuration_service_needs_only_load_and_save(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    class Fake:
        def __init__(self) -> None:
            self.config = ReadinessConfig()

        def load(self) -> ReadinessConfig:
            return self.config

        def save(self, config: ReadinessConfig) -> tuple[str, ...]:
            self.config = config
            return ()

    fake = Fake()
    vars(app_context.services)["config"] = fake
    section = AlertsSection(app_context)
    qtbot.addWidget(section)
    section.cert_edit.setText("100")
    section.save()
    assert fake.config.cert_warning_days == 100
    assert fake_prompts.calls == []


# --------------------------------------------------------------------------- no placeholder badges


@pytest.mark.parametrize("lang", LANGUAGES)
def test_no_section_shows_a_placeholder_badge_or_confirm_button(
    app_context: AppContext, qtbot: QtBot, lang: str
) -> None:
    """D39: no Settings section has a "to be confirmed" badge or a Confirm button."""
    app_context.translator_manager.set_language(lang)
    sections = (
        GeneralSection(app_context),
        AlertsSection(app_context),
        TargetsSection(app_context),
    )
    for section in sections:
        qtbot.addWidget(section)
    for root in sections:
        names = [w.objectName() for w in root.findChildren(QWidget)]
        assert not [n for n in names if n.endswith(("_badge", "_confirm"))], names
        labels = [w.text() for w in root.findChildren(QLabel)]
        buttons = [w.text() for w in root.findChildren(QPushButton)]
        for text in (*labels, *buttons):
            assert "Placeholder" not in text, text
            assert "Valor provisório" not in text, text
            assert "Valor provisional" not in text, text
        assert "Confirm" not in buttons
        assert "Confirmar" not in buttons


# --------------------------------------------------------------------------- pseudo-locale walk

FACTORIES: dict[str, Callable[[AppContext], QWidget]] = {
    "page": create_page,
    "general": create_general_section,
    "alerts": create_alerts_section,
    "targets": create_targets_section,
    "target_dialog": lambda context: demo_target_dialog(context, None),
}


@pytest.mark.parametrize("name", list(FACTORIES))
def test_everything_is_translated_in_the_pseudo_locale(
    pseudo_context: AppContext, qtbot: QtBot, name: str
) -> None:
    widget = FACTORIES[name](pseudo_context)
    qtbot.addWidget(widget)
    assert_fully_translated(widget)


@pytest.mark.parametrize("lang", LANGUAGES)
@pytest.mark.parametrize("name", list(FACTORIES))
def test_the_walk_carries_the_marker_of_each_language(
    pseudo_context: AppContext, qtbot: QtBot, name: str, lang: str
) -> None:
    pseudo_context.translator_manager.set_language(lang)
    widget = FACTORIES[name](pseudo_context)
    qtbot.addWidget(widget)
    assert_fully_translated(widget, lang)


def test_the_walk_with_data(pseudo_context: AppContext, qtbot: QtBot) -> None:
    _put_target(pseudo_context, "PERS_CERT_VALID", "level=A", 10, 5)
    _put_target(pseudo_context, "BUD_EXEC_RATE", "currency=BRL;source=DIRSA", 0.9, 0.7)
    with registry.registered(
        registry.SettingsSectionSpec(
            "test.walk",
            "backup",
            lambda: QCoreApplication.translate("Settings", "Backup"),
            lambda context: QLabel(QCoreApplication.translate("Settings", "Save")),
        )
    ):
        page = SettingsPage(pseudo_context)
    qtbot.addWidget(page)
    targets = page.section_widget("settings.targets")
    assert isinstance(targets, TargetsSection)
    targets.view.selectRow(0)
    assert_fully_translated(page)
    edit = TargetDialog(pseudo_context, None, _indicators(pseudo_context).list_targets()[0])
    qtbot.addWidget(edit)
    assert_fully_translated(edit)


def test_a_language_switch_re_applies_every_text(pseudo_context: AppContext, qtbot: QtBot) -> None:
    page = SettingsPage(pseudo_context)
    qtbot.addWidget(page)
    dialog = demo_target_dialog(pseudo_context, None)
    qtbot.addWidget(dialog)
    for lang in ("en_US", "es_ES", "pt_BR"):
        pseudo_context.translator_manager.set_language(lang)
        qtbot.waitUntil(lambda lang=lang: find_untranslated(page, lang) == [])
        qtbot.waitUntil(lambda lang=lang: find_untranslated(dialog, lang) == [])


def test_a_mixed_text_is_rejected_by_the_walk(pseudo_context: AppContext, qtbot: QtBot) -> None:
    section = GeneralSection(pseudo_context)
    qtbot.addWidget(section)
    section.save_button.setText("\u27e6Save\u27e7 now")
    section.operator_caption.setToolTip("Hard-coded tip")
    found = {(item.kind, item.text) for item in find_untranslated(section)}
    assert found == {("button", "\u27e6Save\u27e7 now"), ("tooltip", "Hard-coded tip")}


def test_the_titles_are_translated(pseudo_context: AppContext) -> None:
    assert page_title() == "\u27e6Settings\u27e7"
    assert general_section_title() == "\u27e6Language, operator and institution\u27e7"
    assert alerts_section_title() == "\u27e6Warning windows\u27e7"
    assert targets_section_title() == "\u27e6Indicator targets\u27e7"


# --------------------------------------------------------------------------- labels


def test_every_code_has_a_label_in_all_languages(app_context: AppContext) -> None:
    texts: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        app_context.translator_manager.set_language(lang)
        texts[lang] = {
            **{f"error:{c}": error_label(c) for c in ALL_ERROR_CODES},
            **{f"indicator:{c}": indicator_label(c) for c in INDICATOR_CODES},
            **{f"unit:{u.value}": unit_label(u.value) for u in UnitKind},
            **{f"direction:{d.value}": direction_label(d.value) for d in Direction},
            **{f"group:{g}": group_label(g) for g in GROUP_CODES},
        }
    for lang in LANGUAGES:
        for key, text in texts[lang].items():
            assert text.strip(), (lang, key)
            assert text != key.split(":", 1)[1], (lang, key)
    for key, english in texts["en_US"].items():
        assert texts["pt_BR"][key] != english, key
        assert texts["es_ES"][key] != english, key
    assert texts["en_US"]["indicator:BUD_EXEC_RATE"] == "Budget execution rate"
    assert texts["pt_BR"]["indicator:BUD_EXEC_RATE"] == "Taxa de execução orçamentária"
    assert texts["es_ES"]["direction:LOWER_IS_BETTER"] == "Cuanto menor, mejor"
    assert texts["en_US"]["group:backup"] == "Backup"


def test_the_label_tables_match_the_registries() -> None:
    assert set(INDICATOR_CODES) == set(build_registry().codes())
    assert set(GROUP_CODES) == set(registry.SETTINGS_GROUPS)


def test_an_unknown_code_is_shown_as_itself() -> None:
    assert error_label("NOT_A_CODE") == "NOT_A_CODE"
    assert indicator_label("NOT_A_CODE") == "NOT_A_CODE"
    assert unit_label("NOT_A_CODE") == "NOT_A_CODE"
    assert direction_label("NOT_A_CODE") == "NOT_A_CODE"
    assert group_label("not_a_group") == "not_a_group"


def test_a_dimension_is_shown_with_translated_keys(app_context: AppContext) -> None:
    assert dimension_text("") == "No dimension"
    assert dimension_text("level=A") == "Level: A"
    assert dimension_text("currency=BRL;source=DIRSA") == "Currency: BRL; Source: DIRSA"
    assert dimension_text("unknown=1") == "unknown: 1"
    assert dimension_text("loose") == "loose"
    app_context.translator_manager.set_language("pt_BR")
    assert dimension_text("level=A;status=ACTIVE") == "Nível: A; Situação: ACTIVE"


def _defined_constants(module: ModuleType) -> set[str]:
    """Upper-case names the module ASSIGNS to the string of their own name (not imported ones)."""
    found: set[str] = set()
    for node in ast.parse(inspect.getsource(module)).body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            found |= {
                target.id
                for target in targets
                if isinstance(target, ast.Name) and target.id.isupper() and target.id == value.value
            }
    return found


def test_all_error_codes_list_the_codes_of_the_services() -> None:
    mapped = set(ALL_ERROR_CODES)
    own = _defined_constants(indicators_module)
    assert {"UNKNOWN_INDICATOR", "TARGET_ORDER", "TARGET_EMPTY", "INVALID_NUMBER"} <= own
    assert "READ_ONLY" not in own  # imported from services.errors, not defined there
    assert own <= mapped, sorted(own - mapped)
    shared = _defined_constants(errors_module)
    assert {"READ_ONLY", "NOT_FOUND", "REQUIRED"} <= shared
    assert {"READ_ONLY", "NOT_FOUND", "REQUIRED"} <= mapped
    stored = _defined_constants(config_module)
    assert {"CORRUPT_SETTING", "UNKNOWN_PLACEHOLDER"} == stored
    # The Settings UI no longer confirms placeholders, so it cannot receive UNKNOWN_PLACEHOLDER.
    assert "UNKNOWN_PLACEHOLDER" not in mapped
    assert stored - {"UNKNOWN_PLACEHOLDER"} <= mapped
    assert set(CONFIG_ERROR_CODES) - {"UNKNOWN_PLACEHOLDER"} <= mapped
    typed = _defined_constants(formatting_module)
    assert {"EMPTY", "INVALID_NUMBER", "AMBIGUOUS_NUMBER", "TOO_LARGE"} <= typed
    assert {"EMPTY", "INVALID_NUMBER", "AMBIGUOUS_NUMBER", "TOO_LARGE"} <= mapped
    assert len(mapped) == len(ALL_ERROR_CODES)
    assert "TARGET_OUT_OF_RANGE" in own


# --------------------------------------------------------------------------- review fixes P6-xx


def _corrupt_setting(context: AppContext) -> None:
    """A stored setting that no longer validates (what a restored older backup can leave)."""
    assert context.conn is not None
    context.conn.execute(
        "INSERT INTO setting (key, value_json) VALUES (?, ?)",
        ("config.cert_warning_days", "not json"),
    )


def test_an_unreadable_setting_is_explained_in_every_section(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    """P6-01: the sections only greyed out; the translated message was never shown."""
    general = GeneralSection(app_context)
    alerts = AlertsSection(app_context)
    targets = TargetsSection(app_context)
    sections = (general, alerts, targets)
    for section in sections:
        qtbot.addWidget(section)
        assert section.problem.label.isHidden()

    _corrupt_setting(app_context)
    app_context.notify_data_changed()

    for section in sections:
        assert not section.problem.label.isHidden()
        assert section.problem.label.text() == "A stored setting cannot be read."
    assert not general.operator_edit.isEnabled()
    assert not alerts.cert_edit.isEnabled()
    assert fake_prompts.calls == []

    app_context.translator_manager.set_language("pt_BR")
    portuguese = "N\u00e3o foi poss\u00edvel ler uma configura\u00e7\u00e3o armazenada."
    for section in sections:
        qtbot.waitUntil(lambda section=section: section.problem.label.text() == portuguese)
    app_context.translator_manager.set_language("es_ES")
    for section in sections:
        qtbot.waitUntil(
            lambda section=section: (
                section.problem.label.text() == "No se puede leer un ajuste almacenado."
            )
        )

    assert app_context.conn is not None  # repaired: the message goes and the forms work again
    app_context.conn.execute("DELETE FROM setting WHERE key = 'config.cert_warning_days'")
    app_context.notify_data_changed()
    for section in sections:
        assert section.problem.label.isHidden()
    assert general.operator_edit.isEnabled()


def test_saving_one_section_keeps_the_unsaved_typing_of_the_others(
    app_context: AppContext, qtbot: QtBot
) -> None:
    """P6-10: every form reloaded on any data_changed, so a save wiped the typing elsewhere."""
    general = GeneralSection(app_context)
    alerts = AlertsSection(app_context)
    qtbot.addWidget(general)
    qtbot.addWidget(alerts)
    assert not general.is_dirty()
    general.operator_edit.setText("typed, not saved")
    assert general.is_dirty()

    alerts.cert_edit.setText("120")
    alerts.save()  # data_changed is announced to every form

    assert general.operator_edit.text() == "typed, not saved"
    assert general.is_dirty()
    assert alerts.cert_edit.text() == "120"
    assert not alerts.is_dirty()  # saved: clean again

    config = _config(app_context)
    config.save(config.load().with_changes(maintenance_warning_days=45))
    app_context.notify_data_changed()
    assert alerts.maintenance_edit.text() == "45"  # a clean form follows the stored value
    alerts.cert_edit.setText("77")
    config.save(config.load().with_changes(maintenance_warning_days=50))
    app_context.notify_data_changed()
    assert alerts.cert_edit.text() == "77"  # a dirty form keeps what was typed
    assert alerts.maintenance_edit.text() == "45"

    general.save()
    assert _config(app_context).load().operator_label == "typed, not saved"
    assert not general.is_dirty()


def test_an_untouched_form_survives_a_language_switch_as_clean(
    app_context: AppContext, qtbot: QtBot
) -> None:
    config = _config(app_context)
    config.save(config.load().with_changes(cert_warning_days=1500))
    alerts = AlertsSection(app_context)
    qtbot.addWidget(alerts)
    assert alerts.cert_edit.text() == "1,500"

    app_context.translator_manager.set_language("pt_BR")
    qtbot.waitUntil(lambda: alerts.cert_edit.text() == "1.500")

    assert not alerts.is_dirty()  # reformatted, not edited


def test_a_target_whose_dimension_has_no_value_is_marked_not_in_use(
    app_context: AppContext, qtbot: QtBot
) -> None:
    """P6-09: "level=a" has the right structure, is stored, and never matches a reading."""
    _put_target(app_context, "PERS_CERT_VALID", "level=A", 10, 5)
    _put_target(app_context, "PERS_CERT_VALID", "level=a", 10, 5)
    section = TargetsSection(app_context)
    qtbot.addWidget(section)

    def uses() -> list[object]:
        return [section.model.index(row, 6).data() for row in range(section.model.rowCount())]

    assert section.model.headerData(6, Qt.Orientation.Horizontal) == "Use"
    assert uses() == ["In use", "Not in use"]
    app_context.translator_manager.set_language("pt_BR")
    qtbot.waitUntil(lambda: uses() == ["Em uso", "Fora de uso"])
    app_context.translator_manager.set_language("es_ES")
    qtbot.waitUntil(lambda: uses() == ["En uso", "Fuera de uso"])


def test_the_dimensions_in_use_follow_the_as_of_date(app_context: AppContext, qtbot: QtBot) -> None:
    _put_target(app_context, "BUD_EXEC_RATE", "currency=BRL;source=DIRSA", 0.9, 0.6)
    section = TargetsSection(app_context)
    qtbot.addWidget(section)
    assert section.model.index(0, 6).data() == "Not in use"  # no budget entry in this database

    budget = app_context.services.budget
    assert budget is not None
    source = budget.get_source_by_code("DIRSA")
    assert source is not None
    budget.create_entry(
        EntryInput(
            fiscal_year=app_context.as_of.year,
            source_id=source.id,
            allocated_minor=1000,
            currency="BRL",
        )
    )
    app_context.set_as_of(app_context.as_of)  # the signal of a new date is enough
    app_context.notify_data_changed()

    assert section.model.index(0, 6).data() == "In use"


@pytest.mark.parametrize(
    ("lang", "warning", "critical", "cells"),
    [
        ("en_US", "90", "60.5", ("90.0%", "60.5%")),
        ("pt_BR", "90", "60,5", ("90,0%", "60,5%")),
        ("es_ES", "90", "60,5", ("90,0\xa0%", "60,5\xa0%")),
    ],
)
def test_a_ratio_target_is_typed_and_listed_as_percent(
    app_context: AppContext,
    qtbot: QtBot,
    lang: str,
    warning: str,
    critical: str,
    cells: tuple[str, str],
) -> None:
    """P6-02: 90 means 90 % and is stored as 0.9; the dialog shows it as typed again."""
    app_context.translator_manager.set_language(lang)
    dialog = TargetDialog(app_context)
    qtbot.addWidget(dialog)
    _fill(dialog, "BUD_EXEC_RATE", "currency=BRL;source=DIRSA", warning, critical)

    dialog.accept()

    stored = _indicators(app_context).get_target("BUD_EXEC_RATE", "currency=BRL;source=DIRSA")
    assert (stored.warning_value, stored.critical_value) == (0.9, 0.605)
    section = TargetsSection(app_context)
    qtbot.addWidget(section)
    assert (section.model.index(0, 3).data(), section.model.index(0, 4).data()) == cells
    section.view.selectRow(0)
    section.edit_target()
    edit = _open_dialog(section)
    assert (edit.warning_edit.text(), edit.critical_edit.text()) == (warning, critical)


@pytest.mark.parametrize("typed", ["9000", "-5", "1000,5"])
def test_a_percentage_out_of_range_is_refused_and_nothing_is_written(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot, typed: str
) -> None:
    app_context.translator_manager.set_language("pt_BR")
    dialog = TargetDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    _fill(dialog, "BUD_EXEC_RATE", "currency=BRL;source=DIRSA", typed, "0")
    rows = _log_rows(app_context)

    dialog.accept()

    assert _warnings(fake_prompts) == ["A porcentagem deve estar entre 0% e 1000%."]
    assert error_label("TARGET_OUT_OF_RANGE") == "A porcentagem deve estar entre 0% e 1000%."
    assert _indicators(app_context).list_targets() == []
    assert _log_rows(app_context) == rows
    assert dialog.isVisible()


def test_the_unit_of_a_ratio_indicator_is_percent(app_context: AppContext, qtbot: QtBot) -> None:
    dialog = TargetDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.indicator_combo.setCurrentIndex(dialog.indicator_combo.findData("BUD_EXEC_RATE"))
    assert dialog.unit_value.text() == "Percent"
    assert unit_label("RATIO") == "Percent"


@pytest.mark.parametrize("lang", LANGUAGES)
def test_the_new_texts_are_translated_in_the_pseudo_locale(
    pseudo_context: AppContext, qtbot: QtBot, lang: str
) -> None:
    """The "Not in use" mark, the percent unit and the unreadable-setting message."""
    pseudo_context.translator_manager.set_language(lang)
    _put_target(pseudo_context, "PERS_CERT_VALID", "level=a", 10, 5)
    _put_target(pseudo_context, "BUD_EXEC_RATE", "currency=BRL;source=DIRSA", 0.9, 0.7)
    page = SettingsPage(pseudo_context)
    qtbot.addWidget(page)
    targets = page.section_widget("settings.targets")
    assert isinstance(targets, TargetsSection)
    assert targets.model.rowCount() == 2  # not vacuous: the "Use" column has two kinds of cell
    assert_fully_translated(page, lang)

    _corrupt_setting(pseudo_context)
    pseudo_context.notify_data_changed()
    assert not targets.problem.label.isHidden()
    assert_fully_translated(page, lang)


def test_joined_texts_are_filled_in_one_pass(app_context: AppContext) -> None:
    """P6-11: a value that looks like a placeholder is never replaced again."""
    assert dimension_text("level=%2;status=%1") == "Level: %2; Status: %1"
    assert dashboard_labels.join_texts(["%2", "%1", "c"]) == "%2, %1, c"
    assert dashboard_labels.join_texts([]) == ""
    app_context.translator_manager.set_language("pt_BR")
    assert dimension_text("level=%2;status=%1") == "N\u00edvel: %2; Situa\u00e7\u00e3o: %1"


def test_settings_and_dashboard_name_every_indicator_alike(app_context: AppContext) -> None:
    """P6-07: two catalogues, one wording (PLAN.md 5.4)."""
    assert set(dashboard_labels.INDICATOR_CODES) == set(INDICATOR_CODES)
    app_context.translator_manager.set_language("en_US")
    for code in INDICATOR_CODES:
        assert indicator_label(code) == dashboard_labels.indicator_name(code), code
    assert indicator_label("PERS_TRAINING_12M") == "Training records in the last 12 months"
    assert indicator_label("PERS_CERT_VALID") == "Staff with a valid PPE qualification"
    assert indicator_label("INFRA_AVAILABLE") == "Available units"
