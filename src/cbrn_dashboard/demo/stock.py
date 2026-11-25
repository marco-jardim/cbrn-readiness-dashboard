# SPDX-License-Identifier: GPL-3.0-or-later
"""Demo data for the stock module (PLAN.md T11.16, D25, D32 to D38, O01 to O04).

Everything here is fictitious management data: lot codes, quantities, dates and prices. The dates
are computed from ``ctx.today`` (the injected clock's date) and no movement is dated after today.
Prices are whole minor units; they are BRL except one USD lot, and the two currencies are never
added. Everything goes THROUGH ``services.stock.StockService``, so every row is validated and
written to the change log with the operator label ``DEMO``. ``ctx.rng`` only varies the unit
prices, so the statuses, quantities and alerts below hold for every seed.

The fixed cases (days are relative to the creation day; ``P11`` is the 90-day warning window):

* Chemical antidote: ``DEMO-L001`` VALID (expires in 400 days; received 50 at -200, 5 issued at
  -30), ``DEMO-L002`` EXPIRING (in 20 days; 10 on hand), ``DEMO-L003`` EXPIRED (15 days ago; 4 on
  hand, ``LOT_EXPIRED``), ``DEMO-L004`` EMPTY (received 10, disposed of 10 after its expiry).
* Radiological and nuclear antidote ``DEMO-L005``: 8 valid against a minimum of 20 (``LOW_STOCK``).
* Biological antidote ``DEMO-L006``: 12 valid against a minimum of 5, with a loss and the two
  adjustments (each with a note starting with ``DEMO``): every movement kind appears.
* Decontaminant: ``DEMO-L007`` valid, ``DEMO-L008`` expiring and priced in USD.
* Chemical detector ``DEMO-L009`` has no expiry date; level A PPE ``DEMO-L010`` and gloves
  ``DEMO-L011`` each have an expiring lot (``LOT_EXPIRING``).
* Oxygen cylinder ``DEMO-L012`` (first received 10 days ago, so as of 30 days ago it reads
  NOT_RECEIVED) and bubble stretcher ``DEMO-L013`` (no price) have no expiry date and small
  quantities.
* The user-defined antidote type ``DEMO-ANTIDOTE-X`` with lot ``DEMO-L014``.

The minimums (P12) exist ONLY in the demo database; a real database has no minimum (D25, D35).

Qt-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from cbrn_dashboard.domain.stock import MovementKind
from cbrn_dashboard.services.stock import (
    InitialReceipt,
    LotInput,
    MovementInput,
    StockService,
    StockTypeInput,
)

if TYPE_CHECKING:
    # The package imports this module to register it, so DemoContext is only needed for typing.
    from cbrn_dashboard.demo import DemoContext

__all__ = [
    "DEMO_TYPE_CODE",
    "LOT_CODES",
    "MINIMUMS",
    "OPERATOR",
    "generate",
]

#: Operator label written to the change log for every row this generator creates.
OPERATOR = "DEMO"

#: Code of the user-defined demo item type (category antidote).
DEMO_TYPE_CODE = "DEMO-ANTIDOTE-X"

#: The demo minimums by type code (P12); they are written only into the demo database.
MINIMUMS: dict[str, int] = {"ANTIDOTE_RAD_NUCLEAR": 20, "ANTIDOTE_BIOLOGICAL": 5}

_NOTE = "DEMO - fictitious lot"


@dataclass(frozen=True)
class _Move:
    """A movement after the initial receipt, ``days_ago`` days before today."""

    days_ago: int
    kind: MovementKind
    quantity: int
    note: str | None = None


@dataclass(frozen=True)
class _Lot:
    """One lot: ``expires_in`` days from today (``None`` = no expiry), a price base or none."""

    code: str
    type_code: str
    expires_in: int | None
    received_days_ago: int
    received_quantity: int
    moves: tuple[_Move, ...] = ()
    price_base: int | None = None
    currency: str = "BRL"


_ISSUE = MovementKind.ISSUE
_DISPOSAL = MovementKind.DISPOSAL
_LOSS = MovementKind.LOSS
_ADJUST_IN = MovementKind.ADJUSTMENT_IN
_ADJUST_OUT = MovementKind.ADJUSTMENT_OUT

# The creation order. Lot codes are unique across the types, so an alert names its lot exactly.
_PLAN: tuple[_Lot, ...] = (
    _Lot("DEMO-L001", "ANTIDOTE_CHEMICAL", 400, 200, 50, (_Move(30, _ISSUE, 5),), 12_500),
    _Lot("DEMO-L002", "ANTIDOTE_CHEMICAL", 20, 150, 10, (), 11_800),
    _Lot("DEMO-L003", "ANTIDOTE_CHEMICAL", -15, 300, 12, (_Move(100, _ISSUE, 8),), 10_900),
    _Lot(
        "DEMO-L004",
        "ANTIDOTE_CHEMICAL",
        -60,
        320,
        10,
        (_Move(45, _DISPOSAL, 10, "DEMO - disposed of after expiry (fictitious)"),),
        10_900,
    ),
    _Lot("DEMO-L005", "ANTIDOTE_RAD_NUCLEAR", 300, 100, 12, (_Move(25, _ISSUE, 4),), 48_000),
    _Lot(
        "DEMO-L006",
        "ANTIDOTE_BIOLOGICAL",
        250,
        150,
        15,
        (
            _Move(80, _ADJUST_IN, 3, "DEMO - count correction, found stock (fictitious)"),
            _Move(60, _LOSS, 4, "DEMO - lost in storage (fictitious)"),
            _Move(20, _ADJUST_OUT, 2, "DEMO - count correction, missing stock (fictitious)"),
        ),
        36_500,
    ),
    _Lot("DEMO-L007", "DECONTAMINANT", 300, 120, 30, (_Move(20, _ISSUE, 5),), 4_500),
    _Lot("DEMO-L008", "DECONTAMINANT", 60, 200, 20, (), 950, "USD"),
    _Lot("DEMO-L009", "DETECTOR_CHEMICAL", None, 180, 6, (_Move(60, _ISSUE, 1),), 850_000),
    _Lot("DEMO-L010", "PPE_LEVEL_A", 45, 250, 10, (), 120_000),
    _Lot("DEMO-L011", "GLOVE", 70, 180, 200, (_Move(30, _ISSUE, 40),), 350),
    _Lot("DEMO-L012", "OXYGEN_CYLINDER", None, 10, 8, (), 18_000),
    _Lot("DEMO-L013", "ISOLATION_STRETCHER", None, 90, 2, (), None),
    _Lot("DEMO-L014", DEMO_TYPE_CODE, 200, 60, 6, (), 7_000),
)

#: The lot codes of the plan, in creation order.
LOT_CODES: tuple[str, ...] = tuple(lot.code for lot in _PLAN)

_PRICE_STEP = 100  # unit prices vary by multiples of 1.00 of the currency
_PRICE_JITTER = 10  # up to nine steps


def generate(ctx: DemoContext) -> None:
    """Create the demo item type, the lots with their movements and the demo minimums."""
    # Imported here, not at the top: the package imports this module while it is still being
    # initialised, and this helper is defined in the package itself.
    from cbrn_dashboard.demo import assert_demo_identifier

    service = StockService(ctx.conn, ctx.clock, lambda: OPERATOR)
    rng = ctx.rng
    today = ctx.today

    labels = (
        "DEMO - ant\u00eddoto X (fict\u00edcio)",
        "DEMO - antidote X (fictitious)",
        "DEMO - ant\u00eddoto X (ficticio)",
    )
    assert_demo_identifier(DEMO_TYPE_CODE)
    for label in labels:
        assert_demo_identifier(label)
    service.create_type(
        StockTypeInput(
            code=DEMO_TYPE_CODE,
            category="antidote",
            label_pt_br=labels[0],
            label_en_us=labels[1],
            label_es_es=labels[2],
        )
    )
    type_ids: dict[str, int] = {}
    for view in service.list_types(include_inactive=True):
        type_ids[view.code] = view.id

    counter = 0
    for lot in _PLAN:
        assert_demo_identifier(lot.code)
        counter += 1
        price = None
        if lot.price_base is not None:
            price = lot.price_base + rng.randrange(_PRICE_JITTER) * _PRICE_STEP
        expires_on = None if lot.expires_in is None else today + timedelta(days=lot.expires_in)
        lot_id = service.create_lot(
            LotInput(
                type_id=type_ids[lot.type_code],
                lot_code=lot.code,
                expires_on=expires_on,
                unit_price_minor=price,
                currency=None if price is None else lot.currency,
                notes=_NOTE,
            ),
            InitialReceipt(
                moved_on=today - timedelta(days=lot.received_days_ago),
                quantity=lot.received_quantity,
                reference=f"DEMO-MV-{counter:03d}",
            ),
        )
        for move in lot.moves:
            counter += 1
            service.record_movement(
                lot_id,
                MovementInput(
                    moved_on=today - timedelta(days=move.days_ago),
                    kind=move.kind,
                    quantity=move.quantity,
                    reference=f"DEMO-MV-{counter:03d}",
                    note=move.note,
                ),
            )

    # The minimums are demo data only; a real database has none.
    for code, minimum in MINIMUMS.items():
        service.set_minimum(type_ids[code], minimum)
