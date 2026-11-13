# SPDX-License-Identifier: GPL-3.0-or-later
"""The Settings page, its own sections, the target dialog and the labels (PLAN.md T6.1)."""

import ast
import inspect
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard.domain.config import ReadinessConfig
from cbrn_dashboard.domain.indicators import Direction, UnitKind
from cbrn_dashboard.domain.registry import build_registry
from cbrn_dashboard.services import config as config_module
from cbrn_dashboard.services import errors as errors_module
from cbrn_dashboard.services import indicators as indicators_module
from cbrn_dashboard.services.config import CONFIG_ERROR_CODES, ConfigService
from cbrn_dashboard.services.indicators import IndicatorService
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
    assert page.section_keys("infrastructure") == ("infrastructure.types",)
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
    assert not section.names_badge.badge.isHidden()
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
    # Changing the names confirms D18: the badge is gone and the database says so.
    assert section.names_badge.badge.isHidden()
    assert _config(app_context).needs_badge("D18") is False


def test_changing_only_the_operator_label_keeps_the_names_badge(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = GeneralSection(app_context)
    qtbot.addWidget(section)
    section.operator_edit.setText("Only me")
    section.save()
    assert _config(app_context).load().operator_label == "Only me"
    assert not section.names_badge.badge.isHidden()
    assert _config(app_context).needs_badge("D18") is True
    section.names_badge.confirm.click()
    assert section.names_badge.badge.isHidden()
    assert _config(app_context).needs_badge("D18") is False


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


def test_the_alert_windows_are_stored_and_the_badges_follow_the_change(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = AlertsSection(app_context)
    qtbot.addWidget(section)
    assert (section.cert_edit.text(), section.maintenance_edit.text()) == ("90", "30")
    assert not section.cert_badge.badge.isHidden()
    assert not section.maintenance_badge.badge.isHidden()
    section.cert_edit.setText("120")
    section.maintenance_edit.setText("45")
    section.save_button.click()
    stored = _config(app_context).load()
    assert (stored.cert_warning_days, stored.maintenance_warning_days) == (120, 45)
    assert section.cert_badge.badge.isHidden()
    assert section.maintenance_badge.badge.isHidden()
    assert _config(app_context).needs_badge("P01") is False
    assert _config(app_context).needs_badge("P02") is False


def test_confirming_one_window_hides_only_its_badge_and_keeps_the_value(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = AlertsSection(app_context)
    qtbot.addWidget(section)
    section.cert_badge.confirm.click()
    assert section.cert_badge.badge.isHidden()
    assert section.cert_badge.confirm.isHidden()
    assert not section.maintenance_badge.badge.isHidden()
    assert _config(app_context).needs_badge("P01") is False
    assert _config(app_context).needs_badge("P02") is True
    assert _config(app_context).load().cert_warning_days == 90


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


def test_the_dialog_stores_a_target_and_the_table_and_badge_follow(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = TargetsSection(app_context)
    qtbot.addWidget(section)
    assert section.model.rowCount() == 0
    assert not section.badge.badge.isHidden()
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
        "Valid certificates",
        "Level: A",
        "Count",
        "10",
        "5",
        "Enabled",
    ]
    assert section.badge.badge.isHidden()
    assert _config(app_context).needs_badge("P03") is False

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
    assert _config(app_context).needs_badge("P03") is True


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
    _fill(dialog, "BUD_EXEC_RATE", "currency=BRL;source=DIRSA", "0,9", "0,7")
    dialog.accept()
    stored = _indicators(app_context).get_target("BUD_EXEC_RATE", "currency=BRL;source=DIRSA")
    assert (stored.warning_value, stored.critical_value) == (0.9, 0.7)
    assert _cells(section, 0) == [
        "Taxa de execução orçamentária",
        "Moeda: BRL; Fonte: DIRSA",
        "Razão",
        "0,9",
        "0,7",
        "Ativado",
    ]
    app_context.translator_manager.set_language("en_US")
    qtbot.waitUntil(lambda: section.model.index(0, 3).data() == "0.9")
    assert _cells(section, 0)[0] == "Budget execution rate"


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
    assert "Valid certificates" in call.text
    assert len(_indicators(app_context).list_targets()) == 1
    fake_prompts.script("confirm", True)
    section.delete_action.trigger()
    assert _indicators(app_context).list_targets() == []
    assert section.model.rowCount() == 0
    assert not section.delete_action.isEnabled()


def test_the_targets_badge_is_confirmed_without_changing_a_target(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = TargetsSection(app_context)
    qtbot.addWidget(section)
    section.badge.confirm.click()
    assert section.badge.badge.isHidden()
    assert _config(app_context).needs_badge("P03") is False
    assert _indicators(app_context).list_targets() == []


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
        general.names_badge.confirm,
        alerts.cert_edit,
        alerts.maintenance_edit,
        alerts.save_button,
        alerts.cert_badge.confirm,
        alerts.maintenance_badge.confirm,
        targets.badge.confirm,
        *targets._actions,
    ]
    registered = app_context.edit_targets()
    assert len(controls) == 15
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
        alerts.save_button,
        targets.add_action,
    ):
        assert not widget.isEnabled()
    assert general.language_combo.isEnabled()
    assert general.names_badge.badge.isHidden()
    assert alerts.cert_badge.badge.isHidden()
    assert targets.badge.badge.isHidden()
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


def test_a_fake_configuration_service_drives_the_badges(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    class Fake:
        def __init__(self) -> None:
            self.config = ReadinessConfig()
            self.confirmed: list[str] = []

        def load(self) -> ReadinessConfig:
            return self.config

        def save(self, config: ReadinessConfig) -> tuple[str, ...]:
            self.config = config
            return ()

        def badge_for_field(self, field: str) -> str | None:
            return "P01" if field == "cert_warning_days" else None

        def needs_badge(self, placeholder_id: str) -> bool:
            return False

        def confirm(self, placeholder_id: str) -> None:
            self.confirmed.append(placeholder_id)

    fake = Fake()
    vars(app_context.services)["config"] = fake
    section = AlertsSection(app_context)
    qtbot.addWidget(section)
    assert not section.cert_badge.badge.isHidden()
    assert section.maintenance_badge.badge.isHidden()
    section.cert_badge.confirm.click()
    assert fake.confirmed == ["P01"]


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


def test_the_walk_with_data_and_hidden_badges(pseudo_context: AppContext, qtbot: QtBot) -> None:
    _put_target(pseudo_context, "PERS_CERT_VALID", "level=A", 10, 5)
    _put_target(pseudo_context, "BUD_EXEC_RATE", "currency=BRL;source=DIRSA", 0.9, 0.7)
    config = _config(pseudo_context)
    for placeholder in ("P01", "P02", "P03", "D18"):
        config.confirm(placeholder)
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
    assert targets.badge.badge.isHidden()
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
    assert stored <= mapped
    assert set(CONFIG_ERROR_CODES) <= mapped
    typed = _defined_constants(formatting_module)
    assert {"EMPTY", "INVALID_NUMBER", "AMBIGUOUS_NUMBER", "TOO_LARGE"} <= typed
    assert {"EMPTY", "INVALID_NUMBER", "AMBIGUOUS_NUMBER", "TOO_LARGE"} <= mapped
    assert len(mapped) == len(ALL_ERROR_CODES)
