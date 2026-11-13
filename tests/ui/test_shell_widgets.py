# SPDX-License-Identifier: GPL-3.0-or-later
"""The shared building blocks of the module pages (ui/shell/widgets.py, PLAN.md T4.5)."""

from datetime import date
from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QAbstractItemView, QLineEdit, QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard.services.errors import REQUIRED, ServiceError
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import format_date
from cbrn_dashboard.ui.shell.widgets import (
    Column,
    FormDialog,
    ModuleTableModel,
    apply_change,
    current_language,
    guarded,
    label_for,
    make_edit_action,
    make_table_view,
    mark_data,
)
from tests.ui._fakes import FakePrompts

pytestmark = pytest.mark.ui

DAY = date(2026, 3, 5)


def _navigation() -> str:
    return QCoreApplication.translate("Shell", "Navigation")


def _label(code: str) -> str:
    return f"label {code}"


class _Model(ModuleTableModel):
    COLUMNS = (
        Column[Any]("name", _navigation, lambda row, lang: lang),
        Column[Any](
            "date", _navigation, lambda row, lang: format_date(row, lang), align_right=True
        ),
    )


class _Dialog(FormDialog):
    def __init__(self, context: AppContext) -> None:
        super().__init__(context)
        self.accepting = False
        self.submissions = 0
        self.edit = QLineEdit(self)
        self.label = self.add_field(_navigation, self.edit)

    def submit(self) -> bool:
        self.submissions += 1
        return self.accepting


# --------------------------------------------------------------------------- language helpers


def test_current_language_follows_the_manager(app_context: AppContext) -> None:
    for lang in ("pt_BR", "es_ES", "en_US"):
        app_context.translator_manager.set_language(lang)
        assert current_language(app_context) == lang
    app_context.translator_manager.clear()
    assert current_language(app_context) == "pt_BR"


def test_label_for_returns_the_label_or_the_code() -> None:
    mapping = {"A": lambda: "Label A"}
    assert label_for(mapping, "A") == "Label A"
    assert label_for(mapping, "UNKNOWN") == "UNKNOWN"
    assert label_for(mapping, "") == ""


# --------------------------------------------------------------------------- table model


def test_headers_follow_a_language_switch(app_context: AppContext) -> None:
    model = _Model()
    horizontal = Qt.Orientation.Horizontal
    assert model.columnCount() == 2
    assert model.headerData(0, horizontal) == "Navigation"
    app_context.translator_manager.set_language("pt_BR")
    assert model.headerData(0, horizontal) == _navigation()
    assert model.headerData(0, horizontal) != "Navigation"
    app_context.translator_manager.set_language("en_US")
    assert model.headerData(1, horizontal) == "Navigation"


def test_cells_are_reformatted_after_a_language_switch(app_context: AppContext) -> None:
    model = _Model()
    model.set_rows([DAY])
    changed: list[object] = []
    model.dataChanged.connect(lambda *args: changed.append(args))
    headers: list[object] = []
    model.headerDataChanged.connect(lambda *args: headers.append(args))
    model.set_language("pt_BR")
    assert model.data(model.index(0, 1)) == "05/03/2026"
    assert model.data(model.index(0, 0)) == "pt_BR"
    assert changed
    assert headers
    model.set_language("en_US")
    assert model.data(model.index(0, 1)) == "03/05/2026"
    alignment = model.data(model.index(0, 1), Qt.ItemDataRole.TextAlignmentRole)
    assert alignment is not None
    assert model.data(model.index(0, 0), Qt.ItemDataRole.TextAlignmentRole) is None
    assert model.data(model.index(0, 0), Qt.ItemDataRole.EditRole) is None


def test_model_rows_and_selection(app_context: AppContext, qtbot: QtBot) -> None:
    model = _Model()
    model.set_rows([DAY, date(2026, 4, 1)])
    assert model.rowCount() == 2
    assert model.rows() == [DAY, date(2026, 4, 1)]
    assert model.row_at(model.index(1, 0)) == date(2026, 4, 1)
    assert model.row_at(model.index(5, 0)) is None
    holder = QWidget()
    qtbot.addWidget(holder)
    view = make_table_view(model, holder)
    assert view.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert not view.isSortingEnabled()
    assert model.selected_row(view) is None
    view.selectRow(1)
    assert model.selected_row(view) == date(2026, 4, 1)


# --------------------------------------------------------------------------- errors


def test_guarded_presents_a_service_error_and_returns_none(
    app_context: AppContext, fake_prompts: FakePrompts
) -> None:
    def refuse() -> int:
        raise ServiceError(REQUIRED, "code")

    assert guarded(app_context, None, _label, refuse) is None
    (call,) = fake_prompts.calls_of("warning")
    assert call.title == "Cannot save"
    assert call.text == "label REQUIRED"
    assert guarded(app_context, None, _label, lambda: 5) == 5
    assert len(fake_prompts.calls_of("warning")) == 1


def test_guarded_lets_other_exceptions_propagate(app_context: AppContext) -> None:
    def crash() -> int:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        guarded(app_context, None, _label, crash)


def test_apply_change_notifies_only_on_success(
    app_context: AppContext, fake_prompts: FakePrompts
) -> None:
    seen: list[int] = []
    app_context.data_changed.connect(lambda: seen.append(1))

    def refuse() -> None:
        raise ServiceError(REQUIRED)

    assert not apply_change(app_context, None, _label, refuse)
    assert seen == []
    assert apply_change(app_context, None, _label, lambda: None)
    assert seen == [1]
    assert len(fake_prompts.calls_of("warning")) == 1


# --------------------------------------------------------------------------- edit actions


def test_an_edit_action_is_enabled_unless_the_context_is_read_only(app_context: AppContext) -> None:
    action = make_edit_action(app_context, app_context, _navigation, lambda: None)
    assert action.isEnabled()
    assert action in app_context.edit_targets()
    app_context.read_only = True
    read_only_action = make_edit_action(app_context, app_context, _navigation, lambda: None)
    assert not read_only_action.isEnabled()
    app_context.set_edit_enabled(read_only_action, True)
    assert not read_only_action.isEnabled()


def test_an_edit_action_runs_its_slot_and_retranslates(app_context: AppContext) -> None:
    calls: list[int] = []
    action = make_edit_action(app_context, app_context, _navigation, lambda: calls.append(1))
    action.trigger()
    assert calls == [1]
    assert action.text() == "Navigation"
    app_context.translator_manager.set_language("es_ES")
    action.retranslate()
    assert action.text() == _navigation()
    assert action.text() != "Navigation"


def test_mark_data_sets_the_walker_property(app_context: AppContext) -> None:
    edit = QLineEdit()
    mark_data(edit)
    assert edit.property("i18nData") is True


# --------------------------------------------------------------------------- form dialog


def test_a_form_dialog_stays_open_while_submit_refuses(
    app_context: AppContext, qtbot: QtBot
) -> None:
    dialog = _Dialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.accept()
    assert dialog.submissions == 1
    assert dialog.isVisible()
    assert dialog.result() != dialog.DialogCode.Accepted
    dialog.accepting = True
    dialog.accept()
    assert dialog.submissions == 2
    assert not dialog.isVisible()
    assert dialog.result() == dialog.DialogCode.Accepted


def test_a_form_dialog_cancel_does_not_submit(app_context: AppContext, qtbot: QtBot) -> None:
    dialog = _Dialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.reject()
    assert dialog.submissions == 0
    assert not dialog.isVisible()


def test_a_form_dialog_field_labels_follow_the_language(
    app_context: AppContext, qtbot: QtBot
) -> None:
    dialog = _Dialog(app_context)
    qtbot.addWidget(dialog)
    assert dialog.label.text() == "Navigation"
    app_context.translator_manager.set_language("pt_BR")
    assert dialog.label.text() == _navigation()
    assert dialog.label.text() != "Navigation"
    assert dialog.language == "pt_BR"
