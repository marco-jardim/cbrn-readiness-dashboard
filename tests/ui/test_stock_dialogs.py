# SPDX-License-Identifier: GPL-3.0-or-later
"""Labels, table models and dialogs of the shared stock UI (PLAN.md Phase 11, T11.9).

The tests run in en-US and compare with the label functions where a catalogue could change the
wording, so they stay valid once the pt-BR and es-ES catalogues are filled in.
"""

from collections.abc import Callable
from datetime import date
from itertools import combinations
from pathlib import Path

import pytest
from PySide6.QtCore import QAbstractItemModel, QCoreApplication, QDate, Qt
from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import QDialog
from pytestqt.qtbot import QtBot

from cbrn_dashboard.domain.indicators import IndicatorStatus
from cbrn_dashboard.domain.stock import (
    ANTIDOTE_PAGE_CATEGORIES,
    LotRow,
    LotStatus,
    MovementKind,
    StockCategory,
)
from cbrn_dashboard.services import stock as stock_module
from cbrn_dashboard.services.config import CONFIG_ERROR_CODES
from cbrn_dashboard.services.errors import (
    CODE_IMMUTABLE,
    INVALID_CODE,
    INVALID_DATE,
    LABEL_PT_BR_REQUIRED,
    NOT_FOUND,
    READ_ONLY,
    REQUIRED,
    ServiceError,
)
from cbrn_dashboard.services.stock import (
    BALANCE_NEGATIVE,
    DUPLICATE_CODE,
    DUPLICATE_LOT,
    DUPLICATE_MOVEMENT,
    NOTE_REQUIRED,
    InitialReceipt,
    LotInput,
    LotView,
    MovementInput,
    MovementView,
    StockService,
    StockTypeView,
)
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import (
    format_amount,
    format_month,
    parse_amount,
    to_qdate,
)
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from cbrn_dashboard.ui.stock.dialogs import (
    LotDialog,
    MovementDialog,
    StockTypeDialog,
    demo_lot_dialog,
    demo_movement_dialog,
    demo_type_dialog,
)
from cbrn_dashboard.ui.stock.labels import (
    ALL_ERROR_CODES,
    BUILT_IN_TYPE_CODES,
    category_label,
    code_label,
    error_label,
    fill_placeholders,
    kind_label,
    lot_status_label,
    stock_type_display,
)
from cbrn_dashboard.ui.stock.models import (
    LOT_STATUS_LOOK,
    LotsModel,
    MovementsModel,
    ScheduleModel,
    StockTypesModel,
    SummaryModel,
    below_minimum_look,
    signed_text,
)
from tests.ui._fakes import FakePrompts
from tests.ui._walk import assert_fully_translated

pytestmark = pytest.mark.ui

AS_OF = date(2026, 3, 5)

#: The English names of the 17 built-in types (the Python source strings), by code.
BUILT_IN_NAMES_EN = {
    "ANTIDOTE_CHEMICAL": "Chemical antidote",
    "ANTIDOTE_RAD_NUCLEAR": "Radiological and nuclear antidote",
    "ANTIDOTE_BIOLOGICAL": "Biological antidote",
    "DECONTAMINANT": "Decontaminant",
    "DETECTOR_CHEMICAL": "Chemical detector",
    "DETECTOR_RAD_NUCLEAR": "Radiological and nuclear detector",
    "DETECTOR_BIOLOGICAL": "Biological detector",
    "MASK_FULL_FACE": "Full-face mask",
    "FILTER_CBRN": "CBRN filter",
    "PPE_LEVEL_A": "Level A PPE",
    "PPE_LEVEL_B": "Level B PPE",
    "PPE_LEVEL_C": "Level C PPE",
    "GLOVE": "Glove",
    "BOOT": "Boot",
    "APRON": "Apron",
    "OXYGEN_CYLINDER": "Oxygen cylinder (O2)",
    "ISOLATION_STRETCHER": "Bubble stretcher (isolation transport capsule)",
}


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
    expires: date | None = date(2026, 4, 1),
    received: date = date(2026, 2, 1),
    quantity: int = 50,
    price: int | None = None,
    reference: str = "",
) -> int:
    return _service(context).create_lot(
        LotInput(
            type_id=_type_id(context, code),
            lot_code=lot_code,
            expires_on=expires,
            unit_price_minor=price,
            currency=None if price is None else "BRL",
        ),
        InitialReceipt(moved_on=received, quantity=quantity, reference=reference),
    )


def _movement(
    context: AppContext,
    lot_id: int,
    day: date,
    kind: MovementKind,
    quantity: int,
    note: str | None = None,
) -> int:
    return _service(context).record_movement(
        lot_id, MovementInput(moved_on=day, kind=kind, quantity=quantity, note=note)
    )


def _cell(model: QAbstractItemModel, row: int, column: int) -> object:
    return model.index(row, column).data()


def _cells(model: QAbstractItemModel, row: int, columns: int) -> list[object]:
    return [_cell(model, row, column) for column in range(columns)]


def _icon(model: QAbstractItemModel, row: int, column: int) -> QIcon:
    icon = model.index(row, column).data(Qt.ItemDataRole.DecorationRole)
    assert isinstance(icon, QIcon)
    assert not icon.isNull()
    return icon


def _image(model: QAbstractItemModel, row: int, column: int) -> QImage:
    return _icon(model, row, column).pixmap(16, 16).toImage()


def _lot_view(context: AppContext, lot_id: int) -> LotView:
    return _service(context).get_lot(lot_id)


def _warnings(prompts: FakePrompts) -> list[str]:
    return [call.text for call in prompts.calls_of("warning")]


def _pick_type(dialog: LotDialog, context: AppContext, code: str) -> None:
    index = dialog.type_combo.findData(_type_id(context, code))
    assert index >= 0
    dialog.type_combo.setCurrentIndex(index)


def _pick_kind(dialog: MovementDialog, kind: MovementKind) -> None:
    index = dialog.kind_combo.findData(kind.value)
    assert index >= 0
    dialog.kind_combo.setCurrentIndex(index)


def _lot_row(status: LotStatus, code: str = "GLOVE") -> LotRow:
    return LotRow(
        lot_id=1,
        type_code=code,
        category=StockCategory.PPE,
        lot_code="X1",
        received_on=None,
        expires_on=None,
        on_hand=0,
        valid_quantity=0,
        status=status,
        days_to_expiry=None,
        unit_price_minor=None,
        currency=None,
        value_minor=None,
    )


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


# --------------------------------------------------------------------------- labels


def test_the_17_built_in_names_are_the_design_names_in_english(app_context: AppContext) -> None:
    service = _service(app_context)
    stored = [item for item in service.list_types(include_inactive=True) if item.built_in]
    assert {item.code for item in stored} == set(BUILT_IN_TYPE_CODES)
    assert len(BUILT_IN_TYPE_CODES) == 17
    for item in stored:
        assert stock_type_display(item, "en_US") == BUILT_IN_NAMES_EN[item.code]
        assert code_label(item.code) == BUILT_IN_NAMES_EN[item.code]


def test_every_category_kind_and_status_has_a_label(app_context: AppContext) -> None:
    for category in StockCategory:
        text = category_label(category.value)
        assert text.strip()
        assert text != category.value
    for kind in MovementKind:
        text = kind_label(kind.value)
        assert text.strip()
        assert text != kind.value
    for status in LotStatus:
        text = lot_status_label(status.value)
        assert text.strip()
        assert text != status.value
    assert kind_label("receipt") == "Receipt"
    assert lot_status_label("NOT_RECEIVED") == "Not yet received"
    assert category_label("ppe") == "PPE"
    assert len({kind_label(kind.value) for kind in MovementKind}) == len(MovementKind)
    assert len({lot_status_label(status.value) for status in LotStatus}) == len(LotStatus)


def test_every_error_code_of_the_stock_service_has_a_label(app_context: AppContext) -> None:
    service_codes = {
        getattr(stock_module, name)
        for name in stock_module.__all__
        if name.isupper() and isinstance(getattr(stock_module, name), str)
    }
    assert {
        "BALANCE_NEGATIVE",
        "NOTE_REQUIRED",
        "DUPLICATE_MOVEMENT",
        "ONLY_MOVEMENT",
        "INVALID_KIND",
        "INVALID_MONTHS",
        "INVALID_QUANTITY",
        "INITIAL_RECEIPT_REQUIRED",
        "EXPIRY_REQUIRED",
        "CATEGORY_IMMUTABLE",
        "DATE_IN_FUTURE",
        "DUPLICATE_LOT",
        "INVALID_CATEGORY",
    } <= service_codes
    shared = {READ_ONLY, NOT_FOUND, REQUIRED, INVALID_DATE, INVALID_CODE, LABEL_PT_BR_REQUIRED}
    expected = service_codes | shared | set(CONFIG_ERROR_CODES) | {CODE_IMMUTABLE}
    expected |= {"CORRUPT_SETTING", "UNKNOWN_PLACEHOLDER"}
    expected |= {"INVALID_NUMBER", "AMBIGUOUS_NUMBER", "NEGATIVE_AMOUNT", "TOO_MANY_DECIMALS"}
    assert expected <= set(ALL_ERROR_CODES)
    for code in ALL_ERROR_CODES:
        text = error_label(code)
        assert text.strip(), code
        assert text != code, code
    assert error_label("NO_SUCH_CODE") == "NO_SUCH_CODE"  # never an exception


def test_the_labels_of_the_balance_and_note_errors_say_what_is_wrong(
    app_context: AppContext,
) -> None:
    assert "below zero" in error_label(BALANCE_NEGATIVE)
    assert "note" in error_label(NOTE_REQUIRED)
    assert error_label(DUPLICATE_MOVEMENT) != error_label(DUPLICATE_LOT)


def test_a_user_type_shows_its_own_labels_with_the_fallback_order(
    app_context: AppContext,
) -> None:
    def view(pt: str | None, en: str | None, es: str | None) -> StockTypeView:
        return StockTypeView(
            id=0,
            code="USER-1",
            built_in=False,
            category=StockCategory.OTHER,
            label_pt_br=pt,
            label_en_us=en,
            label_es_es=es,
            minimum_quantity=None,
            active=True,
        )

    both = view("Rotulo pt", "English label", "Etiqueta es")
    assert stock_type_display(both, "pt_BR") == "Rotulo pt"
    assert stock_type_display(both, "en_US") == "English label"
    assert stock_type_display(both, "es_ES") == "Etiqueta es"
    only_pt = view("Rotulo pt", None, None)
    assert stock_type_display(only_pt, "es_ES") == "Rotulo pt"
    assert stock_type_display(view(None, None, None), "en_US") == "USER-1"
    # the name of a built-in type is the translated one, not a stored label
    built_in = StockTypeView(
        0, "GLOVE", True, StockCategory.PPE, "Luva armazenada", None, None, None, True
    )
    assert stock_type_display(built_in, "pt_BR") == code_label("GLOVE")


def test_fill_placeholders_is_one_pass() -> None:
    assert fill_placeholders("%2 of %1", "a", "%1") == "%1 of a"


# --------------------------------------------------------------------------- models


def test_lot_status_looks_cover_every_status_with_distinct_icons(
    app_context: AppContext, qtbot: QtBot
) -> None:
    assert LOT_STATUS_LOOK == {
        LotStatus.VALID: IndicatorStatus.OK,
        LotStatus.EXPIRING: IndicatorStatus.WARNING,
        LotStatus.EXPIRED: IndicatorStatus.CRITICAL,
        LotStatus.EMPTY: IndicatorStatus.NO_TARGET,
        LotStatus.NOT_RECEIVED: IndicatorStatus.NO_DATA,
    }
    model = LotsModel()
    model.set_language("en_US")
    model.set_lots([_lot_row(status) for status in LotStatus], {})
    status_column = 5
    images = []
    for row, status in enumerate(LotStatus):
        assert _cell(model, row, status_column) == lot_status_label(status.value)
        images.append(_image(model, row, status_column))
    for first, second in combinations(images, 2):
        assert first != second  # colour is never the only cue (D23): every shape differs


def test_the_lots_model_shows_a_lot_with_several_movements(app_context: AppContext) -> None:
    lot_id = _add_lot(app_context, price=1250, reference="REC-1")
    _movement(app_context, lot_id, date(2026, 2, 10), MovementKind.ISSUE, 5)
    _movement(app_context, lot_id, date(2026, 2, 20), MovementKind.ADJUSTMENT_OUT, 2, "Count")
    service = _service(app_context)
    types = {item.code: item for item in service.list_types(include_inactive=True)}
    model = LotsModel()
    model.set_language("en_US")
    model.set_lots(service.lot_rows(AS_OF), types)
    assert model.rowCount() == 1
    assert _cells(model, 0, 9) == [
        "Chemical antidote",
        "L1",
        "02/01/2026",
        "04/01/2026",
        "43",
        lot_status_label("EXPIRING"),
        "27",
        "R$12.50",
        "R$537.50",
    ]
    assert not _icon(model, 0, 5).isNull()
    headers = [model.headerData(c, Qt.Orientation.Horizontal) for c in range(9)]
    assert headers[0] == QCoreApplication.translate("Stock", "Type")
    assert headers[8] == QCoreApplication.translate("Stock", "Value")
    model.set_language("pt_BR")
    assert _cell(model, 0, 2) == "01/02/2026"
    assert _cell(model, 0, 7) == "R$\u00a012,50"


def test_a_lot_without_expiry_or_price_shows_text_not_blanks(app_context: AppContext) -> None:
    _add_lot(app_context, code="DETECTOR_CHEMICAL", lot_code="D1", expires=None)
    service = _service(app_context)
    types = {item.code: item for item in service.list_types(include_inactive=True)}
    model = LotsModel()
    model.set_language("en_US")
    model.set_lots(service.lot_rows(AS_OF), types)
    cells = _cells(model, 0, 9)
    assert cells[3] == QCoreApplication.translate("Stock", "No expiry date")
    assert cells[5] == lot_status_label("VALID")
    assert cells[6] == "-"
    assert cells[7] == "-"
    assert cells[8] == "-"


def test_the_movements_model_shows_signed_quantities_and_the_balance(
    app_context: AppContext,
) -> None:
    lot_id = _add_lot(app_context, reference="REC-1")
    _movement(app_context, lot_id, date(2026, 2, 10), MovementKind.ISSUE, 5)
    _movement(app_context, lot_id, date(2026, 2, 20), MovementKind.ADJUSTMENT_OUT, 2, "Count")
    _movement(app_context, lot_id, date(2026, 2, 25), MovementKind.RECEIPT, 1200)
    model = MovementsModel()
    model.set_language("en_US")
    model.set_movements(_service(app_context).movements(lot_id))
    assert [_cell(model, row, 2) for row in range(4)] == ["+50", "-5", "-2", "+1,200"]
    assert [_cell(model, row, 3) for row in range(4)] == ["50", "45", "43", "1,243"]
    assert [_cell(model, row, 1) for row in range(4)] == [
        kind_label("receipt"),
        kind_label("issue"),
        kind_label("adjustment_out"),
        kind_label("receipt"),
    ]
    assert _cell(model, 0, 0) == "02/01/2026"
    assert _cell(model, 0, 4) == "REC-1"
    assert _cell(model, 2, 5) == "Count"
    assert _cell(model, 1, 5) == ""
    model.set_language("pt_BR")
    assert _cell(model, 3, 2) == "+1.200"
    assert signed_text(0, "en_US") == "0"


def test_the_summary_model_shows_minimum_status_text_and_icon(app_context: AppContext) -> None:
    service = _service(app_context)
    lot_id = _add_lot(app_context, price=1250)
    _movement(app_context, lot_id, date(2026, 2, 10), MovementKind.ISSUE, 7)
    service.set_minimum(_type_id(app_context, "ANTIDOTE_CHEMICAL"), 50)
    service.set_minimum(_type_id(app_context, "ANTIDOTE_BIOLOGICAL"), 0)
    types = {item.code: item for item in service.list_types(include_inactive=True)}
    model = SummaryModel()
    model.set_language("en_US")
    model.set_summaries(service.type_summaries(AS_OF), service.lot_rows(AS_OF), types)
    by_code = {row.summary.type_code: index for index, row in enumerate(model.rows())}
    assert model.rowCount() == 17

    below = by_code["ANTIDOTE_CHEMICAL"]
    assert _cells(model, below, 8) == [
        "Chemical antidote",
        category_label("antidote"),
        "43",
        "0",
        "43",
        "50",
        QCoreApplication.translate("Stock", "Below the minimum"),
        "R$537.50",
    ]

    at_zero = by_code["ANTIDOTE_BIOLOGICAL"]
    assert _cell(model, at_zero, 5) == "0"  # a minimum of 0 is a minimum, never below
    assert _cell(model, at_zero, 6) == QCoreApplication.translate(
        "Stock", "At or above the minimum"
    )
    assert _cell(model, at_zero, 7) == "-"

    not_set = by_code["GLOVE"]
    assert _cell(model, not_set, 5) == QCoreApplication.translate("Stock", "Not set")
    assert _cell(model, not_set, 6) == QCoreApplication.translate("Stock", "Not set")
    images = [_image(model, below, 6), _image(model, at_zero, 6), _image(model, not_set, 6)]
    for first, second in combinations(images, 2):
        assert first != second  # critical, OK and "no target" look different
    assert below_minimum_look(True) is IndicatorStatus.CRITICAL
    assert below_minimum_look(False) is IndicatorStatus.OK
    assert below_minimum_look(None) is IndicatorStatus.NO_TARGET


def test_the_summary_value_keeps_currencies_apart(app_context: AppContext) -> None:
    service = _service(app_context)
    _add_lot(app_context, lot_code="L1", price=1000)
    usd = service.create_lot(
        LotInput(
            type_id=_type_id(app_context, "ANTIDOTE_CHEMICAL"),
            lot_code="L2",
            expires_on=date(2027, 1, 1),
            unit_price_minor=200,
            currency="USD",
        ),
        InitialReceipt(moved_on=date(2026, 2, 1), quantity=10),
    )
    assert usd > 0
    types = {item.code: item for item in service.list_types(include_inactive=True)}
    model = SummaryModel()
    model.set_language("en_US")
    model.set_summaries(service.type_summaries(AS_OF), service.lot_rows(AS_OF), types)
    row = next(i for i, r in enumerate(model.rows()) if r.summary.type_code == "ANTIDOTE_CHEMICAL")
    assert _cell(model, row, 7) == "R$500.00, US$20.00"


def test_the_schedule_model_lists_the_lots_by_period(app_context: AppContext) -> None:
    _add_lot(app_context, lot_code="SOON", expires=date(2026, 4, 1))
    _add_lot(app_context, lot_code="GONE", expires=date(2026, 2, 1), received=date(2026, 1, 1))
    _add_lot(app_context, code="DETECTOR_CHEMICAL", lot_code="NOEXP", expires=None)
    _add_lot(app_context, lot_code="LATE", expires=date(2030, 1, 1))
    service = _service(app_context)
    types = {item.code: item for item in service.list_types(include_inactive=True)}
    model = ScheduleModel()
    model.set_language("en_US")
    model.set_buckets(service.expiry_schedule(AS_OF, 12), types)
    periods = {_cell(model, row, 2): _cell(model, row, 0) for row in range(model.rowCount())}
    assert periods == {
        "GONE": QCoreApplication.translate("Stock", "Expired (still in stock)"),
        "SOON": "April 2026",
        "LATE": QCoreApplication.translate("Stock", "Later"),
        "NOEXP": QCoreApplication.translate("Stock", "No expiry date"),
    }
    gone = next(r for r in range(model.rowCount()) if _cell(model, r, 2) == "GONE")
    assert _cell(model, gone, 5) == lot_status_label("EXPIRED")
    assert not _icon(model, gone, 5).isNull()
    assert model.headerData(0, Qt.Orientation.Horizontal) == QCoreApplication.translate(
        "Stock", "Period"
    )


def test_month_names_follow_the_language() -> None:
    month = date(2026, 4, 1)
    assert format_month(month, "en_US") == "April 2026"
    assert format_month(month, "pt_BR") == "Abril 2026"
    assert format_month(month, "es_ES") == "Abril 2026"


def test_the_types_model_lists_built_in_and_user_types(app_context: AppContext) -> None:
    service = _service(app_context)
    service.create_type(
        stock_module.StockTypeInput(
            code="USER-1", category="other", label_pt_br="Meu tipo", minimum_quantity=3
        )
    )
    model = StockTypesModel()
    model.set_language("en_US")
    model.set_rows(service.list_types(include_inactive=True))
    rows = {row.code: index for index, row in enumerate(model.rows())}
    built_in = rows["ANTIDOTE_CHEMICAL"]
    assert _cell(model, built_in, 1) == "Chemical antidote"
    assert _cell(model, built_in, 2) == category_label("antidote")
    assert _cell(model, built_in, 3) == QCoreApplication.translate("Stock", "Not set")
    assert _cell(model, built_in, 4) == QCoreApplication.translate("Stock", "Built-in")
    assert _cell(model, built_in, 5) == QCoreApplication.translate("Stock", "Active")
    user = rows["USER-1"]
    assert _cells(model, user, 6)[1:4] == ["Meu tipo", category_label("other"), "3"]
    assert _cell(model, user, 4) == QCoreApplication.translate("Stock", "User-defined")


# --------------------------------------------------------------------------- lot dialog


@pytest.mark.parametrize(
    ("lang", "typed"),
    [("pt_BR", "1.234,56"), ("es_ES", "1.234,56"), ("en_US", "1,234.56")],
)
def test_a_typed_price_is_stored_in_minor_units_and_shown_back(
    app_context: AppContext, qtbot: QtBot, lang: str, typed: str
) -> None:
    app_context.translator_manager.set_language(lang)
    dialog = LotDialog(app_context)
    qtbot.addWidget(dialog)
    _pick_type(dialog, app_context, "ANTIDOTE_CHEMICAL")
    dialog.lot_code_edit.setText("L-100")
    dialog.expires_edit.setDate(QDate(2027, 1, 31))
    dialog.price_edit.setText(typed)
    dialog.received_edit.setDate(QDate(2026, 3, 1))
    dialog.quantity_spin.setValue(20)
    dialog.reference_edit.setText("REC-1")
    dialog.accept()

    (lot,) = _service(app_context).list_lots()
    assert dialog.saved_lot_id == lot.id
    assert lot.unit_price_minor == 123456
    assert lot.currency == "BRL"
    assert lot.expires_on == date(2027, 1, 31)
    (receipt,) = _service(app_context).movements(lot.id)
    assert receipt.kind is MovementKind.RECEIPT
    assert (receipt.moved_on, receipt.quantity, receipt.reference) == (
        date(2026, 3, 1),
        20,
        "REC-1",
    )

    reopened = LotDialog(app_context, None, lot)
    qtbot.addWidget(reopened)
    assert reopened.price_edit.text() == format_amount(123456, "BRL", lang)
    assert parse_amount(reopened.price_edit.text(), "BRL", lang) == 123456


def test_a_typed_price_is_shown_again_when_the_language_changes(
    app_context: AppContext, qtbot: QtBot
) -> None:
    dialog = LotDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.price_edit.setText("1,234.56")
    app_context.translator_manager.set_language("pt_BR")
    assert dialog.price_edit.text() == "1.234,56"
    app_context.translator_manager.set_language("es_ES")
    assert dialog.price_edit.text() == format_amount(123456, "BRL", "es_ES")
    dialog.price_edit.setText("not a number")
    app_context.translator_manager.set_language("en_US")
    # text that did not parse is not carried over: it would be read again in the new language
    assert dialog.price_edit.text() == ""


def test_the_no_expiry_box_is_disabled_for_antidotes_and_decontaminants(
    app_context: AppContext, qtbot: QtBot
) -> None:
    required = ("ANTIDOTE_CHEMICAL", "ANTIDOTE_RAD_NUCLEAR", "ANTIDOTE_BIOLOGICAL", "DECONTAMINANT")
    for code in required:
        dialog = LotDialog(app_context, type_code=code)
        qtbot.addWidget(dialog)
        assert not dialog.no_expiry_check.isEnabled(), code
        assert not dialog.no_expiry_check.isChecked(), code
        assert dialog.expires_edit.isEnabled(), code
        assert dialog.no_expiry_check.toolTip() == error_label("EXPIRY_REQUIRED")
    for code in ("DETECTOR_CHEMICAL", "GLOVE", "OXYGEN_CYLINDER"):
        dialog = LotDialog(app_context, type_code=code)
        qtbot.addWidget(dialog)
        assert dialog.no_expiry_check.isEnabled(), code
        assert dialog.no_expiry_check.isChecked(), code
        assert not dialog.expires_edit.isEnabled(), code

    dialog = LotDialog(app_context, type_code="GLOVE")
    qtbot.addWidget(dialog)
    _pick_type(dialog, app_context, "DECONTAMINANT")
    assert not dialog.no_expiry_check.isEnabled()
    assert dialog.expires_edit.isEnabled()
    _pick_type(dialog, app_context, "BOOT")
    assert dialog.no_expiry_check.isEnabled()


def test_a_lot_of_a_type_without_expiry_can_be_saved_without_one(
    app_context: AppContext, qtbot: QtBot
) -> None:
    dialog = LotDialog(app_context, type_code="DETECTOR_CHEMICAL")
    qtbot.addWidget(dialog)
    dialog.lot_code_edit.setText("D-1")
    dialog.received_edit.setDate(QDate(2026, 3, 1))
    dialog.accept()
    (lot,) = _service(app_context).list_lots()
    assert lot.expires_on is None
    assert lot.unit_price_minor is None
    assert lot.currency is None


def test_the_lot_dialog_offers_only_the_active_types_of_the_allowed_categories(
    app_context: AppContext, qtbot: QtBot
) -> None:
    service = _service(app_context)
    service.deactivate_type(_type_id(app_context, "ANTIDOTE_BIOLOGICAL"))
    dialog = LotDialog(app_context, categories=ANTIDOTE_PAGE_CATEGORIES)
    qtbot.addWidget(dialog)
    offered = {dialog.type_combo.itemData(i) for i in range(dialog.type_combo.count())}
    assert offered == {
        _type_id(app_context, "ANTIDOTE_CHEMICAL"),
        _type_id(app_context, "ANTIDOTE_RAD_NUCLEAR"),
        _type_id(app_context, "DECONTAMINANT"),
    }
    everything = LotDialog(app_context)
    qtbot.addWidget(everything)
    assert everything.type_combo.count() == 16
    assert everything.type_combo.itemText(0) == "Chemical antidote"


def test_the_lot_dialog_shows_service_errors_through_the_prompts(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _add_lot(app_context, lot_code="L1")
    dialog = LotDialog(app_context, type_code="ANTIDOTE_CHEMICAL")
    qtbot.addWidget(dialog)
    dialog.lot_code_edit.setText("L1")
    dialog.expires_edit.setDate(QDate(2027, 1, 31))
    dialog.received_edit.setDate(QDate(2026, 3, 1))
    dialog.accept()
    assert _warnings(fake_prompts) == [error_label(DUPLICATE_LOT)]
    assert fake_prompts.calls_of("warning")[0].parent is dialog
    assert dialog.saved_lot_id is None
    assert len(_service(app_context).list_lots()) == 1

    dialog.lot_code_edit.setText("")
    dialog.accept()
    assert _warnings(fake_prompts)[-1] == error_label(REQUIRED)
    assert len(_service(app_context).list_lots()) == 1


def test_a_price_that_does_not_parse_is_refused_before_the_service(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    dialog = LotDialog(app_context, type_code="DETECTOR_CHEMICAL")
    qtbot.addWidget(dialog)
    dialog.lot_code_edit.setText("D-1")
    dialog.price_edit.setText("abc")
    dialog.accept()
    assert _warnings(fake_prompts) == [error_label("INVALID_NUMBER")]
    assert _service(app_context).list_lots() == []
    dialog.price_edit.setText("-5.00")
    dialog.accept()
    assert _warnings(fake_prompts)[-1] == error_label("NEGATIVE_AMOUNT")
    assert _service(app_context).list_lots() == []


def test_a_lot_is_edited_through_the_service_without_a_second_receipt(
    app_context: AppContext, qtbot: QtBot
) -> None:
    lot_id = _add_lot(app_context, price=1250, reference="REC-1")
    dialog = LotDialog(app_context, None, _lot_view(app_context, lot_id))
    qtbot.addWidget(dialog)
    assert dialog.quantity_spin.isHidden()
    assert dialog.received_edit.isHidden()
    assert dialog.reference_edit.isHidden()
    assert dialog.lot_code_edit.text() == "L1"
    assert dialog.price_edit.text() == format_amount(1250, "BRL", "en_US")
    dialog.lot_code_edit.setText("L1-B")
    dialog.price_edit.setText("")
    dialog.notes_edit.setPlainText("Management note")
    dialog.accept()
    lot = _lot_view(app_context, lot_id)
    assert (lot.lot_code, lot.unit_price_minor, lot.currency) == ("L1-B", None, None)
    assert lot.notes == "Management note"
    assert len(_service(app_context).movements(lot_id)) == 1


def test_the_expiry_field_starts_blank_and_an_antidote_lot_without_a_date_is_refused(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    dialog = LotDialog(app_context, type_code="ANTIDOTE_CHEMICAL")
    qtbot.addWidget(dialog)
    assert dialog.expires_edit.date() == dialog.expires_edit.minimumDate()
    assert dialog.expires_edit.text().strip() == ""
    dialog.lot_code_edit.setText("A-1")
    dialog.accept()
    assert _warnings(fake_prompts) == [error_label("EXPIRY_REQUIRED")]
    assert dialog.saved_lot_id is None
    assert _service(app_context).list_lots() == []

    dialog.expires_edit.setDate(QDate(2027, 1, 31))
    dialog.accept()
    (lot,) = _service(app_context).list_lots()
    assert lot.expires_on == date(2027, 1, 31)
    assert len(_warnings(fake_prompts)) == 1


def test_a_blank_expiry_is_read_as_no_date_for_a_type_that_allows_none(
    app_context: AppContext, qtbot: QtBot
) -> None:
    dialog = LotDialog(app_context, type_code="GLOVE")
    qtbot.addWidget(dialog)
    dialog.no_expiry_check.setChecked(False)
    assert dialog.expires_edit.date() == dialog.expires_edit.minimumDate()
    dialog.lot_code_edit.setText("G-1")
    dialog.accept()
    (lot,) = _service(app_context).list_lots()
    assert lot.expires_on is None


def test_editing_a_lot_shows_its_expiry_and_cannot_change_its_type(
    app_context: AppContext, qtbot: QtBot
) -> None:
    lot_id = _add_lot(app_context)
    dialog = LotDialog(app_context, None, _lot_view(app_context, lot_id))
    qtbot.addWidget(dialog)
    assert dialog.expires_edit.date() == QDate(2026, 4, 1)
    assert not dialog.type_combo.isEnabled()
    selected = dialog.selected_type()
    assert selected is not None
    assert selected.code == "ANTIDOTE_CHEMICAL"
    dialog.notes_edit.setPlainText("Management note")
    dialog.accept()
    lot = _lot_view(app_context, lot_id)
    assert (lot.type_code, lot.notes) == ("ANTIDOTE_CHEMICAL", "Management note")

    adding = LotDialog(app_context)
    qtbot.addWidget(adding)
    assert adding.type_combo.isEnabled()


def test_the_service_refuses_a_type_change_the_dialog_cannot_make(
    app_context: AppContext,
) -> None:
    lot_id = _add_lot(app_context)
    other = _type_id(app_context, "DECONTAMINANT")
    with pytest.raises(ServiceError) as info:
        _service(app_context).update_lot(
            lot_id, LotInput(type_id=other, lot_code="L1", expires_on=date(2026, 4, 1))
        )
    assert info.value.code == stock_module.TYPE_IMMUTABLE
    assert error_label(stock_module.TYPE_IMMUTABLE) != stock_module.TYPE_IMMUTABLE


def test_the_lot_dialog_carries_the_no_clinical_information_hint(
    app_context: AppContext, qtbot: QtBot
) -> None:
    dialog = LotDialog(app_context)
    qtbot.addWidget(dialog)
    assert dialog.lot_hint.text() == QCoreApplication.translate(
        "Stock", "Manufacturer lot or receipt reference; no clinical information."
    )
    assert "clinical" in dialog.notes_edit.placeholderText()


def test_the_lot_dialog_defaults_the_receipt_date_to_the_earlier_of_as_of_and_today(
    app_context: AppContext, qtbot: QtBot
) -> None:
    today = app_context.clock.local_date()
    dialog = LotDialog(app_context)
    qtbot.addWidget(dialog)
    assert dialog.received_edit.date() == to_qdate(min(app_context.as_of, today))
    assert dialog.received_edit.maximumDate() == to_qdate(today)


# --------------------------------------------------------------------------- movement dialog


def test_the_movement_dialog_shows_what_is_on_hand_on_the_chosen_date(
    app_context: AppContext, qtbot: QtBot
) -> None:
    lot_id = _add_lot(app_context)
    _movement(app_context, lot_id, date(2026, 2, 10), MovementKind.ISSUE, 5)
    dialog = MovementDialog(app_context, None, _lot_view(app_context, lot_id))
    qtbot.addWidget(dialog)
    template = QCoreApplication.translate("Stock", "On hand on %1: %2")
    dialog.date_edit.setDate(QDate(2026, 2, 5))
    assert dialog.on_hand_label.text() == fill_placeholders(template, "02/05/2026", "50")
    dialog.date_edit.setDate(QDate(2026, 2, 10))
    assert dialog.on_hand_label.text() == fill_placeholders(template, "02/10/2026", "45")
    dialog.date_edit.setDate(QDate(2026, 1, 31))
    assert dialog.on_hand_label.text() == fill_placeholders(template, "01/31/2026", "0")
    assert dialog.on_hand_on(date(2026, 2, 10)) == 45
    app_context.translator_manager.set_language("es_ES")
    template = QCoreApplication.translate("Stock", "On hand on %1: %2")
    assert dialog.on_hand_label.text() == fill_placeholders(template, "31/01/2026", "0")


def test_the_movement_dialog_starts_at_the_earlier_of_as_of_and_today(
    app_context: AppContext, qtbot: QtBot
) -> None:
    lot_id = _add_lot(app_context)
    today = app_context.clock.local_date()
    dialog = MovementDialog(app_context, None, _lot_view(app_context, lot_id))
    qtbot.addWidget(dialog)
    assert dialog.date_edit.date() == to_qdate(min(app_context.as_of, today))
    assert dialog.date_edit.maximumDate() == to_qdate(today)
    assert dialog.quantity_spin.minimum() == 1
    assert dialog.quantity_spin.maximum() == 1_000_000
    assert [dialog.kind_combo.itemData(i) for i in range(dialog.kind_combo.count())] == [
        kind.value for kind in MovementKind
    ]
    assert dialog.kind_combo.itemText(0) == kind_label("receipt")


def test_a_movement_is_recorded_through_the_service(app_context: AppContext, qtbot: QtBot) -> None:
    lot_id = _add_lot(app_context)
    dialog = MovementDialog(app_context, None, _lot_view(app_context, lot_id))
    qtbot.addWidget(dialog)
    dialog.date_edit.setDate(QDate(2026, 2, 20))
    _pick_kind(dialog, MovementKind.ISSUE)
    dialog.quantity_spin.setValue(5)
    dialog.reference_edit.setText("OUT-1")
    dialog.accept()
    views = _service(app_context).movements(lot_id)
    assert [(v.kind, v.signed_quantity, v.balance_after) for v in views] == [
        (MovementKind.RECEIPT, 50, 50),
        (MovementKind.ISSUE, -5, 45),
    ]
    assert dialog.saved_movement_id == views[1].id
    assert views[1].reference == "OUT-1"


def test_the_movement_dialog_shows_the_balance_error_and_writes_nothing(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    lot_id = _add_lot(app_context)
    dialog = MovementDialog(app_context, None, _lot_view(app_context, lot_id))
    qtbot.addWidget(dialog)
    dialog.date_edit.setDate(QDate(2026, 2, 20))
    _pick_kind(dialog, MovementKind.ISSUE)
    dialog.quantity_spin.setValue(51)
    dialog.accept()
    assert _warnings(fake_prompts) == [error_label(BALANCE_NEGATIVE)]
    assert len(_service(app_context).movements(lot_id)) == 1
    assert dialog.saved_movement_id is None


def test_an_adjustment_needs_a_note(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    lot_id = _add_lot(app_context)
    dialog = MovementDialog(app_context, None, _lot_view(app_context, lot_id))
    qtbot.addWidget(dialog)
    dialog.date_edit.setDate(QDate(2026, 2, 20))
    _pick_kind(dialog, MovementKind.ISSUE)
    optional = dialog.note_edit.placeholderText()
    _pick_kind(dialog, MovementKind.ADJUSTMENT_IN)
    assert dialog.note_edit.placeholderText() != optional
    dialog.quantity_spin.setValue(3)
    dialog.accept()
    assert _warnings(fake_prompts) == [error_label(NOTE_REQUIRED)]
    assert len(_service(app_context).movements(lot_id)) == 1
    dialog.note_edit.setText("Recount found three more")
    dialog.accept()
    views = _service(app_context).movements(lot_id)
    assert [v.balance_after for v in views] == [50, 53]
    assert views[1].note == "Recount found three more"


def test_a_duplicate_movement_is_refused(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    lot_id = _add_lot(app_context)
    _movement(app_context, lot_id, date(2026, 2, 20), MovementKind.ISSUE, 5)
    dialog = MovementDialog(app_context, None, _lot_view(app_context, lot_id))
    qtbot.addWidget(dialog)
    dialog.date_edit.setDate(QDate(2026, 2, 20))
    _pick_kind(dialog, MovementKind.ISSUE)
    dialog.quantity_spin.setValue(5)
    dialog.accept()
    assert _warnings(fake_prompts) == [error_label(DUPLICATE_MOVEMENT)]
    assert len(_service(app_context).movements(lot_id)) == 2


def test_a_movement_is_corrected_through_the_service(app_context: AppContext, qtbot: QtBot) -> None:
    lot_id = _add_lot(app_context)
    issue_id = _movement(app_context, lot_id, date(2026, 2, 20), MovementKind.ISSUE, 5)
    views = _service(app_context).movements(lot_id)
    view: MovementView = next(v for v in views if v.id == issue_id)
    dialog = MovementDialog(app_context, None, _lot_view(app_context, lot_id), view)
    qtbot.addWidget(dialog)
    assert dialog.selected_kind() is MovementKind.ISSUE
    assert dialog.quantity_spin.value() == 5
    assert dialog.date_edit.date() == QDate(2026, 2, 20)
    dialog.quantity_spin.setValue(7)
    dialog.accept()
    views = _service(app_context).movements(lot_id)
    assert [v.balance_after for v in views] == [50, 43]
    assert dialog.saved_movement_id == issue_id


def test_the_movement_dialog_for_a_lot_that_is_gone_still_opens(
    app_context: AppContext, qtbot: QtBot
) -> None:
    lot_id = _add_lot(app_context)
    lot = _lot_view(app_context, lot_id)
    _service(app_context).delete_lot(lot_id)
    dialog = MovementDialog(app_context, None, lot)
    qtbot.addWidget(dialog)
    assert dialog.on_hand_on(date(2026, 3, 1)) == 0


# --------------------------------------------------------------------------- type dialog


def test_the_type_dialog_creates_a_user_type_with_a_not_set_minimum(
    app_context: AppContext, qtbot: QtBot
) -> None:
    dialog = StockTypeDialog(app_context)
    qtbot.addWidget(dialog)
    assert dialog.minimum_spin.specialValueText() == QCoreApplication.translate("Stock", "Not set")
    assert dialog.minimum() is None
    dialog.code_edit.setText("USER-1")
    dialog.category_combo.setCurrentIndex(dialog.category_combo.findData("antidote"))
    dialog.label_pt_edit.setText("Meu tipo")
    dialog.label_en_edit.setText("My type")
    dialog.accept()
    created = _service(app_context).get_type_by_code("USER-1")
    assert created is not None
    assert dialog.saved_type_id == created.id
    assert (created.built_in, created.category, created.minimum_quantity) == (
        False,
        StockCategory.ANTIDOTE,
        None,
    )
    assert (created.label_pt_br, created.label_en_us, created.label_es_es) == (
        "Meu tipo",
        "My type",
        None,
    )

    dialog_with_minimum = StockTypeDialog(app_context, None, created)
    qtbot.addWidget(dialog_with_minimum)
    dialog_with_minimum.minimum_spin.setValue(0)
    assert dialog_with_minimum.minimum() == 0  # 0 is a minimum, not "Not set"
    dialog_with_minimum.accept()
    updated = _service(app_context).get_type(created.id)
    assert updated.minimum_quantity == 0
    dialog_with_minimum.minimum_spin.setValue(dialog_with_minimum.minimum_spin.minimum())
    assert dialog_with_minimum.minimum() is None


def test_the_type_dialog_shows_service_errors_through_the_prompts(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    dialog = StockTypeDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.code_edit.setText("USER-1")
    dialog.accept()
    assert _warnings(fake_prompts) == [error_label(LABEL_PT_BR_REQUIRED)]
    dialog.label_pt_edit.setText("Meu tipo")
    dialog.accept()
    assert len(_warnings(fake_prompts)) == 1
    again = StockTypeDialog(app_context)
    qtbot.addWidget(again)
    again.code_edit.setText("USER-1")
    again.label_pt_edit.setText("Outro")
    again.accept()
    assert _warnings(fake_prompts)[-1] == error_label(DUPLICATE_CODE)
    bad = StockTypeDialog(app_context)
    qtbot.addWidget(bad)
    bad.code_edit.setText("not valid!")
    bad.label_pt_edit.setText("Outro")
    bad.accept()
    assert _warnings(fake_prompts)[-1] == error_label(INVALID_CODE)


def test_a_built_in_type_only_lets_the_minimum_and_the_active_flag_change(
    app_context: AppContext, qtbot: QtBot
) -> None:
    built_in = _service(app_context).get_type_by_code("ANTIDOTE_CHEMICAL")
    assert built_in is not None
    dialog = StockTypeDialog(app_context, None, built_in)
    qtbot.addWidget(dialog)
    for disabled in (
        dialog.code_edit,
        dialog.category_combo,
        dialog.label_pt_edit,
        dialog.label_en_edit,
        dialog.label_es_edit,
    ):
        assert not disabled.isEnabled()
    assert dialog.minimum_spin.isEnabled()
    assert dialog.active_check.isEnabled()
    assert not dialog.built_in_note.isHidden()
    dialog.minimum_spin.setValue(20)
    dialog.active_check.setChecked(False)
    dialog.accept()
    updated = _service(app_context).get_type(built_in.id)
    assert (updated.minimum_quantity, updated.active) == (20, False)
    assert updated.code == "ANTIDOTE_CHEMICAL"
    assert updated.category is StockCategory.ANTIDOTE
    assert (updated.label_pt_br, updated.label_en_us, updated.label_es_es) == (None, None, None)

    user = StockTypeDialog(app_context)
    qtbot.addWidget(user)
    assert user.built_in_note.isHidden()


def test_a_user_type_with_lots_keeps_its_code_and_category(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    service = _service(app_context)
    type_id = service.create_type(
        stock_module.StockTypeInput(code="USER-1", category="other", label_pt_br="Meu tipo")
    )
    service.create_lot(
        LotInput(type_id=type_id, lot_code="U1"),
        InitialReceipt(moved_on=date(2026, 2, 1), quantity=3),
    )
    dialog = StockTypeDialog(app_context, None, service.get_type(type_id))
    qtbot.addWidget(dialog)
    dialog.code_edit.setText("USER-2")
    dialog.accept()
    assert _warnings(fake_prompts) == [error_label(CODE_IMMUTABLE)]
    dialog.code_edit.setText("USER-1")
    dialog.category_combo.setCurrentIndex(dialog.category_combo.findData("ppe"))
    dialog.accept()
    assert _warnings(fake_prompts)[-1] == error_label("CATEGORY_IMMUTABLE")


# --------------------------------------------------------------------------- the dialog registry


def test_the_three_stock_dialogs_are_registered_with_fictitious_data(
    app_context: AppContext, qtbot: QtBot
) -> None:
    keys = [spec.key for spec in registry.dialogs()]
    assert {"stock.lot", "stock.movement", "stock.type"} <= set(keys)
    made: dict[str, QDialog] = {}
    for spec in registry.dialogs():
        if spec.key.startswith("stock."):
            made[spec.key] = spec.factory(app_context, None)
            qtbot.addWidget(made[spec.key])
    assert isinstance(made["stock.lot"], LotDialog)
    assert isinstance(made["stock.movement"], MovementDialog)
    assert isinstance(made["stock.type"], StockTypeDialog)
    assert made["stock.lot"].lot_code_edit.text().startswith("DEMO")
    assert made["stock.type"].code_edit.text().startswith("DEMO")
    assert _service(app_context).list_lots() == []  # nothing is written by building them


def test_the_demo_dialogs_build_without_a_stock_service(
    app_context: AppContext, qtbot: QtBot
) -> None:
    vars(app_context.services)["stock"] = None
    for factory in (demo_lot_dialog, demo_movement_dialog, demo_type_dialog):
        dialog = factory(app_context, None)
        qtbot.addWidget(dialog)
        assert dialog.windowTitle()


# --------------------------------------------------------------------------- pseudo-locale


def test_the_stock_dialogs_are_translated_in_the_pseudo_locale(
    pseudo_context: AppContext, qtbot: QtBot
) -> None:
    lot_id = _add_lot(pseudo_context, price=1250)
    lot = _lot_view(pseudo_context, lot_id)
    movement = _service(pseudo_context).movements(lot_id)[0]
    built_in = _service(pseudo_context).get_type_by_code("GLOVE")
    assert built_in is not None
    for dialog in (
        LotDialog(pseudo_context),
        LotDialog(pseudo_context, None, lot),
        LotDialog(pseudo_context, type_code="DETECTOR_CHEMICAL"),
        MovementDialog(pseudo_context, None, lot),
        MovementDialog(pseudo_context, None, lot, movement),
        StockTypeDialog(pseudo_context),
        StockTypeDialog(pseudo_context, None, built_in),
    ):
        qtbot.addWidget(dialog)
        assert_fully_translated(dialog)


def test_the_stock_dialogs_stay_translated_after_a_language_switch(
    pseudo_context: AppContext, qtbot: QtBot
) -> None:
    lot_id = _add_lot(pseudo_context)
    lot = _lot_view(pseudo_context, lot_id)
    dialogs = (
        LotDialog(pseudo_context),
        MovementDialog(pseudo_context, None, lot),
        StockTypeDialog(pseudo_context),
    )
    for dialog in dialogs:
        qtbot.addWidget(dialog)
    for lang in ("es_ES", "en_US", "pt_BR"):
        pseudo_context.translator_manager.set_language(lang)
        for dialog in dialogs:
            assert_fully_translated(dialog, lang)
