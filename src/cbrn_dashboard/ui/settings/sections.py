# SPDX-License-Identifier: GPL-3.0-or-later
"""The three settings sections owned by T6.1: general, alerts and indicator targets (PLAN.md 3.5).

* General: the user-interface language, the operator label (D05) and the institution and unit
  names (D18, a local-only placeholder).
* Alerts: the certificate warning window (P01) and the maintenance warning window (P02).
* Targets: the stored indicator targets (P03), one row per (indicator, dimension).

Every section reads and writes ONLY through ``context.services.config`` and
``context.services.indicators`` (either may be ``None``: the inputs are then disabled and the
badges hidden). A placeholder shows the "to be confirmed" badge with a Confirm button until it is
confirmed or its value is changed here. A refused change is shown translated and nothing is written;
the form stays as typed. Dialogs are opened non-modally with ``open()``.
"""

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cbrn_dashboard.domain.config import ReadinessConfig
from cbrn_dashboard.i18n import LANGUAGES
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.ui.settings.dialogs import (
    PLACEHOLDER_TARGETS,
    TargetDialog,
    parse_whole,
    reformat_number,
    show_error,
)
from cbrn_dashboard.ui.settings.labels import (
    dimension_text,
    error_label,
    fill_placeholders,
    indicator_label,
)
from cbrn_dashboard.ui.settings.models import TargetRow, TargetsModel
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import FormatError, format_number
from cbrn_dashboard.ui.shell.i18n import language_display_name
from cbrn_dashboard.ui.shell.widgets import (
    EditAction,
    action_row,
    apply_change,
    current_language,
    follow_language,
    make_edit_action,
    make_table_view,
)

__all__ = ["AlertsSection", "GeneralSection", "PlaceholderBadge", "ProblemNote", "TargetsSection"]


def _open(dialog: QDialog) -> None:
    """Show ``dialog`` window-modally without blocking; it deletes itself when closed."""
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.open()


# --------------------------------------------------------------------------- shared helpers


def _read_config(context: AppContext) -> tuple[ReadinessConfig | None, str | None]:
    """The stored configuration and the error code of an unusable one.

    ``(None, None)`` without a configuration service, ``(None, code)`` when a stored setting
    cannot be read (the section then shows the translated message of ``code``).
    """
    service = context.services.config
    if service is None:
        return None, None
    try:
        return service.load(), None
    except ServiceError as error:
        return None, error.code


def _load_config(context: AppContext) -> ReadinessConfig | None:
    """The stored configuration; ``None`` without a configuration service or when it is unusable."""
    return _read_config(context)[0]


class ProblemNote:
    """A visible translated line that says why a section cannot show its values.

    It is hidden until :meth:`show_code` is given an error code (a stored setting that cannot be
    read); it follows the language through :meth:`retranslate`.
    """

    def __init__(self, parent: QWidget, name: str) -> None:
        self.label = QLabel(parent)
        self.label.setObjectName(f"{name}_problem")
        self.label.setWordWrap(True)
        self.label.setVisible(False)
        self._code: str | None = None

    def show_code(self, code: str | None) -> None:
        self._code = code
        self.label.setVisible(code is not None)
        self.retranslate()

    def retranslate(self) -> None:
        self.label.setText("" if self._code is None else error_label(self._code))


def _badge_for_field(context: AppContext, field: str) -> str | None:
    """The placeholder id whose badge is due for config ``field`` (``None`` when none)."""
    service = context.services.config
    if service is None:
        return None
    try:
        return service.badge_for_field(field)
    except ServiceError:
        return None


def _targets_badge_due(context: AppContext) -> str | None:
    """``P03`` while the badge of the indicator targets is due, else ``None``."""
    service = context.services.config
    if service is None:
        return None
    try:
        return PLACEHOLDER_TARGETS if service.needs_badge(PLACEHOLDER_TARGETS) else None
    except ServiceError:
        return None


def _save_config(
    context: AppContext,
    parent: QWidget,
    change: Callable[[ReadinessConfig], ReadinessConfig],
) -> bool:
    """Save ``change(stored configuration)``.

    ``ConfigService.save`` confirms the placeholders of the fields that changed in the same
    transaction. A refusal is shown translated and nothing is written. ``True`` on success.
    """
    service = context.services.config
    if service is None:
        return False
    return apply_change(context, parent, error_label, lambda: service.save(change(service.load())))


def _confirm(context: AppContext, parent: QWidget, placeholder: str | None) -> None:
    """Confirm ``placeholder`` on this installation (the Confirm button of a badge)."""
    service = context.services.config
    if service is None or placeholder is None:
        return
    apply_change(context, parent, error_label, lambda: service.confirm(placeholder))


class PlaceholderBadge:
    """The "placeholder - to be confirmed" badge and its Confirm button for one placeholder.

    Both widgets are hidden until :meth:`show_for` is given a placeholder id; the button is an
    edit target, so read-only mode disables it.
    """

    def __init__(self, context: AppContext, parent: QWidget, name: str) -> None:
        self._context = context
        self.placeholder: str | None = None
        self.badge = QLabel(parent)
        self.badge.setObjectName(f"{name}_badge")
        self.confirm = QPushButton(parent)
        self.confirm.setObjectName(f"{name}_confirm")
        self.badge.setVisible(False)
        self.confirm.setVisible(False)
        context.register_edit_action(self.confirm)
        self.retranslate()

    def retranslate(self) -> None:
        self.badge.setText(QCoreApplication.translate("Settings", "Placeholder - to be confirmed"))
        self.confirm.setText(QCoreApplication.translate("Settings", "Confirm"))

    def show_for(self, placeholder: str | None, *, editable: bool) -> None:
        """Show the badge of ``placeholder`` (hide it for ``None``)."""
        self.placeholder = placeholder
        shown = placeholder is not None
        self.badge.setVisible(shown)
        self.confirm.setVisible(shown)
        self._context.set_edit_enabled(self.confirm, editable)

    def row(self) -> QHBoxLayout:
        """The badge and the button in one row."""
        row = QHBoxLayout()
        row.addWidget(self.badge)
        row.addWidget(self.confirm)
        row.addStretch(1)
        return row


# --------------------------------------------------------------------------- general


class GeneralSection(QWidget):
    """Settings -> General: language, operator label (D05), institution and unit names (D18)."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("general_section")
        self.context = context
        self._syncing = False
        self.language_caption = QLabel(self)
        self.language_combo = QComboBox(self)
        self.language_combo.setObjectName("language_combo")
        for code in LANGUAGES:
            self.language_combo.addItem("", code)
        self.language_caption.setBuddy(self.language_combo)
        self.operator_caption = QLabel(self)
        self.operator_edit = QLineEdit(self)
        self.operator_edit.setObjectName("operator_edit")
        self.operator_caption.setBuddy(self.operator_edit)
        self.institution_caption = QLabel(self)
        self.institution_edit = QLineEdit(self)
        self.institution_edit.setObjectName("institution_edit")
        self.institution_caption.setBuddy(self.institution_edit)
        self.unit_caption = QLabel(self)
        self.unit_edit = QLineEdit(self)
        self.unit_edit.setObjectName("unit_edit")
        self.unit_caption.setBuddy(self.unit_edit)
        self.names_badge = PlaceholderBadge(context, self, "names")
        self.problem = ProblemNote(self, "general")
        self._loaded: tuple[str, str, str] | None = None
        self.save_button = QPushButton(self)
        self.save_button.setObjectName("general_save")
        # Read-only mode disables every control that changes data. The language is a preference
        # of this installation, not data, so its selector stays usable (as the language menu).
        for target in (
            self.operator_edit,
            self.institution_edit,
            self.unit_edit,
            self.save_button,
        ):
            context.register_edit_action(target)

        form = QFormLayout()
        form.addRow(self.language_caption, self.language_combo)
        form.addRow(self.operator_caption, self.operator_edit)
        form.addRow(self.institution_caption, self.institution_edit)
        form.addRow(self.unit_caption, self.unit_edit)
        form.addRow(self.names_badge.row())
        layout = QVBoxLayout(self)
        layout.addWidget(self.problem.label)
        layout.addLayout(form)
        save_row = QHBoxLayout()
        save_row.addWidget(self.save_button)
        save_row.addStretch(1)
        layout.addLayout(save_row)

        self.language_combo.currentIndexChanged.connect(self._language_picked)
        self.save_button.clicked.connect(self.save)
        self.names_badge.confirm.clicked.connect(self._confirm_names)
        context.data_changed.connect(self.refresh)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    # ----- texts

    def retranslate(self) -> None:
        self.language_caption.setText(QCoreApplication.translate("Settings", "Language"))
        self.operator_caption.setText(QCoreApplication.translate("Settings", "Operator label"))
        self.institution_caption.setText(QCoreApplication.translate("Settings", "Institution name"))
        self.unit_caption.setText(QCoreApplication.translate("Settings", "Unit name"))
        self.save_button.setText(QCoreApplication.translate("Settings", "Save"))
        self.names_badge.retranslate()
        self.problem.retranslate()
        for index in range(self.language_combo.count()):
            self.language_combo.setItemText(
                index, language_display_name(str(self.language_combo.itemData(index)))
            )
        self._sync_language()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    # ----- language

    def _sync_language(self) -> None:
        self._syncing = True
        try:
            index = self.language_combo.findData(current_language(self.context))
            self.language_combo.setCurrentIndex(max(0, index))
        finally:
            self._syncing = False

    def _language_picked(self, _index: int) -> None:
        code = self.language_combo.currentData()
        if self._syncing or not isinstance(code, str):
            return
        if code != current_language(self.context):
            self.context.translator_manager.set_language(code)

    # ----- data

    def _typed(self) -> tuple[str, str, str]:
        return (
            self.operator_edit.text().strip(),
            self.institution_edit.text().strip(),
            self.unit_edit.text().strip(),
        )

    def is_dirty(self) -> bool:
        """Whether the inputs differ from what was last loaded into them (unsaved typing)."""
        return self._loaded is not None and self._typed() != self._loaded

    def reload(self) -> None:
        """Put the stored values into the inputs (discarding what was typed)."""
        config = _load_config(self.context)
        if config is not None:
            self._show(config)

    def _show(self, config: ReadinessConfig) -> None:
        self.operator_edit.setText(config.operator_label)
        self.institution_edit.setText(config.institution_name)
        self.unit_edit.setText(config.unit_name)
        self._loaded = self._typed()

    def refresh(self) -> None:
        """Show the badge again, and the stored values unless the form holds unsaved typing.

        The operator label is given to the context.
        """
        config, problem = _read_config(self.context)
        self.problem.show_code(problem)
        if config is not None:
            if not self.is_dirty():
                self._show(config)
            self.context.set_operator_label(config.operator_label)
        due = _badge_for_field(self.context, "institution_name") or _badge_for_field(
            self.context, "unit_name"
        )
        enable = self.context.set_edit_enabled
        for widget in (
            self.operator_edit,
            self.institution_edit,
            self.unit_edit,
            self.save_button,
        ):
            enable(widget, config is not None)
        self.names_badge.show_for(due, editable=config is not None)

    def save(self) -> None:
        """Store the operator label and the names as typed (a refusal keeps the form as typed)."""
        operator = self.operator_edit.text().strip()
        institution = self.institution_edit.text().strip()
        unit = self.unit_edit.text().strip()
        saved = _save_config(
            self.context,
            self,
            lambda config: config.with_changes(
                operator_label=operator, institution_name=institution, unit_name=unit
            ),
        )
        if saved:
            self.reload()  # what is stored now is what is typed: the form is clean again

    def _confirm_names(self) -> None:
        _confirm(self.context, self, self.names_badge.placeholder)


# --------------------------------------------------------------------------- alerts


class AlertsSection(QWidget):
    """Settings -> Alerts: the certificate (P01) and maintenance (P02) warning windows in days."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("alerts_section")
        self.context = context
        self._lang = current_language(context)
        self.cert_caption = QLabel(self)
        self.cert_edit = QLineEdit(self)
        self.cert_edit.setObjectName("cert_days_edit")
        self.cert_caption.setBuddy(self.cert_edit)
        self.cert_badge = PlaceholderBadge(context, self, "cert")
        self.maintenance_caption = QLabel(self)
        self.maintenance_edit = QLineEdit(self)
        self.maintenance_edit.setObjectName("maintenance_days_edit")
        self.maintenance_caption.setBuddy(self.maintenance_edit)
        self.maintenance_badge = PlaceholderBadge(context, self, "maintenance")
        self.problem = ProblemNote(self, "alerts")
        self._loaded: tuple[int, int] | None = None
        self.save_button = QPushButton(self)
        self.save_button.setObjectName("alerts_save")
        for target in (self.cert_edit, self.maintenance_edit, self.save_button):
            context.register_edit_action(target)

        grid = QGridLayout()
        grid.addWidget(self.cert_caption, 0, 0)
        grid.addWidget(self.cert_edit, 0, 1)
        grid.addWidget(self.cert_badge.badge, 0, 2)
        grid.addWidget(self.cert_badge.confirm, 0, 3)
        grid.addWidget(self.maintenance_caption, 1, 0)
        grid.addWidget(self.maintenance_edit, 1, 1)
        grid.addWidget(self.maintenance_badge.badge, 1, 2)
        grid.addWidget(self.maintenance_badge.confirm, 1, 3)
        grid.setColumnStretch(4, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.problem.label)
        layout.addLayout(grid)
        save_row = QHBoxLayout()
        save_row.addWidget(self.save_button)
        save_row.addStretch(1)
        layout.addLayout(save_row)

        self.save_button.clicked.connect(self.save)
        self.cert_badge.confirm.clicked.connect(self._confirm_cert)
        self.maintenance_badge.confirm.clicked.connect(self._confirm_maintenance)
        context.data_changed.connect(self.refresh)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    # ----- texts

    def retranslate(self) -> None:
        self.cert_caption.setText(
            QCoreApplication.translate("Settings", "Warn about certificates expiring within (days)")
        )
        self.maintenance_caption.setText(
            QCoreApplication.translate("Settings", "Warn about maintenance due within (days)")
        )
        self.save_button.setText(QCoreApplication.translate("Settings", "Save"))
        self.cert_badge.retranslate()
        self.maintenance_badge.retranslate()
        self.problem.retranslate()
        lang = current_language(self.context)
        if lang != self._lang:
            reformat_number(self.cert_edit, self._lang, lang)
            reformat_number(self.maintenance_edit, self._lang, lang)
            self._lang = lang

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    # ----- data

    def _typed(self) -> tuple[int, int] | None:
        """The typed windows as numbers (``None`` while one of them does not parse)."""
        lang = current_language(self.context)
        try:
            return parse_whole(self.cert_edit.text(), lang), parse_whole(
                self.maintenance_edit.text(), lang
            )
        except FormatError:
            return None

    def is_dirty(self) -> bool:
        """Whether the inputs differ from what was last loaded into them (unsaved typing)."""
        return self._loaded is not None and self._typed() != self._loaded

    def reload(self) -> None:
        """Put the stored windows into the inputs (discarding what was typed)."""
        config = _load_config(self.context)
        if config is not None:
            self._show(config)

    def _show(self, config: ReadinessConfig) -> None:
        lang = current_language(self.context)
        self.cert_edit.setText(format_number(config.cert_warning_days, lang))
        self.maintenance_edit.setText(format_number(config.maintenance_warning_days, lang))
        self._loaded = (config.cert_warning_days, config.maintenance_warning_days)

    def refresh(self) -> None:
        """Show the badges of P01 and P02 again, and the stored windows unless the form is dirty."""
        config, problem = _read_config(self.context)
        self.problem.show_code(problem)
        lang = current_language(self.context)
        if config is not None and not self.is_dirty():
            self._show(config)
        self._lang = lang
        enable = self.context.set_edit_enabled
        for widget in (self.cert_edit, self.maintenance_edit, self.save_button):
            enable(widget, config is not None)
        editable = config is not None
        self.cert_badge.show_for(
            _badge_for_field(self.context, "cert_warning_days"), editable=editable
        )
        self.maintenance_badge.show_for(
            _badge_for_field(self.context, "maintenance_warning_days"), editable=editable
        )

    def save(self) -> None:
        """Store both windows; a number that does not parse is refused and nothing is written."""
        lang = current_language(self.context)
        try:
            cert = parse_whole(self.cert_edit.text(), lang)
            maintenance = parse_whole(self.maintenance_edit.text(), lang)
        except FormatError as error:
            show_error(self.context, self, error.code)
            return
        saved = _save_config(
            self.context,
            self,
            lambda config: config.with_changes(
                cert_warning_days=cert, maintenance_warning_days=maintenance
            ),
        )
        if saved:
            self.reload()

    def _confirm_cert(self) -> None:
        _confirm(self.context, self, self.cert_badge.placeholder)

    def _confirm_maintenance(self) -> None:
        _confirm(self.context, self, self.maintenance_badge.placeholder)


# --------------------------------------------------------------------------- targets


class TargetsSection(QWidget):
    """Settings -> Targets: warning and critical values per indicator and dimension (P03)."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("targets_section")
        self.context = context
        self.model = TargetsModel(self)
        self.view = make_table_view(self.model, self)
        self.view.setObjectName("targets_view")
        self.note_label = QLabel(self)
        self.note_label.setObjectName("targets_note")
        self.note_label.setWordWrap(True)
        self.badge = PlaceholderBadge(context, self, "targets")
        self.problem = ProblemNote(self, "targets")
        self.add_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Settings", "Add target"),
            self.add_target,
        )
        self.edit_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Settings", "Edit target"),
            self.edit_target,
        )
        self.toggle_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Settings", "Enable or disable target"),
            self.toggle_target,
        )
        self.delete_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Settings", "Delete target"),
            self.delete_target,
        )
        self._actions: tuple[EditAction, ...] = (
            self.add_action,
            self.edit_action,
            self.toggle_action,
            self.delete_action,
        )

        layout = QVBoxLayout(self)
        layout.addWidget(self.problem.label)
        layout.addWidget(self.note_label)
        layout.addLayout(self.badge.row())
        layout.addWidget(self.view, 1)
        layout.addLayout(action_row(self._actions, self))

        selection = self.view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._update_actions)
        self.badge.confirm.clicked.connect(self._confirm_targets)
        context.data_changed.connect(self.refresh)
        context.as_of_changed.connect(self._as_of_changed)  # the dimensions in use depend on it
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    # ----- texts

    def retranslate(self) -> None:
        self.note_label.setText(
            QCoreApplication.translate(
                "Settings",
                "Targets of the budget execution rate are year-end values. "
                "They are scaled over the fiscal year when the indicator is evaluated.",
            )
        )
        self.view.setAccessibleName(QCoreApplication.translate("Settings", "Indicator targets"))
        self.badge.retranslate()
        self.problem.retranslate()
        for action in self._actions:
            action.retranslate()
        self.model.set_language(current_language(self.context))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    # ----- data

    def selected_target(self) -> TargetRow | None:
        row = self.model.selected_row(self.view)
        return row if isinstance(row, TargetRow) else None

    def _as_of_changed(self, _value: object) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Read the stored targets and the badge of P03 again.

        A target whose dimension currently has no value is marked "Not in use". When the
        dimensions cannot be read (a stored setting is unusable) the message is shown instead.
        """
        service = self.context.services.indicators
        previous = self.selected_target()
        targets = [] if service is None else service.list_targets()
        definitions = {} if service is None else {d.code: d for d in service.definitions()}
        known: dict[str, list[str]] | None = None
        problem: str | None = None
        if service is not None:
            try:
                known = service.known_dimensions(self.context.as_of)
            except ServiceError as error:
                problem = error.code
        self.problem.show_code(problem)
        self.model.set_targets(targets, definitions, known)
        if previous is not None:
            for row, target in enumerate(targets):
                if (target.indicator_code, target.dimension) == (
                    previous.view.indicator_code,
                    previous.view.dimension,
                ):
                    self.view.selectRow(row)
        due = _targets_badge_due(self.context)
        self.badge.show_for(due, editable=self.context.services.config is not None)
        self._update_actions()

    def _update_actions(self, *_args: object) -> None:
        has_service = self.context.services.indicators is not None
        selected = self.selected_target() is not None
        enable = self.context.set_edit_enabled
        enable(self.add_action, has_service)
        enable(self.edit_action, has_service and selected)
        enable(self.toggle_action, has_service and selected)
        enable(self.delete_action, has_service and selected)

    # ----- actions

    def add_target(self) -> None:
        _open(TargetDialog(self.context, self))

    def edit_target(self) -> None:
        row = self.selected_target()
        if row is not None:
            _open(TargetDialog(self.context, self, row.view))

    def toggle_target(self) -> None:
        row = self.selected_target()
        service = self.context.services.indicators
        if row is None or service is None:
            return
        view = row.view

        def switch() -> None:
            service.set_target_enabled(
                view.indicator_code,
                view.dimension,
                not view.enabled,
                confirm_placeholder=PLACEHOLDER_TARGETS,
            )

        apply_change(self.context, self, error_label, switch)

    def delete_target(self) -> None:
        row = self.selected_target()
        service = self.context.services.indicators
        if row is None or service is None:
            return
        view = row.view
        title = QCoreApplication.translate("Settings", "Delete target")
        question = fill_placeholders(
            QCoreApplication.translate("Settings", "Delete the target of %1 (%2)?"),
            indicator_label(view.indicator_code),
            dimension_text(view.dimension),
        )
        if self.context.prompts.confirm(self, title, question):
            apply_change(
                self.context,
                self,
                error_label,
                lambda: service.delete_target(view.indicator_code, view.dimension),
            )

    def _confirm_targets(self) -> None:
        _confirm(self.context, self, self.badge.placeholder)
