# SPDX-License-Identifier: GPL-3.0-or-later
"""The placeholder registry in the code and PLAN.md section 3.5 cannot drift apart (T1.5)."""

from __future__ import annotations

import re
from pathlib import Path

from cbrn_dashboard.domain.config import PLACEHOLDERS, flagged_placeholder_ids

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "PLAN.md"

TABLE_ROW = re.compile(r"^\| (P\d\d) \|", re.MULTILINE)


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


def test_every_flagged_placeholder_is_documented_in_the_plan() -> None:
    section = _section_3_5()
    flagged = flagged_placeholder_ids()
    assert flagged  # a release always has flagged placeholders until the owner clears them
    for placeholder_id in flagged:
        assert re.search(rf"\b{re.escape(placeholder_id)}\b", section), placeholder_id


def test_every_p_row_of_the_plan_is_declared_in_the_code() -> None:
    declared = {item.id for item in PLACEHOLDERS}
    documented = TABLE_ROW.findall(_section_3_5())
    assert documented  # the pattern must match the table
    for placeholder_id in documented:
        assert placeholder_id in declared, placeholder_id


def test_every_p_placeholder_in_the_code_has_a_row_in_the_plan() -> None:
    documented = set(TABLE_ROW.findall(_section_3_5()))
    for item in PLACEHOLDERS:
        if item.id.startswith("P"):
            assert item.id in documented, item.id
