# SPDX-License-Identifier: GPL-3.0-or-later
"""CSV export (T8.3): format, round trip, formula guard, demo names, money and the documentation.

All data is fictitious and written through the four module services into a migrated database; the
expected rows are loaded independently through the repositories, with the parents resolved to their
natural keys by the test itself.
"""

from __future__ import annotations

import csv
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.services.budget import BudgetService, EntryInput, SourceInput
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.services.exercises import (
    EditionInput,
    ExercisesService,
    MetricInput,
    ResultInput,
)
from cbrn_dashboard.services.export import EXPORT_FAILED, UNKNOWN_ENTITY, ExportService
from cbrn_dashboard.services.infrastructure import (
    AssetInput,
    AssetTypeInput,
    InfrastructureService,
)
from cbrn_dashboard.services.personnel import (
    IDENTIFIER_LOOKS_LIKE_NATIONAL_ID,
    CertificateInput,
    CourseInput,
    DegreeInput,
    PersonnelService,
    StaffInput,
    TrainingInput,
)
from cbrn_dashboard.storage import (
    app_meta,
    budget_repo,
    exercises_repo,
    infrastructure_repo,
    personnel_repo,
)
from cbrn_dashboard.storage.csv_io import (
    ENTITIES,
    CsvFormatError,
    EntitySpec,
    entity_spec,
    export_file_name,
    guard_cell,
    read_entity,
    unguard_cell,
    write_entity,
)
from cbrn_dashboard.storage.db import DatabaseConnection, open_database
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate
from cbrn_dashboard.storage.repository import WriteContext

CLOCK = FixedClock.at("2026-03-05T12:00:00Z")

DOCS = Path(__file__).resolve().parents[2] / "docs" / "import-templates.md"

DESCRIPTION = 'Line one; "quoted"\nline two\r\nline three'
NOTES = 'Notes; with "quotes"\nand a\r\nbreak'
BIG_MINOR = 2**53 + 1

BOM = b"\xef\xbb\xbf"

ENTITY_NAMES = (
    "training_course",
    "asset_type",
    "evaluation_metric",
    "funding_source",
    "staff_member",
    "ppe_certification",
    "training_record",
    "academic_degree",
    "asset",
    "asset_status_event",
    "maintenance_event",
    "exercise_edition",
    "exercise_country",
    "evaluation_result",
    "budget_entry",
    "budget_execution",
)

SPEC_IDS = [spec.name for spec in ENTITIES]

AWKWARD = [
    "=1+1",
    "+x",
    "-x",
    "@x",
    "\tx",
    "\rx",
    "'x",
    "'=x",
    "''",
    "'",
    "=",
    "-",
    "\t",
    "\r\n=x",
    " =x",
    "x=",
    "plain",
    "a;b",
    'say "hi"',
    "line\nbreak",
    "line\r\nbreak",
    "'\tx",
    "caf\u00e9 -1",
    "",
]

_GUARDED_FIRST = ("=", "+", "-", "@", "\t", "\r", "'")


# --------------------------------------------------------------------------- seeding


def _type_id(conn: DatabaseConnection, code: str) -> int:
    row = infrastructure_repo.get_type_by_code(conn, code)
    assert row is not None
    return row.id


def _source_id(conn: DatabaseConnection, code: str) -> int:
    row = budget_repo.get_source_by_code(conn, code)
    assert row is not None
    return row.id


def _seed_personnel(conn: DatabaseConnection) -> None:
    people = PersonnelService(conn, CLOCK)
    c1 = people.create_course(
        CourseInput(code="007", label_pt_br="Curso DEMO sete", label_en_us="Demo course seven")
    )
    c2 = people.create_course(
        CourseInput(code="DEMO-C2", label_pt_br="Forma\u00e7\u00e3o DEMO", label_es_es="Curso DEMO")
    )
    s1 = people.create_staff(
        StaffInput(
            identifier="DEMO-00123",
            active_from="2020-01-15",
            label='DEMO; "label"',
            category="DEMO-cat",
        )
    )
    s2 = people.create_staff(
        StaffInput(identifier="DEMO-00124", active_from="2021-02-01", active_until="2025-12-31")
    )
    people.add_certificate(
        s1,
        CertificateInput(
            level="A", issued_on="2024-01-10", valid_until="2026-01-10", reference="DEMO-REF-1"
        ),
    )
    people.add_certificate(
        s1, CertificateInput(level="B", issued_on="2024-02-10", valid_until="2026-02-10")
    )
    cert = people.add_certificate(
        s2, CertificateInput(level="C", issued_on="2023-03-01", valid_until="2025-03-01")
    )
    people.set_no_renewal(cert, "2025-01-01", "left_unit")
    people.add_training(s1, TrainingInput(course_id=c1, completed_on="2023-05-01", hours=8.5))
    people.add_training(s1, TrainingInput(course_id=c2, completed_on="2023-06-01"))
    people.add_training(s2, TrainingInput(course_id=c1, completed_on="2022-02-02", hours=0.1 + 0.2))
    people.add_degree(
        s1, DegreeInput(level="master", status="completed", year=2018, field="DEMO field")
    )
    people.add_degree(s1, DegreeInput(level="doctorate", status="in_progress"))
    people.add_degree(
        s2,
        DegreeInput(level="specialisation", year=2015, field='DEMO; "quoted" field'),
    )
    people.deactivate_course(c2)


def _seed_infrastructure(conn: DatabaseConnection) -> None:
    infra = InfrastructureService(conn, CLOCK)
    custom = infra.create_type(
        AssetTypeInput(
            code="DEMO-TYPE", label_pt_br="Tipo DEMO", default_maintenance_interval_days=90
        )
    )
    a1 = infra.create_asset(
        AssetInput(
            tag="DEMO-BED-001",
            type_id=_type_id(conn, "bed"),
            in_service_from="2022-01-01",
            description=DESCRIPTION,
            location="DEMO ward",
            maintenance_interval_days=30,
            notes="=1+1",
        ),
        "operational",
    )
    a2 = infra.create_asset(
        AssetInput(
            tag="DEMO-BAY-002",
            type_id=_type_id(conn, "bay"),
            in_service_from="2022-06-01",
            location="@x",
        ),
        "operational",
    )
    infra.create_asset(
        AssetInput(tag="00789", type_id=custom, in_service_from="2023-01-01"), "degraded"
    )
    infra.change_status(a1, "2023-01-01", "degraded", note="@note")
    infra.change_status(a1, "2023-02-01", "operational")
    infra.change_status(a2, "2023-03-01", "out_of_service", note="DEMO; note")
    infra.record_maintenance(a1, "2023-03-01", "preventive", next_due_on="2023-04-01", note="+x")
    infra.record_maintenance(a1, "2023-03-01", "inspection")
    infra.record_maintenance(a2, "2023-05-01", "corrective")


def _seed_exercises(conn: DatabaseConnection) -> None:
    exercises = ExercisesService(conn, CLOCK)
    m1 = exercises.create_metric(
        MetricInput(
            code="DEMO-M1",
            label_pt_br="Avalia\u00e7\u00e3o DEMO",
            unit="pct",
            scale_min=0.0,
            scale_max=100.0,
        )
    )
    m2 = exercises.create_metric(
        MetricInput(code="DEMO-M2", label_pt_br="Metrica DEMO 2", higher_is_better=False)
    )
    e1 = exercises.create_edition(
        EditionInput(
            code="DEMO-ED-1",
            kind="CBRAMED",
            start_on="2023-09-01",
            end_on="2023-09-05",
            title="Demo edition",
            participants=40,
            notes=NOTES,
            countries=("BR", "AR", "CL"),
        )
    )
    e2 = exercises.create_edition(
        EditionInput(
            code="DEMO-ED-2",
            kind="EXBRAMED",
            start_on="2024-09-01",
            end_on="2024-09-03",
            countries=("BR", "PT"),
        )
    )
    exercises.set_result(e1, ResultInput(metric_id=m1, value=87.5, respondents=30, note="-x"))
    exercises.set_result(e1, ResultInput(metric_id=m2, value=1234567.125))
    exercises.set_result(e2, ResultInput(metric_id=m1, value=42.0))
    exercises.set_result(e2, ResultInput(metric_id=m2, value=0.1 + 0.2, respondents=0))


def _seed_budget(conn: DatabaseConnection) -> None:
    budget = BudgetService(conn, CLOCK)
    dirsa = _source_id(conn, "DIRSA")
    opcw = _source_id(conn, "OPCW_TRUST_FUND")
    custom = budget.create_source(SourceInput(code="DEMO-SRC", label_pt_br="Fonte DEMO"))
    en1 = budget.create_entry(
        EntryInput(
            fiscal_year=2024,
            source_id=dirsa,
            currency="BRL",
            allocated_minor=123456,
            description='DEMO line; "A"',
            notes="DEMO note",
        )
    )
    en2 = budget.create_entry(
        EntryInput(fiscal_year=2024, source_id=dirsa, currency="USD", allocated_minor=2000)
    )
    en3 = budget.create_entry(
        EntryInput(fiscal_year=2025, source_id=opcw, currency="EUR", allocated_minor=None)
    )
    # The service refuses amounts above 2**53 - 1; the exporter must still keep them exact.
    budget_repo.insert_entry(
        WriteContext(conn, CLOCK, ""),
        fiscal_year=2024,
        source_id=custom,
        currency="BRL",
        allocated_minor=BIG_MINOR,
        description="big",
        notes=None,
    )
    budget.create_entry(
        EntryInput(
            fiscal_year=2024,
            source_id=custom,
            currency="BRL",
            allocated_minor=5,
            description="small",
        )
    )
    budget.add_execution(en1, "2024-02-01", 100000, note="DEMO exec")
    budget.add_execution(en1, "2024-03-01", 23456)
    budget.add_execution(en2, "2024-04-01", 7)
    budget.add_execution(en3, "2025-01-15", 250)


def _seed(conn: DatabaseConnection) -> None:
    _seed_personnel(conn)
    _seed_infrastructure(conn)
    _seed_exercises(conn)
    _seed_budget(conn)


@pytest.fixture
def seeded(migrated_db: DatabaseConnection) -> DatabaseConnection:
    """The migrated database as a REAL database, with fictitious data in every module."""
    app_meta.initialise(migrated_db, is_demo=False, created_with="test")
    _seed(migrated_db)
    return migrated_db


@pytest.fixture
def export_dir(seeded: DatabaseConnection, tmp_path: Path) -> Path:
    out = tmp_path / "out"
    ExportService(seeded, CLOCK).export_all(out)
    return out


# --------------------------------------------------------------------------- helpers


def _fields(row: Any, *drop: str) -> dict[str, object]:
    return {key: value for key, value in asdict(row).items() if key not in drop}


def _expected(conn: DatabaseConnection) -> dict[str, list[dict[str, object]]]:
    """The rows the files must hold, loaded through the repositories; parents by natural key."""
    staff = {row.id: row.identifier for row in personnel_repo.list_staff(conn)}
    courses = personnel_repo.list_courses(conn)
    course_code = {row.id: row.code for row in courses}
    types = infrastructure_repo.list_types(conn)
    type_code = {row.id: row.code for row in types}
    assets = infrastructure_repo.list_assets(conn)
    tag = {row.id: row.tag for row in assets}
    editions = exercises_repo.list_editions(conn)
    edition_code = {row.id: row.code for row in editions}
    metrics = exercises_repo.list_metrics(conn)
    metric_code = {row.id: row.code for row in metrics}
    sources = budget_repo.list_sources(conn)
    source_code = {row.id: row.code for row in sources}
    entries = budget_repo.list_entries(conn)
    entry_by_id = {row.id: row for row in entries}

    out: dict[str, list[dict[str, object]]] = {}
    out["training_course"] = [_fields(row, "id") for row in courses]
    out["asset_type"] = [_fields(row, "id") for row in types]
    out["evaluation_metric"] = [_fields(row, "id") for row in metrics]
    out["funding_source"] = [_fields(row, "id") for row in sources]
    out["staff_member"] = [_fields(row, "id") for row in personnel_repo.list_staff(conn)]
    out["ppe_certification"] = [
        {**_fields(row, "id", "staff_id"), "staff_identifier": staff[row.staff_id]}
        for row in personnel_repo.list_certificates(conn)
    ]
    out["training_record"] = [
        {
            "staff_identifier": staff[row.staff_id],
            "course_code": course_code[row.course_id],
            "completed_on": row.completed_on,
            "hours": row.hours,
        }
        for row in personnel_repo.list_training(conn)
    ]
    out["academic_degree"] = [
        {**_fields(row, "id", "staff_id"), "staff_identifier": staff[row.staff_id]}
        for row in personnel_repo.list_degrees(conn)
    ]
    out["asset"] = [
        {**_fields(row, "id", "type_id"), "type_code": type_code[row.type_id]} for row in assets
    ]
    out["asset_status_event"] = [
        {**_fields(row, "id", "asset_id"), "asset_tag": tag[row.asset_id]}
        for row in infrastructure_repo.list_status_events(conn)
    ]
    out["maintenance_event"] = [
        {**_fields(row, "id", "asset_id"), "asset_tag": tag[row.asset_id]}
        for row in infrastructure_repo.list_maintenance(conn)
    ]
    out["exercise_edition"] = [_fields(row, "id") for row in editions]
    out["exercise_country"] = [
        {"edition_code": edition.code, "country_code": country}
        for edition in editions
        for country in exercises_repo.list_edition_countries(conn, edition.id)
    ]
    out["evaluation_result"] = [
        {
            **_fields(row, "edition_id", "metric_id"),
            "edition_code": edition_code[row.edition_id],
            "metric_code": metric_code[row.metric_id],
        }
        for row in exercises_repo.list_results(conn)
    ]
    out["budget_entry"] = [
        {
            **_fields(row, "id", "source_id", "allocated_minor"),
            "source_code": source_code[row.source_id],
            "allocated": row.allocated_minor,
        }
        for row in entries
    ]
    out["budget_execution"] = [
        {
            "fiscal_year": entry_by_id[row.entry_id].fiscal_year,
            "source_code": source_code[entry_by_id[row.entry_id].source_id],
            "currency": entry_by_id[row.entry_id].currency,
            "description": entry_by_id[row.entry_id].description,
            "executed_on": row.executed_on,
            "amount": row.amount_minor,
            "note": row.note,
        }
        for row in budget_repo.list_executions(conn)
    ]
    return out


def _keyed(spec: EntitySpec, rows: list[dict[str, object]]) -> dict[tuple[object, ...], Any]:
    keyed = {tuple(row[code] for code in spec.natural_key): row for row in rows}
    assert len(keyed) == len(rows), f"{spec.name}: the natural key is not unique"
    return keyed


def _raw_rows(path: Path) -> list[dict[str, str]]:
    """The file as plain text cells, without any reversal of the guard."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter=";")]


def _file(folder: Path, name: str) -> Path:
    return folder / f"{name}.csv"


def _asset_row(tag: str, notes: str | None) -> dict[str, object]:
    return {
        "tag": tag,
        "type_code": "bed",
        "description": None,
        "location": None,
        "in_service_from": "2022-01-01",
        "in_service_until": None,
        "maintenance_interval_days": None,
        "notes": notes,
    }


def _spec(name: str) -> EntitySpec:
    spec = entity_spec(name)
    assert spec is not None
    return spec


# --------------------------------------------------------------------------- the round trip


def test_entity_names_are_the_sixteen_entities_in_import_order(seeded: DatabaseConnection) -> None:
    service = ExportService(seeded, CLOCK)
    assert service.entity_names() == ENTITY_NAMES
    assert tuple(spec.name for spec in ENTITIES) == ENTITY_NAMES


def test_export_all_writes_one_file_per_entity(seeded: DatabaseConnection, tmp_path: Path) -> None:
    out = tmp_path / "new" / "folder"
    files = ExportService(seeded, CLOCK).export_all(out)
    assert [item.entity for item in files] == list(ENTITY_NAMES)
    assert sorted(path.name for path in out.iterdir()) == sorted(f"{n}.csv" for n in ENTITY_NAMES)
    for item in files:
        assert item.path == _file(out, item.entity)
        assert item.rows == len(read_entity(item.path, _spec(item.entity)))


@pytest.mark.parametrize("spec", ENTITIES, ids=SPEC_IDS)
def test_files_read_back_as_the_database_rows(
    spec: EntitySpec, seeded: DatabaseConnection, export_dir: Path
) -> None:
    expected = _expected(seeded)[spec.name]
    actual = read_entity(_file(export_dir, spec.name), spec)
    assert len(actual) >= 2
    assert set(actual[0]) == set(spec.column_codes)
    assert _keyed(spec, actual) == _keyed(spec, expected)


def test_no_internal_id_is_exported() -> None:
    for spec in ENTITIES:
        assert not any(code == "id" or code.endswith("_id") for code in spec.column_codes)


def test_export_entity_overwrites_an_existing_file(
    seeded: DatabaseConnection, tmp_path: Path
) -> None:
    (tmp_path / "staff_member.csv").write_text("old content", encoding="utf-8")
    item = ExportService(seeded, CLOCK).export_entity("staff_member", tmp_path)
    assert item.rows == 2
    assert [row["identifier"] for row in read_entity(item.path, _spec("staff_member"))] == [
        "DEMO-00123",
        "DEMO-00124",
    ]


def test_unknown_entity_is_refused(seeded: DatabaseConnection, tmp_path: Path) -> None:
    with pytest.raises(ServiceError) as info:
        ExportService(seeded, CLOCK).export_entity("change_log", tmp_path)
    assert info.value.code == UNKNOWN_ENTITY
    assert list(tmp_path.glob("*.csv")) == []


def test_a_read_only_connection_can_export(
    seeded: DatabaseConnection, export_dir: Path, tmp_path: Path
) -> None:
    read_only = open_database(tmp_path / "test.sqlite3", read_only=True)
    try:
        out = tmp_path / "from_read_only"
        ExportService(read_only, CLOCK).export_all(out)
    finally:
        read_only.close()
    for name in ENTITY_NAMES:
        assert _file(out, name).read_bytes() == _file(export_dir, name).read_bytes()


# --------------------------------------------------------------------------- the format


def test_files_start_with_the_bom_and_use_semicolons(export_dir: Path) -> None:
    for spec in ENTITIES:
        data = _file(export_dir, spec.name).read_bytes()
        assert data.startswith(BOM)
        text = data[len(BOM) :].decode("utf-8")
        assert text.split("\r\n", 1)[0] == ";".join(spec.column_codes)
        assert text.endswith("\r\n")


def test_two_exports_are_byte_identical(seeded: DatabaseConnection, tmp_path: Path) -> None:
    service = ExportService(seeded, CLOCK)
    service.export_all(tmp_path / "one")
    service.export_all(tmp_path / "two")
    for name in ENTITY_NAMES:
        first = _file(tmp_path / "one", name).read_bytes()
        assert first == _file(tmp_path / "two", name).read_bytes()


def test_rows_are_written_sorted_by_the_natural_key(export_dir: Path) -> None:
    tags = [row["tag"] for row in read_entity(_file(export_dir, "asset"), _spec("asset"))]
    assert tags == sorted(tags)
    spec = _spec("staff_member")
    rows: list[dict[str, object]] = [
        {"identifier": "DEMO-B", "active_from": "2020-01-01"},
        {"identifier": "DEMO-A", "active_from": "2020-01-01"},
    ]
    path = _file(export_dir.parent, "ordered")
    write_entity(path, spec, rows)
    assert [r["identifier"] for r in read_entity(path, spec)] == ["DEMO-A", "DEMO-B"]


def test_fields_with_delimiters_quotes_and_line_breaks_survive(
    seeded: DatabaseConnection, export_dir: Path
) -> None:
    assets = read_entity(_file(export_dir, "asset"), _spec("asset"))
    description = next(row["description"] for row in assets if row["tag"] == "DEMO-BED-001")
    assert description == DESCRIPTION
    editions = read_entity(_file(export_dir, "exercise_edition"), _spec("exercise_edition"))
    notes = next(row["notes"] for row in editions if row["code"] == "DEMO-ED-1")
    assert notes == NOTES
    raw = _file(export_dir, "asset").read_bytes().decode("utf-8")
    assert 'Line one; ""quoted""\nline two\r\nline three' in raw
    staff = read_entity(_file(export_dir, "staff_member"), _spec("staff_member"))
    assert staff[0]["label"] == 'DEMO; "label"'


def test_non_ascii_text_round_trips(export_dir: Path) -> None:
    courses = read_entity(_file(export_dir, "training_course"), _spec("training_course"))
    labels = {row["code"]: row["label_pt_br"] for row in courses}
    assert labels["DEMO-C2"] == "Forma\u00e7\u00e3o DEMO"


def test_real_numbers_round_trip_exactly(tmp_path: Path) -> None:
    spec = _spec("training_record")
    values = [0.1 + 0.2, 8.5, 1e22, 5e-07, 1234567.125, 0.0, 1.0]
    rows: list[dict[str, object]] = [
        {
            "staff_identifier": "DEMO-1",
            "course_code": "007",
            "completed_on": f"2023-01-{index + 1:02d}",
            "hours": value,
        }
        for index, value in enumerate(values)
    ]
    path = tmp_path / "hours.csv"
    write_entity(path, spec, rows)
    assert [row["hours"] for row in read_entity(path, spec)] == values
    raw = [row["hours"] for row in _raw_rows(path)]
    assert raw[0] == "0.30000000000000004"
    assert raw[1] == "8.5"
    assert all("," not in cell for cell in raw)


# --------------------------------------------------------------------------- the formula guard


def test_services_data_is_guarded_in_the_raw_files(export_dir: Path) -> None:
    asset = next(r for r in _raw_rows(_file(export_dir, "asset")) if r["tag"] == "DEMO-BED-001")
    assert asset["notes"] == "'=1+1"
    other = next(r for r in _raw_rows(_file(export_dir, "asset")) if r["tag"] == "DEMO-BAY-002")
    assert other["location"] == "'@x"
    notes = {r["note"] for r in _raw_rows(_file(export_dir, "asset_status_event"))}
    assert "'@note" in notes
    notes = {r["note"] for r in _raw_rows(_file(export_dir, "maintenance_event"))}
    assert "'+x" in notes
    notes = {r["note"] for r in _raw_rows(_file(export_dir, "evaluation_result"))}
    assert "'-x" in notes
    # and the guard is gone again after reading
    assets = read_entity(_file(export_dir, "asset"), _spec("asset"))
    assert next(r["notes"] for r in assets if r["tag"] == "DEMO-BED-001") == "=1+1"


@pytest.mark.parametrize("text", AWKWARD)
def test_guard_is_exactly_reversible(text: str) -> None:
    assert unguard_cell(guard_cell(text)) == text


def test_guard_examples() -> None:
    assert guard_cell("=1+1") == "'=1+1"
    assert guard_cell("'x") == "''x"
    assert guard_cell("plain") == "plain"
    assert guard_cell("") == ""
    assert unguard_cell("'=1+1") == "=1+1"
    assert unguard_cell("'plain") == "'plain"
    assert unguard_cell("'") == "'"


@pytest.mark.parametrize("text", [s for s in AWKWARD if s])
def test_awkward_cells_round_trip_through_a_file(text: str, tmp_path: Path) -> None:
    spec = _spec("asset")
    path = tmp_path / "awkward.csv"
    write_entity(path, spec, [_asset_row("DEMO-A", text)])
    (raw,) = _raw_rows(path)
    guarded = text[0] in _GUARDED_FIRST
    assert raw["notes"] == ("'" + text if guarded else text)
    (row,) = read_entity(path, spec)
    assert row["notes"] == text


def test_tab_and_carriage_return_cells_are_prefixed_in_the_raw_text(tmp_path: Path) -> None:
    spec = _spec("asset")
    path = tmp_path / "ctrl.csv"
    write_entity(path, spec, [_asset_row("DEMO-T", "\tx"), _asset_row("DEMO-R", "\rx")])
    raw = path.read_bytes().decode("utf-8")
    assert ";'\tx\r\n" in raw
    assert ';"\'\rx"\r\n' in raw
    assert [row["notes"] for row in read_entity(path, spec)] == ["\rx", "\tx"]


def test_numbers_dates_and_money_are_never_guarded(tmp_path: Path) -> None:
    spec = _spec("budget_entry")
    path = tmp_path / "entry.csv"
    row: dict[str, object] = {
        "fiscal_year": 2024,
        "source_code": "DIRSA",
        "currency": "BRL",
        "description": "",
        "allocated": 100,
        "notes": None,
    }
    write_entity(path, spec, [row])
    (raw,) = _raw_rows(path)
    assert raw["fiscal_year"] == "2024"
    assert raw["allocated"] == "1.00"


# --------------------------------------------------------------------------- DEMO- prefix


def test_real_database_files_have_no_demo_prefix(export_dir: Path) -> None:
    names = sorted(path.name for path in export_dir.iterdir())
    assert len(names) == 16
    assert not any(name.startswith("DEMO-") for name in names)


def test_demo_database_files_all_start_with_demo(tmp_path: Path) -> None:
    conn = open_and_migrate(
        tmp_path / "demo.sqlite3",
        data_dir=tmp_path,
        identity=DatabaseIdentity.DEMO,
        backup=False,
    )
    try:
        app_meta.initialise(conn, is_demo=True, created_with="test")
        _seed(conn)
        out = tmp_path / "demo_out"
        ExportService(conn, CLOCK).export_all(out)
        single = ExportService(conn, CLOCK).export_entity("asset", tmp_path / "single")
    finally:
        conn.close()
    names = sorted(path.name for path in out.iterdir())
    assert names == sorted(f"DEMO-{name}.csv" for name in ENTITY_NAMES)
    assert single.path.name == "DEMO-asset.csv"


def test_file_name_depends_only_on_the_flag() -> None:
    spec = _spec("asset")
    assert export_file_name(spec, is_demo=False) == "asset.csv"
    assert export_file_name(spec, is_demo=True) == "DEMO-asset.csv"


# --------------------------------------------------------------------------- money and codes


def test_amounts_are_written_in_major_units_and_survive_exactly(export_dir: Path) -> None:
    raw_entries = {r["description"]: r for r in _raw_rows(_file(export_dir, "budget_entry"))}
    assert raw_entries['DEMO line; "A"']["allocated"] == "1234.56"
    assert raw_entries['DEMO line; "A"']["currency"] == "BRL"
    assert raw_entries["big"]["allocated"] == "90071992547409.93"
    assert raw_entries["small"]["allocated"] == "0.05"
    usd = next(r for r in _raw_rows(_file(export_dir, "budget_entry")) if r["currency"] == "USD")
    assert usd["allocated"] == "20.00"
    eur = next(r for r in _raw_rows(_file(export_dir, "budget_entry")) if r["currency"] == "EUR")
    assert eur["allocated"] == ""
    entries = read_entity(_file(export_dir, "budget_entry"), _spec("budget_entry"))
    by_description = {r["description"]: r for r in entries if r["currency"] != "EUR"}
    assert by_description['DEMO line; "A"']["allocated"] == 123456
    assert by_description["big"]["allocated"] == BIG_MINOR
    assert BIG_MINOR > 2**53
    assert by_description["small"]["allocated"] == 5
    assert [r["allocated"] for r in entries if r["currency"] == "EUR"] == [None]
    assert next(r for r in entries if r["currency"] == "USD")["allocated"] == 2000


def test_execution_amounts_keep_their_currency(export_dir: Path) -> None:
    raw = _raw_rows(_file(export_dir, "budget_execution"))
    assert {(r["currency"], r["amount"]) for r in raw} == {
        ("BRL", "1000.00"),
        ("BRL", "234.56"),
        ("EUR", "2.50"),
        ("USD", "0.07"),
    }
    rows = read_entity(_file(export_dir, "budget_execution"), _spec("budget_execution"))
    assert len(rows) == 4
    assert {(r["currency"], r["amount"]) for r in rows} == {
        ("BRL", 23456),
        ("BRL", 100000),
        ("EUR", 250),
        ("USD", 7),
    }


def test_empty_description_is_the_empty_text(export_dir: Path) -> None:
    entries = read_entity(_file(export_dir, "budget_entry"), _spec("budget_entry"))
    assert [r["description"] for r in entries if r["currency"] == "EUR"] == [""]


def test_codes_keep_their_leading_zeros(export_dir: Path) -> None:
    courses = _raw_rows(_file(export_dir, "training_course"))
    assert "007" in {r["code"] for r in courses}
    staff = read_entity(_file(export_dir, "staff_member"), _spec("staff_member"))
    assert staff[0]["identifier"] == "DEMO-00123"
    assert all(isinstance(r["identifier"], str) for r in staff)
    records = read_entity(_file(export_dir, "training_record"), _spec("training_record"))
    assert {r["course_code"] for r in records} == {"007", "DEMO-C2"}
    assets = read_entity(_file(export_dir, "asset"), _spec("asset"))
    assert "00789" in {r["tag"] for r in assets}


def test_an_eleven_digit_identifier_is_refused_by_the_service(
    migrated_db: DatabaseConnection,
) -> None:
    with pytest.raises(ServiceError) as info:
        PersonnelService(migrated_db, CLOCK).create_staff(
            StaffInput(identifier="12345678901", active_from="2020-01-01")
        )
    assert info.value.code == IDENTIFIER_LOOKS_LIKE_NATIONAL_ID


def test_money_conversion_errors(tmp_path: Path) -> None:
    spec = _spec("budget_entry")
    row: dict[str, object] = {
        "fiscal_year": 2024,
        "source_code": "DIRSA",
        "currency": "XXX",
        "description": "",
        "allocated": 100,
    }
    with pytest.raises(CsvFormatError) as info:
        write_entity(tmp_path / "bad.csv", spec, [row])
    assert info.value.code == "INVALID_CURRENCY"
    assert not (tmp_path / "bad.csv.part").exists()
    assert not (tmp_path / "bad.csv").exists()
    path = tmp_path / "decimals.csv"
    header = ";".join(spec.column_codes)
    path.write_bytes(BOM + f"{header}\r\n2024;DIRSA;BRL;;1.234;\r\n".encode())
    with pytest.raises(CsvFormatError) as info:
        read_entity(path, spec)
    assert info.value.code == "TOO_MANY_DECIMALS"


def test_reader_rejects_other_files(tmp_path: Path) -> None:
    spec = _spec("staff_member")
    wrong_header = tmp_path / "wrong.csv"
    wrong_header.write_bytes(BOM + b"a;b\r\n")
    with pytest.raises(CsvFormatError) as info:
        read_entity(wrong_header, spec)
    assert info.value.code == "HEADER_MISMATCH"
    legacy = tmp_path / "legacy.csv"
    legacy.write_bytes(";".join(spec.column_codes).encode() + b"\r\nDEMO-\xe9;;;2020-01-01;\r\n")
    with pytest.raises(CsvFormatError) as info:
        read_entity(legacy, spec)
    assert info.value.code == "NOT_UTF8"
    bad_date = tmp_path / "date.csv"
    bad_text = ";".join(spec.column_codes) + "\r\nDEMO-A;;;2020-13-01;\r\n"
    bad_date.write_bytes(BOM + bad_text.encode())
    with pytest.raises(CsvFormatError) as info:
        read_entity(bad_date, spec)
    assert info.value.code == "INVALID_DATE"
    assert info.value.column == "active_from"


# --------------------------------------------------------------------------- failures


def test_a_failing_write_reports_the_entity_and_leaves_no_partial_file(
    seeded: DatabaseConnection, tmp_path: Path
) -> None:
    out = tmp_path / "blocked"
    (out / "staff_member.csv").mkdir(parents=True)
    with pytest.raises(ServiceError) as info:
        ExportService(seeded, CLOCK).export_all(out)
    assert info.value.code == EXPORT_FAILED
    assert info.value.field == "staff_member"
    assert list(out.glob("*.part")) == []
    assert (out / "staff_member.csv").is_dir()
    # the files finished before the failure stay, complete and readable
    for name in ("training_course", "asset_type", "evaluation_metric", "funding_source"):
        assert read_entity(_file(out, name), _spec(name))
    assert not _file(out, "ppe_certification").exists()


def test_write_entity_leaves_no_temporary_file_on_failure(tmp_path: Path) -> None:
    spec = _spec("staff_member")
    (tmp_path / "staff_member.csv").mkdir()
    with pytest.raises(OSError):
        write_entity(
            tmp_path / "staff_member.csv",
            spec,
            [{"identifier": "DEMO-A", "active_from": "2020-01-01"}],
        )
    assert list(tmp_path.glob("*.part")) == []


def test_an_output_path_that_is_a_file_fails_cleanly(
    seeded: DatabaseConnection, tmp_path: Path
) -> None:
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(ServiceError) as info:
        ExportService(seeded, CLOCK).export_all(blocker)
    assert info.value.code == EXPORT_FAILED
    assert info.value.field == "out_dir"


# --------------------------------------------------------------------------- the documentation


_ENTITY_HEADING = re.compile(r"### `([a-z_]+)`")


def _documented_tables() -> dict[str, list[tuple[str, str, bool, bool, str]]]:
    """``{entity: [(code, kind, is_key, is_required, meaning), ...]}`` from the markdown tables."""
    tables: dict[str, list[tuple[str, str, bool, bool, str]]] = {}
    current: str | None = None
    for line in DOCS.read_text(encoding="utf-8").splitlines():
        heading = _ENTITY_HEADING.fullmatch(line.strip())
        if heading is not None:
            current = heading.group(1)
            assert current not in tables, f"duplicate heading for {current}"
            tables[current] = []
            continue
        if line.startswith("#"):
            current = None
            continue
        if current is None or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[0] == "Column" or set(cells[0]) <= set("-: "):
            continue
        assert len(cells) == 5, f"{current}: malformed table row {line!r}"
        tables[current].append(
            (cells[0].strip("`"), cells[1], cells[2] == "yes", cells[3] == "yes", cells[4])
        )
    return tables


def test_every_column_is_documented_and_nothing_else() -> None:
    tables = _documented_tables()
    assert set(tables) == set(ENTITY_NAMES)
    for spec in ENTITIES:
        documented = tables[spec.name]
        assert [row[0] for row in documented] == list(spec.column_codes), spec.name
        for (code, kind, is_key, is_required, meaning), column in zip(
            documented, spec.columns, strict=True
        ):
            assert kind == column.kind.value, f"{spec.name}.{code}"
            assert is_key == (code in spec.natural_key), f"{spec.name}.{code}"
            assert is_required == column.required, f"{spec.name}.{code}"
            assert meaning, f"{spec.name}.{code}"
        assert {row[0] for row in documented if row[2]} == set(spec.natural_key)


def test_document_has_the_required_sections() -> None:
    text = DOCS.read_text(encoding="utf-8")
    assert "## Import rules" in text
    assert "T8.4" in text
    assert "internal data" in text
    assert "UTF-8 with a byte order mark" in text
