# SPDX-License-Identifier: GPL-3.0-or-later
"""The interpreter of the build is uv's managed CPython, pinned to a full version (P9-08).

The licence notices in ``packaging/licenses/python-build-standalone`` describe the managed build
of CPython, so nothing may let uv pick a system interpreter instead.
"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_python_version_file_pins_a_full_patch_version() -> None:
    text = (ROOT / ".python-version").read_text(encoding="utf-8")
    assert re.fullmatch(r"3\.12\.\d+\n?", text), f"not a 3.12.x patch version: {text!r}"


def test_uv_uses_only_its_managed_python() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["tool"]["uv"]["python-preference"] == "only-managed"


def test_the_pinned_version_satisfies_requires_python() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["requires-python"] == ">=3.12"
    pinned = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    major, minor = (int(part) for part in pinned.split(".")[:2])
    assert (major, minor) >= (3, 12)
