# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the infrastructure service (PLAN.md T3.3); fictitious data only."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain import infrastructure as rules
from cbrn_dashboard.domain.config import ReadinessConfig
from cbrn_dashboard.domain.indicators import decode_dimension
from cbrn_dashboard.domain.infrastructure import (
    Asset,
    AssetStatus,
    AssetType,
    InfrastructureRules,
    MaintenanceEvent,
    MaintenanceKind,
    ScheduleBasis,
    StatusEvent,
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
)
from cbrn_dashboard.services.infrastructure import (
    BUILT_IN_TYPE,
    DUPLICATE_CODE,
    DUPLICATE_MAINTENANCE,
    DUPLICATE_TAG,
    IN_SERVICE_UNTIL_BEFORE_FROM,
    INITIAL_STATUS_REQUIRED,
    INVALID_INTERVAL,
    INVALID_MAINTENANCE_KIND,
    INVALID_STATUS,
    NEGATIVE_INTERVAL,
    NEXT_DUE_BEFORE_PERFORMED,
    STATUS_DATE_TAKEN,
    TEXT_TOO_LONG,
    TYPE_IN_USE,
    TYPE_INACTIVE,
    AssetInput,
    AssetTypeInput,
    AssetTypeView,
    InfrastructureService,
    type_label,
)
from cbrn_dashboard.storage import infrastructure_repo
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.repository import WriteContext
from cbrn_dashboard.storage.settings_repo import save_config
from tests.services.conftest import ChangeLogRows

AS_OF = date(2026, 3, 5)
NOW_TEXT = "2026-03-05T12:00:00Z"
OPERATOR = "op-demo"

_TABLES = ("asset_type", "asset", "asset_status_event", "maintenance_event", "change_log")
_INTERVAL_FIELD = "default_maintenance_interval_days"


@pytest.fixture
def service(db: DatabaseConnection, clock: FixedClock) -> InfrastructureService:
    return InfrastructureService(db, clock, lambda: OPERATOR)


def _error(call: Callable[[], object]) -> ServiceError:
    with pytest.raises(ServiceError) as info:
        call()
    return info.value


def _count(conn: DatabaseConnection, table: str) -> int:
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
    return int(row[0])


def _state(conn: DatabaseConnection) -> tuple[int, ...]:
    """Row counts of every table the service writes (change_log included)."""
    return tuple(_count(conn, table) for table in _TABLES)


def _refused(
    conn: DatabaseConnection, call: Callable[[], object], code: str, field: str | None = None
) -> None:
    """The call raises ``code`` (and ``field`` when given) and writes nothing at all."""
    before = _state(conn)
    error = _error(call)
    assert error.code == code
    if field is not None:
        assert error.field == field
    assert _state(conn) == before


def _entities(rows: list[dict[str, object]]) -> Counter[tuple[object, object]]:
    return Counter((row["entity"], row["action"]) for row in rows)


def _type_id(service: InfrastructureService, code: str) -> int:
    for view in service.list_types(include_inactive=True):
        if view.code == code:
            return view.id
    raise AssertionError(code)


def _user_type(
    service: InfrastructureService,
    code: str = "DEMO-TYPE",
    interval: int | None = None,
    active: bool = True,
) -> int:
    data = AssetTypeInput(
        code=code,
        label_pt_br="Tipo demo",
        label_en_us="Demo type",
        default_maintenance_interval_days=interval,
        active=active,
    )
    return service.create_type(data)


def _input(type_id: int | None, /, **changes: Any) -> AssetInput:
    base = AssetInput(tag="DEMO-A001", type_id=type_id, in_service_from="2025-01-01")
    return replace(base, **changes)


def _asset(
    service: InfrastructureService,
    tag: str,
    type_id: int,
    in_service_from: str = "2025-12-01",
    status: str = "operational",
    in_service_until: str | None = None,
    interval: int | None = None,
) -> int:
    data = AssetInput(
        tag=tag,
        type_id=type_id,
        in_service_from=in_service_from,
        in_service_until=in_service_until,
        maintenance_interval_days=interval,
    )
    return service.create_asset(data, status)


# --------------------------------------------------------------------------- change log


def test_every_write_is_logged_with_operator_and_clock(
    service: InfrastructureService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    type_id = _user_type(service)
    service.update_type(type_id, AssetTypeInput("DEMO-TYPE", "Tipo novo"))
    service.deactivate_type(type_id)
    other_type = _user_type(service, "DEMO-TYPE-2")
    asset_id = _asset(service, "DEMO-A001", other_type)
    service.update_asset(asset_id, _input(other_type, location="Hall"))
    service.retire_asset(asset_id, "2026-01-31")
    event_id = service.change_status(asset_id, "2026-01-10", "degraded")
    service.update_status_event(event_id, "2026-01-10", "out_of_service", "worse")
    maintenance_id = service.record_maintenance(asset_id, "2026-01-12", "corrective")
    service.update_maintenance(maintenance_id, "2026-01-12", "corrective", note="fixed")
    service.delete_maintenance(maintenance_id)
    service.delete_status_event(event_id)
    service.delete_asset(asset_id)
    service.delete_type(type_id)
    rows = change_log_rows(db)
    assert [(row["entity"], row["action"]) for row in rows] == [
        ("asset_type", "insert"),
        ("asset_type", "update"),
        ("asset_type", "update"),
        ("asset_type", "insert"),
        ("asset", "insert"),
        ("asset_status_event", "insert"),
        ("asset", "update"),
        ("asset", "update"),
        ("asset_status_event", "insert"),
        ("asset_status_event", "update"),
        ("maintenance_event", "insert"),
        ("maintenance_event", "update"),
        ("maintenance_event", "delete"),
        ("asset_status_event", "delete"),
        ("asset", "delete"),
        ("asset_status_event", "delete"),
        ("asset_type", "delete"),
    ]
    assert all(row["operator"] == OPERATOR and row["at_utc"] == NOW_TEXT for row in rows)


def test_creating_an_asset_logs_the_asset_and_its_initial_status(
    service: InfrastructureService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    type_id = _user_type(service)
    before = len(change_log_rows(db))
    asset_id = service.create_asset(_input(type_id, in_service_from="2025-06-01"), "degraded")
    rows = change_log_rows(db)[before:]
    assert [(row["entity"], row["action"]) for row in rows] == [
        ("asset", "insert"),
        ("asset_status_event", "insert"),
    ]
    assert rows[0]["entity_id"] == asset_id
    assert all(row["operator"] == OPERATOR and row["at_utc"] == NOW_TEXT for row in rows)
    after = json.loads(str(rows[1]["after_json"]))
    assert (after["asset_id"], after["effective_on"], after["status"]) == (
        asset_id,
        "2025-06-01",
        "degraded",
    )
    detail = service.get_asset(asset_id)
    assert [(e.effective_on, e.status) for e in detail.status_events] == [
        (date(2025, 6, 1), AssetStatus.DEGRADED)
    ]


def test_operator_label_is_read_for_each_write(
    db: DatabaseConnection, clock: FixedClock, change_log_rows: ChangeLogRows
) -> None:
    current = ["first"]
    service = InfrastructureService(db, clock, lambda: current[0])
    _user_type(service)
    current[0] = "second"
    _user_type(service, "DEMO-TYPE-2")
    assert [row["operator"] for row in change_log_rows(db)] == ["first", "second"]
    _user_type(InfrastructureService(db, clock), "DEMO-TYPE-3")
    assert change_log_rows(db)[-1]["operator"] == ""


def test_deleting_an_asset_logs_it_and_each_of_its_events(
    service: InfrastructureService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    type_id = _user_type(service)
    asset_id = _asset(service, "DEMO-A001", type_id)
    other_id = _asset(service, "DEMO-A002", type_id)
    service.change_status(asset_id, "2026-01-10", "degraded")
    service.change_status(asset_id, "2026-02-10", "operational")
    service.record_maintenance(asset_id, "2026-01-12", "corrective")
    service.record_maintenance(asset_id, "2026-02-12", "inspection")
    before = len(change_log_rows(db))
    service.delete_asset(asset_id)
    rows = change_log_rows(db)[before:]
    assert _entities(rows) == Counter(
        {
            ("asset", "delete"): 1,
            ("asset_status_event", "delete"): 3,
            ("maintenance_event", "delete"): 2,
        }
    )
    assert all(row["operator"] == OPERATOR and row["at_utc"] == NOW_TEXT for row in rows)
    assert _count(db, "asset") == 1
    assert _count(db, "asset_status_event") == 1
    assert _count(db, "maintenance_event") == 0
    assert [a.id for a in service.list_assets()] == [other_id]


def test_a_failure_after_the_first_write_rolls_everything_back(
    service: InfrastructureService,
    db: DatabaseConnection,
    change_log_rows: ChangeLogRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    type_id = _user_type(service)
    before = (_state(db), change_log_rows(db))

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError

    monkeypatch.setattr(infrastructure_repo, "insert_status_event", boom)
    with pytest.raises(RuntimeError):
        service.create_asset(_input(type_id), "operational")
    assert (_state(db), change_log_rows(db)) == before
    assert not db.in_transaction


# --------------------------------------------------------------------------- asset types


def test_built_in_types_are_seeded_without_labels(service: InfrastructureService) -> None:
    views = {view.code: view for view in service.list_types()}
    assert set(views) == {"bed", "bay", "neg_pressure_filtration", "decon_tent"}
    assert all(view.built_in and view.active for view in views.values())
    assert all(view.label_pt_br is None for view in views.values())
    assert all(view.default_maintenance_interval_days is None for view in views.values())


def test_built_in_type_cannot_be_deleted(
    service: InfrastructureService, db: DatabaseConnection
) -> None:
    type_id = _type_id(service, "decon_tent")
    _refused(db, lambda: service.delete_type(type_id), BUILT_IN_TYPE)
    assert _type_id(service, "decon_tent") == type_id


def test_built_in_type_can_be_deactivated_and_reactivated(service: InfrastructureService) -> None:
    type_id = _type_id(service, "bay")
    service.deactivate_type(type_id)
    assert "bay" not in {view.code for view in service.list_types()}
    inactive = service.get_type(type_id)
    assert not inactive.active
    assert inactive.built_in
    service.update_type(type_id, AssetTypeInput("bay", None, active=True))
    assert service.get_type(type_id).active


def test_built_in_default_interval_can_be_edited(
    service: InfrastructureService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    type_id = _type_id(service, "bed")
    service.update_type(type_id, AssetTypeInput("bed", None, default_maintenance_interval_days=90))
    view = service.get_type(type_id)
    assert view.default_maintenance_interval_days == 90
    assert view.built_in
    assert view.label_pt_br is None
    assert [(r["entity"], r["action"]) for r in change_log_rows(db)] == [("asset_type", "update")]
    service.update_type(type_id, AssetTypeInput("bed", None, default_maintenance_interval_days=0))
    assert service.get_type(type_id).default_maintenance_interval_days == 0
    service.update_type(type_id, AssetTypeInput("bed", None))
    assert service.get_type(type_id).default_maintenance_interval_days is None


def test_built_in_code_and_flag_cannot_change(
    service: InfrastructureService, db: DatabaseConnection
) -> None:
    type_id = _type_id(service, "bed")
    _refused(
        db,
        lambda: service.update_type(type_id, AssetTypeInput("bed2", "Leito")),
        BUILT_IN_TYPE,
        "code",
    )
    # labels given for a built-in type are not stored: the UI names it (labels.py)
    service.update_type(type_id, AssetTypeInput("bed", "Leito", "Bed", "Cama"))
    view = service.get_type(type_id)
    assert view.built_in
    assert (view.label_pt_br, view.label_en_us, view.label_es_es) == (None, None, None)


def test_user_type_needs_a_pt_br_label(
    service: InfrastructureService, db: DatabaseConnection
) -> None:
    for label in (None, "", "   "):
        _refused(
            db,
            lambda label=label: service.create_type(AssetTypeInput("DEMO-TYPE", label)),
            LABEL_PT_BR_REQUIRED,
            "label_pt_br",
        )
    type_id = service.create_type(AssetTypeInput("DEMO-TYPE", "  Tipo  "))
    view = service.get_type(type_id)
    assert (view.label_pt_br, view.label_en_us, view.label_es_es) == ("Tipo", None, None)
    assert not view.built_in
    assert view.default_maintenance_interval_days is None
    _refused(
        db,
        lambda: service.update_type(type_id, AssetTypeInput("DEMO-TYPE", None)),
        LABEL_PT_BR_REQUIRED,
    )


def test_user_type_labels_in_three_languages(service: InfrastructureService) -> None:
    type_id = service.create_type(AssetTypeInput("DEMO-TYPE", "Tipo", "Type", "Tipo ES", 45))
    view = service.get_type(type_id)
    assert (view.label_pt_br, view.label_en_us, view.label_es_es) == ("Tipo", "Type", "Tipo ES")
    assert view.default_maintenance_interval_days == 45
    service.update_type(type_id, AssetTypeInput("DEMO-TYPE", "Tipo 2", None, "Nuevo", 0))
    view = service.get_type(type_id)
    assert (view.label_pt_br, view.label_en_us, view.label_es_es) == ("Tipo 2", None, "Nuevo")
    assert view.default_maintenance_interval_days == 0


def test_type_label_fallback() -> None:
    def view(pt: str | None, en: str | None, es: str | None) -> AssetTypeView:
        return AssetTypeView(1, "code-x", False, pt, en, es, None, True)

    full = view("Nome", "Name", "Nombre")
    assert type_label(full, "pt_BR") == "Nome"
    assert type_label(full, "en-US") == "Name"
    assert type_label(full, "es_ES") == "Nombre"
    assert type_label(view("Nome", "Name", None), "es_ES") == "Nome"
    assert type_label(view("Nome", None, "  "), "es_ES") == "Nome"
    assert type_label(view(None, "Name", None), "es_ES") == "Name"
    assert type_label(view(None, None, None), "en_US") == "code-x"


def test_type_in_use_cannot_be_deleted_but_an_unused_one_can(
    service: InfrastructureService, db: DatabaseConnection
) -> None:
    used = _user_type(service)
    unused = _user_type(service, "DEMO-UNUSED")
    asset_id = _asset(service, "DEMO-A001", used)
    _refused(db, lambda: service.delete_type(used), TYPE_IN_USE)
    service.delete_type(unused)
    assert unused not in {view.id for view in service.list_types(include_inactive=True)}
    service.delete_asset(asset_id)
    service.delete_type(used)
    assert {view.code for view in service.list_types(include_inactive=True)} == {
        "bed",
        "bay",
        "neg_pressure_filtration",
        "decon_tent",
    }


def test_type_code_rules(service: InfrastructureService, db: DatabaseConnection) -> None:
    used = _user_type(service)
    other = _user_type(service, "DEMO-OTHER")
    _refused(db, lambda: service.create_type(AssetTypeInput("", "x")), REQUIRED, "code")
    _refused(db, lambda: service.create_type(AssetTypeInput("a b", "x")), INVALID_CODE, "code")
    _refused(db, lambda: service.create_type(AssetTypeInput("bed", "x")), DUPLICATE_CODE, "code")
    _refused(
        db,
        lambda: service.create_type(AssetTypeInput("DEMO-TYPE", "x")),
        DUPLICATE_CODE,
        "code",
    )
    _refused(
        db,
        lambda: service.update_type(other, AssetTypeInput("DEMO-TYPE", "x")),
        DUPLICATE_CODE,
        "code",
    )
    # free to change while no asset uses the type; frozen afterwards
    service.update_type(used, AssetTypeInput("DEMO-RENAMED", "x"))
    assert service.get_type(used).code == "DEMO-RENAMED"
    _asset(service, "DEMO-A001", used)
    _refused(
        db,
        lambda: service.update_type(used, AssetTypeInput("DEMO-TYPE", "x")),
        CODE_IMMUTABLE,
        "code",
    )
    service.update_type(used, AssetTypeInput("DEMO-RENAMED", "Outro", None, None, 10))
    assert service.get_type(used).label_pt_br == "Outro"


def test_inactive_type_refuses_new_assets_but_keeps_its_own(
    service: InfrastructureService, db: DatabaseConnection
) -> None:
    type_id = _user_type(service)
    other = _user_type(service, "DEMO-OTHER")
    asset_id = _asset(service, "DEMO-A001", type_id)
    other_asset = _asset(service, "DEMO-A003", other)
    service.deactivate_type(type_id)
    _refused(
        db,
        lambda: service.create_asset(_input(type_id, tag="DEMO-A002"), "operational"),
        TYPE_INACTIVE,
        "type_id",
    )
    # an asset already of the inactive type can still be edited ...
    service.update_asset(asset_id, _input(type_id, location="Hall"))
    # ... but no asset can be moved into it
    _refused(
        db,
        lambda: service.update_asset(other_asset, _input(type_id, tag="DEMO-A003")),
        TYPE_INACTIVE,
        "type_id",
    )
    assert type_id not in {view.id for view in service.list_types()}
    assert type_id in {view.id for view in service.list_types(include_inactive=True)}


def test_type_intervals(service: InfrastructureService, db: DatabaseConnection) -> None:
    def make(value: Any) -> AssetTypeInput:
        return AssetTypeInput("DEMO-TYPE", "x", default_maintenance_interval_days=value)

    _refused(db, lambda: service.create_type(make(-1)), NEGATIVE_INTERVAL, _INTERVAL_FIELD)
    bad_values: list[Any] = [1.5, "30", True, False]
    for bad in bad_values:
        _refused(
            db, lambda bad=bad: service.create_type(make(bad)), INVALID_INTERVAL, _INTERVAL_FIELD
        )
    zero = service.create_type(make(0))
    assert service.get_type(zero).default_maintenance_interval_days == 0
    unset = service.create_type(replace(make(None), code="DEMO-UNSET"))
    assert service.get_type(unset).default_maintenance_interval_days is None


# --------------------------------------------------------------------------- assets


def test_new_asset_without_initial_status_is_rejected_and_nothing_is_written(
    service: InfrastructureService, db: DatabaseConnection
) -> None:
    type_id = _user_type(service)
    missing_values: list[Any] = [None, "", "  "]
    for missing in missing_values:
        _refused(
            db,
            lambda missing=missing: service.create_asset(_input(type_id), missing),
            INITIAL_STATUS_REQUIRED,
            "initial_status",
        )
    assert _count(db, "asset") == 0
    assert _count(db, "asset_status_event") == 0


@pytest.mark.parametrize(
    ("changes", "code", "field"),
    [
        ({"tag": ""}, REQUIRED, "tag"),
        ({"tag": "   "}, REQUIRED, "tag"),
        ({"type_id": None}, REQUIRED, "type_id"),
        ({"type_id": 9999}, NOT_FOUND, "type_id"),
        ({"in_service_from": None}, REQUIRED, "in_service_from"),
        ({"in_service_from": ""}, REQUIRED, "in_service_from"),
        ({"in_service_from": "2025-13-01"}, INVALID_DATE, "in_service_from"),
        ({"in_service_from": "01/02/2025"}, INVALID_DATE, "in_service_from"),
        ({"in_service_until": "2025-02-30"}, INVALID_DATE, "in_service_until"),
        ({"in_service_until": "2024-12-31"}, IN_SERVICE_UNTIL_BEFORE_FROM, "in_service_until"),
        ({"maintenance_interval_days": -5}, NEGATIVE_INTERVAL, "maintenance_interval_days"),
        ({"maintenance_interval_days": 2.5}, INVALID_INTERVAL, "maintenance_interval_days"),
        ({"maintenance_interval_days": True}, INVALID_INTERVAL, "maintenance_interval_days"),
        ({"tag": "T" * 65}, TEXT_TOO_LONG, "tag"),
    ],
)
def test_asset_validation_refuses_and_writes_nothing(
    service: InfrastructureService,
    db: DatabaseConnection,
    changes: dict[str, Any],
    code: str,
    field: str,
) -> None:
    type_id = _user_type(service)
    data = _input(type_id, **changes)
    _refused(db, lambda: service.create_asset(data, "operational"), code, field)
    # the same input is refused on update as well
    asset_id = _asset(service, "DEMO-A777", type_id)
    update = _input(type_id, **{"tag": "DEMO-A777", **changes})
    _refused(db, lambda: service.update_asset(asset_id, update), code, field)


def test_asset_tag_rules(service: InfrastructureService, db: DatabaseConnection) -> None:
    type_id = _user_type(service)
    first = _asset(service, "DEMO-A001", type_id)
    second = _asset(service, "DEMO-A002", type_id)
    _refused(
        db,
        lambda: service.create_asset(_input(type_id, tag="DEMO-A001"), "operational"),
        DUPLICATE_TAG,
        "tag",
    )
    _refused(
        db,
        lambda: service.create_asset(_input(type_id, tag="  DEMO-A001 "), "operational"),
        DUPLICATE_TAG,
        "tag",
    )
    _refused(
        db,
        lambda: service.update_asset(second, _input(type_id, tag="DEMO-A001")),
        DUPLICATE_TAG,
        "tag",
    )
    service.update_asset(first, _input(type_id, tag="DEMO-A001", notes="same tag is fine"))
    assert service.get_asset(first).asset.notes == "same tag is fine"
    service.create_asset(_input(type_id, tag="T" * 64), "operational")  # exactly the limit
    service.update_asset(first, _input(type_id, tag="  DEMO-A001B  "))
    assert service.get_asset(first).asset.tag == "DEMO-A001B"


def test_status_must_be_storable(service: InfrastructureService, db: DatabaseConnection) -> None:
    type_id = _user_type(service)
    asset_id = _asset(service, "DEMO-A001", type_id)
    bad_values: list[Any] = ["unknown", AssetStatus.UNKNOWN, "bogus", "OPERATIONAL", 3]
    for bad in bad_values:
        _refused(
            db,
            lambda bad=bad: service.create_asset(_input(type_id, tag="DEMO-B"), bad),
            INVALID_STATUS,
            "status",
        )
        _refused(
            db,
            lambda bad=bad: service.change_status(asset_id, "2026-01-01", bad),
            INVALID_STATUS,
            "status",
        )
    service.change_status(asset_id, "2026-01-01", AssetStatus.OUT_OF_SERVICE)
    service.change_status(asset_id, "2026-01-02", "degraded")


def test_asset_fields_are_stored_and_trimmed(service: InfrastructureService) -> None:
    type_id = _user_type(service)
    data = AssetInput(
        tag="DEMO-A001",
        type_id=type_id,
        in_service_from=date(2025, 5, 1),
        in_service_until="2026-05-01",
        description="  Demo bed  ",
        location=" ",
        maintenance_interval_days=0,
        notes="n",
    )
    asset_id = service.create_asset(data, AssetStatus.DEGRADED)
    asset = service.get_asset(asset_id).asset
    assert asset.type_code == "DEMO-TYPE"
    assert (asset.in_service_from, asset.in_service_until) == (date(2025, 5, 1), date(2026, 5, 1))
    assert (asset.description, asset.location, asset.notes) == ("Demo bed", None, "n")
    assert asset.maintenance_interval_days == 0


def test_unknown_ids_are_not_found(service: InfrastructureService, db: DatabaseConnection) -> None:
    type_id = _user_type(service)
    _asset(service, "DEMO-A001", type_id)
    calls: list[Callable[[], object]] = [
        lambda: service.get_type(999),
        lambda: service.update_type(999, AssetTypeInput("X", "x")),
        lambda: service.deactivate_type(999),
        lambda: service.delete_type(999),
        lambda: service.get_asset(999),
        lambda: service.asset_history(999),
        lambda: service.update_asset(999, _input(type_id)),
        lambda: service.retire_asset(999, "2026-01-01"),
        lambda: service.delete_asset(999),
        lambda: service.change_status(999, "2026-01-01", "operational"),
        lambda: service.update_status_event(999, "2026-01-01", "operational"),
        lambda: service.delete_status_event(999),
        lambda: service.record_maintenance(999, "2026-01-01", "preventive"),
        lambda: service.update_maintenance(999, "2026-01-01", "preventive"),
        lambda: service.delete_maintenance(999),
    ]
    for call in calls:
        _refused(db, call, NOT_FOUND)


# --------------------------------------------------------------------------- status events


def test_status_change_adds_an_event_and_a_second_one_on_the_same_date_is_refused(
    service: InfrastructureService, db: DatabaseConnection
) -> None:
    type_id = _user_type(service)
    asset_id = _asset(service, "DEMO-A001", type_id, in_service_from="2025-12-01")
    event_id = service.change_status(asset_id, date(2026, 2, 1), "degraded", " worn ")
    history = service.asset_history(asset_id).status_events
    assert [(e.effective_on, e.status, e.note) for e in history] == [
        (date(2025, 12, 1), AssetStatus.OPERATIONAL, None),
        (date(2026, 2, 1), AssetStatus.DEGRADED, "worn"),
    ]
    assert history[1].id == event_id
    _refused(
        db,
        lambda: service.change_status(asset_id, "2026-02-01", "operational"),
        STATUS_DATE_TAKEN,
        "effective_on",
    )
    # the date of the initial event is taken as well
    _refused(
        db,
        lambda: service.change_status(asset_id, "2025-12-01", "degraded"),
        STATUS_DATE_TAKEN,
    )
    _refused(db, lambda: service.change_status(asset_id, "2026-13-01", "degraded"), INVALID_DATE)
    _refused(db, lambda: service.change_status(asset_id, "", "degraded"), REQUIRED)
    assert len(service.asset_history(asset_id).status_events) == 2


def test_status_event_corrections(service: InfrastructureService, db: DatabaseConnection) -> None:
    type_id = _user_type(service)
    asset_id = _asset(service, "DEMO-A001", type_id, in_service_from="2025-12-01")
    other_id = _asset(service, "DEMO-A002", type_id, in_service_from="2026-02-01")
    event_id = service.change_status(asset_id, "2026-02-01", "degraded")
    initial_id = service.asset_history(asset_id).status_events[0].id
    service.update_status_event(event_id, "2026-02-01", "out_of_service", "n")  # same date: fine
    service.update_status_event(event_id, "2026-02-02", "out_of_service")
    _refused(
        db,
        lambda: service.update_status_event(event_id, "2025-12-01", "degraded"),
        STATUS_DATE_TAKEN,
        "effective_on",
    )
    _refused(db, lambda: service.update_status_event(event_id, "x", "degraded"), INVALID_DATE)
    _refused(
        db,
        lambda: service.update_status_event(event_id, "2026-02-03", "unknown"),
        INVALID_STATUS,
    )
    history = service.asset_history(asset_id).status_events
    assert [(e.effective_on, e.status) for e in history] == [
        (date(2025, 12, 1), AssetStatus.OPERATIONAL),
        (date(2026, 2, 2), AssetStatus.OUT_OF_SERVICE),
    ]
    service.delete_status_event(event_id)
    assert [e.id for e in service.asset_history(asset_id).status_events] == [initial_id]
    assert len(service.asset_history(other_id).status_events) == 1


def test_status_changes_are_seen_by_the_as_of_views(service: InfrastructureService) -> None:
    type_id = _user_type(service)
    asset_id = _asset(service, "DEMO-A001", type_id, in_service_from="2025-12-01")
    service.change_status(asset_id, "2026-03-01", "out_of_service")
    service.change_status(asset_id, "2026-03-10", "operational")

    def status_on(day: date) -> AssetStatus:
        return service.asset_rows(day)[0].status

    assert status_on(date(2026, 2, 28)) is AssetStatus.OPERATIONAL
    assert status_on(date(2026, 3, 1)) is AssetStatus.OUT_OF_SERVICE
    assert status_on(date(2026, 3, 9)) is AssetStatus.OUT_OF_SERVICE
    assert status_on(date(2026, 3, 10)) is AssetStatus.OPERATIONAL
    assert status_on(date(2025, 11, 30)) is AssetStatus.UNKNOWN


# --------------------------------------------------------------------------- maintenance


def test_recording_maintenance_updates_the_due_date(service: InfrastructureService) -> None:
    type_id = _user_type(service, interval=30)
    asset_id = _asset(service, "DEMO-A001", type_id, in_service_from="2025-12-01")
    row = service.asset_rows(AS_OF)[0]
    assert (row.due_on, row.basis) == (date(2025, 12, 31), ScheduleBasis.IN_SERVICE_PLUS_INTERVAL)
    assert row.overdue
    assert row.last_maintenance_on is None

    service.record_maintenance(asset_id, "2026-02-20", "preventive")
    row = service.asset_rows(AS_OF)[0]
    assert (row.due_on, row.basis) == (date(2026, 3, 22), ScheduleBasis.PREVENTIVE_PLUS_INTERVAL)
    assert (row.last_maintenance_on, row.overdue, row.due_soon) == (date(2026, 2, 20), False, True)
    assert service.maintenance_due_lists(AS_OF).due_soon[0].asset_id == asset_id

    service.record_maintenance(asset_id, date(2026, 3, 1), "inspection", "2026-09-01", "next")
    row = service.asset_rows(AS_OF)[0]
    assert (row.due_on, row.basis) == (date(2026, 9, 1), ScheduleBasis.RECORDED_NEXT_DUE)
    assert not row.due_soon
    assert service.maintenance_due_lists(AS_OF).due_soon == ()
    assert service.maintenance_due_lists(AS_OF).overdue == ()


def test_maintenance_log_is_sorted_and_correctable(
    service: InfrastructureService, db: DatabaseConnection
) -> None:
    type_id = _user_type(service)
    asset_id = _asset(service, "DEMO-A001", type_id)
    late = service.record_maintenance(asset_id, "2026-02-01", MaintenanceKind.PREVENTIVE)
    early = service.record_maintenance(asset_id, "2026-01-01", "corrective", "2026-01-01", " n ")
    log = service.asset_history(asset_id).maintenance_events
    assert [(m.id, m.performed_on, m.kind, m.next_due_on, m.note) for m in log] == [
        (early, date(2026, 1, 1), MaintenanceKind.CORRECTIVE, date(2026, 1, 1), "n"),
        (late, date(2026, 2, 1), MaintenanceKind.PREVENTIVE, None, None),
    ]
    assert service.get_asset(asset_id).maintenance_events == log
    service.update_maintenance(late, "2026-02-02", "inspection", "2026-03-01", "ok")
    assert service.asset_history(asset_id).maintenance_events[1].kind is MaintenanceKind.INSPECTION
    # same date and another kind is a different record; same date and kind is the same record
    service.record_maintenance(asset_id, "2026-02-02", "preventive")
    _refused(
        db,
        lambda: service.update_maintenance(late, "2026-02-02", "preventive"),
        DUPLICATE_MAINTENANCE,
    )
    service.update_maintenance(late, "2026-02-02", "inspection", None, "no due date now")
    service.delete_maintenance(late)
    assert len(service.asset_history(asset_id).maintenance_events) == 2


def test_maintenance_validation(service: InfrastructureService, db: DatabaseConnection) -> None:
    type_id = _user_type(service)
    asset_id = _asset(service, "DEMO-A001", type_id)
    service.record_maintenance(asset_id, "2026-01-10", "preventive")
    bad_kinds: list[Any] = ["repair", "", "PREVENTIVE", None, 4]
    for bad in bad_kinds:
        _refused(
            db,
            lambda bad=bad: service.record_maintenance(asset_id, "2026-01-11", bad),
            INVALID_MAINTENANCE_KIND,
            "kind",
        )
    _refused(
        db,
        lambda: service.record_maintenance(asset_id, "2026-02-30", "preventive"),
        INVALID_DATE,
        "performed_on",
    )
    _refused(
        db,
        lambda: service.record_maintenance(asset_id, "", "preventive"),
        REQUIRED,
        "performed_on",
    )
    _refused(
        db,
        lambda: service.record_maintenance(asset_id, "2026-01-11", "preventive", "soon"),
        INVALID_DATE,
        "next_due_on",
    )
    _refused(
        db,
        lambda: service.record_maintenance(asset_id, "2026-01-11", "preventive", "2026-01-10"),
        NEXT_DUE_BEFORE_PERFORMED,
        "next_due_on",
    )
    _refused(
        db,
        lambda: service.record_maintenance(asset_id, "2026-01-10", "preventive"),
        DUPLICATE_MAINTENANCE,
        "performed_on",
    )
    service.record_maintenance(asset_id, "2026-01-11", "preventive", "2026-01-11")  # equal: fine
    service.record_maintenance(asset_id, "2026-01-10", "inspection", "")  # blank due date: unset
    first = service.asset_history(asset_id).maintenance_events[0]
    assert (first.kind, first.next_due_on) == (MaintenanceKind.INSPECTION, None)
    _refused(
        db,
        lambda: service.update_maintenance(first.id, "2026-01-10", "inspection", "2026-01-01"),
        NEXT_DUE_BEFORE_PERFORMED,
    )
    _refused(
        db,
        lambda: service.update_maintenance(first.id, "2026-01-10", "x"),
        INVALID_MAINTENANCE_KIND,
    )


# --------------------------------------------------------------------------- retire versus delete


def test_retired_asset_keeps_its_history_and_leaves_the_counts_after_the_last_day(
    service: InfrastructureService, db: DatabaseConnection
) -> None:
    type_id = _user_type(service)
    asset_id = _asset(service, "DEMO-A001", type_id, in_service_from="2025-12-01")
    service.change_status(asset_id, "2026-01-15", "degraded")
    service.record_maintenance(asset_id, "2026-01-20", "preventive")
    log_before = _count(db, "change_log")

    _refused(db, lambda: service.retire_asset(asset_id, "2025-11-30"), IN_SERVICE_UNTIL_BEFORE_FROM)
    _refused(db, lambda: service.retire_asset(asset_id, "nope"), INVALID_DATE)
    service.retire_asset(asset_id, date(2026, 3, 1))

    asset = service.get_asset(asset_id)
    assert asset.asset.in_service_until == date(2026, 3, 1)
    assert len(asset.status_events) == 2
    assert len(asset.maintenance_events) == 1
    assert _count(db, "change_log") == log_before + 1

    def counts(day: date) -> tuple[int, int]:
        entry = {a.type_code: a for a in service.availability(day)}["DEMO-TYPE"]
        return entry.in_service, entry.available

    assert counts(date(2026, 2, 1)) == (1, 0)  # degraded does not count as available
    assert counts(date(2026, 3, 1)) == (1, 0)  # the last day is still counted
    assert counts(date(2026, 3, 2)) == (0, 0)
    assert service.maintenance_due_lists(date(2026, 3, 2)).overdue == ()
    assert [a.id for a in service.list_assets()] == [asset_id]  # still in the registry
    assert [a.id for a in service.list_assets(in_service_on=date(2026, 3, 1))] == [asset_id]
    assert service.list_assets(in_service_on=date(2026, 3, 2)) == []
    assert service.list_assets(type_id=type_id)[0].id == asset_id
    assert service.list_assets(type_id=_type_id(service, "bed")) == []

    # retirement can be undone through update_asset; delete removes the record altogether
    service.update_asset(asset_id, _input(type_id, tag="DEMO-A001", in_service_from="2025-12-01"))
    assert service.get_asset(asset_id).asset.in_service_until is None
    service.delete_asset(asset_id)
    assert service.list_assets() == []


def test_not_yet_in_service_asset_is_not_counted(service: InfrastructureService) -> None:
    type_id = _user_type(service)
    _asset(service, "DEMO-A001", type_id, in_service_from="2026-04-01")
    entry = {a.type_code: a for a in service.availability(AS_OF)}["DEMO-TYPE"]
    assert (entry.in_service, entry.available) == (0, 0)
    assert not service.asset_rows(AS_OF)[0].in_service
    assert service.data_quality(AS_OF) == []


def test_changing_in_service_from_keeps_the_initial_event_date_and_reports_unknown(
    service: InfrastructureService,
) -> None:
    type_id = _user_type(service)
    asset_id = _asset(service, "DEMO-A001", type_id, in_service_from="2026-01-01")
    service.update_asset(asset_id, _input(type_id, in_service_from="2025-12-01"))
    detail = service.get_asset(asset_id)
    assert detail.asset.in_service_from == date(2025, 12, 1)
    assert [e.effective_on for e in detail.status_events] == [date(2026, 1, 1)]
    assert service.data_quality(date(2025, 12, 15)) == ["DEMO-A001"]
    assert service.data_quality(AS_OF) == []


# --------------------------------------------------------------------------- read-only


_READ_ONLY_CALLS: list[Callable[[InfrastructureService], object]] = [
    lambda s: s.create_type(AssetTypeInput("DEMO-X", "x")),
    lambda s: s.update_type(1, AssetTypeInput("bed", None)),
    lambda s: s.deactivate_type(1),
    lambda s: s.delete_type(1),
    lambda s: s.create_asset(_input(1, tag="DEMO-X"), "operational"),
    lambda s: s.update_asset(1, _input(1)),
    lambda s: s.retire_asset(1, "2026-01-01"),
    lambda s: s.delete_asset(1),
    lambda s: s.change_status(1, "2026-01-01", "operational"),
    lambda s: s.update_status_event(1, "2026-01-01", "operational"),
    lambda s: s.delete_status_event(1),
    lambda s: s.record_maintenance(1, "2026-01-01", "preventive"),
    lambda s: s.update_maintenance(1, "2026-01-01", "preventive"),
    lambda s: s.delete_maintenance(1),
]


@pytest.mark.parametrize("index", range(len(_READ_ONLY_CALLS)))
def test_read_only_connection_refuses_every_write(
    service: InfrastructureService,
    read_only_db: DatabaseConnection,
    clock: FixedClock,
    index: int,
) -> None:
    type_id = _user_type(service)
    _asset(service, "DEMO-A001", type_id)
    reader = InfrastructureService(read_only_db, clock, lambda: OPERATOR)
    call = _READ_ONLY_CALLS[index]
    assert _error(lambda: call(reader)).code == READ_ONLY


def test_reads_work_on_a_read_only_connection(
    service: InfrastructureService, read_only_db: DatabaseConnection, clock: FixedClock
) -> None:
    type_id = _user_type(service, interval=30)
    asset_id = _asset(service, "DEMO-A001", type_id)
    service.record_maintenance(asset_id, "2026-02-20", "preventive")
    reader = InfrastructureService(read_only_db, clock)
    assert "DEMO-TYPE" in {view.code for view in reader.list_types()}
    assert reader.get_type(type_id).code == "DEMO-TYPE"
    assert [a.tag for a in reader.list_assets()] == ["DEMO-A001"]
    assert reader.get_asset(asset_id).asset.tag == "DEMO-A001"
    assert len(reader.asset_history(asset_id).maintenance_events) == 1
    assert reader.asset_rows(AS_OF) == service.asset_rows(AS_OF)
    assert reader.availability(AS_OF) == service.availability(AS_OF)
    assert reader.maintenance_due_lists(AS_OF) == service.maintenance_due_lists(AS_OF)
    assert reader.data_quality(AS_OF) == []
    assert reader.indicator_values(AS_OF) == service.indicator_values(AS_OF)


# --------------------------------------------------------------------------- as-of views vs domain


def _d(text: str) -> date:
    return date.fromisoformat(text)


@dataclass(frozen=True)
class _Filled:
    """The service holding the fictitious fixture and the equivalent domain objects."""

    service: InfrastructureService
    assets: list[Asset]
    types: list[AssetType]
    status_events: list[StatusEvent]
    maintenance: list[MaintenanceEvent]
    active_types: list[AssetType]


@pytest.fixture
def filled(service: InfrastructureService) -> _Filled:
    bed = _type_id(service, "bed")
    bay = _type_id(service, "bay")
    service.update_type(bed, AssetTypeInput("bed", None, default_maintenance_interval_days=100))
    demo = _user_type(service, "DEMO-TYPE", interval=30)
    _user_type(service, "DEMO-EMPTY")
    _user_type(service, "DEMO-OFF", active=False)

    ids: dict[str, int] = {}
    ids["A001"] = _asset(service, "DEMO-A001", demo, "2025-12-01")
    ids["A002"] = _asset(service, "DEMO-A002", demo, "2025-12-01")
    ids["A003"] = _asset(service, "DEMO-A003", demo, "2026-02-20")
    ids["A004"] = _asset(service, "DEMO-A004", bed, "2025-12-01", "out_of_service", interval=0)
    ids["A005"] = _asset(service, "DEMO-A005", bed, "2025-11-01")
    ids["A006"] = _asset(service, "DEMO-A006", bay, "2025-12-01")
    ids["A007"] = _asset(service, "DEMO-A007", demo, "2025-10-01", interval=365)
    ids["A008"] = _asset(service, "DEMO-A008", bed, "2025-01-01", in_service_until="2026-02-28")
    ids["A009"] = _asset(service, "DEMO-A009", bay, "2026-04-01")
    ids["A010"] = _asset(service, "DEMO-A010", bed, "2026-01-01")
    service.delete_status_event(service.get_asset(ids["A010"]).status_events[0].id)

    service.change_status(ids["A002"], "2026-02-01", "degraded")
    service.change_status(ids["A007"], "2026-03-06", "out_of_service")
    service.record_maintenance(ids["A001"], "2026-02-10", "preventive", "2026-03-20")
    service.record_maintenance(ids["A002"], "2026-01-15", "preventive")
    service.record_maintenance(ids["A003"], "2026-04-01", "preventive", "2026-05-01")
    service.record_maintenance(ids["A005"], "2026-01-05", "corrective")
    service.record_maintenance(ids["A006"], "2026-02-01", "inspection")

    def asset(
        key: str,
        type_code: str,
        start: str,
        until: str | None = None,
        interval: int | None = None,
    ) -> Asset:
        return Asset(
            id=ids[key],
            tag=f"DEMO-{key}",
            type_code=type_code,
            in_service_from=_d(start),
            in_service_until=None if until is None else _d(until),
            maintenance_interval_days=interval,
        )

    assets = [
        asset("A001", "DEMO-TYPE", "2025-12-01"),
        asset("A002", "DEMO-TYPE", "2025-12-01"),
        asset("A003", "DEMO-TYPE", "2026-02-20"),
        asset("A004", "bed", "2025-12-01", None, 0),
        asset("A005", "bed", "2025-11-01"),
        asset("A006", "bay", "2025-12-01"),
        asset("A007", "DEMO-TYPE", "2025-10-01", None, 365),
        asset("A008", "bed", "2025-01-01", "2026-02-28"),
        asset("A009", "bay", "2026-04-01"),
        asset("A010", "bed", "2026-01-01"),
    ]
    operational = AssetStatus.OPERATIONAL
    degraded = AssetStatus.DEGRADED
    out = AssetStatus.OUT_OF_SERVICE
    status_events = [
        StatusEvent(ids["A001"], _d("2025-12-01"), operational),
        StatusEvent(ids["A002"], _d("2025-12-01"), operational),
        StatusEvent(ids["A002"], _d("2026-02-01"), degraded),
        StatusEvent(ids["A003"], _d("2026-02-20"), operational),
        StatusEvent(ids["A004"], _d("2025-12-01"), out),
        StatusEvent(ids["A005"], _d("2025-11-01"), operational),
        StatusEvent(ids["A006"], _d("2025-12-01"), operational),
        StatusEvent(ids["A007"], _d("2025-10-01"), operational),
        StatusEvent(ids["A007"], _d("2026-03-06"), out),
        StatusEvent(ids["A008"], _d("2025-01-01"), operational),
        StatusEvent(ids["A009"], _d("2026-04-01"), operational),
    ]
    preventive = MaintenanceKind.PREVENTIVE
    maintenance = [
        MaintenanceEvent(ids["A001"], _d("2026-02-10"), preventive, _d("2026-03-20")),
        MaintenanceEvent(ids["A002"], _d("2026-01-15"), preventive, None),
        MaintenanceEvent(ids["A003"], _d("2026-04-01"), preventive, _d("2026-05-01")),
        MaintenanceEvent(ids["A005"], _d("2026-01-05"), MaintenanceKind.CORRECTIVE, None),
        MaintenanceEvent(ids["A006"], _d("2026-02-01"), MaintenanceKind.INSPECTION, None),
    ]
    types = [
        AssetType("bed", 100),
        AssetType("bay", None),
        AssetType("neg_pressure_filtration", None),
        AssetType("decon_tent", None),
        AssetType("DEMO-TYPE", 30),
        AssetType("DEMO-EMPTY", None),
        AssetType("DEMO-OFF", None),
    ]
    active_types = [t for t in types if t.code != "DEMO-OFF"]
    return _Filled(service, assets, types, status_events, maintenance, active_types)


def _assert_equals_domain(fx: _Filled, domain_rules: InfrastructureRules) -> None:
    service = fx.service
    args = (fx.assets, fx.types, fx.status_events, fx.maintenance)
    for as_of in (AS_OF, date(2026, 3, 1), date(2025, 12, 15), date(2026, 5, 2)):
        assert service.asset_rows(as_of) == rules.asset_rows(*args, as_of, domain_rules)
        assert service.maintenance_due_lists(as_of) == rules.maintenance_due_lists(
            *args, as_of, domain_rules
        )
        assert service.data_quality(as_of) == rules.data_quality(fx.assets, fx.status_events, as_of)
        expected = rules.indicator_values(
            fx.assets, fx.active_types, fx.status_events, fx.maintenance, as_of, domain_rules
        )
        assert service.indicator_values(as_of) == expected
        expected_availability = [
            (
                decode_dimension(value.dimension)["type"],
                int(value.value or 0),
                int((value.context or {})["in_service"]),
            )
            for value in expected
            if value.code == "INFRA_AVAILABLE"
        ]
        assert [
            (a.type_code, a.available, a.in_service) for a in service.availability(as_of)
        ] == expected_availability


def test_as_of_views_equal_the_domain_results_with_the_default_configuration(
    filled: _Filled,
) -> None:
    _assert_equals_domain(filled, InfrastructureRules())
    service = filled.service

    # the fixture really exercises every A06 branch, the unknown status and the exclusions
    rows = {row.tag: row for row in service.asset_rows(AS_OF)}
    assert {row.basis for row in rows.values()} == set(ScheduleBasis)
    assert rows["DEMO-A001"].basis is ScheduleBasis.RECORDED_NEXT_DUE
    assert rows["DEMO-A002"].basis is ScheduleBasis.PREVENTIVE_PLUS_INTERVAL
    assert rows["DEMO-A003"].basis is ScheduleBasis.IN_SERVICE_PLUS_INTERVAL
    assert rows["DEMO-A004"].basis is ScheduleBasis.NO_SCHEDULED_MAINTENANCE
    assert rows["DEMO-A005"].due_on == date(2026, 2, 9)  # type default 100, no override
    assert rows["DEMO-A006"].schedule_unknown
    assert rows["DEMO-A007"].due_on == date(2026, 10, 1)  # override 365 beats the type's 30
    assert not rows["DEMO-A008"].in_service  # retired
    assert not rows["DEMO-A009"].in_service  # not yet in service
    assert rows["DEMO-A010"].status is AssetStatus.UNKNOWN
    assert service.data_quality(AS_OF) == ["DEMO-A010"]
    due = service.maintenance_due_lists(AS_OF)
    assert [row.tag for row in due.overdue] == ["DEMO-A002", "DEMO-A005"]
    assert [row.tag for row in due.due_soon] == ["DEMO-A001", "DEMO-A003"]

    availability = {a.type_code: (a.available, a.in_service) for a in service.availability(AS_OF)}
    assert availability == {
        "bed": (1, 3),  # A005 available; A004 out of service, A010 unknown; A008 retired
        "bay": (1, 1),  # A006; A009 not yet in service
        "neg_pressure_filtration": (0, 0),
        "decon_tent": (0, 0),
        "DEMO-TYPE": (3, 4),  # A002 is degraded
        "DEMO-EMPTY": (0, 0),
    }
    values = service.indicator_values(AS_OF)
    types_seen = {decode_dimension(value.dimension)["type"] for value in values}
    assert "DEMO-OFF" not in types_seen  # inactive
    assert "DEMO-EMPTY" in types_seen  # active, without assets
    assert len(values) == 12  # two indicators for each of the six active types


def test_as_of_views_equal_the_domain_results_with_a_stored_configuration(
    filled: _Filled, db: DatabaseConnection, clock: FixedClock
) -> None:
    service = filled.service
    before = service.maintenance_due_lists(AS_OF)
    config = ReadinessConfig().with_changes(
        maintenance_warning_days=16, degraded_counts_as_available=True
    )
    save_config(WriteContext(db, clock, OPERATOR), config)
    domain_rules = InfrastructureRules(
        maintenance_warning_days=16, degraded_counts_as_available=True
    )
    _assert_equals_domain(filled, domain_rules)

    after = service.maintenance_due_lists(AS_OF)
    assert after != before
    assert [row.tag for row in after.due_soon] == ["DEMO-A001"]  # A003 is 17 days away
    availability = {a.type_code: a.available for a in service.availability(AS_OF)}
    assert availability["DEMO-TYPE"] == 4  # the degraded A002 now counts


def test_alert_inputs_feed_the_domain_to_the_same_rows_as_the_page(
    filled: _Filled, db: DatabaseConnection, clock: FixedClock
) -> None:
    service = filled.service
    inputs = service.alert_inputs()
    assert inputs.rules == InfrastructureRules()  # the default configuration
    # ALL types, the inactive DEMO-OFF included, exactly as asset_rows passes them
    codes = {asset_type.code for asset_type in inputs.types}
    assert "DEMO-OFF" in codes
    stored = service.list_types(include_inactive=True)
    assert [t.active for t in stored if t.code == "DEMO-OFF"] == [False]
    assert codes == {t.code for t in stored}
    assert len(inputs.assets) == _count(db, "asset")
    assert len(inputs.status_events) == _count(db, "asset_status_event")
    assert len(inputs.maintenance) == _count(db, "maintenance_event")
    rows = rules.asset_rows(
        inputs.assets, inputs.types, inputs.status_events, inputs.maintenance, AS_OF, inputs.rules
    )
    assert rows == service.asset_rows(AS_OF)

    config = ReadinessConfig().with_changes(maintenance_warning_days=16)
    save_config(WriteContext(db, clock, OPERATOR), config)
    assert service.alert_inputs().rules == InfrastructureRules(maintenance_warning_days=16)


def test_asset_history_is_sorted_by_date(service: InfrastructureService) -> None:
    type_id = _user_type(service)
    asset_id = _asset(service, "DEMO-A001", type_id, in_service_from="2025-12-01")
    service.change_status(asset_id, "2026-03-01", "degraded")
    service.change_status(asset_id, "2026-01-01", "out_of_service")
    service.record_maintenance(asset_id, "2026-03-03", "preventive")
    service.record_maintenance(asset_id, "2026-01-03", "inspection")
    history = service.asset_history(asset_id)
    assert [e.effective_on for e in history.status_events] == [
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 3, 1),
    ]
    assert [m.performed_on for m in history.maintenance_events] == [
        date(2026, 1, 3),
        date(2026, 3, 3),
    ]
