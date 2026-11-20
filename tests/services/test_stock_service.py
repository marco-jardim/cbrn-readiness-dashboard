# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the stock service: item types and lots (PLAN.md T11.5); fictitious data only."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import date
from functools import partial
from typing import Any

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain.config import ConfigError, ReadinessConfig
from cbrn_dashboard.domain.stock import MovementKind, StockCategory
from cbrn_dashboard.services.budget import MAX_MINOR
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
    BUILT_IN_TYPE,
    CATEGORY_IMMUTABLE,
    DATE_IN_FUTURE,
    DUPLICATE_CODE,
    DUPLICATE_LOT,
    EXPIRY_REQUIRED,
    INITIAL_RECEIPT_REQUIRED,
    INVALID_AMOUNT,
    INVALID_CATEGORY,
    INVALID_CURRENCY,
    INVALID_QUANTITY,
    MAX_QUANTITY,
    TEXT_TOO_LONG,
    TYPE_IMMUTABLE,
    TYPE_IN_USE,
    TYPE_INACTIVE,
    InitialReceipt,
    LotInput,
    StockService,
    StockTypeInput,
    StockTypeView,
    stock_type_label,
)
from cbrn_dashboard.storage import settings_repo, snapshots_repo, stock_repo, targets_repo
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.repository import REDACTED_COLUMNS, WriteContext
from cbrn_dashboard.storage.settings_repo import save_config
from tests.services.conftest import ChangeLogRows

TODAY = date(2026, 3, 5)
NOW_TEXT = "2026-03-05T12:00:00Z"
OPERATOR = "op-demo"

_TABLES = ("stock_item_type", "stock_lot", "stock_movement", "setting", "change_log")
_STOCK_ENTITIES = ("stock_item_type", "stock_lot", "stock_movement")


@pytest.fixture
def service(db: DatabaseConnection, clock: FixedClock) -> StockService:
    return StockService(db, clock, lambda: OPERATOR)


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


def _type_id(service: StockService, code: str) -> int:
    view = service.get_type_by_code(code)
    assert view is not None
    return view.id


def _type_input(code: str = "DEMO-ITEM", **changes: Any) -> StockTypeInput:
    fields: dict[str, Any] = {
        "code": code,
        "category": StockCategory.OTHER,
        "label_pt_br": "Item demo",
        "label_en_us": "Demo item",
    }
    fields.update(changes)
    return StockTypeInput(**fields)


def _user_type(service: StockService, code: str = "DEMO-ITEM", **changes: Any) -> int:
    return service.create_type(_type_input(code, **changes))


def _lot_input(type_id: int | None, code: str = "DEMO-L001", **changes: Any) -> LotInput:
    fields: dict[str, Any] = {"type_id": type_id, "lot_code": code}
    fields.update(changes)
    return LotInput(**fields)


def _receipt(**changes: Any) -> InitialReceipt:
    fields: dict[str, Any] = {"moved_on": "2026-03-01", "quantity": 10}
    fields.update(changes)
    return InitialReceipt(**fields)


def _lot(
    service: StockService, type_id: int | None, code: str = "DEMO-L001", **changes: Any
) -> int:
    return service.create_lot(_lot_input(type_id, code, **changes), _receipt())


# --------------------------------------------------------------------------- the seeded types


def test_the_seventeen_built_in_types_are_listed_with_their_categories(
    service: StockService,
) -> None:
    views = service.list_types()

    assert len(views) == 17
    assert all(view.built_in and view.active for view in views)
    assert all(view.label_pt_br is None and view.minimum_quantity is None for view in views)
    by_code = {view.code: view.category for view in views}
    assert by_code["ANTIDOTE_CHEMICAL"] is StockCategory.ANTIDOTE
    assert by_code["DECONTAMINANT"] is StockCategory.DECONTAMINANT
    assert by_code["DETECTOR_BIOLOGICAL"] is StockCategory.DETECTOR
    assert by_code["GLOVE"] is StockCategory.PPE
    assert by_code["OXYGEN_CYLINDER"] is StockCategory.OTHER


# --------------------------------------------------------------------------- change log


def test_every_type_and_lot_write_is_logged_with_operator_and_clock(
    service: StockService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    before = len(change_log_rows(db))
    type_id = _user_type(service)
    service.update_type(type_id, _type_input(label_pt_br="Item novo"))
    service.deactivate_type(type_id)
    service.activate_type(type_id)
    assert service.set_minimum(type_id, 5) is True
    lot_id = _lot(service, type_id)
    service.update_lot(lot_id, _lot_input(type_id, notes="nota"))
    service.delete_lot(lot_id)
    service.delete_type(type_id)

    rows = change_log_rows(db)[before:]

    assert [(row["entity"], row["action"]) for row in rows] == [
        ("stock_item_type", "insert"),
        ("stock_item_type", "update"),
        ("stock_item_type", "update"),
        ("stock_item_type", "update"),
        ("stock_item_type", "update"),
        ("stock_lot", "insert"),
        ("stock_movement", "insert"),
        ("stock_lot", "update"),
        ("stock_lot", "delete"),
        ("stock_movement", "delete"),
        ("stock_item_type", "delete"),
    ]
    assert {row["operator"] for row in rows} == {OPERATOR}
    assert {row["at_utc"] for row in rows} == {NOW_TEXT}


def test_a_lot_and_its_initial_receipt_appear_together_in_the_log(
    service: StockService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    type_id = _type_id(service, "ANTIDOTE_CHEMICAL")
    before = len(change_log_rows(db))

    lot_id = service.create_lot(
        _lot_input(type_id, "DEMO-A1", expires_on="2027-01-31"),
        _receipt(moved_on="2026-02-20", quantity=12, reference="NF-1", note="entrada"),
    )

    rows = change_log_rows(db)[before:]
    assert [(row["entity"], row["action"]) for row in rows] == [
        ("stock_lot", "insert"),
        ("stock_movement", "insert"),
    ]
    movement = json.loads(str(rows[1]["after_json"]))
    assert movement["lot_id"] == lot_id
    assert movement["kind"] == MovementKind.RECEIPT.value
    assert (movement["moved_on"], movement["quantity"]) == ("2026-02-20", 12)
    assert (movement["reference"], movement["note"]) == ("NF-1", "entrada")
    lot = json.loads(str(rows[0]["after_json"]))
    assert lot["expires_on"] == "2027-01-31"


def test_a_failing_initial_receipt_leaves_no_lot_and_no_log_row(
    service: StockService, db: DatabaseConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    type_id = _user_type(service)

    def boom(*_args: object, **_kwargs: object) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(stock_repo, "insert_movement", boom)
    before = _state(db)

    with pytest.raises(RuntimeError):
        _lot(service, type_id)

    assert _state(db) == before
    assert service.list_lots() == []


def test_no_stock_log_row_holds_a_personal_column(
    service: StockService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    for table in _STOCK_ENTITIES:
        assert table not in REDACTED_COLUMNS
    type_id = _user_type(service, category=StockCategory.ANTIDOTE)
    lot_id = _lot(service, type_id, expires_on="2027-01-01", notes="sem dados pessoais")
    service.delete_lot(lot_id)

    for row in change_log_rows(db):
        if row["entity"] not in _STOCK_ENTITIES:
            continue
        for column in ("before_json", "after_json"):
            if row[column] is None:
                continue
            document = json.loads(str(row[column]))
            columns = {
                str(info[1])
                for info in db.execute(f"PRAGMA table_info({row['entity']})").fetchall()
            }
            assert set(document) == columns
            assert not any(isinstance(value, dict) for value in document.values())


# --------------------------------------------------------------------------- item types


def test_create_type_stores_a_user_type(service: StockService) -> None:
    type_id = _user_type(
        service, "DEMO-X", category="antidote", label_es_es=" Articulo ", minimum_quantity=0
    )

    view = service.get_type(type_id)

    assert (view.code, view.built_in, view.active) == ("DEMO-X", False, True)
    assert view.category is StockCategory.ANTIDOTE
    assert (view.label_pt_br, view.label_en_us, view.label_es_es) == (
        "Item demo",
        "Demo item",
        "Articulo",
    )
    assert view.minimum_quantity == 0
    assert service.get_type_by_code("DEMO-X") == view
    assert service.get_type_by_code("NO-SUCH") is None


@pytest.mark.parametrize("label", [None, "", "   "])
def test_a_user_type_needs_a_pt_br_label(
    service: StockService, db: DatabaseConnection, label: str | None
) -> None:
    _refused(
        db,
        lambda: service.create_type(_type_input(label_pt_br=label)),
        LABEL_PT_BR_REQUIRED,
        "label_pt_br",
    )


def test_create_type_validates_code_category_and_minimum(
    service: StockService, db: DatabaseConnection
) -> None:
    _refused(db, lambda: service.create_type(_type_input("")), REQUIRED, "code")
    _refused(db, lambda: service.create_type(_type_input("bad code")), INVALID_CODE, "code")
    _refused(db, lambda: service.create_type(_type_input("GLOVE")), DUPLICATE_CODE, "code")
    _refused(
        db,
        lambda: service.create_type(_type_input(category="clinical")),
        INVALID_CATEGORY,
        "category",
    )
    for bad in (-1, True, 1.5, "3", 1_000_000_001):
        data = _type_input(minimum_quantity=bad)
        _refused(db, partial(service.create_type, data), INVALID_QUANTITY, "minimum_quantity")


def test_a_built_in_type_is_never_deleted(service: StockService, db: DatabaseConnection) -> None:
    glove = _type_id(service, "GLOVE")

    _refused(db, lambda: service.delete_type(glove), BUILT_IN_TYPE, "type_id")

    assert service.get_type(glove).code == "GLOVE"


def test_a_built_in_type_only_changes_its_minimum_and_active_flag(
    service: StockService, db: DatabaseConnection
) -> None:
    glove = service.get_type(_type_id(service, "GLOVE"))
    same = StockTypeInput(
        code="GLOVE",
        category=StockCategory.PPE,
        label_pt_br=None,
        minimum_quantity=40,
        active=False,
    )

    service.update_type(glove.id, same)

    changed = service.get_type(glove.id)
    assert (changed.minimum_quantity, changed.active) == (40, False)
    assert (changed.label_pt_br, changed.category, changed.built_in) == (
        None,
        StockCategory.PPE,
        True,
    )
    for forbidden in (
        StockTypeInput("GLOVE2", StockCategory.PPE, None),
        StockTypeInput("GLOVE", StockCategory.OTHER, None),
        StockTypeInput("GLOVE", StockCategory.PPE, "Luva nova"),
        StockTypeInput("GLOVE", StockCategory.PPE, None, label_en_us="Glove"),
    ):
        _refused(db, partial(service.update_type, glove.id, forbidden), BUILT_IN_TYPE)


def test_a_built_in_type_can_be_deactivated_and_activated(service: StockService) -> None:
    boot = _type_id(service, "BOOT")

    service.deactivate_type(boot)
    assert service.get_type(boot).active is False
    assert "BOOT" not in {view.code for view in service.list_types()}
    assert "BOOT" in {view.code for view in service.list_types(include_inactive=True)}

    service.activate_type(boot)
    assert service.get_type(boot).active is True


def test_a_type_that_does_not_exist_is_not_found(
    service: StockService, db: DatabaseConnection
) -> None:
    _refused(db, lambda: service.get_type(9999), NOT_FOUND, "type_id")
    _refused(db, lambda: service.update_type(9999, _type_input()), NOT_FOUND, "type_id")
    _refused(db, lambda: service.deactivate_type(9999), NOT_FOUND, "type_id")
    _refused(db, lambda: service.set_minimum(9999, 1), NOT_FOUND, "type_id")
    _refused(db, lambda: service.delete_type(9999), NOT_FOUND, "type_id")


def test_update_type_cannot_take_a_code_that_exists(
    service: StockService, db: DatabaseConnection
) -> None:
    type_id = _user_type(service)

    _refused(db, lambda: service.update_type(type_id, _type_input("GLOVE")), DUPLICATE_CODE, "code")
    service.update_type(type_id, _type_input("DEMO-ITEM", label_pt_br="Outro"))

    assert service.get_type(type_id).label_pt_br == "Outro"


def test_a_type_with_lots_cannot_be_deleted(service: StockService, db: DatabaseConnection) -> None:
    type_id = _user_type(service)
    _lot(service, type_id)

    _refused(db, lambda: service.delete_type(type_id), TYPE_IN_USE, "type_id")

    assert service.get_type(type_id).code == "DEMO-ITEM"


def test_a_type_without_lots_is_deleted(service: StockService) -> None:
    type_id = _user_type(service)

    service.delete_type(type_id)

    assert service.get_type_by_code("DEMO-ITEM") is None


def test_the_code_and_the_category_are_free_until_a_lot_uses_the_type(
    service: StockService,
) -> None:
    type_id = _user_type(service)

    service.update_type(type_id, _type_input("DEMO-ITEM-2", category=StockCategory.PPE))

    view = service.get_type(type_id)
    assert (view.code, view.category) == ("DEMO-ITEM-2", StockCategory.PPE)


def test_the_code_and_the_category_are_frozen_once_a_lot_uses_the_type(
    service: StockService, db: DatabaseConnection
) -> None:
    type_id = _user_type(service)
    _lot(service, type_id)

    _refused(
        db,
        lambda: service.update_type(type_id, _type_input("OTHER-CODE")),
        CODE_IMMUTABLE,
        "code",
    )
    _refused(
        db,
        lambda: service.update_type(type_id, _type_input(category=StockCategory.PPE)),
        CATEGORY_IMMUTABLE,
        "category",
    )
    service.update_type(type_id, _type_input(minimum_quantity=3, label_pt_br="Rotulo"))

    view = service.get_type(type_id)
    assert (view.minimum_quantity, view.label_pt_br) == (3, "Rotulo")


# --------------------------------------------------------------------------- minimum and P12


def test_set_minimum_sets_clears_and_reports_whether_it_changed(
    service: StockService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    glove = _type_id(service, "GLOVE")
    before = len(change_log_rows(db))

    assert service.set_minimum(glove, 20) is True
    assert service.get_type(glove).minimum_quantity == 20
    assert service.set_minimum(glove, 20) is False
    assert service.set_minimum(glove, 0) is True
    assert service.set_minimum(glove, None) is True
    assert service.get_type(glove).minimum_quantity is None

    rows = change_log_rows(db)[before:]
    assert _entities(rows) == Counter({("stock_item_type", "update"): 3})


@pytest.mark.parametrize("bad", [-1, True, 2.5, "7", 1_000_000_001])
def test_set_minimum_refuses_a_value_that_is_not_a_whole_quantity(
    service: StockService, db: DatabaseConnection, bad: Any
) -> None:
    glove = _type_id(service, "GLOVE")

    _refused(db, lambda: service.set_minimum(glove, bad), INVALID_QUANTITY, "minimum_quantity")


def test_set_minimum_confirms_p12_in_the_same_transaction(
    service: StockService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    glove = _type_id(service, "GLOVE")
    assert settings_repo.needs_badge(db, "P12") is True
    before = len(change_log_rows(db))

    changed = service.set_minimum(glove, 15, confirm_placeholder="P12")

    assert changed is True
    assert settings_repo.needs_badge(db, "P12") is False
    rows = change_log_rows(db)[before:]
    assert sorted(str(row["entity"]) for row in rows) == ["setting", "stock_item_type"]


def test_a_minimum_that_changes_nothing_confirms_nothing(
    service: StockService, db: DatabaseConnection
) -> None:
    glove = _type_id(service, "GLOVE")
    service.set_minimum(glove, 15)

    again = service.set_minimum(glove, 15, confirm_placeholder="P12")

    assert again is False
    assert settings_repo.needs_badge(db, "P12") is True


def test_a_failing_confirmation_rolls_the_minimum_back(
    service: StockService, db: DatabaseConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    glove = _type_id(service, "GLOVE")

    def failing(*_args: object) -> None:
        raise ConfigError("UNKNOWN_PLACEHOLDER", "placeholder_id")

    monkeypatch.setattr(settings_repo, "confirm_placeholder", failing)

    _refused(
        db,
        lambda: service.set_minimum(glove, 15, confirm_placeholder="P12"),
        "UNKNOWN_PLACEHOLDER",
        "placeholder_id",
    )

    assert service.get_type(glove).minimum_quantity is None


def test_an_unknown_placeholder_rolls_the_minimum_back(
    service: StockService, db: DatabaseConnection
) -> None:
    glove = _type_id(service, "GLOVE")

    _refused(
        db, lambda: service.set_minimum(glove, 15, confirm_placeholder="P99"), "UNKNOWN_PLACEHOLDER"
    )

    assert service.get_type(glove).minimum_quantity is None


def test_a_refused_minimum_does_not_confirm_p12(
    service: StockService, db: DatabaseConnection
) -> None:
    glove = _type_id(service, "GLOVE")

    _refused(
        db,
        lambda: service.set_minimum(glove, -1, confirm_placeholder="P12"),
        INVALID_QUANTITY,
    )

    assert settings_repo.needs_badge(db, "P12") is True


# --------------------------------------------------------------------------- lots: create


def test_create_lot_writes_the_lot_and_a_receipt_movement(
    service: StockService, db: DatabaseConnection
) -> None:
    type_id = _type_id(service, "ANTIDOTE_BIOLOGICAL")

    lot_id = service.create_lot(
        _lot_input(
            type_id,
            " DEMO-B1 ",
            expires_on="2027-06-30",
            unit_price_minor=1250,
            currency="USD",
            notes=" lote de teste ",
        ),
        _receipt(moved_on=date(2026, 3, 5), quantity=MAX_QUANTITY, reference=" NF-9 "),
    )

    lot = service.get_lot(lot_id)
    assert (lot.type_id, lot.type_code, lot.lot_code) == (type_id, "ANTIDOTE_BIOLOGICAL", "DEMO-B1")
    assert lot.expires_on == date(2027, 6, 30)
    assert (lot.unit_price_minor, lot.currency, lot.notes) == (1250, "USD", "lote de teste")
    movements = stock_repo.list_movements(db, lot_id)
    assert len(movements) == 1
    assert (movements[0].moved_on, movements[0].kind, movements[0].quantity) == (
        "2026-03-05",
        "receipt",
        MAX_QUANTITY,
    )
    assert (movements[0].reference, movements[0].note) == ("NF-9", None)
    assert service.list_lots() == [lot]
    assert service.list_lots(type_id) == [lot]
    assert service.list_lots(_type_id(service, "GLOVE")) == []


def test_a_lot_without_an_initial_receipt_is_refused(
    service: StockService, db: DatabaseConnection
) -> None:
    type_id = _user_type(service)

    _refused(db, lambda: service.create_lot(_lot_input(type_id), None), INITIAL_RECEIPT_REQUIRED)
    _refused(
        db,
        lambda: service.create_lot(_lot_input(type_id), _receipt(moved_on=None)),
        INITIAL_RECEIPT_REQUIRED,
        "moved_on",
    )
    _refused(
        db,
        lambda: service.create_lot(_lot_input(type_id), _receipt(moved_on="  ")),
        INITIAL_RECEIPT_REQUIRED,
        "moved_on",
    )
    _refused(
        db,
        lambda: service.create_lot(_lot_input(type_id), _receipt(quantity=None)),
        INITIAL_RECEIPT_REQUIRED,
        "quantity",
    )


@pytest.mark.parametrize("quantity", [0, -3, True, 2.0, "5", MAX_QUANTITY + 1])
def test_the_initial_quantity_is_a_whole_number_from_one(
    service: StockService, db: DatabaseConnection, quantity: Any
) -> None:
    type_id = _user_type(service)

    _refused(
        db,
        lambda: service.create_lot(_lot_input(type_id), _receipt(quantity=quantity)),
        INVALID_QUANTITY,
        "quantity",
    )


def test_the_initial_receipt_date_may_be_today_but_not_later(
    service: StockService, db: DatabaseConnection
) -> None:
    type_id = _user_type(service)

    _refused(
        db,
        lambda: service.create_lot(_lot_input(type_id), _receipt(moved_on="2026-03-06")),
        DATE_IN_FUTURE,
        "moved_on",
    )
    _refused(
        db,
        lambda: service.create_lot(_lot_input(type_id), _receipt(moved_on=date(2026, 12, 1))),
        DATE_IN_FUTURE,
        "moved_on",
    )
    _refused(
        db,
        lambda: service.create_lot(_lot_input(type_id), _receipt(moved_on="2026-02-30")),
        INVALID_DATE,
        "moved_on",
    )
    service.create_lot(_lot_input(type_id), _receipt(moved_on="2026-03-05"))

    assert len(service.list_lots()) == 1


@pytest.mark.parametrize("code", ["ANTIDOTE_CHEMICAL", "DECONTAMINANT"])
def test_antidotes_and_decontaminants_need_an_expiry_date(
    service: StockService, db: DatabaseConnection, code: str
) -> None:
    type_id = _type_id(service, code)

    _refused(db, lambda: _lot(service, type_id), EXPIRY_REQUIRED, "expires_on")
    _refused(db, lambda: _lot(service, type_id, expires_on="  "), EXPIRY_REQUIRED, "expires_on")
    _lot(service, type_id, expires_on="2027-01-01")

    assert len(service.list_lots()) == 1


def test_a_user_antidote_type_needs_an_expiry_date_and_other_categories_do_not(
    service: StockService, db: DatabaseConnection
) -> None:
    antidote = _user_type(service, "DEMO-ANT", category=StockCategory.ANTIDOTE)
    detector = _type_id(service, "DETECTOR_CHEMICAL")

    _refused(db, lambda: _lot(service, antidote), EXPIRY_REQUIRED, "expires_on")
    lot_id = _lot(service, detector)

    assert service.get_lot(lot_id).expires_on is None


def test_an_expiry_date_must_be_a_real_date(service: StockService, db: DatabaseConnection) -> None:
    type_id = _user_type(service)

    _refused(
        db, lambda: _lot(service, type_id, expires_on="2027-02-30"), INVALID_DATE, "expires_on"
    )
    _refused(db, lambda: _lot(service, type_id, expires_on="31/12/2027"), INVALID_DATE)


def test_a_lot_code_is_required_and_has_at_most_64_characters(
    service: StockService, db: DatabaseConnection
) -> None:
    type_id = _user_type(service)

    _refused(db, lambda: _lot(service, type_id, "   "), REQUIRED, "lot_code")
    _refused(db, lambda: _lot(service, type_id, "L" * 65), TEXT_TOO_LONG, "lot_code")
    lot_id = _lot(service, type_id, "L" * 64)

    assert service.get_lot(lot_id).lot_code == "L" * 64


def test_a_duplicate_lot_code_is_refused_inside_one_type_only(
    service: StockService, db: DatabaseConnection
) -> None:
    first = _user_type(service, "DEMO-A")
    second = _user_type(service, "DEMO-B")
    _lot(service, first, "DEMO-L001")

    _refused(db, lambda: _lot(service, first, "DEMO-L001"), DUPLICATE_LOT, "lot_code")
    _lot(service, second, "DEMO-L001")

    assert len(service.list_lots()) == 2


def test_an_inactive_type_takes_no_new_lot_but_keeps_its_lots(
    service: StockService, db: DatabaseConnection
) -> None:
    type_id = _user_type(service)
    lot_id = _lot(service, type_id)
    service.deactivate_type(type_id)

    _refused(db, lambda: _lot(service, type_id, "DEMO-L002"), TYPE_INACTIVE, "type_id")
    service.update_lot(lot_id, _lot_input(type_id, notes="ainda editavel"))

    assert service.get_lot(lot_id).notes == "ainda editavel"


def test_a_lot_needs_an_existing_type(service: StockService, db: DatabaseConnection) -> None:
    _refused(db, lambda: _lot(service, None), REQUIRED, "type_id")
    _refused(db, lambda: _lot(service, 9999), NOT_FOUND, "type_id")


# --------------------------------------------------------------------------- lots: price


@pytest.mark.parametrize("currency", ["XXX", "brl", "", "REAL", "US"])
def test_the_currency_must_be_in_the_allow_list(
    service: StockService, db: DatabaseConnection, currency: str
) -> None:
    type_id = _user_type(service)

    _refused(
        db,
        lambda: _lot(service, type_id, unit_price_minor=100, currency=currency),
        INVALID_CURRENCY,
        "currency",
    )
    _refused(
        db,
        lambda: _lot(service, type_id, currency=currency),
        INVALID_CURRENCY,
        "currency",
    )


@pytest.mark.parametrize("price", [-1, True, 1.5, "10", MAX_MINOR + 1])
def test_a_price_is_a_whole_number_of_minor_units_in_range(
    service: StockService, db: DatabaseConnection, price: Any
) -> None:
    type_id = _user_type(service)

    _refused(
        db,
        lambda: _lot(service, type_id, unit_price_minor=price, currency="BRL"),
        INVALID_AMOUNT,
        "unit_price_minor",
    )


def test_the_price_limits_are_accepted(service: StockService) -> None:
    type_id = _user_type(service)

    free = service.get_lot(_lot(service, type_id, "L0", unit_price_minor=0, currency="EUR"))
    top = service.get_lot(_lot(service, type_id, "L1", unit_price_minor=MAX_MINOR, currency="EUR"))

    assert (free.unit_price_minor, free.currency) == (0, "EUR")
    assert top.unit_price_minor == MAX_MINOR


def test_a_price_without_a_currency_takes_the_default_currency(
    service: StockService, db: DatabaseConnection, clock: FixedClock
) -> None:
    type_id = _user_type(service)

    assert service.get_lot(_lot(service, type_id, "L0", unit_price_minor=500)).currency == "BRL"

    save_config(WriteContext(db, clock, OPERATOR), ReadinessConfig(default_currency="USD"))
    assert service.get_lot(_lot(service, type_id, "L1", unit_price_minor=500)).currency == "USD"


def test_no_price_means_no_currency(service: StockService) -> None:
    type_id = _user_type(service)

    lot = service.get_lot(_lot(service, type_id, currency="USD"))

    assert (lot.unit_price_minor, lot.currency) == (None, None)


# --------------------------------------------------------------------------- lots: update


def test_update_lot_changes_the_fields_and_keeps_the_stored_currency(
    service: StockService, change_log_rows: ChangeLogRows, db: DatabaseConnection
) -> None:
    type_id = _type_id(service, "DECONTAMINANT")
    lot_id = _lot(service, type_id, expires_on="2027-01-01", unit_price_minor=100, currency="EUR")
    before = len(change_log_rows(db))

    service.update_lot(
        lot_id,
        _lot_input(type_id, "DEMO-L009", expires_on="2027-02-01", unit_price_minor=300),
    )

    lot = service.get_lot(lot_id)
    assert (lot.lot_code, lot.expires_on) == ("DEMO-L009", date(2027, 2, 1))
    assert (lot.unit_price_minor, lot.currency) == (300, "EUR")
    assert _entities(change_log_rows(db)[before:]) == Counter({("stock_lot", "update"): 1})
    # Clearing the price clears the currency (price and currency are both set or both empty).
    service.update_lot(lot_id, _lot_input(type_id, "DEMO-L009", expires_on="2027-02-01"))
    assert service.get_lot(lot_id).currency is None


def test_update_lot_applies_the_same_rules_as_create(
    service: StockService, db: DatabaseConnection
) -> None:
    antidote = _type_id(service, "ANTIDOTE_CHEMICAL")
    lot_id = _lot(service, antidote, "DEMO-L001", expires_on="2027-01-01")
    _lot(service, antidote, "DEMO-L002", expires_on="2027-01-01")

    _refused(db, lambda: service.update_lot(lot_id, _lot_input(antidote)), EXPIRY_REQUIRED)
    _refused(
        db,
        lambda: service.update_lot(
            lot_id, _lot_input(antidote, "DEMO-L002", expires_on="2027-01-01")
        ),
        DUPLICATE_LOT,
        "lot_code",
    )
    _refused(
        db,
        lambda: service.update_lot(
            lot_id,
            _lot_input(antidote, expires_on="2027-01-01", unit_price_minor=1, currency="XXX"),
        ),
        INVALID_CURRENCY,
    )
    _refused(db, lambda: service.update_lot(9999, _lot_input(antidote)), NOT_FOUND, "lot_id")
    # Saving a lot under its own code is not a duplicate.
    service.update_lot(lot_id, _lot_input(antidote, "DEMO-L001", expires_on="2028-01-01"))


def test_a_lot_without_movements_can_move_to_another_active_type_only(
    service: StockService, db: DatabaseConnection, clock: FixedClock
) -> None:
    first = _user_type(service, "DEMO-A")
    second = _user_type(service, "DEMO-B")
    closed = _user_type(service, "DEMO-C", active=False)
    # create_lot always writes a receipt, so a lot without movements is stored directly
    lot_id = stock_repo.insert_lot(
        WriteContext(db, clock, OPERATOR),
        type_id=first,
        lot_code="DEMO-L001",
        expires_on=None,
        unit_price_minor=None,
        currency=None,
        notes=None,
    )

    _refused(db, lambda: service.update_lot(lot_id, _lot_input(closed)), TYPE_INACTIVE, "type_id")
    service.update_lot(lot_id, _lot_input(second))

    assert service.get_lot(lot_id).type_code == "DEMO-B"


def test_a_lot_with_movements_keeps_its_type(service: StockService, db: DatabaseConnection) -> None:
    first = _user_type(service, "DEMO-A")
    second = _user_type(service, "DEMO-B")
    lot_id = _lot(service, first)

    _refused(db, lambda: service.update_lot(lot_id, _lot_input(second)), TYPE_IMMUTABLE, "type_id")
    # the same type is not a change: the other fields of the lot can still be edited
    service.update_lot(lot_id, _lot_input(first, "DEMO-L001-B", notes="Management note"))

    view = service.get_lot(lot_id)
    assert (view.type_code, view.lot_code) == ("DEMO-A", "DEMO-L001-B")
    assert view.notes == "Management note"


# --------------------------------------------------------------------------- frozen code (P11-05)


def _snapshot_with_dimension(db: DatabaseConnection, clock: FixedClock, dimension: str) -> None:
    ctx = WriteContext(db, clock, OPERATOR)
    snapshot_id = snapshots_repo.insert_snapshot(
        ctx,
        taken_at_utc=NOW_TEXT,
        as_of="2026-03-05",
        origin="manual",
        app_version="1.0.0",
        config_hash="0" * 64,
        config_json="{}",
        note=None,
    )
    row = snapshots_repo.SnapshotValueRow(
        snapshot_id=snapshot_id,
        indicator_code="STOCK_VALID_QTY",
        dimension=dimension,
        value=1.0,
        status="OK",
        warning_value=None,
        critical_value=None,
    )
    snapshots_repo.insert_values(ctx, snapshot_id, [row])


def _assert_frozen(service: StockService, db: DatabaseConnection, type_id: int) -> None:
    _refused(
        db,
        lambda: service.update_type(type_id, _type_input("OTHER-CODE", minimum_quantity=None)),
        CODE_IMMUTABLE,
        "code",
    )
    _refused(
        db,
        lambda: service.update_type(type_id, _type_input(category=StockCategory.PPE)),
        CATEGORY_IMMUTABLE,
        "category",
    )


def test_the_code_and_the_category_are_frozen_once_a_minimum_is_set(
    service: StockService, db: DatabaseConnection
) -> None:
    type_id = _user_type(service, minimum_quantity=5)

    _assert_frozen(service, db, type_id)
    service.update_type(type_id, _type_input(minimum_quantity=8, label_pt_br="Rotulo"))
    assert service.get_type(type_id).minimum_quantity == 8


def test_clearing_the_minimum_frees_the_code_again(service: StockService) -> None:
    type_id = _user_type(service, minimum_quantity=5)
    service.set_minimum(type_id, None)

    service.update_type(type_id, _type_input("DEMO-ITEM-2"))

    assert service.get_type(type_id).code == "DEMO-ITEM-2"


@pytest.mark.parametrize("dimension", ["item=DEMO-ITEM", "category=other;item=DEMO-ITEM"])
def test_the_code_and_the_category_are_frozen_once_a_snapshot_reading_names_the_type(
    service: StockService, db: DatabaseConnection, clock: FixedClock, dimension: str
) -> None:
    type_id = _user_type(service)
    _snapshot_with_dimension(db, clock, "item=DEMO-ITEM-LONGER")  # another code: not a match
    service.update_type(type_id, _type_input("DEMO-ITEM"))  # still free
    _snapshot_with_dimension(db, clock, dimension)

    _assert_frozen(service, db, type_id)


def test_the_code_and_the_category_are_frozen_once_an_indicator_target_names_the_type(
    service: StockService, db: DatabaseConnection, clock: FixedClock
) -> None:
    type_id = _user_type(service)
    targets_repo.upsert_target(
        WriteContext(db, clock, OPERATOR),
        "STOCK_VALID_QTY",
        "category=other;item=DEMO-ITEM",
        10.0,
        5.0,
        True,
    )

    _assert_frozen(service, db, type_id)


# --------------------------------------------------------------------------- save with minimum


def test_save_type_with_minimum_creates_the_type_with_its_minimum_and_confirms_p12(
    service: StockService, db: DatabaseConnection
) -> None:
    assert settings_repo.needs_badge(db, "P12") is True

    type_id = service.save_type_with_minimum(None, _type_input(), 12)

    view = service.get_type(type_id)
    assert (view.code, view.minimum_quantity) == ("DEMO-ITEM", 12)
    assert settings_repo.needs_badge(db, "P12") is False


def test_save_type_with_minimum_ignores_the_minimum_of_the_input(
    service: StockService,
) -> None:
    type_id = service.save_type_with_minimum(None, _type_input(minimum_quantity=99), None)

    assert service.get_type(type_id).minimum_quantity is None


def test_save_type_with_minimum_changes_a_type_and_confirms_only_a_changed_minimum(
    service: StockService, db: DatabaseConnection
) -> None:
    type_id = _user_type(service)

    service.save_type_with_minimum(type_id, _type_input(label_pt_br="Novo"), None)
    assert settings_repo.needs_badge(db, "P12") is True  # the minimum did not change

    service.save_type_with_minimum(type_id, _type_input(label_pt_br="Novo"), 4)
    view = service.get_type(type_id)
    assert (view.label_pt_br, view.minimum_quantity) == ("Novo", 4)
    assert settings_repo.needs_badge(db, "P12") is False


@pytest.mark.parametrize("bad", [-1, True, 2.5, 1_000_000_001])
def test_a_failing_minimum_leaves_no_type_created(
    service: StockService, db: DatabaseConnection, bad: Any
) -> None:
    _refused(
        db,
        lambda: service.save_type_with_minimum(None, _type_input(), bad),
        INVALID_QUANTITY,
        "minimum_quantity",
    )

    assert service.get_type_by_code("DEMO-ITEM") is None
    assert settings_repo.needs_badge(db, "P12") is True


def test_a_failing_confirmation_leaves_no_type_created_and_a_type_unchanged(
    service: StockService, db: DatabaseConnection
) -> None:
    _refused(
        db,
        lambda: service.save_type_with_minimum(None, _type_input(), 3, "P99"),
        "UNKNOWN_PLACEHOLDER",
    )
    assert service.get_type_by_code("DEMO-ITEM") is None

    type_id = _user_type(service)
    _refused(
        db,
        lambda: service.save_type_with_minimum(type_id, _type_input(label_pt_br="Novo"), 3, "P99"),
        "UNKNOWN_PLACEHOLDER",
    )
    view = service.get_type(type_id)
    assert (view.label_pt_br, view.minimum_quantity) == ("Item demo", None)


def test_a_refusal_of_the_type_fields_leaves_everything_as_it_was(
    service: StockService, db: DatabaseConnection
) -> None:
    _user_type(service)

    _refused(
        db,
        lambda: service.save_type_with_minimum(None, _type_input(), 3),  # duplicate code
        DUPLICATE_CODE,
        "code",
    )
    assert settings_repo.needs_badge(db, "P12") is True


def test_save_type_with_minimum_refuses_a_read_only_connection(
    read_only_db: DatabaseConnection, clock: FixedClock
) -> None:
    reader = StockService(read_only_db, clock, lambda: OPERATOR)
    before = _state(read_only_db)

    _refused(read_only_db, lambda: reader.save_type_with_minimum(None, _type_input(), 3), READ_ONLY)

    assert _state(read_only_db) == before


# --------------------------------------------------------------------------- lots: delete


def test_deleting_a_lot_logs_the_lot_and_each_movement(
    service: StockService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    type_id = _user_type(service)
    lot_id = _lot(service, type_id)
    other = _lot(service, type_id, "DEMO-L002")
    for day, kind, quantity in (
        ("2026-03-02", MovementKind.ISSUE, 2),
        ("2026-03-03", MovementKind.DISPOSAL, 1),
    ):
        stock_repo.insert_movement(
            WriteContext(db, FixedClock.at(NOW_TEXT), OPERATOR),
            lot_id=lot_id,
            moved_on=day,
            kind=kind.value,
            quantity=quantity,
            reference="",
            note=None,
        )
    before = len(change_log_rows(db))

    service.delete_lot(lot_id)

    rows = change_log_rows(db)[before:]
    assert _entities(rows) == Counter({("stock_lot", "delete"): 1, ("stock_movement", "delete"): 3})
    assert all(row["after_json"] is None and row["before_json"] for row in rows)
    assert {row["operator"] for row in rows} == {OPERATOR}
    assert [lot.id for lot in service.list_lots()] == [other]
    assert stock_repo.list_movements(db, lot_id) == []
    assert len(stock_repo.list_movements(db, other)) == 1
    _refused(db, lambda: service.delete_lot(lot_id), NOT_FOUND, "lot_id")


# --------------------------------------------------------------------------- read-only


def test_read_only_mode_refuses_every_write(
    read_only_db: DatabaseConnection, clock: FixedClock
) -> None:
    reader = StockService(read_only_db, clock, lambda: OPERATOR)
    before = _state(read_only_db)
    calls: list[Callable[[], object]] = [
        lambda: reader.create_type(_type_input()),
        lambda: reader.update_type(1, _type_input()),
        lambda: reader.deactivate_type(1),
        lambda: reader.activate_type(1),
        lambda: reader.set_minimum(1, 5),
        lambda: reader.set_minimum(1, 5, confirm_placeholder="P12"),
        lambda: reader.delete_type(1),
        lambda: reader.create_lot(_lot_input(1), _receipt()),
        lambda: reader.update_lot(1, _lot_input(1)),
        lambda: reader.delete_lot(1),
    ]

    for call in calls:
        assert _error(call).code == READ_ONLY

    assert _state(read_only_db) == before
    assert len(reader.list_types()) == 17


# --------------------------------------------------------------------------- labels and wiring


def _view(**changes: Any) -> StockTypeView:
    fields: dict[str, Any] = {
        "id": 1,
        "code": "DEMO-X",
        "built_in": False,
        "category": StockCategory.OTHER,
        "label_pt_br": "Rotulo pt",
        "label_en_us": "Label en",
        "label_es_es": None,
        "minimum_quantity": None,
        "active": True,
    }
    fields.update(changes)
    return StockTypeView(**fields)


def test_stock_type_label_falls_back_to_pt_br_then_en_us_then_the_code() -> None:
    view = _view()

    assert stock_type_label(view, "en_US") == "Label en"
    assert stock_type_label(view, "en-US") == "Label en"
    assert stock_type_label(view, "es_ES") == "Rotulo pt"
    assert stock_type_label(_view(label_pt_br="  "), "es_ES") == "Label en"
    assert stock_type_label(_view(label_pt_br=None, label_en_us=None), "pt_BR") == "DEMO-X"


def test_build_services_wires_the_stock_service(db: DatabaseConnection, clock: FixedClock) -> None:
    from cbrn_dashboard.ui.shell.context import Services, build_services

    services = build_services(db, clock, lambda: OPERATOR)

    assert isinstance(services.stock, StockService)
    assert Services().stock is None
    assert build_services(None, clock, lambda: OPERATOR).stock is None
