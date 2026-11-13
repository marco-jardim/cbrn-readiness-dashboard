# SPDX-License-Identifier: GPL-3.0-or-later
"""The README is the package readme and the front page: its links must point at real files."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"

#: The documents the README must link, written by hand (P10-08).
REQUIRED_LINKS = (
    "docs/install.en-US.md",
    "docs/install.pt-BR.md",
    "docs/install.es-ES.md",
    "docs/demo-walkthrough.md",
    "docs/architecture.md",
    "docs/indicators.md",
    "docs/data-protection.md",
    "PLAN.md",
    "LICENSE",
)


def _targets() -> list[str]:
    """The relative targets of the Markdown links of the README (no web or anchor-only links)."""
    found = re.findall(r"\]\(([^)\s]+)\)", README.read_text(encoding="utf-8"))
    return [
        target.split("#", 1)[0]
        for target in found
        if not re.match(r"[a-z][a-z0-9+.-]*:", target) and not target.startswith("#")
    ]


def test_every_relative_link_of_the_readme_is_an_existing_file() -> None:
    targets = _targets()
    assert targets
    assert [target for target in targets if not (ROOT / target).is_file()] == []


@pytest.mark.parametrize("required", REQUIRED_LINKS)
def test_the_readme_links_the_reference_documents(required: str) -> None:
    assert required in _targets()


def test_the_status_no_longer_says_there_is_no_code() -> None:
    text = README.read_text(encoding="utf-8")
    assert "no code yet" not in text
    assert "0.1.0" in text
    assert "No release has been published" in text
