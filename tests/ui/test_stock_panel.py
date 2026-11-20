# SPDX-License-Identifier: GPL-3.0-or-later
"""The shared stock panel: summary, lots, movements, filter, read-only mode (PLAN.md T11.10).

The tests run in en-US and compare with the label functions where a catalogue could change the
wording, so they stay valid once the pt-BR and es-ES catalogues are filled in.
"""

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QDate
from PySide6.QtWidgets import QDialog, QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard.domain.stock import (
    ANTIDOTE_PAGE_CATEGORIES,
    LotStatus,
    MovementKind,
    StockCategory,
)
from cbrn_dashboard.services.stock import (
    BALANCE_NEGATIVE,
    ONLY_MOVEMENT,
    InitialReceipt,
    LotInput,
    MovementInput,
    StockService,
)
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from cbrn_dashboard.ui.shell.widgets import ModuleTableModel
from cbrn_dashboard.ui.stock.dialogs import LotDialog, MovementDialog
from cbrn_dashboard.ui.stock.labels import error_label, kind_label, lot_status_label
from cbrn_dashboard.ui.stock.panel import StockPanel
from tests.ui._fakes import FakePrompts
from tests.ui._walk import assert_fully_translated

pytestmark = pytest.mark.ui

AS_OF = date(2026, 3, 5)


# --------------------------------------------------------------------------- helpers


def _service(context: AppContext) -> StockService:
    service = context.services.stock
    assert service is not None
    return service


def _type_id(context: AppContext, code: str) -> int:
    view = _service(context).get_type_by_code(code)
    assert view is not None
    return view.id


def _add_lot(
    context: AppContext,
    *,
    code: str = "ANTIDOTE_CHEMICAL",
    lot_code: str = "L1",
    expires: date | None = date(2026, 6, 1),
    received: date = date(2026, 2, 1),
    quantity: int = 50,
) -> int:
    return _service(context).create_lot(
        LotInput(type_id=_type_id(context, code), lot_code=lot_code, expires_on=expires),
        InitialReceipt(moved_on=received, quantity=quantity),
    )


def _movement(
    context: AppContext, lot_id: int, day: date, kind: MovementKind, quantity: int
) -> int:
    return _service(context).record_movement(
        lot_id, MovementInput(moved_on=day, kind=kind, quantity=quantity)
    )


def _cell(model: ModuleTableModel, row: int, key: str) -> str:
    column = [item.key for item in model.COLUMNS].index(key)
    return str(model.index(row, column).data())


def _lot_codes(panel: StockPanel) -> list[str]:
    return [row.row.lot_code for row in panel.lots_model.rows()]


def _select_lot(panel: StockPanel, lot_code: str) -> None:
    for index, row in enumerate(panel.lots_model.rows()):
        if row.row.lot_code == lot_code:
            panel.lots_view.selectRow(index)
            return
    raise AssertionError(lot_code)


def _open_dialog[D: QDialog](panel: QWidget, kind: type[D]) -> D:
    shown = [dialog for dialog in panel.findChildren(kind) if dialog.isVisible()]
    assert len(shown) == 1
    return shown[0]


def _warnings(prompts: FakePrompts) -> list[str]:
    return [call.text for call in prompts.calls_of("warning")]


def _panel(
    context: AppContext, qtbot: QtBot, categories: frozenset[StockCategory] | None = None
) -> StockPanel:
    panel = StockPanel(context, categories)
    qtbot.addWidget(panel)
    return panel


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


# --------------------------------------------------------------------------- the empty panel


def test_an_empty_database_shows_empty_tables(app_context: AppContext, qtbot: QtBot) -> None:
    panel = _panel(app_context, qtbot)
    assert panel.summary_model.rowCount() == 0
    assert panel.lots_model.rowCount() == 0
    assert panel.movements_model.rowCount() == 0
    assert not panel.show_empty_check.isChecked()
    assert panel.count_label.text() == QCoreApplication.translate(
        "Stock", "%n lot(s) shown", None, 0
    )
    assert panel.empty_label.isHidden()
    assert panel.add_lot_action.isEnabled()
    for action in (
        panel.edit_lot_action,
        panel.delete_lot_action,
        panel.record_action,
        panel.edit_movement_action,
        panel.delete_movement_action,
    ):
        assert not action.isEnabled()


def test_the_panel_builds_without_a_stock_service(app_context: AppContext, qtbot: QtBot) -> None:
    app_context.services.stock = None
    panel = _panel(app_context, qtbot)
    assert panel.lots_model.rowCount() == 0
    assert not panel.add_lot_action.isEnabled()
    panel.refresh()
    assert panel.summary_model.rowCount() == 0


# --------------------------------------------------------------------------- add through dialogs


def test_adding_a_lot_updates_lots_summary_and_movements(
    app_context: AppContext, qtbot: QtBot
) -> None:
    panel = _panel(app_context, qtbot)
    panel.add_lot_action.trigger()
    dialog = _open_dialog(panel, LotDialog)
    dialog.type_combo.setCurrentIndex(
        dialog.type_combo.findData(_type_id(app_context, "ANTIDOTE_CHEMICAL"))
    )
    dialog.lot_code_edit.setText("L-100")
    dialog.expires_edit.setDate(QDate(2027, 1, 31))
    dialog.received_edit.setDate(QDate(2026, 3, 1))
    dialog.quantity_spin.setValue(20)
    dialog.reference_edit.setText("REC-1")
    dialog.accept()

    (stored,) = _service(app_context).list_lots()
    assert stored.lot_code == "L-100"
    assert _lot_codes(panel) == ["L-100"]
    assert _cell(panel.lots_model, 0, "on_hand") == "20"
    assert _cell(panel.lots_model, 0, "status") == lot_status_label(LotStatus.VALID.value)
    (summary,) = [row.summary for row in panel.summary_model.rows()]
    assert (summary.type_code, summary.valid, summary.on_hand) == ("ANTIDOTE_CHEMICAL", 20, 20)
    selected = panel.selected_lot()
    assert selected is not None
    assert selected.lot_id == dialog.saved_lot_id == stored.id
    movements = panel.movements_model.rows()
    assert [(m.kind, m.signed_quantity, m.balance_after, m.reference) for m in movements] == [
        (MovementKind.RECEIPT, 20, 20, "REC-1")
    ]
    assert panel.count_label.text() == QCoreApplication.translate(
        "Stock", "%n lot(s) shown", None, 1
    )


def test_recording_a_movement_updates_the_three_tables(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _add_lot(app_context)
    panel = _panel(app_context, qtbot)
    _select_lot(panel, "L1")
    assert panel.record_action.isEnabled()
    panel.record_action.trigger()
    dialog = _open_dialog(panel, MovementDialog)
    dialog.date_edit.setDate(QDate(2026, 2, 20))
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData(MovementKind.ISSUE.value))
    dialog.quantity_spin.setValue(5)
    dialog.reference_edit.setText("OUT-1")
    dialog.accept()

    assert _cell(panel.lots_model, 0, "on_hand") == "45"
    assert panel.summary_model.rows()[0].summary.valid == 45
    model = panel.movements_model
    keys = ("kind", "quantity", "balance_after")
    assert [tuple(_cell(model, row, key) for key in keys) for row in range(model.rowCount())] == [
        (kind_label("receipt"), "+50", "50"),
        (kind_label("issue"), "-5", "45"),
    ]
    movement = panel.selected_movement()
    assert movement is not None
    assert movement.id == dialog.saved_movement_id
    assert panel.edit_movement_action.isEnabled()
    assert panel.delete_movement_action.isEnabled()


def test_the_dialog_for_a_new_lot_offers_the_filtered_type(
    app_context: AppContext, qtbot: QtBot
) -> None:
    panel = _panel(app_context, qtbot)
    panel.set_type_filter("GLOVE")
    panel.add_lot()
    dialog = _open_dialog(panel, LotDialog)
    selected = dialog.selected_type()
    assert selected is not None
    assert selected.code == "GLOVE"


# --------------------------------------------------------------------------- the service refuses


def test_a_negative_balance_is_shown_as_text_and_changes_nothing(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    lot_id = _add_lot(app_context)
    panel = _panel(app_context, qtbot)
    _select_lot(panel, "L1")
    panel.record_action.trigger()
    dialog = _open_dialog(panel, MovementDialog)
    dialog.date_edit.setDate(QDate(2026, 2, 20))
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData(MovementKind.ISSUE.value))
    dialog.quantity_spin.setValue(51)
    dialog.accept()
    assert _warnings(fake_prompts) == [error_label(BALANCE_NEGATIVE)]
    assert dialog.saved_movement_id is None
    assert len(_service(app_context).movements(lot_id)) == 1
    assert panel.movements_model.rowCount() == 1
    assert _cell(panel.lots_model, 0, "on_hand") == "50"


def test_deleting_the_only_movement_or_a_needed_one_is_refused(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    lot_id = _add_lot(app_context)
    panel = _panel(app_context, qtbot)
    _select_lot(panel, "L1")
    fake_prompts.script("confirm", True, True)
    panel.movements_view.selectRow(0)
    panel.delete_movement_action.trigger()
    assert _warnings(fake_prompts) == [error_label(ONLY_MOVEMENT)]
    assert len(_service(app_context).movements(lot_id)) == 1

    _movement(app_context, lot_id, date(2026, 2, 20), MovementKind.ISSUE, 5)
    app_context.notify_data_changed()
    assert panel.movements_model.rowCount() == 2
    panel.movements_view.selectRow(0)  # the receipt the issue depends on
    panel.delete_movement_action.trigger()
    assert _warnings(fake_prompts)[-1] == error_label(BALANCE_NEGATIVE)
    assert len(_service(app_context).movements(lot_id)) == 2


# --------------------------------------------------------------------------- edit and delete


def test_a_lot_and_a_movement_are_edited_through_their_dialogs(
    app_context: AppContext, qtbot: QtBot
) -> None:
    lot_id = _add_lot(app_context)
    panel = _panel(app_context, qtbot)
    _select_lot(panel, "L1")
    panel.edit_lot_action.trigger()
    lot_dialog = _open_dialog(panel, LotDialog)
    assert lot_dialog.lot_code_edit.text() == "L1"
    lot_dialog.lot_code_edit.setText("L1-B")
    lot_dialog.accept()
    assert _lot_codes(panel) == ["L1-B"]
    selected = panel.selected_lot()
    assert selected is not None
    assert selected.lot_id == lot_id

    panel.movements_view.selectRow(0)
    panel.edit_movement_action.trigger()
    movement_dialog = _open_dialog(panel, MovementDialog)
    movement_dialog.quantity_spin.setValue(60)
    movement_dialog.accept()
    assert _cell(panel.movements_model, 0, "balance_after") == "60"
    assert _cell(panel.lots_model, 0, "on_hand") == "60"
    assert panel.selected_movement() is not None


def test_deleting_a_lot_and_a_movement_asks_first(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    lot_id = _add_lot(app_context)
    _add_lot(app_context, lot_code="L2")
    _movement(app_context, lot_id, date(2026, 2, 20), MovementKind.ISSUE, 5)
    panel = _panel(app_context, qtbot)
    _select_lot(panel, "L1")
    panel.movements_view.selectRow(1)

    panel.delete_movement_action.trigger()  # refused by the user: confirm answers False
    assert len(fake_prompts.calls_of("confirm")) == 1
    assert len(_service(app_context).movements(lot_id)) == 2
    fake_prompts.script("confirm", True)
    panel.delete_movement_action.trigger()
    assert [m.signed_quantity for m in _service(app_context).movements(lot_id)] == [50]
    assert panel.movements_model.rowCount() == 1

    panel.delete_lot_action.trigger()  # confirm answers False again
    assert sorted(_lot_codes(panel)) == ["L1", "L2"]
    fake_prompts.script("confirm", True)
    panel.delete_lot_action.trigger()
    assert [lot.lot_code for lot in _service(app_context).list_lots()] == ["L2"]
    assert _lot_codes(panel) == ["L2"]
    assert panel.movements_model.rowCount() == 0
    assert "L1" in fake_prompts.calls_of("confirm")[-1].text


# --------------------------------------------------------------------------- empty lots


def test_empty_lots_are_hidden_until_the_box_is_checked(
    app_context: AppContext, qtbot: QtBot
) -> None:
    emptied = _add_lot(app_context, lot_code="L-EMPTY", quantity=5)
    _movement(app_context, emptied, date(2026, 2, 20), MovementKind.DISPOSAL, 5)
    _add_lot(app_context, lot_code="L-FULL")
    panel = _panel(app_context, qtbot)
    assert _lot_codes(panel) == ["L-FULL"]
    assert panel.count_label.text() == QCoreApplication.translate(
        "Stock", "%n lot(s) shown", None, 1
    )
    panel.show_empty_check.setChecked(True)
    assert sorted(_lot_codes(panel)) == ["L-EMPTY", "L-FULL"]
    statuses = {row.row.lot_code: row.row.status for row in panel.lots_model.rows()}
    assert statuses["L-EMPTY"] is LotStatus.EMPTY
    assert panel.count_label.text() == QCoreApplication.translate(
        "Stock", "%n lot(s) shown", None, 2
    )
    panel.show_empty_check.setChecked(False)
    assert _lot_codes(panel) == ["L-FULL"]


# --------------------------------------------------------------------------- the as-of date


def test_the_as_of_date_changes_quantities_and_statuses(
    app_context: AppContext, qtbot: QtBot
) -> None:
    lot_id = _add_lot(app_context, expires=date(2026, 4, 1))
    _movement(app_context, lot_id, date(2026, 2, 20), MovementKind.ISSUE, 10)
    panel = _panel(app_context, qtbot)

    def state() -> tuple[str, str, int, int]:
        summary = panel.summary_model.rows()[0].summary
        return (
            _cell(panel.lots_model, 0, "on_hand"),
            _cell(panel.lots_model, 0, "status"),
            summary.valid,
            summary.expired_qty,
        )

    expiring = lot_status_label(LotStatus.EXPIRING.value)
    assert state() == ("40", expiring, 40, 0)
    app_context.set_as_of(date(2026, 2, 10))
    assert state() == ("50", expiring, 50, 0)
    app_context.set_as_of(date(2026, 4, 2))
    assert state() == ("40", lot_status_label(LotStatus.EXPIRED.value), 0, 40)
    app_context.set_as_of(date(2026, 1, 15))
    assert _cell(panel.lots_model, 0, "status") == lot_status_label(LotStatus.NOT_RECEIVED.value)
    assert _cell(panel.lots_model, 0, "on_hand") == "0"
    app_context.set_as_of(AS_OF)
    assert state() == ("40", expiring, 40, 0)


# --------------------------------------------------------------------------- the filter


def test_the_type_filter_and_the_empty_state(app_context: AppContext, qtbot: QtBot) -> None:
    _add_lot(app_context, code="ANTIDOTE_CHEMICAL", lot_code="L1")
    _add_lot(app_context, code="GLOVE", lot_code="G1", expires=None)
    panel = _panel(app_context, qtbot)
    assert sorted(_lot_codes(panel)) == ["G1", "L1"]
    assert {row.summary.type_code for row in panel.summary_model.rows()} == {
        "ANTIDOTE_CHEMICAL",
        "GLOVE",
    }

    panel.set_type_filter("GLOVE")
    assert panel.type_filter == "GLOVE"
    assert _lot_codes(panel) == ["G1"]
    assert [row.summary.type_code for row in panel.summary_model.rows()] == ["GLOVE"]

    panel.set_no_match()
    assert panel.no_match
    assert panel.lots_model.rowCount() == 0
    assert panel.summary_model.rowCount() == 0
    assert panel.movements_model.rowCount() == 0
    assert not panel.empty_label.isHidden()
    assert not panel.add_lot_action.isEnabled()
    assert panel.count_label.text() == QCoreApplication.translate(
        "Stock", "%n lot(s) shown", None, 0
    )

    panel.set_type_filter("GLOVE")
    assert not panel.no_match
    assert panel.empty_label.isHidden()
    assert _lot_codes(panel) == ["G1"]
    assert panel.add_lot_action.isEnabled()

    panel.set_type_filter(None)
    assert sorted(_lot_codes(panel)) == ["G1", "L1"]


def test_a_panel_limited_to_categories_shows_only_those_lots(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _add_lot(app_context, code="ANTIDOTE_CHEMICAL", lot_code="L1")
    _add_lot(app_context, code="GLOVE", lot_code="G1", expires=None)
    panel = _panel(app_context, qtbot, ANTIDOTE_PAGE_CATEGORIES)
    assert _lot_codes(panel) == ["L1"]
    assert {row.summary.type_code for row in panel.summary_model.rows()} == {"ANTIDOTE_CHEMICAL"}


# --------------------------------------------------------------------------- language, read-only


def test_the_panel_follows_the_language(app_context: AppContext, qtbot: QtBot) -> None:
    _add_lot(app_context)
    panel = _panel(app_context, qtbot)
    app_context.translator_manager.set_language("pt_BR")
    assert panel.show_empty_check.text() == QCoreApplication.translate("Stock", "Show empty lots")
    assert panel.count_label.text() == QCoreApplication.translate(
        "Stock", "%n lot(s) shown", None, 1
    )
    assert _cell(panel.lots_model, 0, "status") == lot_status_label(LotStatus.EXPIRING.value)
    assert _cell(panel.lots_model, 0, "expiry") == "01/06/2026"
    app_context.translator_manager.set_language("en_US")
    assert _cell(panel.lots_model, 0, "expiry") == "06/01/2026"


def test_read_only_mode_disables_every_edit_action(app_context: AppContext, qtbot: QtBot) -> None:
    lot_id = _add_lot(app_context)
    _movement(app_context, lot_id, date(2026, 2, 20), MovementKind.ISSUE, 5)
    app_context.read_only = True
    panel = _panel(app_context, qtbot)
    _select_lot(panel, "L1")
    panel.movements_view.selectRow(0)
    targets = app_context.edit_targets()
    assert len(panel._actions) == 6
    for action in panel._actions:
        assert action in targets
        assert not action.isEnabled()


# --------------------------------------------------------------------------- pseudo-locale walk


def test_everything_is_translated_in_the_pseudo_locale(
    pseudo_context: AppContext, qtbot: QtBot
) -> None:
    panel = StockPanel(pseudo_context, None)
    qtbot.addWidget(panel)
    assert_fully_translated(panel)


def test_the_pseudo_locale_walk_with_data_and_the_empty_state(
    pseudo_context: AppContext, qtbot: QtBot
) -> None:
    lot_id = _add_lot(pseudo_context)
    _movement(pseudo_context, lot_id, date(2026, 2, 20), MovementKind.ISSUE, 5)
    panel = StockPanel(pseudo_context, None)
    qtbot.addWidget(panel)
    _select_lot(panel, "L1")
    panel.movements_view.selectRow(1)
    assert_fully_translated(panel)
    panel.set_no_match()
    assert_fully_translated(panel)
