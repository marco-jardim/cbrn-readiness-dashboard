# SPDX-License-Identifier: GPL-3.0-or-later
"""Modal Qt dialogs are created only in ``ui/shell/prompts.py`` (PLAN.md T1.9).

Every message box, file picker, input or progress dialog goes through the ``Prompts`` interface,
so tests can replace it with a fake and a console-less (frozen, windowed) run never blocks on a
dialog nobody can see. This guard parses every module below ``src/cbrn_dashboard`` and fails on
an import of, or a reference (a name or an attribute) to, one of Qt's ready-made modal dialog
classes anywhere but ``ui/shell/prompts.py``. The application's own ``QDialog`` subclasses are
allowed; words in strings and comments are not code and are ignored.
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "src" / "cbrn_dashboard"
PROMPTS_RELATIVE = Path("ui") / "shell" / "prompts.py"

FORBIDDEN: frozenset[str] = frozenset(
    {
        "QMessageBox",
        "QFileDialog",
        "QInputDialog",
        "QColorDialog",
        "QFontDialog",
        "QErrorMessage",
        "QProgressDialog",
    }
)


def forbidden_uses(source: str) -> list[tuple[int, str]]:
    """``(line, name)`` of every import of or reference to a forbidden dialog class."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import | ast.ImportFrom):
            module = node.module if isinstance(node, ast.ImportFrom) else None
            for alias in node.names:
                if alias.name == "*" and module is not None and module.endswith("QtWidgets"):
                    # a star import would hide every forbidden name from this scan
                    found.append((node.lineno, f"{module}.*"))
                elif alias.name.rsplit(".", 1)[-1] in FORBIDDEN:
                    found.append((node.lineno, alias.name))
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN:
            found.append((node.lineno, node.id))
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN:
            found.append((node.lineno, node.attr))
    return sorted(set(found))


def offenders(package: Path) -> list[str]:
    """``<path>:<line>: <name>`` for every forbidden use outside ``ui/shell/prompts.py``."""
    allowed = package / PROMPTS_RELATIVE
    found: list[str] = []
    for path in sorted(package.rglob("*.py")):
        if path == allowed:
            continue
        for line, name in forbidden_uses(path.read_text(encoding="utf-8")):
            found.append(f"{path.relative_to(package).as_posix()}:{line}: {name}")
    return found


# --------------------------------------------------------------------------- the real guard


def test_modal_qt_dialogs_are_created_only_in_prompts() -> None:
    found = offenders(PACKAGE)
    assert found == [], "modal Qt dialogs outside ui/shell/prompts.py:\n" + "\n".join(found)


def test_the_guard_is_not_vacuous() -> None:
    assert len(list(PACKAGE.rglob("*.py"))) > 10
    prompts = (PACKAGE / PROMPTS_RELATIVE).read_text(encoding="utf-8")
    assert forbidden_uses(prompts)  # the one allowed module really uses them, and is seen


# --------------------------------------------------------------------------- self-tests


@pytest.mark.parametrize("name", sorted(FORBIDDEN))
def test_every_forbidden_class_is_caught_when_imported(name: str) -> None:
    assert forbidden_uses(f"from PySide6.QtWidgets import {name}\n") == [(1, name)]


@pytest.mark.parametrize(
    "source",
    [
        "from PySide6.QtWidgets import QMessageBox\n",
        "from PySide6.QtWidgets import QLabel, QMessageBox\n",
        "from PySide6.QtWidgets import QFileDialog as Picker\n",
        "from PySide6 import QtWidgets\nQtWidgets.QMessageBox.critical(None, 't', 'x')\n",
        "import PySide6.QtWidgets as W\nW.QInputDialog.getText(None, 't', 'l')\n",
        "def f(box: QMessageBox) -> None: ...\n",
        "progress = QProgressDialog()\n",
        "from PySide6.QtWidgets import *\n",
    ],
)
def test_the_scanner_catches_each_form(source: str) -> None:
    assert forbidden_uses(source)


@pytest.mark.parametrize(
    "source",
    [
        "from PySide6.QtWidgets import QDialog\n\n\nclass Editor(QDialog):\n    pass\n",
        "from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBoxLike\n",
        "# QMessageBox and QFileDialog are only named in this comment\nx = 1\n",
        "text = 'QMessageBox QFileDialog QInputDialog QProgressDialog'\n",
        '"""QErrorMessage, QColorDialog and QFontDialog in a docstring."""\n',
    ],
)
def test_the_scanner_leaves_allowed_code_alone(source: str) -> None:
    assert forbidden_uses(source) == []


def test_only_prompts_may_use_them(tmp_path: Path) -> None:
    package = tmp_path / "cbrn_dashboard"
    prompts = package / PROMPTS_RELATIVE
    prompts.parent.mkdir(parents=True)
    prompts.write_text("from PySide6.QtWidgets import QMessageBox\n", encoding="utf-8")
    (package / "ui" / "page.py").write_text(
        "from PySide6.QtWidgets import QDialog\n", encoding="utf-8"
    )
    assert offenders(package) == []

    (package / "ui" / "other.py").write_text(
        "from PySide6 import QtWidgets\n\nQtWidgets.QFileDialog.getOpenFileName()\n",
        encoding="utf-8",
    )
    assert offenders(package) == ["ui/other.py:3: QFileDialog"]
