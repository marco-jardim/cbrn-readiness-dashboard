# SPDX-License-Identifier: GPL-3.0-or-later
"""Guard: translation contexts are string literals and ``self.tr()`` is never used.

``pyside6-lupdate`` extracts only ``QCoreApplication.translate("<literal>", "<literal>")``
calls, so a constant or variable context would silently drop the message from the catalogues.
"""

import ast
import textwrap
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QObject, QTranslator

from tests.i18n._ts import SRC_ROOT, load_script

QT_APPLICATION_CLASSES = frozenset({"QCoreApplication", "QGuiApplication", "QApplication"})

# Observed behaviour of ``self.tr()`` in an inherited method with PySide6 6.12 (PLAN.md section 6
# pitfall). True: the context is the class name of the *instance*, so a catalogue that holds only
# the base class's context loses the translation for subclass instances. False: PySide6 falls back
# along the MRO, so the base class's context is still found.
# NOTE: set from an educated guess because the experiment could not be run when this file was
# written; flip the constant if ``test_tr_inheritance_experiment`` fails.
TR_USES_SUBCLASS_CONTEXT = False


def _is_literal_string(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _receiver_names(node: ast.expr) -> set[str]:
    """Names along an attribute chain: ``QtCore.QCoreApplication`` -> both names."""
    names: set[str] = set()
    while isinstance(node, ast.Attribute):
        names.add(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.add(node.id)
    return names


def find_violations(source: str, filename: str = "<snippet>") -> list[str]:
    """Return one message per ``translate()`` with a non-literal context and per ``.tr()`` call."""
    tree = ast.parse(source, filename=filename)

    class_names = set(QT_APPLICATION_CLASSES)
    function_names = {"translate"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in QT_APPLICATION_CLASSES:
                    class_names.add(alias.asname or alias.name)
                elif alias.name == "translate":
                    function_names.add(alias.asname or alias.name)
        elif (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "translate"
            and _receiver_names(node.value.value) & class_names
        ):
            # ``_translate = QCoreApplication.translate``
            function_names.update(t.id for t in node.targets if isinstance(t, ast.Name))

    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        where = f"{filename}:{node.lineno}"
        if isinstance(func, ast.Attribute) and func.attr == "tr":
            problems.append(f"{where}: .tr() is forbidden; use QCoreApplication.translate")
            continue
        is_translate = (
            isinstance(func, ast.Attribute)
            and func.attr == "translate"
            and (bool(_receiver_names(func.value) & class_names) or len(node.args) >= 2)
        ) or (isinstance(func, ast.Name) and func.id in function_names)
        if not is_translate:
            continue
        context: ast.expr | None = node.args[0] if node.args else None
        if context is None:
            context = next((kw.value for kw in node.keywords if kw.arg == "context"), None)
        if context is None or not _is_literal_string(context):
            problems.append(f"{where}: translate() context must be a string literal")
    return problems


def test_src_translate_contexts_are_literals() -> None:
    files = sorted((SRC_ROOT / "cbrn_dashboard").rglob("*.py"))
    assert files, "no source files found"
    problems: list[str] = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        problems.extend(find_violations(source, str(path.relative_to(SRC_ROOT))))
    assert not problems, "\n".join(problems)


# --- self-tests of the guard -------------------------------------------------------------------


@pytest.mark.parametrize(
    "snippet",
    [
        'QCoreApplication.translate("Shell", "Hello")',
        'QCoreApplication.translate("Shell", "%n item(s)", None, n)',
        'QCoreApplication.translate(context="Shell", sourceText="Hello")',
        'QtCore.QCoreApplication.translate("Shell", "Hello")',
        '_translate = QCoreApplication.translate\n_translate("Shell", "Hello")',
        'from PySide6.QtCore import QCoreApplication as QCA\nQCA.translate("Shell", "Hello")',
        "text.translate(table)",
        'title = labels.get("x")',
    ],
)
def test_guard_accepts_literal_contexts(snippet: str) -> None:
    assert find_violations(snippet) == []


@pytest.mark.parametrize(
    "snippet",
    [
        'CTX = "Shell"\nQCoreApplication.translate(CTX, "Hello")',
        'QCoreApplication.translate(context, "Hello")',
        'QCoreApplication.translate(f"Sh{x}", "Hello")',
        'QCoreApplication.translate("Sh" + "ell", "Hello")',
        'QCoreApplication.translate(self.CONTEXT, "Hello")',
        "QCoreApplication.translate()",
        'QCoreApplication.translate(context=ctx, sourceText="Hello")',
        'QtCore.QCoreApplication.translate(ctx, "Hello")',
        '_translate = QCoreApplication.translate\n_translate(ctx, "Hello")',
        'from PySide6.QtCore import QCoreApplication as QCA\nQCA.translate(ctx, "Hello")',
        'app.translate(ctx, "Hello")',
        'self.tr("Hello")',
        'QObject.tr("Hello")',
    ],
)
def test_guard_catches_violations(snippet: str) -> None:
    assert find_violations(textwrap.dedent(snippet)) != []


# --- the self.tr() inheritance pitfall (PLAN.md section 6) --------------------------------------

_PROBE_TS = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="pt_BR" sourcelanguage="en_US">
<context>
    <name>TrProbeBase</name>
    <message>
        <source>Hello</source>
        <translation>Ol\u00e1-base</translation>
    </message>
</context>
</TS>
"""


class TrProbeBase(QObject):
    def label(self) -> str:
        return self.tr("Hello")


class TrProbeDerived(TrProbeBase):
    pass


@pytest.mark.ui
def test_tr_inheritance_experiment(qapp: QCoreApplication, tmp_path: Path) -> None:
    """Record whether ``self.tr()`` in an inherited method uses the subclass's context."""
    ts_path = tmp_path / "probe.ts"
    qm_path = tmp_path / "probe.qm"
    ts_path.write_text(_PROBE_TS, encoding="utf-8")
    result = load_script().run_lrelease(ts_path, qm_path)
    assert result.returncode == 0, result.stdout + result.stderr

    translator = QTranslator()
    assert translator.load(str(qm_path))
    qapp.installTranslator(translator)
    try:
        # Control: the catalogue is looked up under the class name, so the experiment is valid.
        assert TrProbeBase().label() == "Ol\u00e1-base"
        # The catalogue holds only the base class's context.
        derived_lost_translation = TrProbeDerived().label() == "Hello"
    finally:
        qapp.removeTranslator(translator)

    assert derived_lost_translation is TR_USES_SUBCLASS_CONTEXT
