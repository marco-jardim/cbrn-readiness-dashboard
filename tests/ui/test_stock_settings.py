# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings -> Infrastructure -> stock item types and the minimum stock P12 (PLAN.md T11.13).

User-defined types can be added, renamed, deactivated and deleted (only without lots); a built-in
type allows only its minimum and its active flag. The badge of P12 shows until it is confirmed or
a minimum is set; a minimum that changes confirms P12 in the same transaction; read-only mode
disables every edit; the pseudo-locale walk passes. All values are fictitious.
"""

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QDialog, QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard.domain.config import ConfigError
from cbrn_dashboard.domain.stock import StockCategory
from cbrn_dashboard.services.config import ConfigService
from cbrn_dashboard.services.stock import (
    DUPLICATE_CODE,
    InitialReceipt,
    LotInput,
    StockService,
    StockTypeInput,
    StockTypeView,
)
from cbrn_dashboard.storage import settings_repo
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.context import AppContext, Services
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from cbrn_dashboard.ui.stock.labels import BUILT_IN_TYPE_CODES, error_label
from cbrn_dashboard.ui.stock.settings import (
    PLACEHOLDER_MINIMUM,
    StockTypeSettingsDialog,
    StockTypesSection,
    create_settings_section,
    settings_section_title,
)
from tests.ui._fakes import FakePrompts
from tests.ui._walk import assert_fully_translated

pytestmark = pytest.mark.ui

LANGUAGES = ("pt_BR", "en_US", "es_ES")


# --------------------------------------------------------------------------- helpers


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


def _service(context: AppContext) -> StockService:
    service = context.services.stock
    assert service is not None
    return service


def _config(context: AppContext) -> ConfigService:
    service = context.services.config
    assert service is not None
    return service


def _section(context: AppContext, qtbot: QtBot) -> StockTypesSection:
    section = StockTypesSection(context)
    qtbot.addWidget(section)
    return section


def _view(context: AppContext, code: str) -> StockTypeView:
    view = _service(context).get_type_by_code(code)
    assert view is not None
    return view


def _minimum(context: AppContext, code: str) -> int | None:
    return _view(context, code).minimum_quantity


def _select(section: StockTypesSection, code: str) -> None:
    for index, row in enumerate(section.model.rows()):
        if row.code == code:
            section.view.selectRow(index)
            return
    raise AssertionError(code)


def _cell(section: StockTypesSection, code: str, key: str) -> str:
    column = [item.key for item in section.model.COLUMNS].index(key)
    for index, row in enumerate(section.model.rows()):
        if row.code == code:
            return str(section.model.index(index, column).data())
    raise AssertionError(code)


def _open_dialog(section: QWidget) -> StockTypeSettingsDialog:
    shown = [d for d in section.findChildren(StockTypeSettingsDialog) if d.isVisible()]
    assert len(shown) == 1
    return shown[0]


def _warnings(prompts: FakePrompts) -> list[str]:
    return [call.text for call in prompts.calls_of("warning")]


def _create(context: AppContext, code: str = "DEMO-X", minimum: int | None = None) -> int:
    return _service(context).create_type(
        StockTypeInput(
            code=code,
            category=StockCategory.ANTIDOTE,
            label_pt_br="Tipo de demonstracao",
            minimum_quantity=minimum,
        )
    )


def _fill_new(dialog: StockTypeSettingsDialog, code: str, minimum: int | None) -> None:
    dialog.code_edit.setText(code)
    dialog.category_combo.setCurrentIndex(
        dialog.category_combo.findData(StockCategory.ANTIDOTE.value)
    )
    dialog.label_pt_edit.setText("Tipo de demonstracao")
    dialog.label_en_edit.setText("Demo type")
    if minimum is None:
        dialog.minimum_spin.setValue(dialog.minimum_spin.minimum())
    else:
        dialog.minimum_spin.setValue(minimum)


def _badge_shown(section: StockTypesSection) -> bool:
    return not section.badge_label.isHidden() and not section.confirm_button.isHidden()


# --------------------------------------------------------------------------- the list


def test_the_section_lists_every_type_with_the_badge_of_p12(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = _section(app_context, qtbot)

    assert section.model.rowCount() == len(BUILT_IN_TYPE_CODES) == 17
    assert {row.code for row in section.model.rows()} == set(BUILT_IN_TYPE_CODES)
    assert _cell(section, "GLOVE", "minimum") == QCoreApplication.translate("Stock", "Not set")
    assert _cell(section, "GLOVE", "origin") == QCoreApplication.translate("Stock", "Built-in")
    assert _badge_shown(section)
    assert section.badge_label.text() == "Placeholder - to be confirmed"
    assert _config(app_context).needs_badge(PLACEHOLDER_MINIMUM) is True
    assert section.add_action.isEnabled()
    assert section.confirm_action.isEnabled()
    for action in (
        section.edit_action,
        section.deactivate_action,
        section.activate_action,
        section.delete_action,
    ):
        assert not action.isEnabled()


def test_the_confirm_button_confirms_p12_without_changing_a_minimum(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = _section(app_context, qtbot)

    section.confirm_action.trigger()

    assert not _badge_shown(section)
    assert not section.confirm_action.isEnabled()
    assert _config(app_context).needs_badge(PLACEHOLDER_MINIMUM) is False
    assert all(row.minimum_quantity is None for row in section.model.rows())


def test_the_section_is_registered_in_the_infrastructure_group() -> None:
    (spec,) = [item for item in registry.settings_sections() if item.key == "stock.types"]
    assert spec.group == "infrastructure"
    assert spec.title is settings_section_title
    assert spec.factory is create_settings_section
    assert settings_section_title() == "Stock item types"


# --------------------------------------------------------------------------- user-defined types


def test_a_user_type_is_added_with_a_minimum_and_p12_is_confirmed(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    section = _section(app_context, qtbot)
    section.add_action.trigger()
    dialog = _open_dialog(section)
    _fill_new(dialog, "DEMO-X", 25)

    dialog.accept()

    view = _view(app_context, "DEMO-X")
    assert not view.built_in
    assert view.category is StockCategory.ANTIDOTE
    assert view.minimum_quantity == 25
    assert view.active
    assert _cell(section, "DEMO-X", "minimum") == "25"
    assert _cell(section, "DEMO-X", "origin") == QCoreApplication.translate("Stock", "User-defined")
    selected = section.selected_type()
    assert selected is not None
    assert selected.id == dialog.saved_type_id == view.id
    assert not _badge_shown(section)
    assert _config(app_context).needs_badge(PLACEHOLDER_MINIMUM) is False
    assert _warnings(fake_prompts) == []


def test_a_user_type_without_a_minimum_keeps_the_badge(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = _section(app_context, qtbot)
    section.add_action.trigger()
    dialog = _open_dialog(section)
    _fill_new(dialog, "DEMO-X", None)

    dialog.accept()

    assert _minimum(app_context, "DEMO-X") is None
    assert _badge_shown(section)
    assert _config(app_context).needs_badge(PLACEHOLDER_MINIMUM) is True


def test_a_refused_new_type_writes_nothing_and_keeps_the_badge(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    section = _section(app_context, qtbot)
    section.add_action.trigger()
    dialog = _open_dialog(section)
    _fill_new(dialog, "GLOVE", 5)  # the code of a built-in type

    dialog.accept()

    assert dialog.isVisible()
    assert _warnings(fake_prompts) == [error_label(DUPLICATE_CODE)]
    assert _minimum(app_context, "GLOVE") is None
    assert section.model.rowCount() == 17
    assert _badge_shown(section)
    assert _config(app_context).needs_badge(PLACEHOLDER_MINIMUM) is True


def test_a_failing_confirmation_creates_no_type_and_a_retry_creates_it_once(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section = _section(app_context, qtbot)
    section.add_action.trigger()
    dialog = _open_dialog(section)
    _fill_new(dialog, "DEMO-X", 25)

    def failing(*_args: object) -> None:
        raise ConfigError("UNKNOWN_PLACEHOLDER", "placeholder_id")

    with monkeypatch.context() as patch:
        patch.setattr(settings_repo, "confirm_placeholder", failing)
        dialog.accept()

    assert dialog.isVisible()
    assert _warnings(fake_prompts) == [error_label("UNKNOWN_PLACEHOLDER")]
    assert _service(app_context).get_type_by_code("DEMO-X") is None  # one transaction: no half
    assert dialog.saved_type_id is None
    assert _config(app_context).needs_badge(PLACEHOLDER_MINIMUM) is True

    dialog.accept()  # the same dialog, now without the failure: creates the type once

    assert _minimum(app_context, "DEMO-X") == 25
    assert _config(app_context).needs_badge(PLACEHOLDER_MINIMUM) is False
    assert [row.code for row in section.model.rows()].count("DEMO-X") == 1


def test_a_user_type_is_renamed_without_confirming_p12(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _create(app_context, minimum=None)
    section = _section(app_context, qtbot)
    _select(section, "DEMO-X")
    section.edit_action.trigger()
    dialog = _open_dialog(section)
    assert dialog.code_edit.isEnabled()
    dialog.label_pt_edit.setText("Novo nome")
    dialog.label_en_edit.setText("New name")

    dialog.accept()

    view = _view(app_context, "DEMO-X")
    assert (view.label_pt_br, view.label_en_us) == ("Novo nome", "New name")
    assert _cell(section, "DEMO-X", "name") == "New name"
    assert view.minimum_quantity is None
    assert _badge_shown(section)  # the minimum did not change: nothing is confirmed
    assert _config(app_context).needs_badge(PLACEHOLDER_MINIMUM) is True


def test_a_user_type_is_deactivated_and_activated(app_context: AppContext, qtbot: QtBot) -> None:
    _create(app_context)
    section = _section(app_context, qtbot)
    _select(section, "DEMO-X")
    assert section.deactivate_action.isEnabled()
    assert not section.activate_action.isEnabled()

    section.deactivate_action.trigger()

    assert not _view(app_context, "DEMO-X").active
    assert _cell(section, "DEMO-X", "status") == QCoreApplication.translate("Stock", "Inactive")
    assert not section.deactivate_action.isEnabled()
    assert section.activate_action.isEnabled()
    assert _badge_shown(section)  # (de)activating a type is not setting a minimum

    section.activate_action.trigger()

    assert _view(app_context, "DEMO-X").active
    assert _cell(section, "DEMO-X", "status") == QCoreApplication.translate("Stock", "Active")
    assert section.deactivate_action.isEnabled()


def test_a_user_type_without_lots_is_deleted_after_the_confirmation(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _create(app_context)
    section = _section(app_context, qtbot)
    _select(section, "DEMO-X")
    assert section.delete_action.isEnabled()

    section.delete_action.trigger()  # the prompt is answered "no"

    (call,) = fake_prompts.calls_of("confirm")
    assert "DEMO-X" in call.text
    assert _service(app_context).get_type_by_code("DEMO-X") is not None

    fake_prompts.script("confirm", True)
    section.delete_action.trigger()

    assert _service(app_context).get_type_by_code("DEMO-X") is None
    assert section.model.rowCount() == 17
    assert not section.delete_action.isEnabled()
    assert _warnings(fake_prompts) == []


def test_a_user_type_with_lots_cannot_be_deleted(app_context: AppContext, qtbot: QtBot) -> None:
    type_id = _create(app_context)
    _service(app_context).create_lot(
        LotInput(type_id=type_id, lot_code="L-1", expires_on=date(2030, 1, 31)),
        InitialReceipt(moved_on=date(2026, 3, 1), quantity=5),
    )
    section = _section(app_context, qtbot)
    _select(section, "DEMO-X")

    assert section.edit_action.isEnabled()
    assert section.deactivate_action.isEnabled()
    assert not section.delete_action.isEnabled()


# --------------------------------------------------------------------------- built-in types


def test_a_built_in_type_allows_only_the_minimum_and_the_active_flag(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = _section(app_context, qtbot)
    _select(section, "GLOVE")
    assert not section.delete_action.isEnabled()  # a built-in type is never deleted
    section.edit_action.trigger()
    dialog = _open_dialog(section)

    for fixed in (
        dialog.code_edit,
        dialog.category_combo,
        dialog.label_pt_edit,
        dialog.label_en_edit,
        dialog.label_es_edit,
    ):
        assert not fixed.isEnabled()
    assert dialog.minimum_spin.isEnabled()
    assert dialog.active_check.isEnabled()


def test_a_minimum_is_set_changed_and_cleared_and_p12_is_confirmed_by_the_first(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = _section(app_context, qtbot)
    assert _badge_shown(section)

    _select(section, "GLOVE")
    section.edit_action.trigger()
    dialog = _open_dialog(section)
    dialog.minimum_spin.setValue(40)
    dialog.accept()

    assert _minimum(app_context, "GLOVE") == 40
    assert _cell(section, "GLOVE", "minimum") == "40"
    assert not _badge_shown(section)  # the change confirmed P12 in the same call
    assert _config(app_context).needs_badge(PLACEHOLDER_MINIMUM) is False

    section.edit_action.trigger()
    dialog = _open_dialog(section)
    assert dialog.minimum() == 40
    dialog.minimum_spin.setValue(0)  # 0 is a minimum that is never below, not "not set"
    dialog.accept()

    assert _minimum(app_context, "GLOVE") == 0
    assert _cell(section, "GLOVE", "minimum") == "0"

    section.edit_action.trigger()
    dialog = _open_dialog(section)
    dialog.minimum_spin.setValue(dialog.minimum_spin.minimum())
    dialog.accept()

    assert _minimum(app_context, "GLOVE") is None
    assert _cell(section, "GLOVE", "minimum") == QCoreApplication.translate("Stock", "Not set")
    assert not _badge_shown(section)  # a confirmed placeholder does not come back


def test_clearing_a_minimum_that_was_never_set_confirms_nothing(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = _section(app_context, qtbot)
    _select(section, "GLOVE")
    section.edit_action.trigger()
    dialog = _open_dialog(section)

    dialog.accept()  # the form as loaded: nothing changed

    assert _minimum(app_context, "GLOVE") is None
    assert _badge_shown(section)
    assert _config(app_context).needs_badge(PLACEHOLDER_MINIMUM) is True


def test_a_built_in_type_is_deactivated_and_activated(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = _section(app_context, qtbot)
    _select(section, "APRON")

    section.deactivate_action.trigger()
    assert not _view(app_context, "APRON").active
    assert _cell(section, "APRON", "status") == QCoreApplication.translate("Stock", "Inactive")

    section.activate_action.trigger()
    assert _view(app_context, "APRON").active


# --------------------------------------------------------------------------- read-only, no service


def test_read_only_mode_disables_every_edit(app_context: AppContext, qtbot: QtBot) -> None:
    _create(app_context)
    app_context.read_only = True
    section = _section(app_context, qtbot)
    _select(section, "DEMO-X")
    registered = app_context.edit_targets()

    assert len(section._actions) == 6
    assert _badge_shown(section)
    for action in section._actions:
        assert action in registered
        assert not action.isEnabled()


def test_the_section_builds_without_services(app_context: AppContext, qtbot: QtBot) -> None:
    app_context.services = Services()
    section = _section(app_context, qtbot)

    assert section.model.rowCount() == 0
    assert not _badge_shown(section)
    for action in section._actions:
        assert not action.isEnabled()
    section.add_type()  # nothing to write to: the dialog opens and a save does nothing
    dialog = _open_dialog(section)
    dialog.code_edit.setText("DEMO-X")
    dialog.accept()
    assert dialog.isVisible()


def test_without_a_stock_service_the_confirm_button_still_follows_the_configuration(
    app_context: AppContext, qtbot: QtBot
) -> None:
    app_context.services.stock = None
    section = _section(app_context, qtbot)

    assert section.model.rowCount() == 0
    assert not section.add_action.isEnabled()
    assert _badge_shown(section)
    assert section.confirm_action.isEnabled()


# --------------------------------------------------------------------------- pseudo-locale walk


def test_everything_is_translated_in_the_pseudo_locale(
    pseudo_context: AppContext, qtbot: QtBot
) -> None:
    section = create_settings_section(pseudo_context)
    qtbot.addWidget(section)
    assert_fully_translated(section)


@pytest.mark.parametrize("lang", LANGUAGES)
def test_the_walk_carries_the_marker_of_each_language(
    pseudo_context: AppContext, qtbot: QtBot, lang: str
) -> None:
    pseudo_context.translator_manager.set_language(lang)
    section = create_settings_section(pseudo_context)
    qtbot.addWidget(section)
    assert_fully_translated(section, lang)


def test_the_walk_with_a_selection_a_confirmed_badge_and_the_dialogs(
    pseudo_context: AppContext, qtbot: QtBot
) -> None:
    _create(pseudo_context, minimum=3)
    _config(pseudo_context).confirm(PLACEHOLDER_MINIMUM)
    section = _section(pseudo_context, qtbot)
    _select(section, "DEMO-X")
    assert not _badge_shown(section)
    assert_fully_translated(section)
    selected = section.selected_type()
    assert selected is not None
    dialogs: list[QDialog] = [
        StockTypeSettingsDialog(pseudo_context),
        StockTypeSettingsDialog(pseudo_context, None, selected),
        StockTypeSettingsDialog(pseudo_context, None, _view(pseudo_context, "GLOVE")),
    ]
    for dialog in dialogs:
        qtbot.addWidget(dialog)
        assert_fully_translated(dialog)


def test_the_titles_are_translated(pseudo_context: AppContext) -> None:
    assert settings_section_title() == "\u27e6Stock item types\u27e7"
