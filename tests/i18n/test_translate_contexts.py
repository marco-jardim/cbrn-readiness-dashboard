# SPDX-License-Identifier: GPL-3.0-or-later
"""Guard: translation contexts and source texts are string literals; ``self.tr()`` is never used.

``pyside6-lupdate`` extracts only ``QCoreApplication.translate("<literal>", "<literal>")``
calls, so a constant or variable context or source text would silently drop the message from the
catalogues. A ``translate`` reference that is not called on the spot (``partial(...)``, a
``lambda``, an attribute) hides its arguments from the guard and is flagged as well.
"""

import ast
import textwrap
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QObject, QTranslator

from tests.i18n._ts import (
    SRC_ROOT,
    is_translate_call,
    load_script,
    receiver_names,
    translate_aliases,
)

# Recorded observation of ``self.tr()`` in an inherited method (PLAN.md section 6 pitfall),
# measured by ``test_tr_inheritance_experiment`` on PySide6 6.12.0. The probe catalogue holds only
# the base class's context; True would mean that a subclass instance gets the untranslated source
# text from the inherited method (the context is the instance's class name), False means that it
# still gets the translation (the base class's context is found). Observed: False.
TR_USES_SUBCLASS_CONTEXT = False


def _is_literal_string(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _argument(call: ast.Call, position: int, keyword: str) -> ast.expr | None:
    """Return the positional argument ``position`` or the keyword ``keyword``, if present."""
    if len(call.args) > position:
        return call.args[position]
    return next((kw.value for kw in call.keywords if kw.arg == keyword), None)


def find_violations(source: str, filename: str = "<snippet>") -> list[str]:
    """Return one message per bad ``translate()``/``.tr()`` call or non-call ``translate`` use."""
    tree = ast.parse(source, filename=filename)
    class_names, function_names = translate_aliases(tree)

    problems: list[str] = []

    # A ``QCoreApplication.translate`` that is neither called nor a plain alias assignment.
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            allowed.add(id(node.func))
        elif isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) for t in node.targets):
            allowed.add(id(node.value))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "translate"
            and id(node) not in allowed
            and receiver_names(node.value) & class_names
        ):
            problems.append(
                f"{filename}:{node.lineno}: translate referenced without a direct call "
                "(partial/lambda/attribute); call QCoreApplication.translate with literals"
            )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        where = f"{filename}:{node.lineno}"
        if isinstance(func, ast.Attribute) and func.attr == "tr":
            problems.append(f"{where}: .tr() is forbidden; use QCoreApplication.translate")
            continue
        if not is_translate_call(node, class_names, function_names):
            continue
        context = _argument(node, 0, "context")
        if context is None or not _is_literal_string(context):
            problems.append(f"{where}: translate() context must be a string literal")
        source_text = _argument(node, 1, "sourceText")
        if source_text is None or not _is_literal_string(source_text):
            problems.append(f"{where}: translate() source text must be a string literal")
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
        'QCoreApplication.translate("Shell", "Hel" "lo")',
        'QCoreApplication.translate("Shell", sourceText="Hello")',
        'QCoreApplication.translate("Shell", "Hello", "disambiguation")',
        'f = _translate = QCoreApplication.translate\nf("Shell", "Hello")',
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
        # non-literal source text
        'QCoreApplication.translate("Shell", text)',
        'QCoreApplication.translate("Shell", f"Hello {name}")',
        'QCoreApplication.translate("Shell", "Hel" + "lo")',
        'QCoreApplication.translate("Shell", sourceText=text)',
        'QCoreApplication.translate("Shell", b"Hello")',
        'QCoreApplication.translate("Shell")',
        'def t(s):\n    return QCoreApplication.translate("Shell", s)',
        '_translate = QCoreApplication.translate\n_translate("Shell", text)',
        'from PySide6.QtCore import QCoreApplication as QCA\nQCA.translate("Shell", text)',
        # translate referenced without a direct call
        'partial(QCoreApplication.translate, "Shell")',
        'functools.partial(QtCore.QCoreApplication.translate, "Shell")',
        "tr = lambda: QCoreApplication.translate",
        "self.t = QCoreApplication.translate",
        "translate_fn: object = QApplication.translate",
        "handlers = [QGuiApplication.translate]",
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
