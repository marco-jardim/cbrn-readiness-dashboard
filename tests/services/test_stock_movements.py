# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the stock movements, the balance rule and the as-of views (PLAN.md T11.6).

Fictitious data only. The clock is fixed at 2026-03-05.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from functools import partial
from typing import Any

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain import stock as rules
from cbrn_dashboard.domain.config import ReadinessConfig
from cbrn_dashboard.domain.stock import (
    Lot,
    LotStatus,
    Movement,
    MovementKind,
    StockCategory,
    StockRules,
    StockType,
)
from cbrn_dashboard.services.errors import (
    INVALID_DATE,
    NOT_FOUND,
    READ_ONLY,
    REQUIRED,
    ServiceError,
)
from cbrn_dashboard.services.stock import (
    BALANCE_NEGATIVE,
    DATE_IN_FUTURE,
    DUPLICATE_MOVEMENT,
    INVALID_CATEGORY,
    INVALID_KIND,
    INVALID_MONTHS,
    INVALID_QUANTITY,
    MAX_QUANTITY,
    NOTE_REQUIRED,
    ONLY_MOVEMENT,
    InitialReceipt,
    LotInput,
    MovementInput,
    StockService,
    StockTypeInput,
)
from cbrn_dashboard.storage import stock_repo
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.repository import WriteContext
from cbrn_dashboard.storage.settings_repo import save_config
from tests.services.conftest import ChangeLogRows

TODAY = date(2026, 3, 5)
NOW_TEXT = "2026-03-05T12:00:00Z"
OPERATOR = "op-demo"

_TABLES = ("stock_item_type", "stock_lot", "stock_movement", "setting", "change_log")

R = MovementKind.RECEIPT
ISSUE = MovementKind.ISSUE


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


def _movement_rows(conn: DatabaseConnection) -> list[tuple[object, ...]]:
    cursor = conn.execute("SELECT * FROM stock_movement ORDER BY id")
    return [tuple(row) for row in cursor.fetchall()]


def _refused(
    conn: DatabaseConnection, call: Callable[[], object], code: str, field: str | None = None
) -> None:
    """The call raises ``code`` (and ``field`` when given) and leaves the database as it was."""
    before_counts = _state(conn)
    before_rows = _movement_rows(conn)
    error = _error(call)
    assert error.code == code
    if field is not None:
        assert error.field == field
    assert _state(conn) == before_counts
    assert _movement_rows(conn) == before_rows


def _mv(
    moved_on: str | date | None, kind: MovementKind | str | None, quantity: int | None, **more: Any
) -> MovementInput:
    return MovementInput(moved_on=moved_on, kind=kind, quantity=quantity, **more)


def _type_id(service: StockService, code: str) -> int:
    view = service.get_type_by_code(code)
    assert view is not None
    return view.id


def _lot(
    service: StockService,
    type_code: str = "GLOVE",
    lot_code: str = "DEMO-L1",
    *,
    moved_on: str = "2026-03-01",
    quantity: int = 10,
    **lot_fields: Any,
) -> int:
    """A lot of a built-in type with its initial receipt; returns the lot id."""
    data = LotInput(type_id=_type_id(service, type_code), lot_code=lot_code, **lot_fields)
    return service.create_lot(data, InitialReceipt(moved_on=moved_on, quantity=quantity))


def _ids(service: StockService, lot_id: int) -> list[int]:
    return [view.id for view in service.movements(lot_id)]


# --------------------------------------------------------------------------- the balance rule


def test_a_backdated_issue_that_makes_a_later_day_negative_is_refused(
    service: StockService, db: DatabaseConnection
) -> None:
    lot_id = _lot(service)  # 10 on 03-01
    service.record_movement(lot_id, _mv("2026-03-03", ISSUE, 8))  # 2 left from 03-03

    # 5 on 03-02 is fine on 03-02 itself but makes 03-03 negative (10 - 5 - 8).
    _refused(
        db,
        partial(service.record_movement, lot_id, _mv("2026-03-02", ISSUE, 5)),
        BALANCE_NEGATIVE,
        "quantity",
    )
    # Before the first receipt the balance would be negative on that very day.
    _refused(
        db,
        partial(service.record_movement, lot_id, _mv("2026-02-20", MovementKind.LOSS, 1)),
        BALANCE_NEGATIVE,
        "quantity",
    )
    assert [view.balance_after for view in service.movements(lot_id)] == [10, 2]


def test_an_issue_larger_than_the_balance_today_is_refused(
    service: StockService, db: DatabaseConnection
) -> None:
    lot_id = _lot(service)

    _refused(
        db,
        partial(service.record_movement, lot_id, _mv("2026-03-05", ISSUE, 11)),
        BALANCE_NEGATIVE,
        "quantity",
    )


def test_issuing_the_whole_stock_leaves_zero_and_the_lot_reads_as_empty(
    service: StockService,
) -> None:
    lot_id = _lot(service)

    service.record_movement(lot_id, _mv("2026-03-04", MovementKind.DISPOSAL, 10))

    assert [view.balance_after for view in service.movements(lot_id)] == [10, 0]
    (row,) = service.lot_rows(TODAY)
    assert (row.on_hand, row.status) == (0, LotStatus.EMPTY)


def test_deleting_the_receipt_an_issue_depends_on_is_refused(
    service: StockService, db: DatabaseConnection
) -> None:
    lot_id = _lot(service)  # 10 on 03-01
    second = service.record_movement(lot_id, _mv("2026-03-02", R, 5))
    issue = service.record_movement(lot_id, _mv("2026-03-03", ISSUE, 12))
    first = _ids(service, lot_id)[0]

    # 15 - 12 = 3 left; without the second receipt 10 - 12 < 0, without the first 5 - 12 < 0.
    _refused(db, partial(service.delete_movement, second), BALANCE_NEGATIVE, "movement_id")
    _refused(db, partial(service.delete_movement, first), BALANCE_NEGATIVE, "movement_id")

    service.delete_movement(issue)  # nothing depends on the issue
    assert [view.balance_after for view in service.movements(lot_id)] == [10, 15]


def test_the_last_movement_of_a_lot_cannot_be_deleted(
    service: StockService, db: DatabaseConnection
) -> None:
    lot_id = _lot(service)
    (only,) = _ids(service, lot_id)

    _refused(db, partial(service.delete_movement, only), ONLY_MOVEMENT, "movement_id")

    # With a second movement the first can go as long as the balance holds.
    extra = service.record_movement(lot_id, _mv("2026-03-02", R, 1))
    service.delete_movement(only)
    assert _ids(service, lot_id) == [extra]
    _refused(db, partial(service.delete_movement, extra), ONLY_MOVEMENT, "movement_id")


def test_an_update_that_breaks_the_balance_is_refused(
    service: StockService, db: DatabaseConnection
) -> None:
    lot_id = _lot(service)  # 10 on 03-01
    receipt = _ids(service, lot_id)[0]
    service.record_movement(lot_id, _mv("2026-03-03", ISSUE, 8))

    # A smaller receipt, a receipt moved after the issue, and a receipt turned into an issue.
    _refused(
        db,
        partial(service.update_movement, receipt, _mv("2026-03-01", R, 7)),
        BALANCE_NEGATIVE,
        "quantity",
    )
    _refused(
        db,
        partial(service.update_movement, receipt, _mv("2026-03-04", R, 10)),
        BALANCE_NEGATIVE,
        "quantity",
    )
    _refused(
        db,
        partial(service.update_movement, receipt, _mv("2026-03-01", ISSUE, 10)),
        BALANCE_NEGATIVE,
        "quantity",
    )
    # An issue made larger.
    issue = _ids(service, lot_id)[1]
    _refused(
        db,
        partial(service.update_movement, issue, _mv("2026-03-03", ISSUE, 11)),
        BALANCE_NEGATIVE,
        "quantity",
    )
    assert [view.balance_after for view in service.movements(lot_id)] == [10, 2]


def test_an_update_that_keeps_the_balance_is_accepted(service: StockService) -> None:
    lot_id = _lot(service)
    receipt = _ids(service, lot_id)[0]
    issue = service.record_movement(lot_id, _mv("2026-03-03", ISSUE, 8))

    service.update_movement(receipt, _mv("2026-03-02", R, 9, reference="NF-9", note="corrigido"))
    service.update_movement(issue, _mv("2026-03-04", ISSUE, 9))

    views = service.movements(lot_id)
    assert [(v.moved_on, v.kind, v.quantity, v.balance_after) for v in views] == [
        (date(2026, 3, 2), R, 9, 9),
        (date(2026, 3, 4), ISSUE, 9, 0),
    ]
    assert (views[0].reference, views[0].note) == ("NF-9", "corrigido")


def test_a_receipt_and_an_issue_on_the_same_day_are_accepted_in_any_order(
    service: StockService,
) -> None:
    lot_id = _lot(service)  # 10 on 03-01
    # An issue of 12 on 03-02 is more than the 10 on hand but not more than the day's receipt of 5.
    service.record_movement(lot_id, _mv("2026-03-02", R, 5))
    service.record_movement(lot_id, _mv("2026-03-02", ISSUE, 12))
    # A receipt recorded after an issue of the same day is accepted too.
    service.record_movement(lot_id, _mv("2026-03-04", ISSUE, 3))
    service.record_movement(lot_id, _mv("2026-03-04", R, 4))

    views = service.movements(lot_id)
    assert [(v.moved_on.day, v.kind, v.balance_after) for v in views] == [
        (1, R, 10),
        (2, R, 15),
        (2, ISSUE, 3),
        (4, R, 7),  # inflows come before outflows inside a day, so no balance shows negative
        (4, ISSUE, 4),
    ]
    assert all(view.balance_after >= 0 for view in views)


def test_movements_on_a_lot_of_an_inactive_type_stay_allowed(service: StockService) -> None:
    lot_id = _lot(service)
    service.deactivate_type(_type_id(service, "GLOVE"))

    service.record_movement(lot_id, _mv("2026-03-02", R, 2))
    service.record_movement(lot_id, _mv("2026-03-03", ISSUE, 12))

    assert [view.balance_after for view in service.movements(lot_id)] == [10, 12, 0]


# --------------------------------------------------------------------------- input rules


def test_a_movement_dated_after_the_clock_date_is_refused_and_today_is_accepted(
    service: StockService, db: DatabaseConnection
) -> None:
    lot_id = _lot(service)
    movement = _ids(service, lot_id)[0]

    _refused(
        db,
        partial(service.record_movement, lot_id, _mv("2026-03-06", R, 1)),
        DATE_IN_FUTURE,
        "moved_on",
    )
    _refused(
        db,
        partial(service.update_movement, movement, _mv(date(2026, 3, 6), R, 10)),
        DATE_IN_FUTURE,
        "moved_on",
    )
    service.record_movement(lot_id, _mv("2026-03-05", R, 1))  # today

    assert service.movements(lot_id)[-1].moved_on == TODAY


def test_the_future_is_judged_with_the_injected_clock(db: DatabaseConnection) -> None:
    later = StockService(db, FixedClock.at("2026-03-06T12:00:00Z"), lambda: OPERATOR)
    lot_id = _lot(later)

    later.record_movement(lot_id, _mv("2026-03-06", R, 1))

    assert later.movements(lot_id)[-1].moved_on == date(2026, 3, 6)


def test_an_adjustment_needs_a_note(service: StockService, db: DatabaseConnection) -> None:
    lot_id = _lot(service)
    movement = _ids(service, lot_id)[0]

    for kind in (MovementKind.ADJUSTMENT_IN, MovementKind.ADJUSTMENT_OUT):
        for note in (None, "", "   "):
            _refused(
                db,
                partial(service.record_movement, lot_id, _mv("2026-03-02", kind, 1, note=note)),
                NOTE_REQUIRED,
                "note",
            )
    _refused(
        db,
        partial(service.update_movement, movement, _mv("2026-03-01", "adjustment_in", 10)),
        NOTE_REQUIRED,
        "note",
    )

    service.record_movement(lot_id, _mv("2026-03-02", "adjustment_in", 2, note="contagem"))
    service.record_movement(lot_id, _mv("2026-03-03", "adjustment_out", 3, note=" erro "))

    views = service.movements(lot_id)
    assert [v.balance_after for v in views] == [10, 12, 9]
    assert views[2].note == "erro"  # stripped
    assert [v.signed_quantity for v in views] == [10, 2, -3]


def test_the_other_kinds_need_no_note(service: StockService) -> None:
    lot_id = _lot(service)

    for day, kind in enumerate(
        (MovementKind.ISSUE, MovementKind.DISPOSAL, MovementKind.LOSS, MovementKind.RECEIPT), 2
    ):
        service.record_movement(lot_id, _mv(f"2026-03-0{day}", kind, 1))

    assert len(service.movements(lot_id)) == 5


@pytest.mark.parametrize("quantity", [0, -1, MAX_QUANTITY + 1, 1.5, "3", True, None])
def test_a_quantity_outside_one_to_a_million_is_refused(
    service: StockService, db: DatabaseConnection, quantity: Any
) -> None:
    lot_id = _lot(service)
    data = MovementInput(moved_on="2026-03-02", kind=R, quantity=quantity)

    _refused(db, partial(service.record_movement, lot_id, data), INVALID_QUANTITY, "quantity")
    _refused(
        db,
        partial(service.update_movement, _ids(service, lot_id)[0], data),
        INVALID_QUANTITY,
        "quantity",
    )


def test_the_largest_quantity_is_accepted(service: StockService) -> None:
    lot_id = _lot(service)

    service.record_movement(lot_id, _mv("2026-03-02", R, MAX_QUANTITY))

    assert service.movements(lot_id)[-1].balance_after == MAX_QUANTITY + 10


def test_a_bad_date_or_kind_or_lot_is_refused(
    service: StockService, db: DatabaseConnection
) -> None:
    lot_id = _lot(service)

    _refused(db, partial(service.record_movement, lot_id, _mv(None, R, 1)), REQUIRED, "moved_on")
    _refused(db, partial(service.record_movement, lot_id, _mv("", R, 1)), REQUIRED, "moved_on")
    _refused(
        db,
        partial(service.record_movement, lot_id, _mv("2026-02-30", R, 1)),
        INVALID_DATE,
        "moved_on",
    )
    _refused(
        db, partial(service.record_movement, lot_id, _mv("2026-03-02", None, 1)), REQUIRED, "kind"
    )
    _refused(
        db,
        partial(service.record_movement, lot_id, _mv("2026-03-02", "sale", 1)),
        INVALID_KIND,
        "kind",
    )
    _refused(
        db, partial(service.record_movement, 9999, _mv("2026-03-02", R, 1)), NOT_FOUND, "lot_id"
    )
    _refused(
        db,
        partial(service.update_movement, 9999, _mv("2026-03-02", R, 1)),
        NOT_FOUND,
        "movement_id",
    )
    _refused(db, partial(service.delete_movement, 9999), NOT_FOUND, "movement_id")
    _refused(db, partial(service.movements, 9999), NOT_FOUND, "lot_id")


def test_a_duplicate_movement_is_refused(service: StockService, db: DatabaseConnection) -> None:
    lot_id = _lot(service)
    service.record_movement(lot_id, _mv("2026-03-02", R, 5, reference="NF-1"))
    other = service.record_movement(lot_id, _mv("2026-03-02", R, 5, reference="NF-2"))

    # Same lot, date, kind, quantity and reference (a blank reference is the empty one).
    _refused(
        db,
        partial(service.record_movement, lot_id, _mv("2026-03-02", R, 5, reference=" NF-1 ")),
        DUPLICATE_MOVEMENT,
    )
    _refused(
        db,
        partial(service.record_movement, lot_id, _mv("2026-03-01", R, 10, reference=None)),
        DUPLICATE_MOVEMENT,
    )
    _refused(
        db,
        partial(service.update_movement, other, _mv("2026-03-02", R, 5, reference="NF-1")),
        DUPLICATE_MOVEMENT,
    )
    # An update that keeps its own key (only the note changes) is not a duplicate of itself.
    service.update_movement(other, _mv("2026-03-02", R, 5, reference="NF-2", note="ok"))
    # Another lot may repeat the key.
    second_lot = _lot(service, "BOOT", "DEMO-L2")
    service.record_movement(second_lot, _mv("2026-03-02", R, 5, reference="NF-1"))


# --------------------------------------------------------------------------- change log and mode


def test_every_movement_write_is_logged(
    service: StockService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    lot_id = _lot(service)
    before = len(change_log_rows(db))

    movement = service.record_movement(lot_id, _mv("2026-03-02", R, 5, reference="NF-1"))
    service.update_movement(movement, _mv("2026-03-02", R, 6, reference="NF-1"))
    service.update_movement(movement, _mv("2026-03-02", R, 6, reference="NF-1"))  # no change
    service.delete_movement(movement)

    rows = change_log_rows(db)[before:]
    assert [(row["entity"], row["action"]) for row in rows] == [
        ("stock_movement", "insert"),
        ("stock_movement", "update"),
        ("stock_movement", "delete"),
    ]
    assert {row["operator"] for row in rows} == {OPERATOR}
    assert {row["at_utc"] for row in rows} == {NOW_TEXT}
    inserted = json.loads(str(rows[0]["after_json"]))
    assert (inserted["lot_id"], inserted["quantity"], inserted["reference"]) == (lot_id, 5, "NF-1")
    changed_before = json.loads(str(rows[1]["before_json"]))
    changed_after = json.loads(str(rows[1]["after_json"]))
    assert (changed_before["quantity"], changed_after["quantity"]) == (5, 6)
    assert json.loads(str(rows[2]["before_json"]))["quantity"] == 6


def test_a_refusal_writes_no_change_log_row(
    service: StockService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    lot_id = _lot(service)
    rows_before = change_log_rows(db)

    assert _error(partial(service.record_movement, lot_id, _mv("2026-03-02", ISSUE, 11))).code
    assert _error(partial(service.delete_movement, _ids(service, lot_id)[0])).code

    assert change_log_rows(db) == rows_before


def test_read_only_mode_refuses_every_movement_write(
    read_only_db: DatabaseConnection, clock: FixedClock
) -> None:
    reader = StockService(read_only_db, clock, lambda: OPERATOR)
    before = _state(read_only_db)
    calls: list[Callable[[], object]] = [
        partial(reader.record_movement, 1, _mv("2026-03-02", R, 1)),
        partial(reader.update_movement, 1, _mv("2026-03-02", R, 1)),
        partial(reader.delete_movement, 1),
    ]

    for call in calls:
        assert _error(call).code == READ_ONLY

    assert _state(read_only_db) == before
    assert reader.lot_rows(TODAY) == ()  # the views still read


# --------------------------------------------------------------------------- as-of views


def _fixture(service: StockService, db: DatabaseConnection, clock: FixedClock) -> dict[str, int]:
    """Four lots in three categories, two currencies, one expired, one unpriced, a minimum."""
    save_config(WriteContext(db, clock, OPERATOR), ReadinessConfig(default_currency="BRL"))
    user_type = service.create_type(
        StockTypeInput(code="DEMO-ITEM", category=StockCategory.OTHER, label_pt_br="Item demo")
    )
    service.set_minimum(_type_id(service, "ANTIDOTE_CHEMICAL"), 20)
    ids = {
        "A1": _lot(
            service,
            "ANTIDOTE_CHEMICAL",
            "DEMO-A1",
            moved_on="2026-02-01",
            expires_on="2026-04-01",
            unit_price_minor=1000,
            currency="BRL",
        ),
        "A2": _lot(
            service,
            "ANTIDOTE_CHEMICAL",
            "DEMO-A2",
            moved_on="2026-01-10",
            quantity=5,
            expires_on="2026-02-01",
        ),
        "D1": _lot(
            service,
            "DECONTAMINANT",
            "DEMO-D1",
            moved_on="2026-03-01",
            quantity=8,
            expires_on="2027-06-30",
            unit_price_minor=250,
            currency="USD",
        ),
    }
    ids["O1"] = service.create_lot(
        LotInput(type_id=user_type, lot_code="DEMO-O1"),
        InitialReceipt(moved_on="2026-02-15", quantity=3),
    )
    service.record_movement(ids["A1"], _mv("2026-02-10", ISSUE, 4))
    return ids


def _hand_built(
    service: StockService,
) -> tuple[list[StockType], list[Lot], list[Movement]]:
    """The domain records built from the public reads, independently of ``alert_inputs``."""
    types = [
        StockType(
            id=view.id,
            code=view.code,
            category=view.category,
            minimum_quantity=view.minimum_quantity,
            active=view.active,
        )
        for view in service.list_types(include_inactive=True)
    ]
    lots = [
        Lot(
            id=view.id,
            type_code=view.type_code,
            lot_code=view.lot_code,
            expires_on=view.expires_on,
            unit_price_minor=view.unit_price_minor,
            currency=view.currency,
        )
        for view in service.list_lots()
    ]
    movements = [
        Movement(
            id=view.id,
            lot_id=view.lot_id,
            moved_on=view.moved_on,
            kind=view.kind,
            quantity=view.quantity,
        )
        for lot in lots
        for view in service.movements(lot.id)
    ]
    return types, lots, movements


def test_the_views_equal_the_domain_results(
    service: StockService, db: DatabaseConnection, clock: FixedClock
) -> None:
    ids = _fixture(service, db, clock)
    types, lots, movements = _hand_built(service)
    domain_rules = StockRules(expiry_warning_days=90)

    for as_of in (date(2026, 1, 1), date(2026, 2, 12), TODAY, date(2027, 1, 1)):
        expected_rows = rules.lot_rows(types, lots, movements, as_of, domain_rules)
        assert service.lot_rows(as_of) == expected_rows
        assert service.type_summaries(as_of) == rules.type_summaries(
            types, lots, movements, as_of, domain_rules
        )
        assert service.stock_value(as_of) == rules.stock_value(expected_rows)
        assert service.expiry_schedule(as_of) == rules.expiry_schedule(expected_rows, as_of)
        assert service.expiry_schedule(as_of, months=3) == rules.expiry_schedule(
            expected_rows, as_of, 3
        )

    by_code = {row.lot_code: row for row in service.lot_rows(TODAY)}
    assert {code: (row.on_hand, row.status) for code, row in by_code.items()} == {
        "DEMO-A1": (6, LotStatus.EXPIRING),
        "DEMO-A2": (5, LotStatus.EXPIRED),
        "DEMO-D1": (8, LotStatus.VALID),
        "DEMO-O1": (3, LotStatus.VALID),
    }
    assert by_code["DEMO-A1"].lot_id == ids["A1"]
    value = service.stock_value(TODAY)
    assert value.unpriced_lots == 2
    assert value.by_currency["BRL"].valid_minor == 6000
    assert value.by_currency["USD"].valid_minor == 2000
    summary = {s.type_code: s for s in service.type_summaries(TODAY)}["ANTIDOTE_CHEMICAL"]
    assert (summary.valid, summary.below_minimum) == (6, True)


def test_the_views_follow_a_new_movement(
    service: StockService, db: DatabaseConnection, clock: FixedClock
) -> None:
    ids = _fixture(service, db, clock)

    service.record_movement(ids["A1"], _mv("2026-03-02", R, 20))

    today = {row.lot_code: row.on_hand for row in service.lot_rows(TODAY)}
    yesterday = {row.lot_code: row.on_hand for row in service.lot_rows(date(2026, 3, 1))}
    assert today["DEMO-A1"] == 26
    assert yesterday["DEMO-A1"] == 6  # the new receipt is dated 03-02


def test_a_date_before_the_first_receipt_shows_the_lot_as_not_received(
    service: StockService, db: DatabaseConnection, clock: FixedClock
) -> None:
    _fixture(service, db, clock)

    rows = {row.lot_code: row for row in service.lot_rows(date(2026, 1, 20))}

    assert rows["DEMO-A2"].status is LotStatus.EXPIRING  # received on 01-10, expires on 02-01
    assert rows["DEMO-A1"].status is LotStatus.NOT_RECEIVED
    assert rows["DEMO-A1"].on_hand == 0
    assert rows["DEMO-D1"].status is LotStatus.NOT_RECEIVED
    assert rows["DEMO-O1"].status is LotStatus.NOT_RECEIVED
    assert service.stock_value(date(2026, 1, 20)).unpriced_lots == 1


def test_the_views_can_be_limited_to_categories(
    service: StockService, db: DatabaseConnection, clock: FixedClock
) -> None:
    _fixture(service, db, clock)

    antidotes = service.lot_rows(TODAY, [StockCategory.ANTIDOTE])
    both = service.lot_rows(TODAY, categories=["antidote", StockCategory.OTHER])

    assert {row.lot_code for row in antidotes} == {"DEMO-A1", "DEMO-A2"}
    assert {row.lot_code for row in both} == {"DEMO-A1", "DEMO-A2", "DEMO-O1"}
    assert {s.category for s in service.type_summaries(TODAY, [StockCategory.OTHER])} == {
        StockCategory.OTHER
    }
    assert service.lot_rows(TODAY, []) == ()
    only_decontaminant = service.stock_value(TODAY, [StockCategory.DECONTAMINANT])
    assert list(only_decontaminant.by_currency) == ["USD"]
    assert only_decontaminant.unpriced_lots == 0
    schedule = service.expiry_schedule(TODAY, categories=[StockCategory.DECONTAMINANT])
    assert sum(len(bucket.lots) for bucket in schedule) == 1
    unknown = _error(partial(service.lot_rows, TODAY, ["tool"]))
    assert (unknown.code, unknown.field) == (INVALID_CATEGORY, "category")


def test_the_expiry_window_comes_from_the_configuration(
    service: StockService, db: DatabaseConnection, clock: FixedClock
) -> None:
    _fixture(service, db, clock)  # DEMO-A1 expires in 27 days
    config = ReadinessConfig(default_currency="BRL", stock_expiry_warning_days=10)
    save_config(WriteContext(db, clock, OPERATOR), config)

    rows = {row.lot_code: row for row in service.lot_rows(TODAY)}

    assert rows["DEMO-A1"].status is LotStatus.VALID


def test_the_schedule_horizon_is_checked(service: StockService) -> None:
    for months in (0, 61, -1):
        error = _error(partial(service.expiry_schedule, TODAY, months))
        assert (error.code, error.field) == (INVALID_MONTHS, "months")
    assert len(service.expiry_schedule(TODAY, months=60)) == 60 + 3


def test_the_data_quality_finds_lots_without_movements_and_without_a_price(
    service: StockService, db: DatabaseConnection, clock: FixedClock
) -> None:
    ids = _fixture(service, db, clock)
    # A lot without any movement can only come from outside the service: write it by hand.
    orphan = stock_repo.insert_lot(
        WriteContext(db, clock, OPERATOR),
        type_id=_type_id(service, "GLOVE"),
        lot_code="DEMO-EMPTY",
        expires_on=None,
        unit_price_minor=None,
        currency=None,
        notes=None,
    )

    quality = service.data_quality(TODAY)

    assert quality.as_of == TODAY
    assert quality.lots_without_movements == (orphan,)
    assert quality.lots_without_price == tuple(sorted((ids["A2"], ids["O1"])))
    # Before any receipt nothing is on hand, so no lot lacks a price yet.
    assert service.data_quality(date(2026, 1, 1)).lots_without_price == ()


def test_the_alert_inputs_are_the_domain_records(
    service: StockService, db: DatabaseConnection, clock: FixedClock
) -> None:
    _fixture(service, db, clock)
    service.deactivate_type(_type_id(service, "GLOVE"))

    types, lots, movements = service.alert_inputs()
    hand_types, hand_lots, hand_movements = _hand_built(service)

    assert isinstance(types, tuple) and isinstance(lots, tuple) and isinstance(movements, tuple)
    assert sorted(types, key=lambda item: item.id) == sorted(hand_types, key=lambda i: i.id)
    assert sorted(lots, key=lambda item: item.id) == sorted(hand_lots, key=lambda i: i.id)
    assert sorted(movements, key=lambda item: item.id) == sorted(hand_movements, key=lambda i: i.id)
    assert len(types) == 18  # 17 built-in and the user type; the inactive one is included
    assert any(not item.active for item in types)
    assert (len(lots), len(movements)) == (4, 5)
