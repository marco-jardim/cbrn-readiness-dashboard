# SPDX-License-Identifier: GPL-3.0-or-later
"""The Exercises page, its dialogs, the metric editor and the labels (PLAN.md T4.5)."""

import itertools
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QAbstractItemModel, QCollator, QCoreApplication, QDate, QLocale, Qt
from PySide6.QtWidgets import QDialog, QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard.domain.exercises import ExerciseKind
from cbrn_dashboard.services import errors as errors_module
from cbrn_dashboard.services import exercises as exercises_module
from cbrn_dashboard.services.countries import load_countries
from cbrn_dashboard.services.exercises import (
    EditionInput,
    ExercisesService,
    MetricInput,
    ResultInput,
)
from cbrn_dashboard.ui.exercises.dialogs import (
    CountryPicker,
    EditionDialog,
    MetricDialog,
    ResultDialog,
)
from cbrn_dashboard.ui.exercises.labels import ALL_ERROR_CODES, error_label, kind_label
from cbrn_dashboard.ui.exercises.page import (
    ExercisesPage,
    MetricsSettingsSection,
    create_page,
    create_settings_section,
    demo_edition_dialog,
    demo_metric_dialog,
    demo_result_dialog,
    page_title,
    settings_section_title,
)
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from tests.ui._fakes import FakePrompts
from tests.ui._walk import assert_fully_translated

pytestmark = pytest.mark.ui

LANGUAGES = ("pt_BR", "en_US", "es_ES")
START_DATE = date(2026, 3, 5)


# --------------------------------------------------------------------------- helpers


def _service(context: AppContext) -> ExercisesService:
    service = context.services.exercises
    assert service is not None
    return service


def _add_edition(
    context: AppContext,
    code: str = "CB-2026",
    kind: str = "CBRAMED",
    countries: tuple[str, ...] = ("BR", "DE"),
) -> int:
    return _service(context).create_edition(
        EditionInput(
            code=code,
            kind=kind,
            start_on=START_DATE,
            end_on=date(2026, 3, 9),
            title="First exercise",
            participants=40,
            countries=countries,
        )
    )


def _add_metric(context: AppContext, code: str = "SAT") -> int:
    return _service(context).create_metric(
        MetricInput(
            code=code,
            label_pt_br="Satisfacao",
            label_en_us="Satisfaction",
            label_es_es="Satisfaccion",
            scale_min=0.0,
            scale_max=5.0,
        )
    )


def _cells(model: QAbstractItemModel, row: int, columns: int) -> list[object]:
    return [model.index(row, column).data() for column in range(columns)]


def _open_dialog[D: QDialog](page: QWidget, kind: type[D]) -> D:
    shown = [dialog for dialog in page.findChildren(kind) if dialog.isVisible()]
    assert len(shown) == 1
    return shown[0]


def _warnings(prompts: FakePrompts) -> list[str]:
    return [call.text for call in prompts.calls_of("warning")]


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


def test_adding_an_edition_and_a_result_through_the_dialogs(
    app_context: AppContext, qtbot: QtBot
) -> None:
    service = _service(app_context)
    _add_metric(app_context)
    page = ExercisesPage(app_context)
    qtbot.addWidget(page)

    dialog = EditionDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.code_edit.setText("CB-2026")
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("CBRAMED"))
    dialog.title_edit.setText("First exercise")
    dialog.start_edit.setDate(QDate(2026, 3, 2))
    dialog.end_edit.setDate(QDate(2026, 3, 6))
    dialog.participants_edit.setValue(40)
    dialog.picker.set_selected(["BR", "AR"])
    dialog.accept()

    stored = service.list_editions()
    assert [edition.code for edition in stored] == ["CB-2026"]
    assert stored[0].countries == ("AR", "BR")
    assert stored[0].participants == 40
    assert page.editions_model.rowCount() == 1
    assert _cells(page.editions_model, 0, 7) == [
        "CB-2026",
        "CBRAMED",
        "First exercise",
        "03/02/2026",
        "03/06/2026",
        "40",
        "2",
    ]

    page.editions_view.selectRow(0)
    result_dialog = ResultDialog(app_context, None, stored[0].id)
    qtbot.addWidget(result_dialog)
    assert result_dialog.metric_combo.count() == 1
    assert result_dialog.metric_combo.itemText(0) == "Satisfaction"
    result_dialog.value_edit.setText("4.5")
    result_dialog.respondents_edit.setValue(12)
    result_dialog.accept()

    results = service.list_results(stored[0].id)
    assert [(r.metric_code, r.value, r.respondents) for r in results] == [("SAT", 4.5, 12)]
    assert page.results_model.rowCount() == 1
    assert _cells(page.results_model, 0, 4) == ["Satisfaction", "4.5", "12", "0 - 5"]


def test_editing_an_edition_and_a_result_through_the_dialogs(
    app_context: AppContext, qtbot: QtBot
) -> None:
    service = _service(app_context)
    edition_id = _add_edition(app_context)
    metric_id = _add_metric(app_context)
    service.set_result(edition_id, ResultInput(metric_id, 4.5, 12))
    edition = service.get_edition(edition_id)

    dialog = EditionDialog(app_context, None, edition)
    qtbot.addWidget(dialog)
    assert dialog.code_edit.text() == "CB-2026"
    assert dialog.picker.selected_codes() == ("BR", "DE")
    dialog.title_edit.setText("Renamed")
    dialog.accept()
    updated = service.get_edition(edition_id)
    assert updated.title == "Renamed"
    assert updated.countries == ("BR", "DE")

    result_dialog = ResultDialog(app_context, None, edition_id, edition.results[0])
    qtbot.addWidget(result_dialog)
    assert result_dialog.value_edit.text() == "4.5"
    assert not result_dialog.metric_combo.isEnabled()
    result_dialog.value_edit.setText("3")
    result_dialog.accept()
    assert service.list_results(edition_id)[0].value == 3.0


def test_the_page_opens_its_dialogs_without_blocking(app_context: AppContext, qtbot: QtBot) -> None:
    edition_id = _add_edition(app_context)
    page = ExercisesPage(app_context)
    qtbot.addWidget(page)
    page.editions_view.selectRow(0)
    page.edit_edition()
    dialog = _open_dialog(page, EditionDialog)
    assert dialog.code_edit.text() == "CB-2026"
    dialog.title_edit.setText("Changed by the dialog")
    dialog.accept()
    assert _service(app_context).get_edition(edition_id).title == "Changed by the dialog"
    assert page.editions_model.rows()[0].title == "Changed by the dialog"


# --------------------------------------------------------------------------- country picker


@pytest.mark.parametrize(
    ("lang", "name"), [("pt_BR", "Alemanha"), ("en_US", "Germany"), ("es_ES", "Alemania")]
)
def test_the_country_picker_shows_localized_names(
    app_context: AppContext, qtbot: QtBot, lang: str, name: str
) -> None:
    app_context.translator_manager.set_language(lang)
    picker = CountryPicker(app_context)
    qtbot.addWidget(picker)
    item = picker.item_for("DE")
    assert item is not None
    assert item.text() == name
    assert item.data(Qt.ItemDataRole.UserRole) == "DE"
    assert len(picker.all_names()) == len(load_countries())


@pytest.mark.parametrize("lang", LANGUAGES)
def test_the_country_picker_is_sorted_in_the_current_language(
    app_context: AppContext, qtbot: QtBot, lang: str
) -> None:
    app_context.translator_manager.set_language(lang)
    picker = CountryPicker(app_context)
    qtbot.addWidget(picker)
    names = picker.all_names()
    collator = QCollator(QLocale(lang))
    collator.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    for first, second in itertools.pairwise(names):
        assert collator.compare(first, second) <= 0, (first, second)
    germany, brazil = picker.item_for("DE"), picker.item_for("BR")
    assert germany is not None
    assert brazil is not None
    before = names.index(germany.text()) < names.index(brazil.text())
    # Alemanha/Alemania come before Brasil, but Brazil comes before Germany.
    assert before is (lang != "en_US")


def test_the_country_picker_follows_a_language_switch(
    app_context: AppContext, qtbot: QtBot
) -> None:
    picker = CountryPicker(app_context)
    qtbot.addWidget(picker)
    picker.set_selected(["DE"])
    app_context.translator_manager.set_language("pt_BR")
    item = picker.item_for("DE")
    assert item is not None
    assert item.text() == "Alemanha"
    assert item.checkState() == Qt.CheckState.Checked
    assert picker.selected_codes() == ("DE",)
    assert picker.counter.text() == "1 país selecionado"


def test_the_country_picker_filters_and_keeps_the_selection(
    app_context: AppContext, qtbot: QtBot
) -> None:
    picker = CountryPicker(app_context)
    qtbot.addWidget(picker)
    germany, brazil = picker.item_for("DE"), picker.item_for("BR")
    assert germany is not None
    assert brazil is not None
    assert picker.counter.text() == "0 countries selected"

    germany.setCheckState(Qt.CheckState.Checked)
    picker.filter_edit.setText("brazi")  # "braz" would also match "Congo - Brazzaville"
    assert picker.visible_names() == [brazil.text()]
    assert germany.isHidden()
    brazil.setCheckState(Qt.CheckState.Checked)
    assert picker.counter.text() == "2 countries selected"

    picker.filter_edit.setText("GERM")
    assert picker.visible_names() == [germany.text()]
    picker.filter_edit.setText("")
    assert len(picker.visible_names()) == len(load_countries())
    assert picker.selected_codes() == ("BR", "DE")


# --------------------------------------------------------------------------- validation errors


def test_end_before_start_shows_the_translated_error_and_writes_nothing(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    dialog = EditionDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.code_edit.setText("X-1")
    dialog.start_edit.setDate(QDate(2026, 3, 9))
    dialog.end_edit.setDate(QDate(2026, 3, 2))
    dialog.accept()
    assert _warnings(fake_prompts) == ["The end date cannot be before the start date."]
    assert fake_prompts.calls_of("warning")[0].title == "Cannot save"
    assert dialog.isVisible()
    assert _service(app_context).list_editions() == []


def test_a_validation_error_is_shown_in_the_current_language(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    app_context.translator_manager.set_language("pt_BR")
    dialog = EditionDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.code_edit.setText("X-1")
    dialog.start_edit.setDate(QDate(2026, 3, 9))
    dialog.end_edit.setDate(QDate(2026, 3, 2))
    dialog.accept()
    (text,) = _warnings(fake_prompts)
    assert text == error_label("END_BEFORE_START")
    assert text != "The end date cannot be before the start date."


def test_a_duplicate_code_is_refused_and_nothing_is_written(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _add_edition(app_context)
    dialog = EditionDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.code_edit.setText("CB-2026")
    dialog.accept()
    assert _warnings(fake_prompts) == ["This code is already in use."]
    assert dialog.isVisible()
    assert len(_service(app_context).list_editions()) == 1


def test_a_value_out_of_scale_is_refused_and_nothing_is_written(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    edition_id = _add_edition(app_context)
    _add_metric(app_context)
    dialog = ResultDialog(app_context, None, edition_id)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.value_edit.setText("9")
    dialog.accept()
    assert _warnings(fake_prompts) == ["The value is outside the scale of the metric."]
    assert dialog.isVisible()
    assert _service(app_context).list_results(edition_id) == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("abc", "The number is not valid."),
        ("", "A required field is empty."),
        ("4,5", "The number uses the separators of another language."),
    ],
)
def test_a_badly_typed_number_is_refused(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot, text: str, message: str
) -> None:
    edition_id = _add_edition(app_context)
    _add_metric(app_context)
    dialog = ResultDialog(app_context, None, edition_id)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.value_edit.setText(text)
    dialog.accept()
    assert _warnings(fake_prompts) == [message]
    assert dialog.isVisible()


# --------------------------------------------------------------------------- the editions table


def test_dates_follow_the_language_and_reformat_on_a_switch(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _add_edition(app_context)
    page = ExercisesPage(app_context)
    qtbot.addWidget(page)
    model = page.editions_model
    horizontal = Qt.Orientation.Horizontal
    assert model.index(0, 3).data() == "03/05/2026"
    assert model.headerData(0, horizontal) == "Code"
    assert page.add_action.text() == "Add edition"
    expected_dates = (("pt_BR", "05/03/2026"), ("es_ES", "05/03/2026"), ("en_US", "03/05/2026"))
    for lang, expected in expected_dates:
        app_context.translator_manager.set_language(lang)
        assert model.index(0, 3).data() == expected
        assert model.index(0, 0).data() == "CB-2026"
        assert model.headerData(0, horizontal) == QCoreApplication.translate("Exercises", "Code")
    app_context.translator_manager.set_language("pt_BR")
    assert model.headerData(0, horizontal) != "Code"
    assert page.add_action.text() != "Add edition"
    assert page.add_action.text() == QCoreApplication.translate("Exercises", "Add edition")


def test_the_kind_filter_limits_the_editions(app_context: AppContext, qtbot: QtBot) -> None:
    _add_edition(app_context, "CB-2026", "CBRAMED")
    _add_edition(app_context, "EX-2026", "EXBRAMED")
    page = ExercisesPage(app_context)
    qtbot.addWidget(page)
    assert page.editions_model.rowCount() == 2
    assert page.kind_combo.count() == 1 + len(ExerciseKind)
    page.kind_combo.setCurrentIndex(page.kind_combo.findData("EXBRAMED"))
    assert [row.code for row in page.editions_model.rows()] == ["EX-2026"]
    page.kind_combo.setCurrentIndex(page.kind_combo.findData("OTHER"))
    assert page.editions_model.rowCount() == 0
    page.kind_combo.setCurrentIndex(0)
    assert page.editions_model.rowCount() == 2


def test_the_results_table_shows_the_selected_edition(
    app_context: AppContext, qtbot: QtBot
) -> None:
    service = _service(app_context)
    first = _add_edition(app_context, "CB-2026")
    _add_edition(app_context, "EX-2026", "EXBRAMED")
    metric_id = _add_metric(app_context)
    service.set_result(first, ResultInput(metric_id, 4.0))
    page = ExercisesPage(app_context)
    qtbot.addWidget(page)
    assert page.results_model.rowCount() == 0
    assert not page.add_result_action.isEnabled()
    page.editions_view.selectRow(0)
    assert page.results_model.rowCount() == 1
    assert page.add_result_action.isEnabled()
    assert not page.edit_result_action.isEnabled()
    page.results_view.selectRow(0)
    assert page.edit_result_action.isEnabled()
    assert page.selected_result() is not None
    page.editions_view.selectRow(1)
    assert page.results_model.rowCount() == 0


# --------------------------------------------------------------------------- delete


def test_deleting_an_edition_asks_for_confirmation(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _add_edition(app_context)
    page = ExercisesPage(app_context)
    qtbot.addWidget(page)
    page.editions_view.selectRow(0)
    assert page.delete_action.isEnabled()

    fake_prompts.script("confirm", False)
    page.delete_action.trigger()
    (call,) = fake_prompts.calls_of("confirm")
    assert "CB-2026" in call.text
    assert call.title == "Delete edition"
    assert len(_service(app_context).list_editions()) == 1
    assert page.editions_model.rowCount() == 1

    fake_prompts.script("confirm", True)
    page.delete_action.trigger()
    assert _service(app_context).list_editions() == []
    assert page.editions_model.rowCount() == 0


def test_deleting_a_result_asks_for_confirmation(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    service = _service(app_context)
    edition_id = _add_edition(app_context)
    service.set_result(edition_id, ResultInput(_add_metric(app_context), 4.0))
    page = ExercisesPage(app_context)
    qtbot.addWidget(page)
    page.editions_view.selectRow(0)
    page.results_view.selectRow(0)
    page.delete_result_action.trigger()
    assert len(service.list_results(edition_id)) == 1
    fake_prompts.script("confirm", True)
    page.delete_result_action.trigger()
    assert service.list_results(edition_id) == []
    assert page.results_model.rowCount() == 0


# --------------------------------------------------------------------------- read-only, no service


def test_read_only_mode_disables_every_edit_action(app_context: AppContext, qtbot: QtBot) -> None:
    _add_edition(app_context)
    _add_metric(app_context)
    app_context.read_only = True
    page = ExercisesPage(app_context)
    qtbot.addWidget(page)
    section = MetricsSettingsSection(app_context)
    qtbot.addWidget(section)
    page.editions_view.selectRow(0)
    section.view.selectRow(0)
    actions = [*page._actions, *section._actions]
    assert len(actions) == 10
    targets = app_context.edit_targets()
    for action in actions:
        assert action in targets
        assert not action.isEnabled()


def test_the_page_builds_without_an_exercises_service(
    app_context: AppContext, qtbot: QtBot
) -> None:
    app_context.services.exercises = None
    page = ExercisesPage(app_context)
    qtbot.addWidget(page)
    section = MetricsSettingsSection(app_context)
    qtbot.addWidget(section)
    assert page.editions_model.rowCount() == 0
    assert page.results_model.rowCount() == 0
    assert section.model.rowCount() == 0
    assert not page.add_action.isEnabled()
    for dialog in (
        demo_edition_dialog(app_context, None),
        demo_result_dialog(app_context, None),
        demo_metric_dialog(app_context, None),
    ):
        qtbot.addWidget(dialog)
        assert dialog.windowTitle()


# --------------------------------------------------------------------------- the metric editor


def test_the_metric_editor_adds_and_deactivates_a_metric(
    app_context: AppContext, qtbot: QtBot
) -> None:
    service = _service(app_context)
    section = MetricsSettingsSection(app_context)
    qtbot.addWidget(section)
    assert section.model.rowCount() == 0

    dialog = MetricDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.code_edit.setText("SAT")
    dialog.label_pt_edit.setText("Satisfacao")
    dialog.label_en_edit.setText("Satisfaction")
    dialog.unit_edit.setText("points")
    dialog.scale_min_edit.setText("0")
    dialog.scale_max_edit.setText("5.5")
    dialog.accept()

    (metric,) = service.list_metrics()
    assert (metric.code, metric.scale_min, metric.scale_max) == ("SAT", 0.0, 5.5)
    assert metric.active
    assert section.model.rowCount() == 1
    assert _cells(section.model, 0, 6) == [
        "SAT",
        "Satisfaction",
        "points",
        "0 - 5.5 points",
        "Higher is better",
        "Active",
    ]

    section.view.selectRow(0)
    assert section.deactivate_action.isEnabled()
    section.deactivate_metric()
    assert service.list_metrics() == []
    (inactive,) = service.list_metrics(include_inactive=True)
    assert not inactive.active
    assert section.model.rowCount() == 1
    assert section.model.index(0, 5).data() == "Inactive"
    assert not section.deactivate_action.isEnabled()


def test_the_metric_editor_refuses_an_invalid_metric(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    dialog = MetricDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.code_edit.setText("SAT")
    dialog.accept()
    assert _warnings(fake_prompts) == ["The Portuguese (Brazil) label is required."]
    dialog.label_pt_edit.setText("Satisfacao")
    dialog.scale_min_edit.setText("5")
    dialog.scale_max_edit.setText("1")
    dialog.accept()
    assert _warnings(fake_prompts)[-1] == "The maximum of the scale cannot be below the minimum."
    assert dialog.isVisible()
    assert _service(app_context).list_metrics(include_inactive=True) == []


def test_the_metric_editor_deletes_an_unused_metric(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _add_metric(app_context)
    section = MetricsSettingsSection(app_context)
    qtbot.addWidget(section)
    section.view.selectRow(0)
    section.delete_action.trigger()
    assert len(_service(app_context).list_metrics()) == 1
    fake_prompts.script("confirm", True)
    section.delete_action.trigger()
    assert _service(app_context).list_metrics(include_inactive=True) == []
    assert section.model.rowCount() == 0


# --------------------------------------------------------------------------- pseudo-locale walk

FACTORIES: dict[str, Callable[[AppContext], QWidget]] = {
    "page": create_page,
    "settings_section": create_settings_section,
    "edition_dialog": lambda context: demo_edition_dialog(context, None),
    "result_dialog": lambda context: demo_result_dialog(context, None),
    "metric_dialog": lambda context: demo_metric_dialog(context, None),
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
    service = _service(pseudo_context)
    edition_id = _add_edition(pseudo_context)
    service.set_result(edition_id, ResultInput(_add_metric(pseudo_context), 4.0, 3))
    widget = FACTORIES[name](pseudo_context)
    qtbot.addWidget(widget)
    if isinstance(widget, ExercisesPage):
        widget.editions_view.selectRow(0)
    assert_fully_translated(widget)


def test_the_titles_are_translated(pseudo_context: AppContext) -> None:
    assert page_title() == "\u27e6Exercises\u27e7"
    assert settings_section_title() == "\u27e6Evaluation metrics\u27e7"


# --------------------------------------------------------------------------- labels


def test_every_kind_and_error_code_has_a_label_in_all_languages(app_context: AppContext) -> None:
    errors: dict[str, dict[str, str]] = {}
    kinds: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        app_context.translator_manager.set_language(lang)
        errors[lang] = {code: error_label(code) for code in ALL_ERROR_CODES}
        kinds[lang] = {kind.value: kind_label(kind.value) for kind in ExerciseKind}
    for lang in LANGUAGES:
        for code, text in errors[lang].items():
            assert text.strip(), (lang, code)
            assert text != code, (lang, code)
        assert all(text.strip() for text in kinds[lang].values())
    for code, english in errors["en_US"].items():
        assert errors["pt_BR"][code] != english, code
        assert errors["es_ES"][code] != english, code
    for lang in LANGUAGES:
        assert kinds[lang]["CBRAMED"] == "CBRAMED"
        assert kinds[lang]["EXBRAMED"] == "EXBRAMED"
    assert kinds["en_US"]["OTHER"] == "Other"
    assert kinds["pt_BR"]["OTHER"] != "Other"
    assert kinds["es_ES"]["OTHER"] != "Other"


def test_an_unknown_code_is_shown_as_itself() -> None:
    assert error_label("NOT_A_CODE") == "NOT_A_CODE"
    assert kind_label("NOT_A_KIND") == "NOT_A_KIND"


def test_all_error_codes_lists_every_code_of_the_services() -> None:
    def constants(module: object) -> set[str]:
        return {
            name
            for name, value in vars(module).items()
            if name.isupper() and isinstance(value, str) and value == name
        }

    found = constants(exercises_module) | constants(errors_module)
    assert {"DUPLICATE_CODE", "READ_ONLY", "VALUE_OUT_OF_SCALE", "REQUIRED"} <= found
    assert found <= set(ALL_ERROR_CODES), sorted(found - set(ALL_ERROR_CODES))
    assert len(set(ALL_ERROR_CODES)) == len(ALL_ERROR_CODES)
