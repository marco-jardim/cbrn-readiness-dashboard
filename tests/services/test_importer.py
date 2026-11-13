# SPDX-License-Identifier: GPL-3.0-or-later
"""CSV import (T8.4): templates, the lenient reader, validation, all-or-nothing, the dry run.

All data is fictitious (``tests/fixtures/csv``, ``DEMO-...`` values) and written through the four
module services into a migrated database by the importer.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import NoReturn

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain.dates import format_utc_timestamp
from cbrn_dashboard.services import importer as importer_module
from cbrn_dashboard.services.budget import BudgetService
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.services.exercises import ExercisesService
from cbrn_dashboard.services.export import UNKNOWN_ENTITY, ExportService
from cbrn_dashboard.services.importer import _IMPORTERS, ImportReport, ImportService
from cbrn_dashboard.services.importer import ImportError as ImportIssue
from cbrn_dashboard.services.infrastructure import InfrastructureService
from cbrn_dashboard.services.personnel import PersonnelService
from cbrn_dashboard.storage import (
    budget_repo,
    exercises_repo,
    infrastructure_repo,
    personnel_repo,
)
from cbrn_dashboard.storage.csv_io import (
    ENTITIES,
    CellError,
    EntitySpec,
    ImportFile,
    entity_spec,
    read_entity,
    read_import_file,
    template_file_name,
)
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.repository import ConstraintViolationError
from tests.services.conftest import ChangeLogRows

OPERATOR = "demo.operator"
BOM = b"\xef\xbb\xbf"

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "csv"
DOCS = Path(__file__).resolve().parents[2] / "docs" / "import-templates.md"

#: Rows per fixture file.
EXPECTED_ROWS: dict[str, int] = {
    "training_course": 3,
    "asset_type": 2,
    "evaluation_metric": 2,
    "funding_source": 1,
    "staff_member": 3,
    "ppe_certification": 3,
    "training_record": 3,
    "academic_degree": 3,
    "asset": 3,
    "asset_status_event": 6,
    "maintenance_event": 3,
    "exercise_edition": 2,
    "exercise_country": 5,
    "evaluation_result": 3,
    "budget_entry": 4,
    "budget_execution": 4,
}

#: Entities whose table also holds built-in rows that the fixtures do not contain.
WITH_BUILT_INS = ("asset_type", "funding_source")

#: Tables with an integer ``id`` (the others are keyed by a natural key in ``change_log``).
ID_TABLES = tuple(
    name for name in EXPECTED_ROWS if name not in ("exercise_country", "evaluation_result")
)

STAFF_HEADER = "identifier;label;category;active_from;active_until"
EXPECTED_STAFF = {
    ("DEMO-00123", "DEMO label", "DEMO-cat", "2020-01-15", None),
    ("DEMO-00124", None, None, "2021-02-01", "2025-12-31"),
    ("DEMO-00125", None, "DEMO-cat", "2022-03-01", None),
}

SECRETS = ("DEMO-00123", "DEMO-00124", "DEMO-00125", "DEMO label", "DEMO-REF-1", "DEMO field")


# --------------------------------------------------------------------------- helpers


def _build(conn: DatabaseConnection, clock: FixedClock) -> ImportService:
    def operator() -> str:
        return OPERATOR

    return ImportService(
        conn,
        clock,
        operator,
        personnel=PersonnelService(conn, clock, operator),
        infrastructure=InfrastructureService(conn, clock, operator),
        exercises=ExercisesService(conn, clock, operator),
        budget=BudgetService(conn, clock, operator),
    )


@pytest.fixture
def importer(db: DatabaseConnection, clock: FixedClock) -> ImportService:
    return _build(db, clock)


def _spec(name: str) -> EntitySpec:
    spec = entity_spec(name)
    assert spec is not None
    return spec


def _fixture(name: str) -> Path:
    return FIXTURES / f"{name}.csv"


def _write(folder: Path, name: str, text: str, *, bom: bool = False) -> Path:
    path = folder / name
    data = text.encode("utf-8")
    path.write_bytes(BOM + data if bom else data)
    return path


def _count(conn: DatabaseConnection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _counts(conn: DatabaseConnection) -> dict[str, int]:
    return {table: _count(conn, table) for table in (*EXPECTED_ROWS, "change_log")}


def _import_all(importer: ImportService) -> dict[str, ImportReport]:
    return {name: importer.import_file(name, _fixture(name)) for name in importer.entity_names()}


def _staff(conn: DatabaseConnection) -> set[tuple[object, ...]]:
    return {
        (r.identifier, r.label, r.category, r.active_from, r.active_until)
        for r in personnel_repo.list_staff(conn)
    }


def _issue(line: int, column: str, code: str) -> ImportIssue:
    return ImportIssue(line, column, code)


def _read(folder: Path, spec_name: str, text: str, *, bom: bool = False) -> ImportFile:
    return read_import_file(_write(folder, "x.csv", text, bom=bom), _spec(spec_name))


# --------------------------------------------------------------------------- the whole set


def test_every_entity_has_an_importer() -> None:
    assert set(_IMPORTERS) == {spec.name for spec in ENTITIES}
    assert tuple(_IMPORTERS) == tuple(spec.name for spec in ENTITIES)


def test_fixture_set_imports_in_order_with_the_expected_counts(
    importer: ImportService, db: DatabaseConnection
) -> None:
    assert importer.entity_names() == tuple(EXPECTED_ROWS)
    before = _counts(db)
    reports = _import_all(importer)
    after = _counts(db)
    for name, expected in EXPECTED_ROWS.items():
        report = reports[name]
        assert report.errors == (), (name, report.errors)
        assert report.ok
        assert report.entity == name
        assert report.total_rows == report.imported == expected
        assert after[name] - before[name] == expected, name


def test_export_after_import_reproduces_the_fixture_rows(
    importer: ImportService, db: DatabaseConnection, clock: FixedClock, tmp_path: Path
) -> None:
    _import_all(importer)
    out = tmp_path / "out"
    ExportService(db, clock).export_all(out)
    for spec in ENTITIES:
        fixture = read_entity(_fixture(spec.file_stem), spec)
        exported = read_entity(out / f"{spec.file_stem}.csv", spec)
        by_key = {tuple(row[code] for code in spec.natural_key): row for row in exported}
        assert len(by_key) == len(exported)
        for row in fixture:
            assert by_key[tuple(row[code] for code in spec.natural_key)] == row, spec.name
        if spec.name in WITH_BUILT_INS:
            assert len(exported) > len(fixture)
        else:
            assert len(exported) == len(fixture), spec.name


def test_asset_import_creates_no_status_event(
    importer: ImportService, db: DatabaseConnection
) -> None:
    for name in ("asset_type", "asset"):
        assert importer.import_file(name, _fixture(name)).ok
    assert len(infrastructure_repo.list_assets(db)) == 3
    assert infrastructure_repo.list_status_events(db) == []
    events = importer.import_file("asset_status_event", _fixture("asset_status_event"))
    assert events.imported == 6
    assert len(infrastructure_repo.list_status_events(db)) == 6


def test_a_storage_constraint_error_is_reported_per_row_and_never_escapes(
    importer: ImportService, db: DatabaseConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # P8-13: a repository error (not a ServiceError) used to abort the whole run
    def refuse(env: object, row: object) -> NoReturn:
        raise ConstraintViolationError("a constraint broke")

    # ``_IMPORTERS`` is a read-only mapping: the module attribute is replaced for the test.
    monkeypatch.setattr(importer_module, "_IMPORTERS", {**_IMPORTERS, "training_course": refuse})
    before = _count(db, "training_course")

    for run in (importer.dry_run, importer.import_file):
        report = run("training_course", _fixture("training_course"))

        assert report.total_rows > 0
        assert report.imported == 0
        assert len(report.errors) == report.total_rows
        assert {(e.column, e.code) for e in report.errors} == {("", "STORAGE_REFUSED")}
        assert _count(db, "training_course") == before


def test_assets_without_a_status_event_are_counted_for_a_dry_run_and_the_import(
    importer: ImportService, db: DatabaseConnection
) -> None:
    # P8-12: the three fixture assets are in service on 2026-03-05 and have no status event
    types = importer.import_file("asset_type", _fixture("asset_type"))
    assert types.assets_without_status_event == 0

    dry = importer.dry_run("asset", _fixture("asset"))
    assert (dry.ok, dry.imported, dry.assets_without_status_event) == (True, 0, 3)
    assert len(infrastructure_repo.list_assets(db)) == 0

    real = importer.import_file("asset", _fixture("asset"))
    assert (real.ok, real.imported, real.assets_without_status_event) == (True, 3, 3)


def test_a_retired_or_future_asset_is_not_counted_as_without_a_status_event(
    importer: ImportService, tmp_path: Path
) -> None:
    header = "tag;type_code;description;location;in_service_from;in_service_until"
    header += ";maintenance_interval_days;notes\n"
    rows = "DEMO-OLD;bay;;;2020-01-01;2021-01-01;;\nDEMO-NEW;bay;;;2030-01-01;;;\n"
    rows += "DEMO-NOW;bay;;;2020-01-01;;;\n"

    report = importer.dry_run("asset", _write(tmp_path, "asset.csv", header + rows))

    assert (report.ok, report.imported) == (True, 0)
    assert report.assets_without_status_event == 1  # only DEMO-NOW is in service today


def test_other_files_report_no_assets_without_a_status_event(
    importer: ImportService,
) -> None:
    report = importer.dry_run("training_course", _fixture("training_course"))

    assert report.assets_without_status_event == 0


# --------------------------------------------------------------------------- all or nothing


def test_a_file_with_any_invalid_row_writes_nothing_and_lists_every_error(
    importer: ImportService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    before = _counts(db)
    log_before = change_log_rows(db)
    path = FIXTURES / "invalid-staff-three-errors.csv"
    report = importer.import_file("staff_member", path)
    assert report.errors == (
        _issue(3, "active_from", "INVALID_DATE"),
        _issue(4, "identifier", "REQUIRED"),
        _issue(5, "active_until", "ACTIVE_UNTIL_BEFORE_FROM"),
    )
    assert not report.ok
    assert report.imported == 0
    assert report.total_rows == 5
    assert personnel_repo.list_staff(db) == []
    assert _counts(db) == before
    assert change_log_rows(db) == log_before


def test_a_rule_of_the_module_is_reported_with_its_line_and_column(
    importer: ImportService, db: DatabaseConnection, tmp_path: Path
) -> None:
    assert importer.import_file("staff_member", _fixture("staff_member")).ok
    header = ";".join(_spec("ppe_certification").column_codes)
    text = "\n".join(
        [
            header,
            "DEMO-00123;A;2024-01-10;2026-01-10;;;",
            "DEMO-00123;B;2024-05-10;2024-01-01;;;",
            "DEMO-00123;Z;2024-05-10;2025-01-01;;;",
            "DEMO-NOBODY;A;2024-05-10;2025-01-01;;;",
            "DEMO-00123;A;2024-01-10;2026-01-10;;;",
            "DEMO-00123;C;2024-01-10;2026-01-10;;other;",
            "",
        ]
    )
    before = _counts(db)
    report = importer.import_file("ppe_certification", _write(tmp_path, "cert.csv", text))
    assert report.errors == (
        _issue(3, "valid_until", "VALID_UNTIL_BEFORE_ISSUED"),
        _issue(4, "ppe_level", "INVALID_PPE_LEVEL"),
        _issue(5, "staff_identifier", "UNKNOWN_REFERENCE"),
        _issue(6, "", "DUPLICATE_IN_FILE"),
        _issue(7, "no_renewal_reason", "NO_RENEWAL_REASON_WITHOUT_DATE"),
    )
    assert report.total_rows == 6
    assert report.imported == 0
    assert personnel_repo.list_certificates(db) == []
    assert _counts(db) == before


def test_unknown_references_name_the_referencing_column(
    importer: ImportService, db: DatabaseConnection
) -> None:
    report = importer.dry_run("ppe_certification", _fixture("ppe_certification"))
    assert report.errors == tuple(
        _issue(line, "staff_identifier", "UNKNOWN_REFERENCE") for line in (2, 3, 4)
    )
    report = importer.dry_run("exercise_country", _fixture("exercise_country"))
    assert {e.column for e in report.errors} == {"edition_code"}
    assert {e.code for e in report.errors} == {"UNKNOWN_REFERENCE"}
    assert len(report.errors) == 5
    assert _count(db, "staff_member") == 0


def test_an_unknown_country_is_a_rule_error_on_its_column(
    importer: ImportService, tmp_path: Path
) -> None:
    assert importer.import_file("exercise_edition", _fixture("exercise_edition")).ok
    text = "edition_code;country_code\nDEMO-ED-1;BR\nDEMO-ED-1;XX\n"
    report = importer.dry_run("exercise_country", _write(tmp_path, "c.csv", text))
    assert report.errors == (_issue(3, "country_code", "UNKNOWN_COUNTRY"),)


# --------------------------------------------------------------------------- dry run


def test_a_dry_run_reports_like_the_import_and_changes_nothing(
    importer: ImportService, db: DatabaseConnection
) -> None:
    path = _fixture("staff_member")
    content = path.read_bytes()
    before = _counts(db)
    dry = importer.dry_run("staff_member", path)
    assert dry.ok
    assert dry.imported == 0
    assert dry.total_rows == 3
    assert _counts(db) == before
    assert path.read_bytes() == content
    real = importer.import_file("staff_member", path)
    assert real.imported == 3
    assert (real.entity, real.total_rows, real.errors) == (dry.entity, dry.total_rows, dry.errors)
    assert _staff(db) == EXPECTED_STAFF


def test_a_dry_run_of_an_invalid_file_has_the_errors_of_the_import(
    importer: ImportService, db: DatabaseConnection
) -> None:
    path = FIXTURES / "invalid-staff-three-errors.csv"
    before = _counts(db)
    dry = importer.dry_run("staff_member", path)
    real = importer.import_file("staff_member", path)
    assert dry.errors == real.errors
    assert len(dry.errors) == 3
    assert dry.imported == real.imported == 0
    assert _counts(db) == before


# --------------------------------------------------------------------------- separators, BOM, UTF-8


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
@pytest.mark.parametrize("bom", [False, True])
@pytest.mark.parametrize("delimiter", [";", ","])
def test_both_separators_are_accepted_with_and_without_a_bom(
    delimiter: str,
    bom: bool,
    eol: str,
    importer: ImportService,
    db: DatabaseConnection,
    tmp_path: Path,
) -> None:
    text = _fixture("staff_member").read_text(encoding="utf-8").replace(";", delimiter)
    path = _write(tmp_path, "variant.csv", text.replace("\n", eol), bom=bom)
    report = importer.import_file("staff_member", path)
    assert report.errors == ()
    assert report.imported == 3
    assert _staff(db) == EXPECTED_STAFF


def test_a_comma_file_keeps_a_quoted_comma_and_non_ascii_text(
    importer: ImportService, db: DatabaseConnection, tmp_path: Path
) -> None:
    text = 'code,label_pt_br,label_en_us,label_es_es,active\n007,"Forma\u00e7\u00e3o, DEMO",,,1\n'
    for bom, name in ((False, "plain.csv"), (True, "bom.csv")):
        path = _write(tmp_path, name, text.replace("007", "007" if not bom else "008"), bom=bom)
        assert importer.import_file("training_course", path).imported == 1
    labels = {c.code: c.label_pt_br for c in personnel_repo.list_courses(db)}
    assert labels == {"007": "Forma\u00e7\u00e3o, DEMO", "008": "Forma\u00e7\u00e3o, DEMO"}


def test_a_legacy_encoded_file_is_refused_as_a_whole(
    importer: ImportService, db: DatabaseConnection, tmp_path: Path
) -> None:
    text = "code;label_pt_br;label_en_us;label_es_es;active\r\nDEMO-A;Forma\u00e7\u00e3o;;;1\r\n"
    path = tmp_path / "legacy.csv"
    path.write_bytes(text.encode("cp1252"))
    before = _counts(db)
    expected = (_issue(0, "", "NOT_UTF8"),)
    assert importer.import_file("training_course", path).errors == expected
    assert importer.dry_run("training_course", path).errors == expected
    report = importer.import_file("training_course", path)
    assert (report.total_rows, report.imported) == (0, 0)
    assert _counts(db) == before
    assert read_import_file(path, _spec("training_course")).errors == [CellError(0, "", "NOT_UTF8")]


# --------------------------------------------------------------------------- codes and the guard


def test_codes_keep_their_leading_zeros(importer: ImportService, db: DatabaseConnection) -> None:
    parsed = read_import_file(_fixture("training_course"), _spec("training_course"))
    assert parsed.rows[0].values["code"] == "00123"
    _import_all(importer)
    assert personnel_repo.get_course_by_code(db, "00123") is not None
    assert personnel_repo.get_course_by_code(db, "123") is None
    assert infrastructure_repo.get_asset_by_tag(db, "00789") is not None
    assert infrastructure_repo.get_type_by_code(db, "00456") is not None


def test_the_formula_guard_is_removed_on_import(
    importer: ImportService, db: DatabaseConnection
) -> None:
    _import_all(importer)
    bed = infrastructure_repo.get_asset_by_tag(db, "DEMO-BED-001")
    bay = infrastructure_repo.get_asset_by_tag(db, "DEMO-BAY-002")
    assert bed is not None
    assert bay is not None
    assert bed.notes == "=1+1"
    assert (bed.description or "").replace("\r\n", "\n") == 'Line one; "quoted"\nline two'
    assert bay.location == "-x"
    assert bay.notes == "'quoted"
    notes = {event.note for event in infrastructure_repo.list_status_events(db)}
    assert "@note" in notes
    assert "+x" in {event.note for event in infrastructure_repo.list_maintenance(db)}
    assert "-x" in {result.note for result in exercises_repo.list_results(db)}


def test_cells_are_trimmed_by_kind(tmp_path: Path) -> None:
    text = f"{STAFF_HEADER}\n DEMO-A ;  label  ;;2020-01-01 ;\n"
    (row,) = _read(tmp_path, "staff_member", text).rows
    assert row.errors == []
    assert row.values["identifier"] == "DEMO-A"
    assert row.values["label"] == "  label  "
    assert row.values["active_from"] == "2020-01-01"
    assert row.values["active_until"] is None


# --------------------------------------------------------------------------- duplicates


def test_a_duplicate_inside_the_file_is_reported_on_the_later_line(
    importer: ImportService, db: DatabaseConnection
) -> None:
    report = importer.import_file("staff_member", FIXTURES / "invalid-staff-duplicate-in-file.csv")
    assert report.errors == (_issue(4, "", "DUPLICATE_IN_FILE"),)
    assert report.imported == 0
    assert personnel_repo.list_staff(db) == []


@pytest.mark.parametrize("name", list(EXPECTED_ROWS))
def test_rows_that_exist_in_the_database_are_refused_as_duplicates(
    name: str, importer: ImportService, db: DatabaseConnection
) -> None:
    _import_all(importer)
    before = _counts(db)
    parsed = read_import_file(_fixture(name), _spec(name))
    report = importer.import_file(name, _fixture(name))
    assert report.errors == tuple(_issue(row.line, "", "DUPLICATE_KEY") for row in parsed.rows)
    assert report.imported == 0
    assert _counts(db) == before


def test_built_in_rows_are_never_created(importer: ImportService, tmp_path: Path) -> None:
    header = ";".join(_spec("asset_type").column_codes)
    text = f"{header}\nbed;1;;;;;1\nmystery;1;;;;;1\nbed;0;Cama;;;;1\n"
    report = importer.dry_run("asset_type", _write(tmp_path, "types.csv", text))
    assert report.errors == (
        _issue(2, "", "DUPLICATE_KEY"),
        _issue(3, "built_in", "BUILT_IN_NOT_ALLOWED"),
        _issue(4, "", "DUPLICATE_IN_FILE"),
    )


# --------------------------------------------------------------------------- budget


def test_executions_are_matched_to_their_entries_by_key(
    importer: ImportService, db: DatabaseConnection
) -> None:
    for name in ("funding_source", "budget_entry", "budget_execution"):
        assert importer.import_file(name, _fixture(name)).ok
    entries = {row.id: row for row in budget_repo.list_entries(db)}
    sources = budget_repo.source_codes(db)
    found = {
        (
            entries[e.entry_id].fiscal_year,
            sources[entries[e.entry_id].source_id],
            entries[e.entry_id].currency,
            entries[e.entry_id].description,
            e.executed_on,
            e.amount_minor,
        )
        for e in budget_repo.list_executions(db)
    }
    assert found == {
        (2024, "DIRSA", "BRL", 'DEMO line; "A"', "2024-02-01", 100000),
        (2024, "DIRSA", "BRL", 'DEMO line; "A"', "2024-03-01", 23456),
        (2024, "DIRSA", "USD", "", "2024-04-01", 7),
        (2025, "COMAER", "EUR", "", "2025-01-15", 250),
    }


def test_an_execution_of_an_entry_that_does_not_exist_is_an_unknown_reference(
    importer: ImportService, db: DatabaseConnection
) -> None:
    unknown = FIXTURES / "invalid-budget-execution-unknown-entry.csv"
    expected = (_issue(2, "description", "UNKNOWN_REFERENCE"),)
    assert importer.import_file("budget_execution", unknown).errors == expected
    # the entries come second: the execution file imported first fails on every row
    first = importer.import_file("budget_execution", _fixture("budget_execution"))
    assert first.errors == tuple(
        _issue(line, "description", "UNKNOWN_REFERENCE") for line in (2, 3, 4, 5)
    )
    # the entries of the custom source cannot be created before the source exists
    assert importer.import_file("budget_entry", _fixture("budget_entry")).errors != ()
    assert importer.import_file("funding_source", _fixture("funding_source")).ok
    assert importer.import_file("budget_entry", _fixture("budget_entry")).ok
    assert importer.import_file("budget_execution", unknown).errors == expected
    assert budget_repo.list_executions(db) == []


def test_a_blank_execution_amount_is_required_and_writes_nothing(
    importer: ImportService, db: DatabaseConnection, tmp_path: Path, change_log_rows: ChangeLogRows
) -> None:
    for name in ("funding_source", "budget_entry"):
        assert importer.import_file(name, _fixture(name)).ok
    header = ";".join(_spec("budget_execution").column_codes)
    path = _write(
        tmp_path,
        "blank-amount.csv",
        f"{header}\n2024;DIRSA;USD;;2024-04-01;;\n2024;DIRSA;USD;;2024-05-01;0.07;\n",
    )
    log_before = change_log_rows(db)
    report = importer.import_file("budget_execution", path)
    assert report.errors == (_issue(2, "amount", "REQUIRED"),)
    assert report.imported == 0
    assert report.total_rows == 2
    assert budget_repo.list_executions(db) == []  # not even the valid row: all or nothing
    assert change_log_rows(db) == log_before


def test_a_blank_result_value_is_required_and_writes_nothing(
    importer: ImportService, db: DatabaseConnection, tmp_path: Path, change_log_rows: ChangeLogRows
) -> None:
    for name in ("evaluation_metric", "exercise_edition"):
        assert importer.import_file(name, _fixture(name)).ok
    header = ";".join(_spec("evaluation_result").column_codes)
    path = _write(
        tmp_path,
        "blank-value.csv",
        f"{header}\nDEMO-ED-1;DEMO-M1;;;\nDEMO-ED-1;DEMO-M2;5.0;;\n",
    )
    log_before = change_log_rows(db)
    report = importer.import_file("evaluation_result", path)
    assert report.errors == (_issue(2, "value", "REQUIRED"),)
    assert report.imported == 0
    assert report.total_rows == 2
    assert _count(db, "evaluation_result") == 0
    assert change_log_rows(db) == log_before


def test_an_execution_dated_outside_the_year_of_its_entry_is_refused_on_its_date(
    importer: ImportService, db: DatabaseConnection, tmp_path: Path
) -> None:
    for name in ("funding_source", "budget_entry"):
        assert importer.import_file(name, _fixture(name)).ok
    header = ";".join(_spec("budget_execution").column_codes)
    path = _write(tmp_path, "outside.csv", f"{header}\n2024;DIRSA;USD;;2025-01-01;1.00;\n")
    report = importer.import_file("budget_execution", path)
    assert report.errors == (_issue(2, "executed_on", "EXECUTION_OUTSIDE_FISCAL_YEAR"),)
    assert budget_repo.list_executions(db) == []


# --------------------------------------------------------------------------- change_log


def test_every_imported_row_has_one_import_row_in_the_change_log(
    importer: ImportService,
    db: DatabaseConnection,
    clock: FixedClock,
    change_log_rows: ChangeLogRows,
) -> None:
    baseline = len(change_log_rows(db))
    _import_all(importer)
    rows = change_log_rows(db)[baseline:]
    imports = [row for row in rows if row["action"] == "import"]
    assert dict(Counter(row["entity"] for row in imports)) == EXPECTED_ROWS
    assert {row["operator"] for row in rows} == {OPERATOR}
    assert {row["at_utc"] for row in rows} == {format_utc_timestamp(clock.utc_now())}
    assert all(row["before_json"] is None and row["after_json"] is None for row in imports)
    identities = [(row["entity"], row["entity_id"], row["entity_key"]) for row in imports]
    assert len(set(identities)) == len(identities)
    for table in ID_TABLES:
        imported = {row["entity_id"] for row in imports if row["entity"] == table}
        inserted = {
            row["entity_id"] for row in rows if row["entity"] == table and row["action"] == "insert"
        }
        assert imported == inserted, table
        stored = {int(r[0]) for r in db.execute(f"SELECT id FROM {table}").fetchall()}
        assert imported <= stored
    for table in ("exercise_country", "evaluation_result"):
        keyed = [row for row in imports if row["entity"] == table]
        assert all(row["entity_id"] is None and row["entity_key"] for row in keyed)


def test_personal_text_never_reaches_the_change_log(
    importer: ImportService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    baseline = len(change_log_rows(db))
    _import_all(importer)
    text = json.dumps(change_log_rows(db)[baseline:])
    for secret in SECRETS:
        assert secret not in text
    imported = [r for r in change_log_rows(db)[baseline:] if r["action"] == "import"]
    staff_rows = [r for r in imported if r["entity"] == "staff_member"]
    assert len(staff_rows) == EXPECTED_ROWS["staff_member"]
    assert all(r["after_json"] is None and r["entity_key"] is None for r in staff_rows)


def test_a_failed_import_leaves_the_change_log_unchanged(
    importer: ImportService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    assert importer.import_file("staff_member", _fixture("staff_member")).ok
    before = change_log_rows(db)
    importer.import_file("staff_member", FIXTURES / "invalid-staff-three-errors.csv")
    importer.dry_run("staff_member", _fixture("staff_member"))
    assert change_log_rows(db) == before


# --------------------------------------------------------------------------- the reader: header


def test_the_header_may_be_in_any_order(tmp_path: Path) -> None:
    text = "active_until;active_from;category;label;identifier\n;2020-01-01;cat;lab;DEMO-A\n"
    parsed = _read(tmp_path, "staff_member", text)
    assert parsed.errors == []
    assert parsed.rows[0].values == {
        "identifier": "DEMO-A",
        "label": "lab",
        "category": "cat",
        "active_from": "2020-01-01",
        "active_until": None,
    }


def test_header_errors_name_the_column(tmp_path: Path) -> None:
    header = "identifier;label;categoria;active_from;active_until\n"
    unknown = _read(tmp_path, "staff_member", header)
    assert unknown.rows == []
    assert unknown.errors == [
        CellError(1, "categoria", "UNKNOWN_COLUMN"),
        CellError(1, "category", "MISSING_COLUMN"),
    ]
    twice = _read(tmp_path, "staff_member", "identifier;label;label;active_from;active_until\n")
    assert twice.errors == [
        CellError(1, "label", "DUPLICATE_COLUMN"),
        CellError(1, "category", "MISSING_COLUMN"),
    ]
    capital = "Identifier;label;category;active_from;active_until\n"
    upper = _read(tmp_path, "staff_member", capital)
    assert CellError(1, "Identifier", "UNKNOWN_COLUMN") in upper.errors
    assert CellError(1, "identifier", "MISSING_COLUMN") in upper.errors


def test_a_header_error_stops_the_import_before_any_row(
    importer: ImportService, db: DatabaseConnection, tmp_path: Path
) -> None:
    text = "identifier;label;categoria;active_from;active_until\nDEMO-A;;;2020-01-01;\n"
    report = importer.import_file("staff_member", _write(tmp_path, "h.csv", text))
    assert [e.code for e in report.errors] == ["UNKNOWN_COLUMN", "MISSING_COLUMN"]
    assert report.errors[0].column == "categoria"
    assert report.imported == 0
    assert personnel_repo.list_staff(db) == []


@pytest.mark.parametrize("content", ["", "\n\n", STAFF_HEADER, f"{STAFF_HEADER}\n\n"])
@pytest.mark.parametrize("bom", [False, True])
def test_an_empty_or_header_only_file_is_valid_with_zero_rows(
    content: str, bom: bool, importer: ImportService, tmp_path: Path
) -> None:
    path = _write(tmp_path, "e.csv", content, bom=bom)
    parsed = read_import_file(path, _spec("staff_member"))
    assert (parsed.rows, parsed.errors) == ([], [])
    assert parsed.ok
    report = importer.dry_run("staff_member", path)
    assert (report.ok, report.total_rows, report.imported) == (True, 0, 0)


# --------------------------------------------------------------------------- the reader: rows


def test_wrong_field_count_and_blank_lines(tmp_path: Path) -> None:
    lines = [STAFF_HEADER, "", "DEMO-A;;2020-01-01", "", "DEMO-B;;;2020-01-01;;extra"]
    text = "\n".join([*lines, "DEMO-C;;;2020-01-01;", ""])
    parsed = _read(tmp_path, "staff_member", text)
    assert [row.line for row in parsed.rows] == [3, 5, 6]
    assert parsed.rows[0].errors == [CellError(3, "", "WRONG_FIELD_COUNT")]
    assert parsed.rows[0].values == {}
    assert parsed.rows[1].errors == [CellError(5, "", "WRONG_FIELD_COUNT")]
    assert parsed.rows[2].errors == []


def test_the_line_of_a_record_is_where_it_starts(tmp_path: Path) -> None:
    parsed = read_import_file(_fixture("asset"), _spec("asset"))
    assert [row.line for row in parsed.rows] == [2, 3, 4]
    description = str(parsed.rows[2].values["description"])
    assert description.replace("\r\n", "\n") == 'Line one; "quoted"\nline two'
    text = f'{STAFF_HEADER}\n"DEMO-A\nsplit";;;2020-01-01;\nDEMO-B;;;2020-13-01;\n'
    again = _read(tmp_path, "staff_member", text)
    assert again.rows[1].line == 4
    assert again.rows[1].errors == [CellError(4, "active_from", "INVALID_DATE")]


def test_a_broken_quote_ends_the_reading_and_keeps_the_rows_before_it(tmp_path: Path) -> None:
    text = f'{STAFF_HEADER}\nDEMO-A;;;2020-01-01;\n"DEMO-B;;;2020-01-01;\n'
    parsed = _read(tmp_path, "staff_member", text)
    assert [row.line for row in parsed.rows] == [2]
    assert [e.code for e in parsed.errors] == ["MALFORMED_CSV"]
    assert not parsed.ok


@pytest.mark.parametrize(
    ("entity", "row", "column", "code"),
    [
        ("staff_member", "DEMO-A;;;2020-1-1;", "active_from", "INVALID_DATE"),
        ("staff_member", "DEMO-A;;;2020-02-30;", "active_from", "INVALID_DATE"),
        ("staff_member", "DEMO-A;;;01/02/2020;", "active_from", "INVALID_DATE"),
        ("staff_member", ";;;2020-01-01;", "identifier", "REQUIRED"),
        ("staff_member", "DEMO-A;;;;", "active_from", "REQUIRED"),
        ("asset", "DEMO-A;bed;;;2020-01-01;;abc;", "maintenance_interval_days", "INVALID_NUMBER"),
        ("asset", "DEMO-A;bed;;;2020-01-01;;1,5;", "maintenance_interval_days", "INVALID_NUMBER"),
        ("asset", "DEMO-A;bed;;;2020-01-01;;1.0;", "maintenance_interval_days", "INVALID_NUMBER"),
        ("training_record", "DEMO-1;007;2020-01-01;1,5", "hours", "INVALID_NUMBER"),
        ("training_record", "DEMO-1;007;2020-01-01;1e999", "hours", "INVALID_NUMBER"),
        ("training_course", "007;Curso;;;yes", "active", "INVALID_BOOL"),
        ("training_course", "007;Curso;;;", "active", "REQUIRED"),
        ("budget_entry", "2024;DIRSA;XXX;;1.00;", "currency", "INVALID_CURRENCY"),
        ("budget_entry", "2024;DIRSA;brl;;1.00;", "currency", "INVALID_CURRENCY"),
        ("budget_entry", "2024;DIRSA;BRL;;1.234;", "allocated", "INVALID_AMOUNT"),
        ("budget_entry", "2024;DIRSA;BRL;;1,50;", "allocated", "INVALID_AMOUNT"),
        ("budget_entry", "2024;DIRSA;BRL;;abc;", "allocated", "INVALID_AMOUNT"),
        ("budget_entry", "20x4;DIRSA;BRL;;1.00;", "fiscal_year", "INVALID_NUMBER"),
        ("budget_execution", "2024;DIRSA;BRL;;2024-02-01;;", "amount", "REQUIRED"),
        ("budget_execution", "2024;DIRSA;BRL;;2024-02-01; ;", "amount", "REQUIRED"),
        ("evaluation_result", "DEMO-ED-1;DEMO-M1;;;", "value", "REQUIRED"),
        ("evaluation_result", "DEMO-ED-1;DEMO-M1; ;;", "value", "REQUIRED"),
    ],
)
def test_each_cell_error_code(
    entity: str, row: str, column: str, code: str, tmp_path: Path
) -> None:
    header = ";".join(_spec(entity).column_codes)
    parsed = _read(tmp_path, entity, f"{header}\n{row}\n")
    assert parsed.errors == []
    assert parsed.rows[0].errors == [CellError(2, column, code)]


def test_valid_cells_are_typed(tmp_path: Path) -> None:
    header = ";".join(_spec("budget_entry").column_codes)
    parsed = _read(tmp_path, "budget_entry", f"{header}\n2024;DIRSA;BRL; d ;1234.5;\n")
    assert parsed.rows[0].values == {
        "fiscal_year": 2024,
        "source_code": "DIRSA",
        "currency": "BRL",
        "description": " d ",
        "allocated": 123450,
        "notes": None,
    }
    metric = ";".join(_spec("evaluation_metric").column_codes)
    reals = _read(tmp_path, "evaluation_metric", f"{metric}\nM;l;;;pct;-1.5;1e2;0;1\n")
    assert reals.rows[0].values["scale_min"] == -1.5
    assert reals.rows[0].values["scale_max"] == 100.0
    assert reals.rows[0].values["higher_is_better"] is False


# --------------------------------------------------------------------------- templates


_ENTITY_HEADING = re.compile(r"### `([a-z_]+)`")


def _documented_columns() -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    current: str | None = None
    for line in DOCS.read_text(encoding="utf-8").splitlines():
        heading = _ENTITY_HEADING.fullmatch(line.strip())
        if heading is not None:
            current = heading.group(1)
            tables[current] = []
            continue
        if line.startswith("#"):
            current = None
            continue
        if current is None or not line.startswith("|"):
            continue
        first = line.strip().strip("|").split("|")[0].strip()
        if first == "Column" or set(first) <= set("-: "):
            continue
        tables[current].append(first.strip("`"))
    return tables


def test_templates_are_header_only_files_that_match_the_documentation(
    importer: ImportService, tmp_path: Path
) -> None:
    paths = importer.write_all_templates(tmp_path / "templates")
    assert [path.name for path in paths] == [template_file_name(spec) for spec in ENTITIES]
    assert paths[4].name == "staff_member-template.csv"
    documented = _documented_columns()
    for spec, path in zip(ENTITIES, paths, strict=True):
        data = path.read_bytes()
        assert data.startswith(BOM)
        assert data.endswith(b"\r\n")
        header = data[len(BOM) :].decode("utf-8").rstrip("\r\n").split(";")
        assert header == list(spec.column_codes) == documented[spec.name], spec.name
        parsed = read_import_file(path, spec)
        assert (parsed.rows, parsed.errors) == ([], [])
        assert importer.dry_run(spec.name, path).ok


def test_a_single_template_and_an_unknown_entity(importer: ImportService, tmp_path: Path) -> None:
    path = importer.write_template("asset", tmp_path / "one")
    assert path == tmp_path / "one" / "asset-template.csv"
    assert [p.name for p in (tmp_path / "one").iterdir()] == ["asset-template.csv"]
    for call in (
        lambda: importer.write_template("change_log", tmp_path),
        lambda: importer.dry_run("change_log", path),
        lambda: importer.import_file("change_log", path),
    ):
        with pytest.raises(ServiceError) as info:
            call()
        assert info.value.code == UNKNOWN_ENTITY


def test_the_documentation_lists_every_error_code() -> None:
    text = DOCS.read_text(encoding="utf-8")
    codes = (
        "NOT_UTF8",
        "MALFORMED_CSV",
        "UNKNOWN_COLUMN",
        "MISSING_COLUMN",
        "DUPLICATE_COLUMN",
        "WRONG_FIELD_COUNT",
        "REQUIRED",
        "INVALID_NUMBER",
        "INVALID_DATE",
        "INVALID_BOOL",
        "INVALID_CURRENCY",
        "INVALID_AMOUNT",
        "UNKNOWN_REFERENCE",
        "DUPLICATE_IN_FILE",
        "DUPLICATE_KEY",
        "BUILT_IN_NOT_ALLOWED",
        "FILE_UNREADABLE",
    )
    for code in codes:
        assert f"`{code}`" in text, code
    assert "dry run" in text


# --------------------------------------------------------------------------- refusals


def test_a_read_only_connection_refuses_import_and_dry_run(
    read_only_db: DatabaseConnection, clock: FixedClock
) -> None:
    service = _build(read_only_db, clock)
    for call in (service.import_file, service.dry_run):
        with pytest.raises(ServiceError) as info:
            call("staff_member", _fixture("staff_member"))
        assert info.value.code == "READ_ONLY"


def test_a_missing_file_is_reported_as_unreadable(importer: ImportService, tmp_path: Path) -> None:
    with pytest.raises(ServiceError) as info:
        importer.import_file("staff_member", tmp_path / "missing.csv")
    assert info.value.code == "FILE_UNREADABLE"
