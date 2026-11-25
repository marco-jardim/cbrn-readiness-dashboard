# SPDX-License-Identifier: GPL-3.0-or-later
"""The placeholder registry in the code and PLAN.md section 3.5 cannot drift apart (T1.5)."""

from __future__ import annotations

import re
from pathlib import Path

from cbrn_dashboard.domain.config import PLACEHOLDERS, flagged_placeholder_ids

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "PLAN.md"

TABLE_ROW = re.compile(r"^\| ([AP]\d\d) \|")
_EM_DASH = "\u2014"  # "Configurable in" of an assumption without a setting or a withdrawn row


def _section_3_5() -> str:
    lines = PLAN.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("### 3.5"))
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "---" or lines[i].startswith("## 4."):
            end = i
            break
    return "\n".join(lines[start:end])


def test_section_is_found_and_contains_the_table() -> None:
    section = _section_3_5()
    assert section.startswith("### 3.5")
    assert "## 4." not in section
    assert "| ID | Assumption or placeholder |" in section


def test_no_placeholder_is_flagged_and_the_plan_says_so() -> None:
    section = _section_3_5()
    flagged = flagged_placeholder_ids()
    assert flagged == ()  # D39: since 1.2.0 no flag is set
    assert "From 1.2.0 (D39) no flag is set" in section
    for placeholder_id in flagged:  # kept for a future release that flags a value again
        assert re.search(rf"\b{re.escape(placeholder_id)}\b", section), placeholder_id


def test_the_withdrawn_p07_is_not_declared_in_the_code() -> None:
    assert "P07" not in {item.id for item in PLACEHOLDERS}
    assert _table_rows().get("P07") == _EM_DASH


def _table_rows() -> dict[str, str]:
    """Row id -> text of its "Configurable in" column (the 4th cell) for the A and P rows."""
    rows: dict[str, str] = {}
    for line in _section_3_5().splitlines():
        if TABLE_ROW.match(line) is None:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == 5, line  # ID, assumption, default, configurable in, question
        rows[cells[0]] = cells[3]
    return rows


def test_every_configurable_row_of_the_plan_is_declared_in_the_code() -> None:
    declared = {item.id for item in PLACEHOLDERS}
    rows = _table_rows()
    assert any(key.startswith("A") for key in rows)  # the pattern must match both kinds
    assert any(key.startswith("P") for key in rows)
    for row_id, configurable_in in rows.items():
        # An em dash: an assumption without a setting, or a withdrawn row (P07, D39).
        if configurable_in != _EM_DASH:
            assert row_id in declared, row_id


def test_every_placeholder_in_the_code_has_a_row_in_the_plan() -> None:
    rows = _table_rows()
    # D18 is declared in the code but documented in section 3.4 (decisions register), not in the
    # section 3.5 table: it is the one documented exception.
    # P07 is withdrawn (D39): its row stays in the plan with "Configurable in" an em dash.
    exceptions = {"D18"}
    for item in PLACEHOLDERS:
        if item.id in exceptions:
            continue
        assert item.id in rows, item.id
    assert {item.id for item in PLACEHOLDERS if item.id[0] not in "AP"} == exceptions
