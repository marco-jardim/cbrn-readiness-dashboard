# SPDX-License-Identifier: GPL-3.0-or-later
"""Demo data of the stock module (T11.16): the design cases, the DEMO marker, P12, determinism.

The expected statuses, quantities and alerts were worked out by hand from the fixed cases of
``demo/stock.py`` (see its docstring); they are not read back from the code under test.
"""

from collections.abc import Callable, Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest

from cbrn_dashboard import demo
from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.demo import (
    DEFAULT_SEED,
    DEMO_SEED_KEY,
    GENERATORS,
    DemoGenerator,
    is_demo_identifier,
    open_demo_database,
)
from cbrn_dashboard.demo import stock as demo_stock
from cbrn_dashboard.domain.alerts import AlertKind, stock_alerts
from cbrn_dashboard.domain.stock import LotRow, LotStatus, MovementKind, StockCategory
from cbrn_dashboard.paths import DATABASE_FILE_NAME
from cbrn_dashboard.services.stock import StockService
from cbrn_dashboard.storage import app_meta, settings_repo
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate

CLOCK = FixedClock.at("2026-03-05T12:00:00Z")
TODAY = date(2026, 3, 5)
OTHER_DAYS = (
    (FixedClock.at("2026-01-01T12:00:00Z"), date(2026, 1, 1)),
    (FixedClock.at("2026-12-31T12:00:00Z"), date(2026, 12, 31)),
    (FixedClock.at("2028-02-29T12:00:00Z"), date(2028, 2, 29)),
)

GENERATOR = DemoGenerator("stock", demo_stock.generate)

type Rows = list[tuple[object, ...]]
type Opener = Callable[..., DatabaseConnection]

TABLE_QUERIES = {
    "stock_item_type": (
        "SELECT id, code, built_in, category, label_pt_br, label_en_us, label_es_es,"
        " minimum_quantity, active FROM stock_item_type ORDER BY id"
    ),
    "stock_lot": (
        "SELECT id, type_id, lot_code, expires_on, unit_price_minor, currency, notes"
        " FROM stock_lot ORDER BY id"
    ),
    "stock_movement": (
        "SELECT id, lot_id, moved_on, kind, quantity, reference, note"
        " FROM stock_movement ORDER BY id"
    ),
}

#: lot code -> (type code, on hand, status) on the creation day, by hand from demo/stock.py.
EXPECTED_LOTS: dict[str, tuple[str, int, LotStatus]] = {
    "DEMO-L001": ("ANTIDOTE_CHEMICAL", 45, LotStatus.VALID),
    "DEMO-L002": ("ANTIDOTE_CHEMICAL", 10, LotStatus.EXPIRING),
    "DEMO-L003": ("ANTIDOTE_CHEMICAL", 4, LotStatus.EXPIRED),
    "DEMO-L004": ("ANTIDOTE_CHEMICAL", 0, LotStatus.EMPTY),
    "DEMO-L005": ("ANTIDOTE_RAD_NUCLEAR", 8, LotStatus.VALID),
    "DEMO-L006": ("ANTIDOTE_BIOLOGICAL", 12, LotStatus.VALID),
    "DEMO-L007": ("DECONTAMINANT", 25, LotStatus.VALID),
    "DEMO-L008": ("DECONTAMINANT", 20, LotStatus.EXPIRING),
    "DEMO-L009": ("DETECTOR_CHEMICAL", 5, LotStatus.VALID),
    "DEMO-L010": ("PPE_LEVEL_A", 10, LotStatus.EXPIRING),
    "DEMO-L011": ("GLOVE", 160, LotStatus.EXPIRING),
    "DEMO-L012": ("OXYGEN_CYLINDER", 8, LotStatus.VALID),
    "DEMO-L013": ("ISOLATION_STRETCHER", 2, LotStatus.VALID),
    "DEMO-L014": ("DEMO-ANTIDOTE-X", 6, LotStatus.VALID),
}


# --------------------------------------------------------------------------- helpers


@pytest.fixture
def opener(tmp_path: Path) -> Iterator[Opener]:
    """Builds migrated databases seeded with ONLY the stock generator; closes them at teardown."""
    opened: list[DatabaseConnection] = []
    counter = 0

    def open_one(*, seed: int = DEFAULT_SEED, clock: FixedClock = CLOCK) -> DatabaseConnection:
        nonlocal counter
        counter += 1
        folder = tmp_path / f"data{counter}"
        folder.mkdir()
        conn = open_and_migrate(
            folder / "stock.sqlite3", data_dir=folder, identity=DatabaseIdentity.DEMO
        )
        opened.append(conn)
        app_meta.initialise(conn, is_demo=True, created_with="0.0.1")  # generate() needs the flag
        assert demo.generate(conn, clock, seed=seed, generators=[GENERATOR]) is True
        return conn

    yield open_one
    for conn in opened:
        conn.close()


def _rows(conn: DatabaseConnection, sql: str, params: tuple[object, ...] = ()) -> Rows:
    return [tuple(row) for row in conn.execute(sql, params).fetchall()]


def _table(conn: DatabaseConnection, name: str) -> Rows:
    return _rows(conn, TABLE_QUERIES[name])


def _lots(conn: DatabaseConnection, as_of: date = TODAY) -> dict[str, LotRow]:
    return {row.lot_code: row for row in StockService(conn, CLOCK).lot_rows(as_of)}


# --------------------------------------------------------------------------- the design cases


def test_every_lot_has_the_hand_worked_quantity_and_status(opener: Opener) -> None:
    rows = _lots(opener())
    assert set(rows) == set(EXPECTED_LOTS)
    for code, (type_code, on_hand, status) in EXPECTED_LOTS.items():
        row = rows[code]
        assert (row.type_code, row.on_hand, row.status) == (type_code, on_hand, status), code


def test_the_lot_codes_of_the_plan_are_the_documented_ones() -> None:
    assert tuple(EXPECTED_LOTS) == demo_stock.LOT_CODES


def test_the_chemical_antidote_lots_have_the_designed_dates(opener: Opener) -> None:
    rows = _lots(opener())
    assert rows["DEMO-L001"].expires_on == TODAY + timedelta(days=400)
    assert rows["DEMO-L001"].received_on == TODAY - timedelta(days=200)
    assert rows["DEMO-L002"].days_to_expiry == 20
    assert rows["DEMO-L003"].days_to_expiry == -15
    assert rows["DEMO-L004"].expires_on == TODAY - timedelta(days=60)


def test_the_empty_lot_was_closed_with_a_disposal_after_its_expiry(opener: Opener) -> None:
    conn = opener()
    [(expires_on,)] = _rows(conn, "SELECT expires_on FROM stock_lot WHERE lot_code = 'DEMO-L004'")
    moves = _rows(
        conn,
        "SELECT m.moved_on, m.kind, m.quantity FROM stock_movement AS m"
        " JOIN stock_lot AS l ON l.id = m.lot_id WHERE l.lot_code = 'DEMO-L004' ORDER BY m.id",
    )
    assert [(kind, quantity) for _, kind, quantity in moves] == [("receipt", 10), ("disposal", 10)]
    assert str(moves[1][0]) > str(expires_on)


def test_every_lot_status_appears(opener: Opener) -> None:
    conn = opener()
    today = {row.status for row in _lots(conn).values()}
    assert today == {
        LotStatus.VALID,
        LotStatus.EXPIRING,
        LotStatus.EXPIRED,
        LotStatus.EMPTY,
    }
    earlier = _lots(conn, TODAY - timedelta(days=30))
    assert LotStatus.NOT_RECEIVED in {row.status for row in earlier.values()}


def test_one_lot_first_received_ten_days_ago_is_not_received_thirty_days_ago(
    opener: Opener,
) -> None:
    conn = opener()
    earlier = _lots(conn, TODAY - timedelta(days=30))
    not_received = [code for code, row in earlier.items() if row.status is LotStatus.NOT_RECEIVED]
    assert not_received == ["DEMO-L012"]
    assert _lots(conn)["DEMO-L012"].received_on == TODAY - timedelta(days=10)
    # the other lots were all received before that day: DEMO-L001 shows 45 (the issue is that day)
    assert earlier["DEMO-L001"].on_hand == 45


def test_every_movement_kind_appears(opener: Opener) -> None:
    conn = opener()
    kinds = {str(row[0]) for row in _rows(conn, "SELECT DISTINCT kind FROM stock_movement")}
    assert kinds == {kind.value for kind in MovementKind}


def test_adjustments_and_the_loss_carry_a_demo_note(opener: Opener) -> None:
    conn = opener()
    notes = _rows(
        conn,
        "SELECT kind, note FROM stock_movement"
        " WHERE kind IN ('loss', 'adjustment_in', 'adjustment_out')",
    )
    assert {kind for kind, _ in notes} == {"loss", "adjustment_in", "adjustment_out"}
    assert all(note is not None and str(note).startswith("DEMO") for _, note in notes)


def test_the_stock_alerts_are_the_three_kinds(opener: Opener) -> None:
    conn = opener()
    service = StockService(conn, CLOCK)
    types, lots, movements = service.alert_inputs()
    alerts = stock_alerts(types, lots, movements, TODAY, service.stock_rules())
    found = {(alert.kind, alert.subject_ref) for alert in alerts}
    assert found == {
        (AlertKind.LOT_EXPIRED, "DEMO-L003"),
        (AlertKind.LOT_EXPIRING, "DEMO-L002"),
        (AlertKind.LOT_EXPIRING, "DEMO-L008"),
        (AlertKind.LOT_EXPIRING, "DEMO-L010"),
        (AlertKind.LOT_EXPIRING, "DEMO-L011"),
        (AlertKind.LOW_STOCK, "ANTIDOTE_RAD_NUCLEAR"),
    }
    low = next(alert for alert in alerts if alert.kind is AlertKind.LOW_STOCK)
    assert (low.value, low.threshold) == (8.0, 20.0)


def test_the_type_summaries_have_the_hand_worked_valid_quantities(opener: Opener) -> None:
    service = StockService(opener(), CLOCK)
    summaries = {summary.type_code: summary for summary in service.type_summaries(TODAY)}
    chemical = summaries["ANTIDOTE_CHEMICAL"]
    assert (chemical.valid, chemical.on_hand, chemical.expired_qty, chemical.expiring_qty) == (
        55,
        59,
        4,
        10,
    )
    assert chemical.minimum is None
    rad = summaries["ANTIDOTE_RAD_NUCLEAR"]
    assert (rad.valid, rad.minimum, rad.below_minimum) == (8, 20, True)
    bio = summaries["ANTIDOTE_BIOLOGICAL"]
    assert (bio.valid, bio.minimum, bio.below_minimum) == (12, 5, False)
    assert summaries["DECONTAMINANT"].valid == 45


def test_the_prices_are_brl_minor_units_except_one_usd_lot_and_one_lot_without_price(
    opener: Opener,
) -> None:
    conn = opener()
    prices = {
        str(code): (price, currency)
        for code, price, currency in _rows(
            conn, "SELECT lot_code, unit_price_minor, currency FROM stock_lot"
        )
    }
    assert prices["DEMO-L013"] == (None, None)
    assert prices["DEMO-L008"][1] == "USD"
    others = [value for code, value in prices.items() if code not in {"DEMO-L008", "DEMO-L013"}]
    assert {currency for _, currency in others} == {"BRL"}
    assert all(isinstance(price, int) and price > 0 for price, _ in others)
    assert [code for code, (price, _) in prices.items() if price is None] == ["DEMO-L013"]


def test_lots_without_an_expiry_date_are_only_outside_antidotes_and_decontaminants(
    opener: Opener,
) -> None:
    rows = _lots(opener())
    without = {code for code, row in rows.items() if row.expires_on is None}
    assert without == {"DEMO-L009", "DEMO-L012", "DEMO-L013"}
    assert not any(
        rows[code].category in (StockCategory.ANTIDOTE, StockCategory.DECONTAMINANT)
        for code in without
    )


def test_the_user_defined_antidote_type_has_a_demo_label(opener: Opener) -> None:
    conn = opener()
    [(code, built_in, category, label)] = _rows(
        conn,
        "SELECT code, built_in, category, label_pt_br FROM stock_item_type WHERE built_in = 0",
    )
    assert (code, built_in, category) == ("DEMO-ANTIDOTE-X", 0, "antidote")
    assert str(label).startswith("DEMO")
    assert code == demo_stock.DEMO_TYPE_CODE


# --------------------------------------------------------------------------- the DEMO marker


def test_every_identifier_label_note_and_reference_starts_with_demo(opener: Opener) -> None:
    conn = opener()
    checks = (
        "SELECT lot_code FROM stock_lot",
        "SELECT notes FROM stock_lot",
        "SELECT code FROM stock_item_type WHERE built_in = 0",
        "SELECT label_pt_br FROM stock_item_type WHERE built_in = 0",
        "SELECT label_en_us FROM stock_item_type WHERE built_in = 0",
        "SELECT label_es_es FROM stock_item_type WHERE built_in = 0",
        "SELECT reference FROM stock_movement",
        "SELECT note FROM stock_movement WHERE note IS NOT NULL",
    )
    for sql in checks:
        values = [str(row[0]) for row in _rows(conn, sql)]
        assert values, sql
        assert [value for value in values if not is_demo_identifier(value)] == [], sql


def test_every_change_is_attributed_to_the_demo_operator(opener: Opener) -> None:
    conn = opener()
    assert _rows(conn, "SELECT DISTINCT operator FROM change_log") == [("DEMO",)]
    assert demo_stock.OPERATOR == "DEMO"


def test_no_movement_is_dated_after_today_on_any_day(opener: Opener) -> None:
    for clock, today in ((CLOCK, TODAY), *OTHER_DAYS):
        conn = opener(clock=clock)
        [(latest,)] = _rows(conn, "SELECT max(moved_on) FROM stock_movement")
        assert str(latest) <= today.isoformat(), today
        rows = {row.lot_code: row for row in StockService(conn, clock).lot_rows(today)}
        assert {code: (r.on_hand, r.status) for code, r in rows.items()} == {
            code: (on_hand, status) for code, (_, on_hand, status) in EXPECTED_LOTS.items()
        }, today


# --------------------------------------------------------------------------- minimums and P12


def test_only_the_demo_minimums_are_set_and_p12_stays_flagged(opener: Opener) -> None:
    conn = opener()
    minimums = {
        str(code): minimum
        for code, minimum in _rows(
            conn,
            "SELECT code, minimum_quantity FROM stock_item_type WHERE minimum_quantity IS NOT NULL",
        )
    }
    assert minimums == {"ANTIDOTE_RAD_NUCLEAR": 20, "ANTIDOTE_BIOLOGICAL": 5}
    assert minimums == demo_stock.MINIMUMS
    assert settings_repo.needs_badge(conn, "P12") is True  # writing demo minimums never confirms it


def test_a_real_database_has_no_minimums_and_no_stock(tmp_path: Path) -> None:
    conn = open_and_migrate(
        tmp_path / DATABASE_FILE_NAME, data_dir=tmp_path, identity=DatabaseIdentity.REAL
    )
    try:
        app_meta.initialise(conn, is_demo=False, created_with="0.0.1")
        with_minimum = "SELECT count(*) FROM stock_item_type WHERE minimum_quantity IS NOT NULL"
        assert _rows(conn, with_minimum) == [(0,)]
        assert _rows(conn, "SELECT count(*) FROM stock_lot") == [(0,)]
        assert _rows(conn, "SELECT count(*) FROM stock_movement") == [(0,)]
        assert _rows(conn, "SELECT count(*) FROM stock_item_type WHERE built_in = 0") == [(0,)]
        assert settings_repo.needs_badge(conn, "P12") is True
    finally:
        conn.close()


def test_the_demo_stock_never_reaches_the_real_database_of_the_same_folder(tmp_path: Path) -> None:
    real = open_and_migrate(
        tmp_path / DATABASE_FILE_NAME, data_dir=tmp_path, identity=DatabaseIdentity.REAL
    )
    app_meta.initialise(real, is_demo=False, created_with="0.0.1")
    real.close()
    conn = open_demo_database(tmp_path, CLOCK, generators=[GENERATOR])
    conn.close()
    reopened = open_and_migrate(
        tmp_path / DATABASE_FILE_NAME, data_dir=tmp_path, identity=DatabaseIdentity.REAL
    )
    try:
        assert _rows(reopened, "SELECT count(*) FROM stock_lot") == [(0,)]
        assert _rows(
            reopened, "SELECT count(*) FROM stock_item_type WHERE minimum_quantity IS NOT NULL"
        ) == [(0,)]
    finally:
        reopened.close()


# --------------------------------------------------------------------------- determinism


def test_the_same_seed_gives_identical_stock(opener: Opener) -> None:
    first, second = opener(seed=7), opener(seed=7)
    for name in TABLE_QUERIES:
        assert _table(first, name) == _table(second, name), name


def test_another_seed_changes_only_the_prices(opener: Opener) -> None:
    first, second = opener(seed=1), opener(seed=2)
    assert _table(first, "stock_movement") == _table(second, "stock_movement")
    assert _table(first, "stock_item_type") == _table(second, "stock_item_type")
    prices_a = _rows(first, "SELECT unit_price_minor FROM stock_lot ORDER BY id")
    prices_b = _rows(second, "SELECT unit_price_minor FROM stock_lot ORDER BY id")
    assert prices_a != prices_b
    # the situations (status, quantity) are the same for every seed
    assert {c: (r.on_hand, r.status) for c, r in _lots(first).items()} == {
        c: (r.on_hand, r.status) for c, r in _lots(second).items()
    }


# --------------------------------------------------------------------------- framework


def test_the_generator_is_registered_after_budget_and_before_targets() -> None:
    names = [generator.name for generator in GENERATORS]
    assert names.index("stock") == names.index("budget") + 1
    assert names.index("stock") == names.index("targets") - 1
    assert GENERATORS[names.index("stock")].run is demo_stock.generate


def test_the_framework_seeds_the_demo_database_once(tmp_path: Path) -> None:
    conn = open_demo_database(tmp_path, CLOCK, generators=[GENERATOR])
    try:
        assert app_meta.get(conn, DEMO_SEED_KEY) == str(DEFAULT_SEED)
        rows = _table(conn, "stock_movement")
        assert rows
    finally:
        conn.close()
    reopened = open_demo_database(tmp_path, CLOCK, generators=[GENERATOR])
    try:
        assert _table(reopened, "stock_movement") == rows  # nothing generated a second time
    finally:
        reopened.close()
