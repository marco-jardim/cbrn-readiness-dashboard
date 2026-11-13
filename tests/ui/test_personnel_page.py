# SPDX-License-Identifier: GPL-3.0-or-later
"""The Personnel page, its dialogs, the settings section and the labels (PLAN.md T2.4)."""

import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QAbstractItemModel, QCoreApplication, QDate, Qt
from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QTextEdit, QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard.domain.config import ReadinessConfig
from cbrn_dashboard.domain.personnel import CertStatus, DegreeLevel, DegreeStatus, PpeLevel
from cbrn_dashboard.services import errors as errors_module
from cbrn_dashboard.services import personnel as personnel_module
from cbrn_dashboard.services.personnel import (
    NO_RENEWAL_REASONS,
    CertificateInput,
    CourseInput,
    DegreeInput,
    PersonnelService,
    StaffInput,
    TrainingInput,
)
from cbrn_dashboard.storage import settings_repo
from cbrn_dashboard.storage.repository import WriteContext
from cbrn_dashboard.ui.personnel.dialogs import (
    CertificateDialog,
    CourseDialog,
    DegreeDialog,
    StaffDialog,
    TrainingDialog,
)
from cbrn_dashboard.ui.personnel.labels import (
    ALL_ERROR_CODES,
    cert_status_label,
    degree_level_label,
    degree_status_label,
    error_label,
    fill_placeholders,
    ppe_level_label,
    reason_label,
)
from cbrn_dashboard.ui.personnel.page import (
    PersonnelPage,
    PersonnelSettingsSection,
    create_page,
    create_settings_section,
    demo_certificate_dialog,
    demo_course_dialog,
    demo_degree_dialog,
    demo_staff_dialog,
    demo_training_dialog,
    page_title,
    settings_section_title,
)
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import from_qdate
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from tests.ui._fakes import FakePrompts
from tests.ui._walk import assert_fully_translated

pytestmark = pytest.mark.ui

LANGUAGES = ("pt_BR", "en_US", "es_ES")
AS_OF = date(2026, 3, 5)
IDENTIFIER_HINT = "A local code, not a service number."
FREE_TEXT_HINT = "No names, health or contact data."


# --------------------------------------------------------------------------- helpers


def _service(context: AppContext) -> PersonnelService:
    service = context.services.personnel
    assert service is not None
    return service


def _english(context: AppContext) -> None:
    context.translator_manager.set_language("en_US")


def _add_staff(
    context: AppContext,
    identifier: str = "DEMO-001",
    active_from: date = date(2025, 1, 1),
    active_until: date | None = None,
    label: str | None = None,
) -> int:
    return _service(context).create_staff(
        StaffInput(
            identifier=identifier,
            active_from=active_from,
            active_until=active_until,
            label=label,
            category="Demo category",
        )
    )


def _add_cert(
    context: AppContext,
    staff_id: int,
    level: str = "A",
    issued_on: date = date(2025, 6, 1),
    valid_until: date = date(2027, 6, 1),
    reference: str | None = None,
) -> int:
    return _service(context).add_certificate(
        staff_id, CertificateInput(level, issued_on, valid_until, reference)
    )


def _add_course(context: AppContext, code: str = "COURSE-1", active: bool = True) -> int:
    return _service(context).create_course(
        CourseInput(
            code=code,
            label_pt_br="Curso demo",
            label_en_us="Demo course",
            label_es_es="Curso de demostracion",
            active=active,
        )
    )


def _seed_three_people(context: AppContext) -> tuple[int, int, int]:
    """P1 valid until 2027-06-01, P2 valid until 2026-04-01, P3 inactive since 2025-12-31."""
    first = _add_staff(context, "DEMO-P1")
    _add_cert(context, first, "A", date(2025, 6, 1), date(2027, 6, 1))
    second = _add_staff(context, "DEMO-P2")
    _add_cert(context, second, "A", date(2025, 4, 1), date(2026, 4, 1))
    third = _add_staff(context, "DEMO-P3", active_until=date(2025, 12, 31))
    return first, second, third


def _set_months(context: AppContext, months: dict[str, int | None]) -> None:
    """Configure A04 through the config service when the context has one, else the repository."""
    config = getattr(context.services, "config", None)
    if config is not None:
        config.save(config.load().with_changes(ppe_validity_months=months))
        return
    conn = context.conn
    assert conn is not None
    current = settings_repo.load_config(conn)
    settings_repo.save_config(
        WriteContext(conn, context.clock, ""), current.with_changes(ppe_validity_months=months)
    )


class FakeConfig:
    """A stand-in with the API of the configuration service, to drive the settings section."""

    def __init__(self) -> None:
        self.config = ReadinessConfig()
        self.badges: dict[str, str] = {
            "ppe_hierarchy_enabled": "A02",
            "ppe_hierarchy": "A02",
            "ppe_validity_months": "A04",
        }
        self.confirmed: list[str] = []

    def load(self) -> ReadinessConfig:
        return self.config

    def save(self, config: ReadinessConfig) -> tuple[str, ...]:
        self.config = config
        return ()

    def badge_for_field(self, field: str) -> str | None:
        return self.badges.get(field)

    def confirm(self, placeholder_id: str) -> None:
        self.confirmed.append(placeholder_id)
        self.badges = {k: v for k, v in self.badges.items() if v != placeholder_id}


def _attach_fake_config(context: AppContext) -> FakeConfig:
    fake = FakeConfig()
    vars(context.services)["config"] = fake
    return fake


def _cells(model: QAbstractItemModel, row: int, columns: int) -> list[object]:
    return [model.index(row, column).data() for column in range(columns)]


def _open_dialog[D: QDialog](page: QWidget, kind: type[D]) -> D:
    shown = [dialog for dialog in page.findChildren(kind) if dialog.isVisible()]
    assert len(shown) == 1
    return shown[0]


def _warnings(prompts: FakePrompts) -> list[str]:
    return [call.text for call in prompts.calls_of("warning")]


def _page(context: AppContext, qtbot: QtBot) -> PersonnelPage:
    page = PersonnelPage(context)
    qtbot.addWidget(page)
    return page


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


# --------------------------------------------------------------------------- add through dialogs


def test_adding_a_person_and_a_certificate_through_the_dialogs(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _english(app_context)
    app_context.set_as_of(AS_OF)
    service = _service(app_context)
    page = _page(app_context, qtbot)

    dialog = StaffDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.identifier_edit.setText("DEMO-001")
    dialog.label_edit.setText("Demo person")
    dialog.category_edit.setText("Demo category")
    dialog.active_from_edit.setDate(QDate(2026, 1, 12))
    dialog.accept()

    (stored,) = service.list_staff()
    assert (stored.identifier, stored.label, stored.category) == (
        "DEMO-001",
        "Demo person",
        "Demo category",
    )
    assert page.staff_model.rowCount() == 1
    assert _cells(page.staff_model, 0, 5) == [
        "DEMO-001",
        "Demo person",
        "Demo category",
        "01/12/2026",
        "-",
    ]

    page.staff_view.selectRow(0)
    cert_dialog = CertificateDialog(app_context, None, stored.id)
    qtbot.addWidget(cert_dialog)
    cert_dialog.level_combo.setCurrentIndex(cert_dialog.level_combo.findData("B"))
    cert_dialog.issued_edit.setDate(QDate(2026, 2, 1))
    cert_dialog.valid_until_edit.setDate(QDate(2027, 2, 1))
    cert_dialog.reference_edit.setText("REF-1")
    cert_dialog.accept()

    (certificate,) = service.list_certificates(stored.id)
    assert certificate.level is PpeLevel.B
    assert certificate.valid_until == date(2027, 2, 1)
    assert page.certificates_model.rowCount() == 1
    assert _cells(page.certificates_model, 0, 6) == [
        "B",
        "02/01/2026",
        "02/01/2027",
        "-",
        "",
        "REF-1",
    ]
    # the status per level shows in the staff table
    assert _cells(page.staff_model, 0, 8)[5:] == ["No qualification", "Valid", "No qualification"]

    app_context.translator_manager.set_language("pt_BR")
    assert page.staff_model.index(0, 3).data() == "12/01/2026"
    assert page.certificates_model.index(0, 1).data() == "01/02/2026"
    app_context.translator_manager.set_language("en_US")
    assert page.staff_model.index(0, 3).data() == "01/12/2026"


def test_adding_training_and_a_degree_through_the_dialogs(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _english(app_context)
    service = _service(app_context)
    sid = _add_staff(app_context)
    _add_course(app_context)
    _add_course(app_context, "OLD-COURSE", active=False)
    page = _page(app_context, qtbot)
    page.staff_view.selectRow(0)

    training = TrainingDialog(app_context, None, sid)
    qtbot.addWidget(training)
    assert training.course_combo.count() == 1  # the inactive course is not offered
    assert training.course_combo.itemText(0) == "Demo course"
    training.completed_edit.setDate(QDate(2026, 3, 4))
    training.hours_edit.setText("1.5")
    training.accept()
    (record,) = service.list_training(sid)
    assert (record.course_code, record.completed_on, record.hours) == (
        "COURSE-1",
        date(2026, 3, 4),
        1.5,
    )
    assert _cells(page.training_model, 0, 3) == ["Demo course", "03/04/2026", "1.5"]

    degree = DegreeDialog(app_context, None, sid)
    qtbot.addWidget(degree)
    degree.level_combo.setCurrentIndex(degree.level_combo.findData("master"))
    degree.status_combo.setCurrentIndex(degree.status_combo.findData("in_progress"))
    degree.year_spin.setValue(2027)
    degree.field_edit.setText("Demo field")
    degree.accept()
    (stored,) = service.list_degrees(sid)
    assert (stored.level, stored.status, stored.year) == (
        DegreeLevel.MASTER,
        DegreeStatus.IN_PROGRESS,
        2027,
    )
    assert _cells(page.degrees_model, 0, 4) == [
        "Master's degree",
        "In progress",
        "2027",
        "Demo field",
    ]


def test_training_without_a_course_is_refused(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _english(app_context)
    sid = _add_staff(app_context)
    dialog = TrainingDialog(app_context, None, sid)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.accept()
    assert _warnings(fake_prompts) == ["A required field is empty."]
    assert dialog.isVisible()
    assert _service(app_context).list_training(sid) == []


def test_the_page_opens_its_dialogs_without_blocking(app_context: AppContext, qtbot: QtBot) -> None:
    _english(app_context)
    sid = _add_staff(app_context, label="Demo person")
    page = _page(app_context, qtbot)
    page.staff_view.selectRow(0)
    page.edit_staff()
    dialog = _open_dialog(page, StaffDialog)
    assert dialog.identifier_edit.text() == "DEMO-001"
    dialog.label_edit.setText("Changed by the dialog")
    dialog.accept()
    assert _service(app_context).get_staff(sid).label == "Changed by the dialog"
    assert page.staff_model.rows()[0].staff.label == "Changed by the dialog"


# --------------------------------------------------------------------------- validation errors


def test_valid_until_before_issued_shows_the_translated_error_and_writes_nothing(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _english(app_context)
    sid = _add_staff(app_context)
    dialog = CertificateDialog(app_context, None, sid)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.issued_edit.setDate(QDate(2026, 2, 1))
    dialog.valid_until_edit.setDate(QDate(2026, 1, 1))
    dialog.accept()
    assert _warnings(fake_prompts) == ["The validity end cannot be before the issue date."]
    assert fake_prompts.calls_of("warning")[0].title == "Cannot save"
    assert dialog.isVisible()
    assert _service(app_context).list_certificates(sid) == []


def test_a_validation_error_is_shown_in_the_current_language(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    app_context.translator_manager.set_language("pt_BR")
    sid = _add_staff(app_context)
    dialog = CertificateDialog(app_context, None, sid)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.issued_edit.setDate(QDate(2026, 2, 1))
    dialog.valid_until_edit.setDate(QDate(2026, 1, 1))
    dialog.accept()
    (text,) = _warnings(fake_prompts)
    assert text == error_label("VALID_UNTIL_BEFORE_ISSUED")
    assert text != "The validity end cannot be before the issue date."
    assert _service(app_context).list_certificates(sid) == []


def test_a_duplicate_identifier_and_a_national_id_are_refused(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _english(app_context)
    _add_staff(app_context)
    dialog = StaffDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.identifier_edit.setText("DEMO-001")
    dialog.accept()
    assert _warnings(fake_prompts) == ["This identifier is already in use."]
    dialog.identifier_edit.setText("123.456.789-09")
    dialog.accept()
    assert _warnings(fake_prompts)[-1] == (
        "The identifier looks like a national ID number. Use a local code instead."
    )
    assert dialog.isVisible()
    assert len(_service(app_context).list_staff()) == 1


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("abc", "The number is not valid."),
        ("1,5", "The number uses the separators of another language."),
        ("-2", "The number of hours cannot be negative."),
    ],
)
def test_badly_typed_hours_are_refused(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    qtbot: QtBot,
    text: str,
    message: str,
) -> None:
    _english(app_context)
    sid = _add_staff(app_context)
    _add_course(app_context)
    dialog = TrainingDialog(app_context, None, sid)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.hours_edit.setText(text)
    dialog.accept()
    assert _warnings(fake_prompts) == [message]
    assert _service(app_context).list_training(sid) == []


# --------------------------------------------------------------------------- hints, no notes


def test_the_hints_are_shown_under_the_free_text_inputs(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _english(app_context)
    staff = StaffDialog(app_context)
    certificate = CertificateDialog(app_context)
    degree = DegreeDialog(app_context)
    expected = (
        (staff, "identifier_hint", IDENTIFIER_HINT),
        (staff, "label_hint", FREE_TEXT_HINT),
        (staff, "category_hint", FREE_TEXT_HINT),  # P2-01: category is personal free text
        (certificate, "reference_hint", FREE_TEXT_HINT),
        (degree, "field_hint", FREE_TEXT_HINT),
    )
    for dialog in (staff, certificate, degree):
        qtbot.addWidget(dialog)
        dialog.show()
    for dialog, name, text in expected:
        hint = dialog.findChild(QLabel, name)
        assert hint is not None, name
        assert hint.text() == text
        assert hint.isVisibleTo(dialog)
    # the hint sits in the same container as its input
    parent = staff.identifier_edit.parentWidget()
    assert parent is not None
    assert staff.findChild(QLabel, "identifier_hint") in parent.findChildren(QLabel)
    # the hints follow a language switch
    app_context.translator_manager.set_language("pt_BR")
    hint = staff.findChild(QLabel, "identifier_hint")
    assert hint is not None
    assert hint.text() == QCoreApplication.translate(
        "Personnel", "A local code, not a service number."
    )
    assert hint.text() != IDENTIFIER_HINT


def test_no_dialog_has_a_notes_field(app_context: AppContext, qtbot: QtBot) -> None:
    _english(app_context)
    dialogs = [
        demo_staff_dialog(app_context, None),
        demo_certificate_dialog(app_context, None),
        demo_training_dialog(app_context, None),
        demo_degree_dialog(app_context, None),
        demo_course_dialog(app_context, None),
        StaffDialog(app_context),
        CertificateDialog(app_context),
        TrainingDialog(app_context),
        DegreeDialog(app_context),
        CourseDialog(app_context),
    ]
    notes = re.compile(r"\b(notes?|observations?|comments?|remarks?)\b")
    for dialog in dialogs:
        qtbot.addWidget(dialog)
        assert not dialog.findChildren(QPlainTextEdit)
        assert not dialog.findChildren(QTextEdit)
        for widget in dialog.findChildren(QWidget):
            assert not notes.search(widget.objectName().lower()), widget.objectName()
        for label in dialog.findChildren(QLabel):
            assert not notes.search(label.text().lower()), label.text()


# --------------------------------------------------------------------------- A04 pre-fill


def test_valid_until_is_prefilled_from_the_configured_months(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _english(app_context)
    app_context.set_as_of(AS_OF)
    service = _service(app_context)
    sid = _add_staff(app_context)
    _set_months(app_context, {"A": 12, "B": None, "C": None})

    dialog = CertificateDialog(app_context, None, sid)
    qtbot.addWidget(dialog)
    expected = service.propose_valid_until("A", AS_OF)
    assert expected is not None
    assert expected > AS_OF
    assert from_qdate(dialog.valid_until_edit.date()) == expected

    dialog.issued_edit.setDate(QDate(2026, 1, 31))
    moved = service.propose_valid_until("A", date(2026, 1, 31))
    assert moved is not None
    assert from_qdate(dialog.valid_until_edit.date()) == moved

    # a level without months proposes nothing: the field goes back to "not set" and stays there
    dialog.level_combo.setCurrentIndex(dialog.level_combo.findData("B"))
    assert dialog.valid_until_edit.date() == dialog.valid_until_edit.minimumDate()
    dialog.issued_edit.setDate(QDate(2026, 3, 1))
    assert dialog.valid_until_edit.date() == dialog.valid_until_edit.minimumDate()
    dialog.issued_edit.setDate(QDate(2026, 1, 31))

    # once the user has edited the field it is never overwritten
    dialog.valid_until_edit.setDate(QDate(2030, 1, 1))
    dialog.level_combo.setCurrentIndex(dialog.level_combo.findData("A"))
    dialog.issued_edit.setDate(QDate(2026, 2, 1))
    assert from_qdate(dialog.valid_until_edit.date()) == date(2030, 1, 1)


def test_the_prefilled_valid_until_is_what_gets_stored(
    app_context: AppContext, qtbot: QtBot
) -> None:
    app_context.set_as_of(AS_OF)
    service = _service(app_context)
    sid = _add_staff(app_context)
    _set_months(app_context, {"A": 24})
    expected = service.propose_valid_until("A", AS_OF)
    dialog = CertificateDialog(app_context, None, sid)
    qtbot.addWidget(dialog)
    dialog.accept()
    (certificate,) = service.list_certificates(sid)
    assert certificate.issued_on == AS_OF
    assert certificate.valid_until == expected


def test_there_is_no_prefill_without_configured_months(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _english(app_context)
    app_context.set_as_of(AS_OF)
    service = _service(app_context)
    sid = _add_staff(app_context)
    assert service.propose_valid_until("A", AS_OF) is None
    dialog = CertificateDialog(app_context, None, sid)
    qtbot.addWidget(dialog)
    dialog.show()
    unset = dialog.valid_until_edit.minimumDate()
    assert dialog.valid_until_edit.date() == unset  # "not set", not a one-day certificate
    assert dialog.valid_until_edit.specialValueText() == "Not set"
    dialog.issued_edit.setDate(QDate(2026, 6, 1))
    assert dialog.valid_until_edit.date() == unset  # it does not follow the issue date

    dialog.accept()  # a forgotten field is refused, nothing is stored
    assert _warnings(fake_prompts) == ["A required field is empty."]
    assert dialog.isVisible()
    assert service.list_certificates(sid) == []

    dialog.valid_until_edit.setDate(QDate(2027, 6, 1))
    dialog.accept()
    (certificate,) = service.list_certificates(sid)
    assert (certificate.issued_on, certificate.valid_until) == (date(2026, 6, 1), date(2027, 6, 1))


def test_editing_a_certificate_keeps_its_valid_until(app_context: AppContext, qtbot: QtBot) -> None:
    sid = _add_staff(app_context)
    cert_id = _add_cert(app_context, sid, "A", date(2025, 6, 1), date(2026, 9, 9))
    _set_months(app_context, {"A": 12})
    certificate = _service(app_context).get_certificate(cert_id)
    dialog = CertificateDialog(app_context, None, sid, certificate)
    qtbot.addWidget(dialog)
    dialog.issued_edit.setDate(QDate(2025, 7, 1))
    assert from_qdate(dialog.valid_until_edit.date()) == date(2026, 9, 9)
    dialog.accept()
    assert _service(app_context).get_certificate(cert_id).issued_on == date(2025, 7, 1)


# --------------------------------------------------------------------------- no renewal


def test_set_and_clear_no_renewal(app_context: AppContext, qtbot: QtBot) -> None:
    _english(app_context)
    app_context.set_as_of(AS_OF)
    service = _service(app_context)
    sid = _add_staff(app_context)
    cert_id = _add_cert(app_context, sid)
    page = _page(app_context, qtbot)
    page.staff_view.selectRow(0)
    page.certificates_view.selectRow(0)
    assert page.set_no_renewal_action.isEnabled()
    assert not page.clear_no_renewal_action.isEnabled()

    page.set_no_renewal_action.trigger()
    dialog = _open_dialog(page, CertificateDialog)
    assert dialog.no_renewal_check.isChecked()
    assert dialog.no_renewal_edit.isEnabled()
    assert [dialog.reason_combo.itemData(i) for i in range(dialog.reason_combo.count())] == [
        None,
        *NO_RENEWAL_REASONS,
    ]
    dialog.no_renewal_edit.setDate(QDate(2026, 2, 1))
    dialog.reason_combo.setCurrentIndex(dialog.reason_combo.findData("left_unit"))
    dialog.accept()
    marked = service.get_certificate(cert_id)
    assert marked.no_renewal_from == date(2026, 2, 1)
    assert marked.no_renewal_reason == "left_unit"
    assert _cells(page.staff_model, 0, 8)[5] == "No renewal"

    page.certificates_view.selectRow(0)
    assert page.clear_no_renewal_action.isEnabled()
    assert _cells(page.certificates_model, 0, 5)[3:] == ["02/01/2026", "Left the unit"]
    page.clear_no_renewal_action.trigger()
    cleared = service.get_certificate(cert_id)
    assert cleared.no_renewal_from is None
    assert cleared.no_renewal_reason is None


def test_the_certificate_dialog_can_set_the_mark_when_adding(
    app_context: AppContext, qtbot: QtBot
) -> None:
    sid = _add_staff(app_context)
    dialog = CertificateDialog(app_context, None, sid)
    qtbot.addWidget(dialog)
    assert not dialog.no_renewal_edit.isEnabled()
    dialog.no_renewal_check.setChecked(True)
    dialog.issued_edit.setDate(QDate(2026, 1, 1))
    dialog.valid_until_edit.setDate(QDate(2027, 1, 1))
    dialog.no_renewal_edit.setDate(QDate(2026, 6, 1))
    dialog.reason_combo.setCurrentIndex(dialog.reason_combo.findData("role_change"))
    dialog.accept()
    (certificate,) = _service(app_context).list_certificates(sid)
    assert certificate.no_renewal_from == date(2026, 6, 1)
    assert certificate.no_renewal_reason == "role_change"


# --------------------------------------------------------------------------- pseudonymise


def test_pseudonymise_asks_for_confirmation_and_replaces_the_identifier(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _english(app_context)
    service = _service(app_context)
    sid = _add_staff(app_context, label="Demo person")
    page = _page(app_context, qtbot)
    page.staff_view.selectRow(0)
    assert page.pseudonymise_action.isEnabled()

    fake_prompts.script("confirm", False)
    page.pseudonymise_action.trigger()
    (call,) = fake_prompts.calls_of("confirm")
    assert call.title == "Pseudonymise person"
    assert "cannot be undone" in call.text.lower()
    assert "DEMO-001" in call.text
    assert service.get_staff(sid).identifier == "DEMO-001"
    assert service.get_staff(sid).label == "Demo person"
    assert page.staff_model.index(0, 0).data() == "DEMO-001"

    fake_prompts.script("confirm", True)
    page.pseudonymise_action.trigger()
    new_identifier = service.get_staff(sid).identifier
    assert new_identifier.startswith("PSEUDO-")
    assert service.get_staff(sid).label is None
    assert page.staff_model.index(0, 0).data() == new_identifier
    selected = page.selected_staff()
    assert selected is not None
    assert selected.identifier == new_identifier


# --------------------------------------------------------------------------- the staff table


def test_the_summary_counts_follow_the_as_of_date(app_context: AppContext, qtbot: QtBot) -> None:
    _english(app_context)
    app_context.set_as_of(AS_OF)
    service = _service(app_context)
    _seed_three_people(app_context)
    page = _page(app_context, qtbot)

    def counts() -> list[list[object]]:
        return [_cells(page.summary_model, row, 4) for row in range(page.summary_model.rowCount())]

    def expected(on: date) -> list[list[object]]:
        return [
            [item.level.value, str(item.valid), str(item.expiring), str(item.retraining_needed)]
            for item in service.summary(on)
        ]

    before = counts()
    assert [row[0] for row in before] == ["A", "B", "C"]
    assert before == expected(AS_OF)
    assert before[0][1:] != ["0", "0", "0"]
    assert page.staff_model.index(1, 5).data() == "Expiring"  # DEMO-P2

    page.staff_view.selectRow(0)
    later = date(2027, 5, 1)
    app_context.set_as_of(later)
    after = counts()
    assert after == expected(later)
    assert after != before
    assert page.staff_model.index(1, 5).data() == "Expired"
    assert page.staff_model.index(0, 5).data() == "Expiring"
    selected = page.selected_staff()
    assert selected is not None
    assert selected.identifier == "DEMO-P1"


def test_the_filters_limit_the_staff(app_context: AppContext, qtbot: QtBot) -> None:
    _english(app_context)
    app_context.set_as_of(AS_OF)
    _seed_three_people(app_context)
    page = _page(app_context, qtbot)

    def identifiers() -> list[str]:
        return [row.staff.identifier for row in page.staff_model.rows()]

    assert identifiers() == ["DEMO-P1", "DEMO-P2", "DEMO-P3"]
    assert page.level_combo.count() == 1 + len(PpeLevel)

    page.active_check.setChecked(True)
    assert identifiers() == ["DEMO-P1", "DEMO-P2"]
    page.active_check.setChecked(False)

    page.level_combo.setCurrentIndex(page.level_combo.findData("A"))
    assert identifiers() == ["DEMO-P1", "DEMO-P2"]
    page.level_combo.setCurrentIndex(page.level_combo.findData("B"))
    assert identifiers() == []
    page.level_combo.setCurrentIndex(0)
    assert len(identifiers()) == 3

    page.retraining_check.setChecked(True)
    assert identifiers() == ["DEMO-P2"]
    page.retraining_check.setChecked(False)
    assert len(identifiers()) == 3


def test_the_detail_view_shows_the_selected_person(app_context: AppContext, qtbot: QtBot) -> None:
    _english(app_context)
    service = _service(app_context)
    first = _add_staff(app_context, "DEMO-P1")
    second = _add_staff(app_context, "DEMO-P2")
    _add_cert(app_context, first)
    course_id = _add_course(app_context)
    service.add_training(first, TrainingInput(course_id, date(2026, 3, 4), 8.0))
    service.add_degree(first, DegreeInput("doctorate", "completed", 2020, "Demo field"))
    page = _page(app_context, qtbot)
    assert not page.add_cert_action.isEnabled()
    page.staff_view.selectRow(0)
    assert page.add_cert_action.isEnabled()
    assert page.certificates_model.rowCount() == 1
    assert _cells(page.training_model, 0, 3) == ["Demo course", "03/04/2026", "8"]
    assert _cells(page.degrees_model, 0, 4) == ["Doctorate", "Completed", "2020", "Demo field"]
    page.staff_view.selectRow(1)
    other = page.selected_staff()
    assert other is not None
    assert other.id == second
    assert page.certificates_model.rowCount() == 0
    assert page.training_model.rowCount() == 0
    assert page.degrees_model.rowCount() == 0
    assert not page.edit_cert_action.isEnabled()


def test_headers_and_actions_follow_the_language(app_context: AppContext, qtbot: QtBot) -> None:
    _english(app_context)
    _add_staff(app_context)
    page = _page(app_context, qtbot)
    assert page.staff_model.headerData(0, Qt.Orientation.Horizontal) == "Identifier"
    assert page.staff_model.headerData(5, Qt.Orientation.Horizontal) == "Level A"
    assert page.add_staff_action.text() == "Add person"
    assert page.pseudonymise_action.text() == "Pseudonymise person"
    app_context.translator_manager.set_language("pt_BR")
    assert page.add_staff_action.text() == QCoreApplication.translate("Personnel", "Add person")
    assert page.add_staff_action.text() != "Add person"
    assert page.retraining_check.text() != "Needs retraining"
    assert page.tabs.tabText(0) != "PPE qualifications"


def test_deactivating_and_deleting_a_person_ask_for_confirmation(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _english(app_context)
    app_context.set_as_of(AS_OF)
    service = _service(app_context)
    sid = _add_staff(app_context)
    page = _page(app_context, qtbot)
    page.staff_view.selectRow(0)

    page.deactivate_staff_action.trigger()
    assert service.get_staff(sid).active_until is None
    fake_prompts.script("confirm", True)
    page.deactivate_staff_action.trigger()
    assert service.get_staff(sid).active_until == AS_OF
    assert not page.deactivate_staff_action.isEnabled()
    assert "DEMO-001" in fake_prompts.calls_of("confirm")[-1].text

    page.delete_staff_action.trigger()
    assert len(service.list_staff()) == 1
    fake_prompts.script("confirm", True)
    page.delete_staff_action.trigger()
    assert service.list_staff() == []
    assert page.staff_model.rowCount() == 0


def test_deleting_records_asks_for_confirmation(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _english(app_context)
    service = _service(app_context)
    sid = _add_staff(app_context)
    _add_cert(app_context, sid)
    course_id = _add_course(app_context)
    service.add_training(sid, TrainingInput(course_id, date(2026, 3, 4)))
    service.add_degree(sid, DegreeInput("master", "completed", 2020, None))
    page = _page(app_context, qtbot)
    page.staff_view.selectRow(0)

    for view, action, listing in (
        (page.certificates_view, page.delete_cert_action, service.list_certificates),
        (page.training_view, page.delete_training_action, service.list_training),
        (page.degrees_view, page.delete_degree_action, service.list_degrees),
    ):
        view.selectRow(0)
        action.trigger()  # the default answer is "no"
        assert len(listing(sid)) == 1
        fake_prompts.script("confirm", True)
        view.selectRow(0)
        action.trigger()
        assert listing(sid) == []
        page.staff_view.selectRow(0)


# --------------------------------------------------------------------------- read-only, no service


def test_read_only_mode_disables_every_edit_action(app_context: AppContext, qtbot: QtBot) -> None:
    sid = _add_staff(app_context)
    _add_cert(app_context, sid)
    _add_course(app_context)
    app_context.read_only = True
    page = _page(app_context, qtbot)
    section = PersonnelSettingsSection(app_context)
    qtbot.addWidget(section)
    page.staff_view.selectRow(0)
    page.certificates_view.selectRow(0)
    section.courses_view.selectRow(0)
    actions = [*page._actions, *section._actions]
    assert len(actions) == 16 + 7
    targets = app_context.edit_targets()
    for action in actions:
        assert action in targets
        assert not action.isEnabled()
    for widget in section._inputs:
        assert widget in targets
        assert not widget.isEnabled()


def test_the_page_builds_without_a_personnel_service(app_context: AppContext, qtbot: QtBot) -> None:
    app_context.services.personnel = None
    page = _page(app_context, qtbot)
    section = PersonnelSettingsSection(app_context)
    qtbot.addWidget(section)
    assert page.staff_model.rowCount() == 0
    assert page.summary_model.rowCount() == 0
    assert section.courses_model.rowCount() == 0
    assert not page.add_staff_action.isEnabled()
    assert not section.add_course_action.isEnabled()
    for dialog in (
        demo_staff_dialog(app_context, None),
        demo_certificate_dialog(app_context, None),
        demo_training_dialog(app_context, None),
        demo_degree_dialog(app_context, None),
        demo_course_dialog(app_context, None),
    ):
        qtbot.addWidget(dialog)
        assert dialog.windowTitle()


# --------------------------------------------------------------------------- the settings section


def test_the_course_editor_adds_deactivates_and_deletes_a_course(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _english(app_context)
    service = _service(app_context)
    section = PersonnelSettingsSection(app_context)
    qtbot.addWidget(section)
    assert section.courses_model.rowCount() == 0

    dialog = CourseDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.code_edit.setText("COURSE-1")
    dialog.label_pt_edit.setText("Curso demo")
    dialog.label_en_edit.setText("Demo course")
    dialog.accept()
    (course,) = service.list_courses()
    assert (course.code, course.active) == ("COURSE-1", True)
    assert _cells(section.courses_model, 0, 3) == ["COURSE-1", "Demo course", "Active"]

    section.courses_view.selectRow(0)
    assert section.deactivate_course_action.isEnabled()
    section.deactivate_course_action.trigger()
    assert service.list_courses() == []
    (inactive,) = service.list_courses(include_inactive=True)
    assert not inactive.active
    assert section.courses_model.index(0, 2).data() == "Inactive"
    assert not section.deactivate_course_action.isEnabled()

    section.courses_view.selectRow(0)
    section.delete_course_action.trigger()
    assert len(service.list_courses(include_inactive=True)) == 1
    fake_prompts.script("confirm", True)
    section.delete_course_action.trigger()
    assert service.list_courses(include_inactive=True) == []
    assert section.courses_model.rowCount() == 0


def test_the_course_editor_refuses_an_invalid_course(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _english(app_context)
    dialog = CourseDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.code_edit.setText("COURSE-1")
    dialog.accept()
    assert _warnings(fake_prompts) == ["The Portuguese (Brazil) label is required."]
    assert dialog.isVisible()
    assert _service(app_context).list_courses(include_inactive=True) == []


def _corrupt_setting(context: AppContext) -> None:
    """A stored setting that no longer validates (what a restored older backup can leave)."""
    assert context.conn is not None
    context.conn.execute(
        "INSERT INTO setting (key, value_json) VALUES (?, ?)",
        ("config.cert_warning_days", "not json"),
    )


def _repair_setting(context: AppContext) -> None:
    assert context.conn is not None
    context.conn.execute("DELETE FROM setting WHERE key = ?", ("config.cert_warning_days",))


def test_an_unreadable_setting_is_explained_and_the_inputs_wait_for_the_repair(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    section = PersonnelSettingsSection(app_context)
    qtbot.addWidget(section)
    inputs = (section.hierarchy_check, *section.months_edits.values())
    assert section.config_error_label.isHidden()
    assert all(widget.isEnabled() for widget in inputs)

    _corrupt_setting(app_context)
    app_context.notify_data_changed()  # a raising slot would fail the test

    assert not section.config_error_label.isHidden()
    assert section.config_error_label.text() == "A stored setting cannot be read."
    assert not any(widget.isEnabled() for widget in inputs)
    assert not any(box.isEnabled() for box in section.mapping_checks.values())
    assert not section.save_action.isEnabled()
    assert section.a02_badge.isHidden()
    assert section.a04_badge.isHidden()
    section.reload_rules()  # also safe to call directly
    assert fake_prompts.calls == []

    app_context.translator_manager.set_language("pt_BR")
    portuguese = "Uma configura\u00e7\u00e3o armazenada n\u00e3o pode ser lida."
    qtbot.waitUntil(lambda: section.config_error_label.text() == portuguese)

    _repair_setting(app_context)
    app_context.notify_data_changed()

    assert section.config_error_label.isHidden()
    assert all(widget.isEnabled() for widget in inputs)
    assert section.save_action.isEnabled()


@pytest.mark.parametrize("lang", LANGUAGES)
def test_the_unreadable_setting_message_is_translated_in_the_pseudo_locale(
    pseudo_context: AppContext, qtbot: QtBot, lang: str
) -> None:
    pseudo_context.translator_manager.set_language(lang)
    section = PersonnelSettingsSection(pseudo_context)
    qtbot.addWidget(section)
    _corrupt_setting(pseudo_context)
    pseudo_context.notify_data_changed()
    assert not section.config_error_label.isHidden()
    assert section.config_error_label.text() != "A stored setting cannot be read."
    assert_fully_translated(section, lang)


def test_the_section_builds_without_a_config_service(app_context: AppContext, qtbot: QtBot) -> None:
    vars(app_context.services)["config"] = None
    section = PersonnelSettingsSection(app_context)
    qtbot.addWidget(section)
    assert section.a02_badge.isHidden()
    assert section.a04_badge.isHidden()
    assert not section.save_action.isEnabled()
    assert not section.hierarchy_check.isEnabled()
    assert not section.months_edits["A"].isEnabled()


def test_the_section_saves_the_mapping_and_the_validity_months(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _english(app_context)
    fake = _attach_fake_config(app_context)
    section = PersonnelSettingsSection(app_context)
    qtbot.addWidget(section)
    section.show()
    assert section.save_action.isEnabled()
    assert section.hierarchy_check.isEnabled()
    assert len(section.mapping_checks) == 6

    section.hierarchy_check.setChecked(True)
    section.mapping_checks[("A", "B")].setChecked(True)
    section.mapping_checks[("A", "C")].setChecked(True)
    section.mapping_checks[("B", "C")].setChecked(True)
    section.months_edits["A"].setText("12")
    section.months_edits["C"].setText(" 24 ")
    section.save_action.trigger()
    saved = fake.config
    assert saved.ppe_hierarchy_enabled is True
    assert saved.ppe_hierarchy.get("A") == ("B", "C")
    assert saved.ppe_hierarchy.get("B") == ("C",)
    assert not saved.ppe_hierarchy.get("C")
    assert saved.ppe_validity_months.get("A") == 12
    assert saved.ppe_validity_months.get("B") is None
    assert saved.ppe_validity_months.get("C") == 24
    assert fake_prompts.calls_of("warning") == []

    # a refresh keeps unsaved edits (P2-05); reload_rules reads the stored values back
    section.months_edits["A"].setText("")
    section.mapping_checks[("A", "B")].setChecked(False)
    assert section.is_dirty()
    section.refresh()
    assert section.months_edits["A"].text() == ""
    section.reload_rules()
    assert not section.is_dirty()
    assert section.months_edits["A"].text() == "12"
    assert section.mapping_checks[("A", "B")].isChecked()
    assert section.months_edits["B"].text() == ""


def test_a_badly_typed_validity_is_refused_and_nothing_is_saved(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _english(app_context)
    fake = _attach_fake_config(app_context)
    section = PersonnelSettingsSection(app_context)
    qtbot.addWidget(section)
    section.months_edits["A"].setText("twelve")
    section.save_action.trigger()
    assert _warnings(fake_prompts) == ["The number is not valid."]
    assert fake.config == ReadinessConfig()


def test_the_placeholder_badges_show_until_confirmed(app_context: AppContext, qtbot: QtBot) -> None:
    _english(app_context)
    fake = _attach_fake_config(app_context)
    section = PersonnelSettingsSection(app_context)
    qtbot.addWidget(section)
    section.show()
    assert section.a02_badge.text() == "Placeholder - to be confirmed"
    assert section.a02_badge.isVisibleTo(section)
    assert section.a04_badge.isVisibleTo(section)
    assert section.confirm_a02_action.isEnabled()
    assert section.confirm_a02_action.text() == "Confirm"

    section.confirm_a04_action.trigger()
    assert fake.confirmed == ["A04"]
    assert section.a04_badge.isHidden()
    assert section.a02_badge.isVisibleTo(section)
    assert not section.confirm_a04_action.isEnabled()

    section.confirm_a02_action.trigger()
    assert fake.confirmed == ["A04", "A02"]
    assert section.a02_badge.isHidden()


# --------------------------------------------------------------- review fixes P2-03 .. P2-08


def _change_log_count(context: AppContext) -> int:
    conn = context.conn
    assert conn is not None
    return int(conn.execute("SELECT count(*) FROM change_log").fetchone()[0])


def test_the_certificate_dialog_stores_certificate_and_mark_in_one_transaction(
    app_context: AppContext, qtbot: QtBot
) -> None:
    sid = _add_staff(app_context)
    emitted: list[int] = []
    app_context.data_changed.connect(lambda *_args: emitted.append(1))
    dialog = CertificateDialog(app_context, None, sid)
    qtbot.addWidget(dialog)
    dialog.issued_edit.setDate(QDate(2026, 1, 1))
    dialog.valid_until_edit.setDate(QDate(2027, 1, 1))
    dialog.no_renewal_check.setChecked(True)
    dialog.no_renewal_edit.setDate(QDate(2026, 6, 1))
    before = _change_log_count(app_context)
    dialog.accept()
    (certificate,) = _service(app_context).list_certificates(sid)
    assert certificate.no_renewal_from == date(2026, 6, 1)
    assert emitted == [1]
    assert _change_log_count(app_context) - before == 1  # one insert row, no second update row


def test_a_refused_mark_leaves_no_certificate_and_ok_again_works(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _english(app_context)
    sid = _add_staff(app_context)
    emitted: list[int] = []
    app_context.data_changed.connect(lambda *_args: emitted.append(1))
    dialog = CertificateDialog(app_context, None, sid)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.issued_edit.setDate(QDate(2026, 1, 1))
    dialog.valid_until_edit.setDate(QDate(2027, 1, 1))
    dialog.no_renewal_check.setChecked(True)
    dialog.reason_combo.addItem("Retired", "retired")  # a reason the service refuses
    dialog.reason_combo.setCurrentIndex(dialog.reason_combo.findData("retired"))
    before = _change_log_count(app_context)

    dialog.accept()
    assert _warnings(fake_prompts) == ["The reason for no renewal is not valid."]
    assert dialog.isVisible()
    assert _service(app_context).list_certificates(sid) == []
    assert _change_log_count(app_context) == before
    assert emitted == []

    dialog.reason_combo.setCurrentIndex(dialog.reason_combo.findData("other"))
    dialog.accept()  # not DUPLICATE_CERTIFICATE: the first attempt stored nothing
    (certificate,) = _service(app_context).list_certificates(sid)
    assert certificate.no_renewal_reason == "other"
    assert emitted == [1]


def test_the_staff_dialog_corrects_and_clears_active_until(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _english(app_context)
    service = _service(app_context)
    sid = _add_staff(app_context, active_until=date(2025, 6, 30))

    dialog = StaffDialog(app_context, None, service.get_staff(sid))
    qtbot.addWidget(dialog)
    dialog.show()
    assert from_qdate(dialog.active_until_edit.date()) == date(2025, 6, 30)
    dialog.active_until_edit.setDate(QDate(2024, 12, 31))  # before active_from (2025-01-01)
    dialog.accept()
    assert _warnings(fake_prompts) == ["The end of the active period cannot be before its start."]
    assert service.get_staff(sid).active_until == date(2025, 6, 30)
    dialog.active_until_edit.setDate(QDate(2025, 7, 31))
    dialog.accept()
    assert service.get_staff(sid).active_until == date(2025, 7, 31)

    again = StaffDialog(app_context, None, service.get_staff(sid))
    qtbot.addWidget(again)
    again.active_until_edit.setDate(again.active_until_edit.minimumDate())  # "not set"
    again.accept()
    assert service.get_staff(sid).active_until is None

    fresh = StaffDialog(app_context)
    qtbot.addWidget(fresh)
    assert fresh.active_until_edit.date() == fresh.active_until_edit.minimumDate()
    assert fresh.active_until_edit.specialValueText() == "Not set"


def test_the_deactivate_prompt_survives_a_percent_two_in_the_identifier(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _english(app_context)
    app_context.set_as_of(AS_OF)
    _add_staff(app_context, "DEMO%2-001")
    page = _page(app_context, qtbot)
    page.staff_view.selectRow(0)
    page.deactivate_staff_action.trigger()
    (call,) = fake_prompts.calls_of("confirm")
    assert call.text == "Deactivate person DEMO%2-001 as of 03/05/2026?"


def test_fill_placeholders_substitutes_in_one_pass() -> None:
    assert fill_placeholders("%1 on %2", "X%2Y", "d") == "X%2Y on d"
    assert fill_placeholders("%2 before %1", "a", "b") == "b before a"
    assert fill_placeholders("%3 stays", "a") == "%3 stays"


def test_unsaved_rule_edits_survive_signals_from_the_course_list(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _english(app_context)
    fake = _attach_fake_config(app_context)
    section = PersonnelSettingsSection(app_context)
    qtbot.addWidget(section)
    section.show()
    section.months_edits["A"].setText("12")
    section.mapping_checks[("A", "B")].setChecked(True)
    assert section.is_dirty()

    dialog = CourseDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.code_edit.setText("COURSE-1")
    dialog.label_pt_edit.setText("Curso demo")
    dialog.accept()  # data_changed is emitted
    assert section.courses_model.rowCount() == 1
    assert section.months_edits["A"].text() == "12"
    assert section.mapping_checks[("A", "B")].isChecked()

    section.courses_view.selectRow(0)
    section.deactivate_course_action.trigger()  # another data_changed
    assert section.months_edits["A"].text() == "12"

    # without unsaved edits a change of the stored configuration is picked up again
    section.reload_rules()
    assert not section.is_dirty()
    fake.config = fake.config.with_changes(ppe_validity_months={"A": 6})
    app_context.notify_data_changed()
    assert section.months_edits["A"].text() == "6"


# --------------------------------------------------------------------------- pseudo-locale walk

FACTORIES: dict[str, Callable[[AppContext], QWidget]] = {
    "page": create_page,
    "settings_section": create_settings_section,
    "staff_dialog": lambda context: demo_staff_dialog(context, None),
    "certificate_dialog": lambda context: demo_certificate_dialog(context, None),
    "training_dialog": lambda context: demo_training_dialog(context, None),
    "degree_dialog": lambda context: demo_degree_dialog(context, None),
    "course_dialog": lambda context: demo_course_dialog(context, None),
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
    sid = _add_staff(pseudo_context, label="Demo person")
    _add_cert(pseudo_context, sid)
    course_id = _add_course(pseudo_context)
    _service(pseudo_context).add_training(sid, TrainingInput(course_id, date(2026, 3, 4), 8.0))
    _service(pseudo_context).add_degree(sid, DegreeInput("master", "completed", 2020, "Demo"))
    _attach_fake_config(pseudo_context)
    widget = FACTORIES[name](pseudo_context)
    qtbot.addWidget(widget)
    if isinstance(widget, PersonnelPage):
        widget.staff_view.selectRow(0)
        widget.certificates_view.selectRow(0)
    assert_fully_translated(widget)


def test_the_titles_are_translated(pseudo_context: AppContext) -> None:
    assert page_title() == "\u27e6Personnel\u27e7"
    assert settings_section_title() == "\u27e6Personnel rules and courses\u27e7"


# --------------------------------------------------------------------------- labels


def test_every_enum_value_and_error_code_has_a_label_in_all_languages(
    app_context: AppContext,
) -> None:
    labels: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        app_context.translator_manager.set_language(lang)
        table: dict[str, str] = {}
        for code in ALL_ERROR_CODES:
            table[f"error:{code}"] = error_label(code)
        for level in DegreeLevel:
            table[f"degree:{level.value}"] = degree_level_label(level.value)
        for status in DegreeStatus:
            table[f"degree_status:{status.value}"] = degree_status_label(status.value)
        for cert_status in CertStatus:
            table[f"cert:{cert_status.value}"] = cert_status_label(cert_status.value)
        for reason in NO_RENEWAL_REASONS:
            table[f"reason:{reason}"] = reason_label(reason)
        labels[lang] = table
    for lang in LANGUAGES:
        for key, text in labels[lang].items():
            assert text.strip(), (lang, key)
            assert text != key.split(":", 1)[1], (lang, key)
    for key, english in labels["en_US"].items():
        assert labels["pt_BR"][key] != english, key
        assert labels["es_ES"][key] != english, key
    assert len(labels["en_US"]) == (
        len(ALL_ERROR_CODES)
        + len(DegreeLevel)
        + len(DegreeStatus)
        + len(CertStatus)
        + len(NO_RENEWAL_REASONS)
    )


def test_ppe_level_letters_are_data_and_unchanged(app_context: AppContext) -> None:
    for lang in LANGUAGES:
        app_context.translator_manager.set_language(lang)
        for level in PpeLevel:
            assert ppe_level_label(level.value) == level.value


def test_the_reason_of_no_renewal_may_be_empty() -> None:
    assert reason_label(None) == ""
    assert reason_label("") == ""


def test_an_unknown_code_is_shown_as_itself() -> None:
    assert error_label("NOT_A_CODE") == "NOT_A_CODE"
    assert degree_level_label("NOT_A_LEVEL") == "NOT_A_LEVEL"
    assert cert_status_label("NOT_A_STATUS") == "NOT_A_STATUS"


def test_all_error_codes_lists_every_code_of_the_services() -> None:
    def constants(module: object) -> set[str]:
        return {
            name
            for name, value in vars(module).items()
            if name.isupper() and isinstance(value, str) and value == name
        }

    found = constants(personnel_module) | constants(errors_module)
    assert {"VALID_UNTIL_BEFORE_ISSUED", "READ_ONLY", "DUPLICATE_IDENTIFIER", "REQUIRED"} <= found
    assert found <= set(ALL_ERROR_CODES), sorted(found - set(ALL_ERROR_CODES))
    assert len(set(ALL_ERROR_CODES)) == len(ALL_ERROR_CODES)
