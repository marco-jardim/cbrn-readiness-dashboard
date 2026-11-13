# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the countries loader and of the exercises service (PLAN.md T4.4); fictitious data."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from datetime import date

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain import exercises as rules
from cbrn_dashboard.domain.exercises import Edition, EvaluationResult, ExerciseKind, Metric
from cbrn_dashboard.services.countries import (
    Country,
    cldr_version,
    country_codes,
    is_known_country,
    load_countries,
)
from cbrn_dashboard.services.errors import (
    CODE_IMMUTABLE,
    INVALID_CODE,
    INVALID_DATE,
    LABEL_PT_BR_REQUIRED,
    NOT_FOUND,
    READ_ONLY,
    REQUIRED,
    ServiceError,
    require,
    translate_storage_error,
)
from cbrn_dashboard.services.exercises import (
    DUPLICATE_CODE,
    END_BEFORE_START,
    INVALID_KIND,
    METRIC_IN_USE,
    METRIC_INACTIVE,
    NEGATIVE_PARTICIPANTS,
    NEGATIVE_RESPONDENTS,
    SCALE_MAX_BELOW_MIN,
    UNKNOWN_COUNTRY,
    VALUE_OUT_OF_SCALE,
    EditionInput,
    ExercisesService,
    MetricInput,
    MetricView,
    ResultInput,
    metric_label,
)
from cbrn_dashboard.storage import exercises_repo
from cbrn_dashboard.storage.db import DatabaseConnection, ReadOnlyDatabaseError
from cbrn_dashboard.storage.repository import RowNotFoundError
from tests.services.conftest import ChangeLogRows

AS_OF = date(2026, 3, 5)
NOW_TEXT = "2026-03-05T12:00:00Z"
OPERATOR = "op-demo"

_BASE_EDITION = EditionInput(
    code="DEMO-EX-01",
    kind="CBRAMED",
    start_on="2024-03-01",
    end_on="2024-03-05",
    title="Demo exercise",
    participants=40,
    countries=("BR", "AR", "PT"),
)
_BASE_METRIC = MetricInput(
    code="DEMO-M1",
    label_pt_br="Satisfação",
    label_en_us="Satisfaction",
    unit="pts",
    scale_min=0.0,
    scale_max=10.0,
)


@pytest.fixture
def service(db: DatabaseConnection, clock: FixedClock) -> ExercisesService:
    return ExercisesService(db, clock, lambda: OPERATOR)


def _error(call: Callable[[], object]) -> ServiceError:
    with pytest.raises(ServiceError) as info:
        call()
    return info.value


def _count(conn: DatabaseConnection, table: str) -> int:
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
    return int(row[0])


def _entities(rows: list[dict[str, object]]) -> Counter[tuple[object, object]]:
    return Counter((row["entity"], row["action"]) for row in rows)


# --------------------------------------------------------------------------- shared errors


def test_service_error_shows_only_code_and_field() -> None:
    error = ServiceError("REQUIRED", "code")
    assert error.code == "REQUIRED"
    assert error.field == "code"
    assert str(error) == "REQUIRED (field: code)"
    assert str(ServiceError("NOT_FOUND")) == "NOT_FOUND"


def test_require_and_translate_storage_error() -> None:
    require(True, "X")
    assert _error(lambda: require(False, "X", "f")).field == "f"
    assert translate_storage_error(ReadOnlyDatabaseError("x")).code == READ_ONLY
    assert translate_storage_error(RowNotFoundError("x")).code == NOT_FOUND
    with pytest.raises(ValueError, match="other"):
        translate_storage_error(ValueError("other"))


# --------------------------------------------------------------------------- countries


def test_countries_list_is_complete_and_cached() -> None:
    countries = load_countries()
    assert len(countries) == 249
    assert len(country_codes()) == 249
    assert load_countries() is countries
    assert cldr_version() != ""
    assert all(len(country.code) == 2 and country.code.isupper() for country in countries)


@pytest.mark.parametrize("code", ["BR", "AR", "PT"])
def test_known_countries(code: str) -> None:
    assert is_known_country(code)


@pytest.mark.parametrize("code", ["XK", "ZZ", "brx", "br", "", "B"])
def test_unknown_countries(code: str) -> None:
    assert not is_known_country(code)


def test_country_name_fallback() -> None:
    country = Country("QQ", {"pt_BR": "Nome", "en_US": "Name"})
    assert country.name("pt_BR") == "Nome"
    assert country.name("en-US") == "Name"
    assert country.name("es_ES") == "Nome"
    assert Country("QQ", {"en_US": "Name"}).name("es_ES") == "Name"
    assert Country("QQ", {}).name("es_ES") == "QQ"
    brazil = next(c for c in load_countries() if c.code == "BR")
    assert brazil.name("en_US") != ""


# --------------------------------------------------------------------------- change log


def test_create_edition_logs_edition_and_countries(
    service: ExercisesService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    edition_id = service.create_edition(_BASE_EDITION)
    rows = change_log_rows(db)
    assert len(rows) == 4
    assert _entities(rows) == Counter(
        {("exercise_edition", "insert"): 1, ("exercise_country", "insert"): 3}
    )
    assert rows[0]["entity_id"] == edition_id
    keys = {json.loads(str(row["entity_key"]))["country_code"] for row in rows[1:]}
    assert keys == {"BR", "AR", "PT"}
    assert all(row["operator"] == OPERATOR and row["at_utc"] == NOW_TEXT for row in rows)
    view = service.get_edition(edition_id)
    assert view.countries == ("AR", "BR", "PT")
    assert view.kind is ExerciseKind.CBRAMED
    assert view.start_on == date(2024, 3, 1)


def test_operator_label_is_read_for_each_write(
    db: DatabaseConnection, clock: FixedClock, change_log_rows: ChangeLogRows
) -> None:
    current = ["first"]
    service = ExercisesService(db, clock, lambda: current[0])
    service.create_metric(_BASE_METRIC)
    current[0] = "second"
    service.create_metric(replace(_BASE_METRIC, code="DEMO-M2"))
    assert [row["operator"] for row in change_log_rows(db)] == ["first", "second"]


def test_default_operator_is_empty(
    db: DatabaseConnection, clock: FixedClock, change_log_rows: ChangeLogRows
) -> None:
    ExercisesService(db, clock).create_metric(_BASE_METRIC)
    assert change_log_rows(db)[0]["operator"] == ""


def test_changing_countries_logs_only_the_differences(
    service: ExercisesService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    edition_id = service.create_edition(_BASE_EDITION)
    before = len(change_log_rows(db))
    service.update_edition(edition_id, replace(_BASE_EDITION, countries=("BR", "AR", "CL")))
    new_rows = change_log_rows(db)[before:]
    assert _entities(new_rows) == Counter(
        {("exercise_country", "insert"): 1, ("exercise_country", "delete"): 1}
    )
    assert {json.loads(str(r["entity_key"]))["country_code"] for r in new_rows} == {"PT", "CL"}
    assert service.get_edition(edition_id).countries == ("AR", "BR", "CL")


def test_update_without_changes_writes_nothing(
    service: ExercisesService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    edition_id = service.create_edition(_BASE_EDITION)
    before = len(change_log_rows(db))
    service.update_edition(edition_id, _BASE_EDITION)
    assert len(change_log_rows(db)) == before


def test_update_edition_fields_logs_one_update(
    service: ExercisesService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    edition_id = service.create_edition(_BASE_EDITION)
    before = len(change_log_rows(db))
    service.update_edition(edition_id, replace(_BASE_EDITION, participants=None, title="New"))
    new_rows = change_log_rows(db)[before:]
    assert _entities(new_rows) == Counter({("exercise_edition", "update"): 1})
    after = json.loads(str(new_rows[0]["after_json"]))
    assert after["participants"] is None
    assert after["title"] == "New"
    assert service.get_edition(edition_id).participants is None


def test_delete_edition_logs_edition_countries_and_results(
    service: ExercisesService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    edition_id = service.create_edition(_BASE_EDITION)
    m1 = service.create_metric(_BASE_METRIC)
    m2 = service.create_metric(replace(_BASE_METRIC, code="DEMO-M2"))
    service.set_result(edition_id, ResultInput(m1, 7.0))
    service.set_result(edition_id, ResultInput(m2, 8.0))
    before = len(change_log_rows(db))
    service.delete_edition(edition_id)
    new_rows = change_log_rows(db)[before:]
    assert _entities(new_rows) == Counter(
        {
            ("exercise_edition", "delete"): 1,
            ("exercise_country", "delete"): 3,
            ("evaluation_result", "delete"): 2,
        }
    )
    assert all(row["operator"] == OPERATOR and row["at_utc"] == NOW_TEXT for row in new_rows)
    assert _count(db, "exercise_edition") == 0
    assert _count(db, "exercise_country") == 0
    assert _count(db, "evaluation_result") == 0
    assert _count(db, "evaluation_metric") == 2


def test_result_and_metric_writes_are_logged(
    service: ExercisesService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    edition_id = service.create_edition(_BASE_EDITION)
    metric_id = service.create_metric(_BASE_METRIC)
    before = len(change_log_rows(db))
    service.set_result(edition_id, ResultInput(metric_id, 7.0, respondents=12))
    service.set_result(edition_id, ResultInput(metric_id, 8.0, respondents=12))
    service.set_result(edition_id, ResultInput(metric_id, 8.0, respondents=12))  # unchanged
    service.deactivate_metric(metric_id)
    service.delete_result(edition_id, metric_id)
    new_rows = change_log_rows(db)[before:]
    assert [(r["entity"], r["action"]) for r in new_rows] == [
        ("evaluation_result", "insert"),
        ("evaluation_result", "update"),
        ("evaluation_metric", "update"),
        ("evaluation_result", "delete"),
    ]
    assert json.loads(str(new_rows[0]["entity_key"])) == {
        "edition_id": edition_id,
        "metric_id": metric_id,
    }


# --------------------------------------------------------------------------- atomicity


@pytest.mark.parametrize("bad", ["XK", "ZZ", "brx"])
def test_unknown_country_is_rejected_and_nothing_is_written(
    service: ExercisesService, db: DatabaseConnection, change_log_rows: ChangeLogRows, bad: str
) -> None:
    error = _error(lambda: service.create_edition(replace(_BASE_EDITION, countries=("BR", bad))))
    assert (error.code, error.field) == (UNKNOWN_COUNTRY, "countries")
    assert _count(db, "exercise_edition") == 0
    assert _count(db, "exercise_country") == 0
    assert change_log_rows(db) == []


def test_unknown_country_on_update_changes_nothing(
    service: ExercisesService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    edition_id = service.create_edition(_BASE_EDITION)
    before = change_log_rows(db)
    error = _error(
        lambda: service.update_edition(
            edition_id, replace(_BASE_EDITION, title="Other", countries=("BR", "XK"))
        )
    )
    assert error.code == UNKNOWN_COUNTRY
    assert change_log_rows(db) == before
    assert service.get_edition(edition_id).title == "Demo exercise"
    assert service.get_edition(edition_id).countries == ("AR", "BR", "PT")


def test_out_of_scale_value_is_rejected_and_nothing_is_written(
    service: ExercisesService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    edition_id = service.create_edition(_BASE_EDITION)
    metric_id = service.create_metric(_BASE_METRIC)
    before = change_log_rows(db)
    for value in (-0.1, 10.1):
        error = _error(lambda v=value: service.set_result(edition_id, ResultInput(metric_id, v)))
        assert (error.code, error.field) == (VALUE_OUT_OF_SCALE, "value")
    assert _count(db, "evaluation_result") == 0
    assert change_log_rows(db) == before


@pytest.mark.parametrize("value", [0.0, 10.0, 5.5])
def test_scale_bounds_are_inclusive(service: ExercisesService, value: float) -> None:
    edition_id = service.create_edition(_BASE_EDITION)
    metric_id = service.create_metric(_BASE_METRIC)
    service.set_result(edition_id, ResultInput(metric_id, value))
    assert service.list_results(edition_id)[0].value == value


def test_open_scale_accepts_any_finite_value(service: ExercisesService) -> None:
    edition_id = service.create_edition(_BASE_EDITION)
    metric_id = service.create_metric(replace(_BASE_METRIC, scale_min=None, scale_max=None))
    service.set_result(edition_id, ResultInput(metric_id, -1000.0))
    error = _error(lambda: service.set_result(edition_id, ResultInput(metric_id, float("nan"))))
    assert error.code == "INVALID_NUMBER"


def test_failure_after_the_first_write_rolls_everything_back(
    service: ExercisesService,
    db: DatabaseConnection,
    change_log_rows: ChangeLogRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError

    monkeypatch.setattr(exercises_repo, "set_countries", boom)
    with pytest.raises(RuntimeError):
        service.create_edition(_BASE_EDITION)
    assert _count(db, "exercise_edition") == 0
    assert change_log_rows(db) == []


# --------------------------------------------------------------------------- edition rules


def test_countries_are_normalised_and_deduplicated(service: ExercisesService) -> None:
    data = replace(_BASE_EDITION, countries=("br", " Ar ", "BR", "pt"))
    edition_id = service.create_edition(data)
    assert service.get_edition(edition_id).countries == ("AR", "BR", "PT")


@pytest.mark.parametrize(
    ("changes", "code", "field"),
    [
        ({"code": ""}, REQUIRED, "code"),
        ({"code": "   "}, REQUIRED, "code"),
        ({"code": "-bad"}, INVALID_CODE, "code"),
        ({"code": "has space"}, INVALID_CODE, "code"),
        ({"code": "A" * 65}, INVALID_CODE, "code"),
        ({"kind": ""}, REQUIRED, "kind"),
        ({"kind": "OTHERX"}, INVALID_KIND, "kind"),
        ({"kind": "cbramed"}, INVALID_KIND, "kind"),
        ({"start_on": ""}, REQUIRED, "start_on"),
        ({"end_on": ""}, REQUIRED, "end_on"),
        ({"start_on": "2024-02-30"}, INVALID_DATE, "start_on"),
        ({"end_on": "05/03/2024"}, INVALID_DATE, "end_on"),
        ({"end_on": "2024-02-29"}, END_BEFORE_START, "end_on"),
        ({"participants": -1}, NEGATIVE_PARTICIPANTS, "participants"),
        ({"countries": ("BR", "")}, UNKNOWN_COUNTRY, "countries"),
    ],
)
def test_edition_validation_codes(
    service: ExercisesService,
    db: DatabaseConnection,
    changes: dict[str, object],
    code: str,
    field: str,
) -> None:
    error = _error(lambda: service.create_edition(replace(_BASE_EDITION, **changes)))
    assert (error.code, error.field) == (code, field)
    assert _count(db, "exercise_edition") == 0


def test_edition_boundaries_and_unknown_participants_accepted(service: ExercisesService) -> None:
    one_day = replace(_BASE_EDITION, end_on="2024-03-01", participants=0)
    assert service.get_edition(service.create_edition(one_day)).participants == 0
    unknown = replace(_BASE_EDITION, code="DEMO-EX-02", participants=None, countries=())
    view = service.get_edition(service.create_edition(unknown))
    assert view.participants is None
    assert view.countries == ()


def test_dates_may_be_given_as_date_objects(service: ExercisesService) -> None:
    data = replace(_BASE_EDITION, start_on=date(2024, 3, 1), end_on=date(2024, 3, 5))
    assert service.get_edition(service.create_edition(data)).end_on == date(2024, 3, 5)


def test_duplicate_edition_code(service: ExercisesService) -> None:
    first = service.create_edition(_BASE_EDITION)
    error = _error(lambda: service.create_edition(_BASE_EDITION))
    assert (error.code, error.field) == (DUPLICATE_CODE, "code")
    other = service.create_edition(replace(_BASE_EDITION, code="DEMO-EX-02"))
    assert _error(lambda: service.update_edition(other, _BASE_EDITION)).code == DUPLICATE_CODE
    service.update_edition(first, replace(_BASE_EDITION, title="same code is fine for itself"))


def test_edition_not_found(service: ExercisesService) -> None:
    assert _error(lambda: service.get_edition(99)).code == NOT_FOUND
    assert _error(lambda: service.update_edition(99, _BASE_EDITION)).code == NOT_FOUND
    assert _error(lambda: service.delete_edition(99)).code == NOT_FOUND
    assert _error(lambda: service.list_results(99)).code == NOT_FOUND


def test_list_editions_by_kind_in_history_order(service: ExercisesService) -> None:
    later = replace(_BASE_EDITION, code="B", start_on="2025-01-01", end_on="2025-01-02")
    service.create_edition(later)
    service.create_edition(replace(_BASE_EDITION, code="A"))
    service.create_edition(replace(_BASE_EDITION, code="C", kind="EXBRAMED"))
    assert [e.code for e in service.list_editions()] == ["A", "C", "B"]
    assert [e.code for e in service.list_editions(ExerciseKind.EXBRAMED)] == ["C"]
    assert [e.code for e in service.list_editions("CBRAMED")] == ["A", "B"]
    assert _error(lambda: service.list_editions("NOPE")).code == INVALID_KIND


# --------------------------------------------------------------------------- metrics


def test_metric_requires_pt_br_label_only(service: ExercisesService) -> None:
    for label in (None, "", "   "):
        data = replace(_BASE_METRIC, label_pt_br=label)
        error = _error(lambda d=data: service.create_metric(d))
        assert (error.code, error.field) == (LABEL_PT_BR_REQUIRED, "label_pt_br")
    metric_id = service.create_metric(
        MetricInput(code="DEMO-M9", label_pt_br="Só português", label_en_us="  ")
    )
    [view] = service.list_metrics()
    assert view.id == metric_id
    assert (view.label_en_us, view.label_es_es) == (None, None)
    assert (view.higher_is_better, view.active) == (True, True)


@pytest.mark.parametrize(
    ("changes", "code", "field"),
    [
        ({"code": ""}, REQUIRED, "code"),
        ({"code": "_x"}, INVALID_CODE, "code"),
        ({"scale_min": 5.0, "scale_max": 1.0}, SCALE_MAX_BELOW_MIN, "scale_max"),
    ],
)
def test_metric_validation_codes(
    service: ExercisesService,
    db: DatabaseConnection,
    changes: dict[str, object],
    code: str,
    field: str,
) -> None:
    error = _error(lambda: service.create_metric(replace(_BASE_METRIC, **changes)))
    assert (error.code, error.field) == (code, field)
    assert _count(db, "evaluation_metric") == 0


def test_metric_scale_with_equal_bounds_and_duplicate_code(service: ExercisesService) -> None:
    service.create_metric(replace(_BASE_METRIC, scale_min=3.0, scale_max=3.0))
    error = _error(lambda: service.create_metric(_BASE_METRIC))
    assert (error.code, error.field) == (DUPLICATE_CODE, "code")


def test_update_metric_and_unit_scale_direction(
    service: ExercisesService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    metric_id = service.create_metric(_BASE_METRIC)
    service.update_metric(
        metric_id,
        replace(
            _BASE_METRIC,
            label_es_es="Satisfacción",
            unit="%",
            scale_min=0.0,
            scale_max=100.0,
            higher_is_better=False,
        ),
    )
    [view] = service.list_metrics()
    assert (view.label_es_es, view.unit, view.scale_max, view.higher_is_better) == (
        "Satisfacción",
        "%",
        100.0,
        False,
    )
    assert change_log_rows(db)[-1]["action"] == "update"
    assert _error(lambda: service.update_metric(99, _BASE_METRIC)).code == NOT_FOUND


def test_metric_code_is_immutable_once_a_result_uses_it(service: ExercisesService) -> None:
    edition_id = service.create_edition(_BASE_EDITION)
    metric_id = service.create_metric(_BASE_METRIC)
    service.update_metric(metric_id, replace(_BASE_METRIC, code="DEMO-M1B"))  # unused: allowed
    service.set_result(edition_id, ResultInput(metric_id, 5.0))
    error = _error(lambda: service.update_metric(metric_id, replace(_BASE_METRIC, code="DEMO-M1C")))
    assert (error.code, error.field) == (CODE_IMMUTABLE, "code")
    service.update_metric(metric_id, replace(_BASE_METRIC, code="DEMO-M1B", label_pt_br="Novo"))
    assert service.list_metrics()[0].label_pt_br == "Novo"


def test_delete_metric_refused_while_results_use_it(
    service: ExercisesService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    edition_id = service.create_edition(_BASE_EDITION)
    metric_id = service.create_metric(_BASE_METRIC)
    service.set_result(edition_id, ResultInput(metric_id, 5.0))
    before = change_log_rows(db)
    error = _error(lambda: service.delete_metric(metric_id))
    assert (error.code, error.field) == (METRIC_IN_USE, "metric_id")
    assert change_log_rows(db) == before
    service.delete_result(edition_id, metric_id)
    service.delete_metric(metric_id)
    assert _count(db, "evaluation_metric") == 0
    assert change_log_rows(db)[-1]["action"] == "delete"
    assert _error(lambda: service.delete_metric(metric_id)).code == NOT_FOUND


def test_inactive_metric_keeps_results_but_takes_no_new_ones(service: ExercisesService) -> None:
    first = service.create_edition(_BASE_EDITION)
    second = service.create_edition(replace(_BASE_EDITION, code="DEMO-EX-02"))
    metric_id = service.create_metric(_BASE_METRIC)
    service.set_result(first, ResultInput(metric_id, 5.0))
    service.deactivate_metric(metric_id)
    assert service.list_metrics() == []
    assert [m.code for m in service.list_metrics(include_inactive=True)] == ["DEMO-M1"]
    error = _error(lambda: service.set_result(second, ResultInput(metric_id, 6.0)))
    assert (error.code, error.field) == (METRIC_INACTIVE, "metric_id")
    assert len(service.list_results(second)) == 0
    service.set_result(first, ResultInput(metric_id, 6.0))  # existing result may still be edited
    assert service.list_results(first)[0].value == 6.0
    service.update_metric(metric_id, _BASE_METRIC)  # active again
    service.set_result(second, ResultInput(metric_id, 6.0))
    assert len(service.list_results(second)) == 1


def test_metric_label_fallback() -> None:
    def view(pt: str | None, en: str | None, es: str | None) -> MetricView:
        return MetricView(1, "DEMO-M1", pt, en, es, None, None, None, True, True)

    full = view("Português", "English", "Español")
    assert metric_label(full, "es_ES") == "Español"
    assert metric_label(full, "en-US") == "English"
    assert metric_label(view("Português", None, " "), "es_ES") == "Português"
    assert metric_label(view(None, "English", None), "es_ES") == "English"
    assert metric_label(view(None, None, None), "pt_BR") == "DEMO-M1"
    assert metric_label(full, "fr_FR") == "Português"


# --------------------------------------------------------------------------- results


def test_result_rules(service: ExercisesService) -> None:
    edition_id = service.create_edition(_BASE_EDITION)
    metric_id = service.create_metric(_BASE_METRIC)
    negative = ResultInput(metric_id, 5.0, respondents=-1)
    error = _error(lambda: service.set_result(edition_id, negative))
    assert (error.code, error.field) == (NEGATIVE_RESPONDENTS, "respondents")
    assert _error(lambda: service.set_result(99, ResultInput(metric_id, 5.0))).code == NOT_FOUND
    assert _error(lambda: service.set_result(edition_id, ResultInput(99, 5.0))).code == NOT_FOUND
    assert _error(lambda: service.delete_result(edition_id, metric_id)).code == NOT_FOUND
    service.set_result(edition_id, ResultInput(metric_id, 5.0, respondents=0, note=" ok "))
    [result] = service.list_results(edition_id)
    assert (result.metric_code, result.respondents, result.note) == ("DEMO-M1", 0, "ok")
    assert service.get_edition(edition_id).results == (result,)


# --------------------------------------------------------------------------- as-of views


def _seed(service: ExercisesService) -> None:
    ids = {
        code: service.create_edition(data)
        for code, data in {
            "DEMO-EX-01": _BASE_EDITION,
            "DEMO-EX-02": replace(
                _BASE_EDITION,
                code="DEMO-EX-02",
                start_on="2025-05-10",
                end_on="2025-05-14",
                participants=55,
                countries=("BR", "AR", "CL", "UY"),
            ),
            "DEMO-EX-03": replace(
                _BASE_EDITION,
                code="DEMO-EX-03",
                kind="EXBRAMED",
                start_on="2025-09-01",
                end_on="2025-09-03",
                participants=None,
                countries=("BR",),
            ),
            "DEMO-EX-04": replace(
                _BASE_EDITION,
                code="DEMO-EX-04",
                start_on="2026-06-01",
                end_on="2026-06-05",
                countries=("PT",),
            ),
        }.items()
    }
    metric_id = service.create_metric(_BASE_METRIC)
    service.set_result(ids["DEMO-EX-01"], ResultInput(metric_id, 7.5, respondents=30))
    service.set_result(ids["DEMO-EX-02"], ResultInput(metric_id, 8.0))
    service.set_result(ids["DEMO-EX-03"], ResultInput(metric_id, 6.0, respondents=10))
    service.set_result(ids["DEMO-EX-04"], ResultInput(metric_id, 9.0))


_DOMAIN_EDITIONS = [
    Edition(
        "DEMO-EX-01",
        ExerciseKind.CBRAMED,
        date(2024, 3, 1),
        date(2024, 3, 5),
        40,
        frozenset({"BR", "AR", "PT"}),
    ),
    Edition(
        "DEMO-EX-02",
        ExerciseKind.CBRAMED,
        date(2025, 5, 10),
        date(2025, 5, 14),
        55,
        frozenset({"BR", "AR", "CL", "UY"}),
    ),
    Edition(
        "DEMO-EX-03",
        ExerciseKind.EXBRAMED,
        date(2025, 9, 1),
        date(2025, 9, 3),
        None,
        frozenset({"BR"}),
    ),
    Edition(
        "DEMO-EX-04",
        ExerciseKind.CBRAMED,
        date(2026, 6, 1),
        date(2026, 6, 5),
        40,
        frozenset({"PT"}),
    ),
]
_DOMAIN_METRICS = [Metric("DEMO-M1", "pts", 0.0, 10.0, True)]
_DOMAIN_RESULTS = [
    EvaluationResult("DEMO-EX-01", "DEMO-M1", 7.5, 30),
    EvaluationResult("DEMO-EX-02", "DEMO-M1", 8.0, None),
    EvaluationResult("DEMO-EX-03", "DEMO-M1", 6.0, 10),
    EvaluationResult("DEMO-EX-04", "DEMO-M1", 9.0, None),
]


def test_as_of_views_equal_the_domain_results(service: ExercisesService) -> None:
    _seed(service)
    assert service.history() == rules.history(_DOMAIN_EDITIONS)
    assert service.history(AS_OF) == rules.history(_DOMAIN_EDITIONS[:3])
    for kind in ExerciseKind:
        assert service.latest_edition(kind, AS_OF) == rules.latest_edition(
            _DOMAIN_EDITIONS, kind, AS_OF
        )
    assert service.latest_edition("CBRAMED", AS_OF) == _DOMAIN_EDITIONS[1]
    assert service.latest_edition(ExerciseKind.OTHER, AS_OF) is None
    assert service.evaluation_summary(AS_OF) == rules.evaluation_summary(
        _DOMAIN_EDITIONS, _DOMAIN_METRICS, _DOMAIN_RESULTS, AS_OF
    )
    assert service.indicator_values(AS_OF) == rules.indicator_values(_DOMAIN_EDITIONS, AS_OF)
    later = date(2026, 12, 31)
    assert service.indicator_values(later) == rules.indicator_values(_DOMAIN_EDITIONS, later)
    assert service.indicator_values(later) != service.indicator_values(AS_OF)


def test_data_quality_has_no_orphans(service: ExercisesService) -> None:
    assert service.data_quality(AS_OF) == []
    _seed(service)
    assert service.data_quality(AS_OF) == []


def test_empty_database_views(service: ExercisesService) -> None:
    assert service.history(AS_OF) == []
    assert service.latest_edition(ExerciseKind.CBRAMED, AS_OF) is None
    assert service.evaluation_summary(AS_OF) == []
    assert all(value.value is None for value in service.indicator_values(AS_OF))


# --------------------------------------------------------------------------- read-only


def test_read_only_connection_refuses_every_write_and_still_reads(
    service: ExercisesService,
    read_only_db: DatabaseConnection,
    db: DatabaseConnection,
    clock: FixedClock,
    change_log_rows: ChangeLogRows,
) -> None:
    _seed(service)
    read_only = ExercisesService(read_only_db, clock, lambda: OPERATOR)
    writes: list[Callable[[], object]] = [
        lambda: read_only.create_edition(_BASE_EDITION),
        lambda: read_only.update_edition(1, _BASE_EDITION),
        lambda: read_only.delete_edition(1),
        lambda: read_only.create_metric(_BASE_METRIC),
        lambda: read_only.update_metric(1, _BASE_METRIC),
        lambda: read_only.deactivate_metric(1),
        lambda: read_only.delete_metric(1),
        lambda: read_only.set_result(1, ResultInput(1, 1.0)),
        lambda: read_only.delete_result(1, 1),
    ]
    log_before = change_log_rows(db)
    for write in writes:
        assert _error(write).code == READ_ONLY
    assert change_log_rows(db) == log_before
    assert [e.code for e in read_only.list_editions()] == [e.code for e in service.list_editions()]
    assert read_only.get_edition(1).countries == ("AR", "BR", "PT")
    assert [m.code for m in read_only.list_metrics()] == ["DEMO-M1"]
    assert read_only.indicator_values(AS_OF) == service.indicator_values(AS_OF)
    assert read_only.history(AS_OF) == service.history(AS_OF)
