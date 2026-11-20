# SPDX-License-Identifier: GPL-3.0-or-later
"""Dialogs of the stock module: lot, movement and item type (PLAN.md Phase 11, T11.9; D32 to D38).

Each dialog builds the service input in ``submit()``, calls the service through ``apply_change`` (a
``ServiceError`` is shown translated through ``context.prompts`` and the dialog stays open) and
never touches storage. The pages open them without blocking (``open()`` and delete on close);
nothing here uses a message box. Prices are TYPED in the locale's format and parsed with
``parse_amount`` into minor units; a price typed in one language is shown again when the
language changes. Lot codes, references, notes and user-defined type labels are data, flagged
with ``i18nData``. Stock is management data only: the hints say so and no field takes clinical
information (D19, D38).
"""

from datetime import date

from PySide6.QtCore import QCoreApplication, QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QWidget,
)

from cbrn_dashboard.domain.budget import CURRENCY_DECIMALS
from cbrn_dashboard.domain.stock import (
    CATEGORY_ORDER,
    EXPIRY_REQUIRED_CATEGORIES,
    MovementKind,
    StockCategory,
)
from cbrn_dashboard.services.errors import REQUIRED, ServiceError
from cbrn_dashboard.services.stock import (
    EXPIRY_REQUIRED,
    MAX_MINIMUM,
    MAX_QUANTITY,
    InitialReceipt,
    LotInput,
    LotView,
    MovementInput,
    MovementView,
    StockTypeInput,
    StockTypeView,
)
from cbrn_dashboard.ui.budget.dialogs import configured_currency
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import (
    EMPTY,
    FormatError,
    apply_locale,
    format_amount,
    format_date,
    format_number,
    from_qdate,
    parse_amount,
    to_qdate,
)
from cbrn_dashboard.ui.shell.widgets import (
    FormDialog,
    apply_change,
    mark_data,
    show_service_error,
)
from cbrn_dashboard.ui.stock.labels import (
    category_label,
    error_label,
    fill_placeholders,
    kind_label,
    stock_type_display,
    type_name,
)

__all__ = [
    "LotDialog",
    "MovementDialog",
    "StockTypeDialog",
    "demo_lot_dialog",
    "demo_movement_dialog",
    "demo_type_dialog",
]

#: The value of the minimum spin box that stands for "not set" (shown as its special text).
_MINIMUM_NOT_SET = -1


def _date_edit(parent: QWidget, value: QDate) -> QDateEdit:
    edit = QDateEdit(value, parent)
    edit.setCalendarPopup(True)
    return edit


def _show_format_error(
    context: AppContext, parent: QWidget | None, error: FormatError, field: str
) -> None:
    """Show a price the user typed wrongly, translated (an empty required value is REQUIRED)."""
    code = REQUIRED if error.code == EMPTY else error.code
    show_service_error(context, parent, ServiceError(code, field), error_label)


def _reformat_amount(edit: QLineEdit, currency: str, old_lang: str, new_lang: str) -> None:
    """Show the amount typed in ``old_lang`` again in the format of ``new_lang``.

    Text that did not parse in ``old_lang`` is cleared: left as typed it would be read in
    ``new_lang`` and could silently become another amount (``1.234`` refused in en-US is 1234 in
    pt-BR).
    """
    text = edit.text().strip()
    if not text:
        return
    try:
        edit.setText(format_amount(parse_amount(text, currency, old_lang), currency, new_lang))
    except FormatError:
        edit.clear()


def _types_by_code(context: AppContext) -> dict[str, StockTypeView]:
    service = context.services.stock
    if service is None:
        return {}
    return {item.code: item for item in service.list_types(include_inactive=True)}


# --------------------------------------------------------------------------- lot


class LotDialog(FormDialog):
    """Add or edit a lot; on creation also the REQUIRED initial receipt (D33).

    ``categories`` limits the item types offered (the antidotes page offers two categories); the
    types are the ACTIVE ones, plus the type of the lot being edited. ``type_code`` preselects a
    type. The "No expiry date" box is disabled (and unchecked) for the categories whose lots need
    an expiry date. After a successful save ``saved_lot_id`` holds the id of the lot.
    """

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        lot: LotView | None = None,
        categories: frozenset[StockCategory] | None = None,
        type_code: str | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("lot_dialog")
        self._lot = lot
        self._amount_lang = self.language
        self.saved_lot_id: int | None = None
        service = context.services.stock
        types = [] if service is None else service.list_types(include_inactive=True)
        wanted = None if lot is None else lot.type_id
        offered = [
            item
            for item in types
            if item.id == wanted
            or (item.active and (categories is None or item.category in categories))
        ]
        # By category, then in the order the types were created (the built-in ones: seed order).
        offered.sort(key=lambda item: (CATEGORY_ORDER.index(item.category), item.id))
        self._types: dict[int, StockTypeView] = {item.id: item for item in offered}
        self.type_combo = QComboBox(self)
        mark_data(self.type_combo)
        for type_id in self._types:
            self.type_combo.addItem("", type_id)
        self.lot_code_edit = QLineEdit(self)
        self.lot_hint = QLabel(self)
        self.lot_hint.setWordWrap(True)
        self.expires_edit = _date_edit(self, to_qdate(context.as_of))
        self.no_expiry_check = QCheckBox(self)
        self.no_expiry_check.setChecked(True)
        self.price_edit = QLineEdit(self)
        self.currency_combo = QComboBox(self)
        mark_data(self.currency_combo)
        for code in CURRENCY_DECIMALS:
            self.currency_combo.addItem(code, code)
        currency = (None if lot is None else lot.currency) or configured_currency(context)
        self.currency_combo.setCurrentIndex(max(0, self.currency_combo.findData(currency)))
        self.notes_edit = QPlainTextEdit(self)
        self.notes_edit.setMaximumHeight(70)
        today = context.clock.local_date()
        self.received_edit = _date_edit(self, to_qdate(min(context.as_of, today)))
        self.received_edit.setMaximumDate(to_qdate(today))
        self.quantity_spin = QSpinBox(self)
        self.quantity_spin.setRange(1, MAX_QUANTITY)
        self.quantity_spin.setGroupSeparatorShown(True)
        self.reference_edit = QLineEdit(self)
        self.add_field(lambda: QCoreApplication.translate("Stock", "Type"), self.type_combo)
        self.add_field(lambda: QCoreApplication.translate("Stock", "Lot code"), self.lot_code_edit)
        self.form.addRow(self.lot_hint)
        self.add_field(lambda: QCoreApplication.translate("Stock", "Expiry"), self.expires_edit)
        self.form.addRow(self.no_expiry_check)
        self.add_field(lambda: QCoreApplication.translate("Stock", "Unit price"), self.price_edit)
        self.add_field(lambda: QCoreApplication.translate("Stock", "Currency"), self.currency_combo)
        self.add_field(lambda: QCoreApplication.translate("Stock", "Notes"), self.notes_edit)
        if lot is None:
            self.add_field(
                lambda: QCoreApplication.translate("Stock", "Received on"), self.received_edit
            )
            self.add_field(
                lambda: QCoreApplication.translate("Stock", "Initial quantity"), self.quantity_spin
            )
            self.add_field(
                lambda: QCoreApplication.translate("Stock", "Reference"), self.reference_edit
            )
        else:
            for hidden in (self.received_edit, self.quantity_spin, self.reference_edit):
                hidden.setVisible(False)
        self.type_combo.currentIndexChanged.connect(self._sync_expiry)
        self.no_expiry_check.toggled.connect(self._sync_expiry)
        if lot is not None:
            self._load(lot)
        elif type_code is not None:
            self._select_type_code(type_code)
        self._sync_expiry()
        self.retranslate()

    def _load(self, lot: LotView) -> None:
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(lot.type_id)))
        self.lot_code_edit.setText(lot.lot_code)
        if lot.expires_on is not None:
            self.expires_edit.setDate(to_qdate(lot.expires_on))
        self.no_expiry_check.setChecked(lot.expires_on is None)
        if lot.unit_price_minor is not None and lot.currency is not None:
            price = format_amount(lot.unit_price_minor, lot.currency, self.language)
            self.price_edit.setText(price)
        self.notes_edit.setPlainText(lot.notes or "")

    def _select_type_code(self, type_code: str) -> None:
        for type_id, item in self._types.items():
            if item.code == type_code:
                self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(type_id)))
                return

    def selected_type(self) -> StockTypeView | None:
        """The item type chosen in the combo box, or ``None`` while there is none."""
        data = self.type_combo.currentData()
        return None if data is None else self._types.get(int(data))

    def selected_currency(self) -> str:
        return str(self.currency_combo.currentData())

    def _sync_expiry(self, *_args: object) -> None:
        """An antidote or decontaminant lot needs an expiry date: no "No expiry date" for it."""
        selected = self.selected_type()
        required = selected is not None and selected.category in EXPIRY_REQUIRED_CATEGORIES
        if required:
            self.no_expiry_check.setChecked(False)
        self.no_expiry_check.setEnabled(not required)
        self.no_expiry_check.setToolTip(error_label(EXPIRY_REQUIRED) if required else "")
        self.expires_edit.setEnabled(not self.no_expiry_check.isChecked())

    def retranslate(self) -> None:
        super().retranslate()
        if self._lot is None:
            self.setWindowTitle(QCoreApplication.translate("Stock", "Add lot"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Stock", "Edit lot"))
        lang = self.language
        for index in range(self.type_combo.count()):
            item = self._types.get(int(self.type_combo.itemData(index)))
            if item is not None:
                self.type_combo.setItemText(index, stock_type_display(item, lang))
        self.lot_hint.setText(
            QCoreApplication.translate(
                "Stock", "Manufacturer lot or receipt reference; no clinical information."
            )
        )
        self.no_expiry_check.setText(QCoreApplication.translate("Stock", "No expiry date"))
        self._sync_expiry()
        self.price_edit.setPlaceholderText(QCoreApplication.translate("Stock", "Not set"))
        self.notes_edit.setPlaceholderText(
            QCoreApplication.translate("Stock", "Management notes only; no clinical information.")
        )
        apply_locale(self.expires_edit, lang)
        apply_locale(self.received_edit, lang)
        apply_locale(self.quantity_spin, lang)
        if lang != self._amount_lang:
            _reformat_amount(self.price_edit, self.selected_currency(), self._amount_lang, lang)
            self._amount_lang = lang

    def submit(self) -> bool:
        service = self.context.services.stock
        if service is None:
            return False
        selected = self.selected_type()
        text = self.price_edit.text().strip()
        price: int | None = None
        currency: str | None = None
        if text:
            try:
                price = parse_amount(text, self.selected_currency(), self.language)
            except FormatError as error:
                _show_format_error(self.context, self, error, "unit_price_minor")
                return False
            currency = self.selected_currency()
        expires = None if self.no_expiry_check.isChecked() else from_qdate(self.expires_edit.date())
        data = LotInput(
            type_id=None if selected is None else selected.id,
            lot_code=self.lot_code_edit.text(),
            expires_on=expires,
            unit_price_minor=price,
            currency=currency,
            notes=self.notes_edit.toPlainText(),
        )
        lot = self._lot
        receipt = (
            InitialReceipt(
                moved_on=from_qdate(self.received_edit.date()),
                quantity=self.quantity_spin.value(),
                reference=self.reference_edit.text(),
            )
            if lot is None
            else None
        )

        def save() -> None:
            if lot is None:
                self.saved_lot_id = service.create_lot(data, receipt)
            else:
                service.update_lot(lot.id, data)
                self.saved_lot_id = lot.id

        return apply_change(self.context, self, error_label, save)


# --------------------------------------------------------------------------- movement


class MovementDialog(FormDialog):
    """Record (or correct) a movement of a lot: date, kind, quantity, reference and note.

    The date starts at the as-of date or today, whichever is earlier, and cannot be after today.
    The information line shows the quantity on hand on the chosen date (from the recorded
    movements). An adjustment needs a note. After a successful save ``saved_movement_id`` holds the
    id of the movement.
    """

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None,
        lot: LotView,
        movement: MovementView | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("movement_dialog")
        self._lot = lot
        self._movement = movement
        self.saved_movement_id: int | None = None
        self._types = _types_by_code(context)
        self._movements = self._load_movements()
        today = context.clock.local_date()
        start = min(context.as_of, today) if movement is None else movement.moved_on
        self.type_label = QLabel(self)
        mark_data(self.type_label)
        self.lot_label = QLabel(lot.lot_code, self)
        mark_data(self.lot_label)
        self.date_edit = _date_edit(self, to_qdate(start))
        self.date_edit.setMaximumDate(to_qdate(max(today, start)))
        self.on_hand_label = QLabel(self)
        self.on_hand_label.setWordWrap(True)
        self.kind_combo = QComboBox(self)
        for kind in MovementKind:
            self.kind_combo.addItem("", kind.value)
        self.quantity_spin = QSpinBox(self)
        self.quantity_spin.setRange(1, MAX_QUANTITY)
        self.quantity_spin.setGroupSeparatorShown(True)
        self.reference_edit = QLineEdit(self)
        self.note_edit = QLineEdit(self)
        self.add_field(lambda: QCoreApplication.translate("Stock", "Type"), self.type_label)
        self.add_field(lambda: QCoreApplication.translate("Stock", "Lot"), self.lot_label)
        self.add_field(lambda: QCoreApplication.translate("Stock", "Date"), self.date_edit)
        self.form.addRow(self.on_hand_label)
        self.add_field(lambda: QCoreApplication.translate("Stock", "Kind"), self.kind_combo)
        self.add_field(lambda: QCoreApplication.translate("Stock", "Quantity"), self.quantity_spin)
        self.add_field(
            lambda: QCoreApplication.translate("Stock", "Reference"), self.reference_edit
        )
        self.add_field(lambda: QCoreApplication.translate("Stock", "Note"), self.note_edit)
        self.date_edit.dateChanged.connect(self._update_info)
        self.kind_combo.currentIndexChanged.connect(self._update_note_hint)
        if movement is not None:
            self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(movement.kind.value)))
            self.quantity_spin.setValue(movement.quantity)
            self.reference_edit.setText(movement.reference)
            self.note_edit.setText(movement.note or "")
        self.retranslate()

    def _load_movements(self) -> list[MovementView]:
        service = self.context.services.stock
        if service is None:
            return []
        try:
            return service.movements(self._lot.id)
        except ServiceError:
            return []  # a lot that does not exist (any more) has nothing on hand

    def on_hand_on(self, day: date) -> int:
        """The quantity of the lot on hand on ``day``, from the movements recorded so far."""
        return sum(item.signed_quantity for item in self._movements if item.moved_on <= day)

    def selected_kind(self) -> MovementKind:
        return MovementKind(str(self.kind_combo.currentData()))

    def _update_info(self, *_args: object) -> None:
        day = from_qdate(self.date_edit.date())
        lang = self.language
        self.on_hand_label.setText(
            fill_placeholders(
                QCoreApplication.translate("Stock", "On hand on %1: %2"),
                format_date(day, lang),
                format_number(self.on_hand_on(day), lang),
            )
        )

    def _update_note_hint(self, *_args: object) -> None:
        if self.selected_kind() in (MovementKind.ADJUSTMENT_IN, MovementKind.ADJUSTMENT_OUT):
            hint = QCoreApplication.translate("Stock", "Required for an adjustment")
        else:
            hint = QCoreApplication.translate("Stock", "Optional")
        self.note_edit.setPlaceholderText(hint)

    def retranslate(self) -> None:
        super().retranslate()
        if self._movement is None:
            self.setWindowTitle(QCoreApplication.translate("Stock", "Record movement"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Stock", "Edit movement"))
        lang = self.language
        self.type_label.setText(type_name(self._lot.type_code, lang, self._types))
        for index in range(self.kind_combo.count()):
            self.kind_combo.setItemText(index, kind_label(str(self.kind_combo.itemData(index))))
        apply_locale(self.date_edit, lang)
        apply_locale(self.quantity_spin, lang)
        self._update_info()
        self._update_note_hint()

    def submit(self) -> bool:
        service = self.context.services.stock
        if service is None:
            return False
        data = MovementInput(
            moved_on=from_qdate(self.date_edit.date()),
            kind=self.selected_kind(),
            quantity=self.quantity_spin.value(),
            reference=self.reference_edit.text(),
            note=self.note_edit.text(),
        )
        movement = self._movement
        lot_id = self._lot.id

        def save() -> None:
            if movement is None:
                self.saved_movement_id = service.record_movement(lot_id, data)
            else:
                service.update_movement(movement.id, data)
                self.saved_movement_id = movement.id

        return apply_change(self.context, self, error_label, save)


# --------------------------------------------------------------------------- item type


class StockTypeDialog(FormDialog):
    """Add or edit an item type: code, category, three labels, minimum stock and active flag.

    The minimum has a "Not set" special value (no minimum, P12). A built-in type keeps its code,
    category and (empty) labels: only the minimum and the active flag are enabled. After a
    successful save ``saved_type_id`` holds the id of the type.
    """

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        stock_type: StockTypeView | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("stock_type_dialog")
        self._type = stock_type
        self.saved_type_id: int | None = None
        self.code_edit = QLineEdit(self)
        self.category_combo = QComboBox(self)
        for category in StockCategory:
            self.category_combo.addItem("", category.value)
        self.label_pt_edit = QLineEdit(self)
        self.label_en_edit = QLineEdit(self)
        self.label_es_edit = QLineEdit(self)
        self.minimum_spin = QSpinBox(self)
        self.minimum_spin.setRange(_MINIMUM_NOT_SET, MAX_MINIMUM)
        self.minimum_spin.setValue(_MINIMUM_NOT_SET)
        self.minimum_spin.setGroupSeparatorShown(True)
        self.active_check = QCheckBox(self)
        self.active_check.setChecked(True)
        self.built_in_note = QLabel(self)
        self.built_in_note.setWordWrap(True)
        self.built_in_note.setVisible(stock_type is not None and stock_type.built_in)
        self.add_field(lambda: QCoreApplication.translate("Stock", "Code"), self.code_edit)
        self.add_field(lambda: QCoreApplication.translate("Stock", "Category"), self.category_combo)
        self.add_field(
            lambda: QCoreApplication.translate("Stock", "Label (Portuguese)"), self.label_pt_edit
        )
        self.add_field(
            lambda: QCoreApplication.translate("Stock", "Label (English)"), self.label_en_edit
        )
        self.add_field(
            lambda: QCoreApplication.translate("Stock", "Label (Spanish)"), self.label_es_edit
        )
        self.add_field(
            lambda: QCoreApplication.translate("Stock", "Minimum stock"), self.minimum_spin
        )
        self.form.addRow(self.active_check)
        self.form.addRow(self.built_in_note)
        if stock_type is not None:
            self._load(stock_type)
        self.retranslate()

    def _load(self, stock_type: StockTypeView) -> None:
        self.code_edit.setText(stock_type.code)
        self.category_combo.setCurrentIndex(
            max(0, self.category_combo.findData(stock_type.category.value))
        )
        self.label_pt_edit.setText(stock_type.label_pt_br or "")
        self.label_en_edit.setText(stock_type.label_en_us or "")
        self.label_es_edit.setText(stock_type.label_es_es or "")
        minimum = stock_type.minimum_quantity
        self.minimum_spin.setValue(_MINIMUM_NOT_SET if minimum is None else minimum)
        self.active_check.setChecked(stock_type.active)
        if stock_type.built_in:
            for widget in (
                self.code_edit,
                self.category_combo,
                self.label_pt_edit,
                self.label_en_edit,
                self.label_es_edit,
            ):
                widget.setEnabled(False)

    def minimum(self) -> int | None:
        """The minimum stock of the spin box: ``None`` for "Not set", else 0 or more."""
        value = self.minimum_spin.value()
        return None if value == _MINIMUM_NOT_SET else value

    def retranslate(self) -> None:
        super().retranslate()
        if self._type is None:
            self.setWindowTitle(QCoreApplication.translate("Stock", "Add item type"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Stock", "Edit item type"))
        for index in range(self.category_combo.count()):
            self.category_combo.setItemText(
                index, category_label(str(self.category_combo.itemData(index)))
            )
        self.minimum_spin.setSpecialValueText(QCoreApplication.translate("Stock", "Not set"))
        self.active_check.setText(QCoreApplication.translate("Stock", "Active"))
        self.built_in_note.setText(
            QCoreApplication.translate(
                "Stock",
                "Built-in item type: only the minimum stock and the active flag can change.",
            )
        )
        apply_locale(self.minimum_spin, self.language)

    def submit(self) -> bool:
        service = self.context.services.stock
        if service is None:
            return False
        data = StockTypeInput(
            code=self.code_edit.text().strip(),
            category=str(self.category_combo.currentData()),
            label_pt_br=self.label_pt_edit.text(),
            label_en_us=self.label_en_edit.text(),
            label_es_es=self.label_es_edit.text(),
            minimum_quantity=self.minimum(),
            active=self.active_check.isChecked(),
        )
        current = self._type

        def save() -> None:
            if current is None:
                self.saved_type_id = service.create_type(data)
            else:
                service.update_type(current.id, data)
                self.saved_type_id = current.id

        return apply_change(self.context, self, error_label, save)


# --------------------------------------------------------------------------- demo dialogs


def demo_lot_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """A lot dialog filled with a fictitious lot (it writes nothing unless accepted)."""
    dialog = LotDialog(context, parent, type_code="ANTIDOTE_CHEMICAL")
    dialog.lot_code_edit.setText("DEMO-L001")
    dialog.quantity_spin.setValue(10)
    dialog.reference_edit.setText("DEMO-REF-001")
    return dialog


def demo_movement_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """A movement dialog for a fictitious lot."""
    lot = LotView(
        id=0,
        type_id=0,
        type_code="ANTIDOTE_CHEMICAL",
        lot_code="DEMO-L001",
        expires_on=date(2027, 6, 30),
        unit_price_minor=1250,
        currency="BRL",
        notes=None,
    )
    dialog = MovementDialog(context, parent, lot)
    dialog.quantity_spin.setValue(5)
    dialog.reference_edit.setText("DEMO-REF-002")
    return dialog


def demo_type_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """An item-type dialog filled with a fictitious user-defined type."""
    stock_type = StockTypeView(
        id=0,
        code="DEMO-ANTIDOTE-X",
        built_in=False,
        category=StockCategory.ANTIDOTE,
        label_pt_br="DEMO Antidoto ficticio",
        label_en_us="Demo antidote",
        label_es_es=None,
        minimum_quantity=10,
        active=True,
    )
    return StockTypeDialog(context, parent, stock_type)
