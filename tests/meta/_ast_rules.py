# SPDX-License-Identifier: GPL-3.0-or-later
"""Reusable AST rule engine for the layering and forbidden-API guard (PLAN T0.4).

The engine parses Python source with the standard-library ``ast`` module and never imports or
executes the code it checks. Paths handed to the engine are *relative to* ``src/cbrn_dashboard/``
and written with forward slashes (``PurePosixPath("ui/shell/folders.py")``).

Rules (ids are the ``Violation.rule`` values):

``NET``
    Imports of network, event-loop, browser and process modules anywhere in ``src/``. Besides plain
    ``import x`` and ``from x import y`` the engine sees ``from PySide6 import QtNetwork`` and the
    dynamic forms ``importlib.import_module("socket")`` / ``__import__("socket")`` with a
    string-literal argument.
``HANDOFF``
    Hand-offs to the shell or to other programs. ``subprocess`` and ``ctypes`` may not be imported
    anywhere in ``src/`` (the plan's exceptions are for ``tests/`` and ``scripts/``, which are not
    scanned). Any use of the name ``startfile`` or ``QDesktopServices`` (import, name or attribute,
    whatever the alias) is allowed only in ``ui/shell/folders.py``.
``CLOCK``
    Wall-clock reads outside ``clock.py``: calls to ``.today()``, ``.now()``, ``.utcnow()``,
    ``.time()``, ``.time_ns()``, ``.localtime()``, ``.gmtime()``, ``.currentDate()``,
    ``.currentDateTime()``, ``.currentDateTimeUtc()`` and ``.currentTime()``, plus bare calls of
    such names imported with ``from time import ...`` / ``from datetime import ...``.

    Matching is by **attribute name**, whatever the import alias or the object it is called on:
    ``foo.now()`` is flagged even when ``foo`` is not a datetime. This is intended. A false
    positive (for example ``datetime.time(12, 0)`` or a method of your own called ``now``) is
    resolved by renaming, never by adding an exception.
``LAYER-QT``
    ``PySide6`` / ``shiboken6`` imports in ``domain/``, ``services/``, ``storage/``,
    ``reports/model.py`` and ``reports/anonymise.py``.
``LAYER-SQL``
    ``sqlite3`` imports in ``ui/``.
``LAYER-DOMAIN``
    Imports of ``cbrn_dashboard.storage`` or ``cbrn_dashboard.services`` from ``domain/``,
    including relative forms (``from ..storage import x``, ``from .. import storage``), which are
    resolved against the package path of the importing file.
``SYNTAX``
    The file does not parse; reported so a broken file can never pass the scan silently.

All rules are data (the tables below), so later tasks can extend them without touching the
dispatch code.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT_PACKAGE = "cbrn_dashboard"

RULE_NET = "NET"
RULE_HANDOFF = "HANDOFF"
RULE_CLOCK = "CLOCK"
RULE_LAYER_QT = "LAYER-QT"
RULE_LAYER_SQL = "LAYER-SQL"
RULE_LAYER_DOMAIN = "LAYER-DOMAIN"
RULE_SYNTAX = "SYNTAX"

# --- NET ---------------------------------------------------------------------------------------

# Dotted module prefixes: ``socket`` matches ``socket`` and ``socket.x`` but not ``socket_like``.
NET_FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "socket",
    "ssl",
    "urllib",
    "urllib3",
    "http",
    "ftplib",
    "smtplib",
    "xmlrpc",
    "imaplib",
    "poplib",
    "asyncio",
    "requests",
    "httpx",
    "webbrowser",
    "subprocess",
    "ctypes",
    "PySide6.QtNetwork",
    "PySide6.QtWebSockets",
)

# (parent module, prefix of the next component): ``PySide6`` + ``QtWebEngine`` matches
# ``PySide6.QtWebEngineCore``, ``PySide6.QtWebEngineWidgets`` and so on.
NET_FORBIDDEN_COMPONENT_PREFIXES: tuple[tuple[str, str], ...] = (("PySide6", "QtWebEngine"),)

# Functions whose first string-literal argument names a module that is imported dynamically.
DYNAMIC_IMPORT_FUNCTIONS: frozenset[str] = frozenset({"import_module", "__import__"})

# --- HANDOFF -----------------------------------------------------------------------------------

# Modules that may not be imported anywhere in ``src/`` (no exceptions).
HANDOFF_FORBIDDEN_PREFIXES: tuple[str, ...] = ("subprocess", "ctypes")

# Names that may not be used (as name, attribute or part of an imported dotted name) ...
HANDOFF_FORBIDDEN_NAMES: frozenset[str] = frozenset({"startfile", "QDesktopServices"})

# ... except in these files.
HANDOFF_ALLOWED_FILES: frozenset[PurePosixPath] = frozenset({PurePosixPath("ui/shell/folders.py")})

# --- CLOCK -------------------------------------------------------------------------------------

# Attribute (or bare) names that read the wall clock when called.
CLOCK_CALL_NAMES: frozenset[str] = frozenset(
    {
        "today",
        "now",
        "utcnow",
        "time",
        "time_ns",
        "localtime",
        "gmtime",
        "currentDate",
        "currentDateTime",
        "currentDateTimeUtc",
        "currentTime",
    }
)

# ``from <module> import <clock name>``: the imported local name is then flagged when called bare.
CLOCK_BARE_IMPORT_MODULES: frozenset[str] = frozenset({"time", "datetime"})

# The only files allowed to read the wall clock.
CLOCK_ALLOWED_FILES: frozenset[PurePosixPath] = frozenset({PurePosixPath("clock.py")})

# --- LAYERS ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LayerRule:
    """A layering rule: files in scope may not import any of the forbidden module prefixes."""

    rule: str
    scope_dirs: tuple[str, ...]
    scope_files: frozenset[PurePosixPath]
    forbidden_prefixes: tuple[str, ...]

    def applies_to(self, rel_path: PurePosixPath) -> bool:
        """Return whether ``rel_path`` (relative to the package root) is in scope."""
        in_dir = len(rel_path.parts) > 1 and rel_path.parts[0] in self.scope_dirs
        return in_dir or rel_path in self.scope_files


LAYER_RULES: tuple[LayerRule, ...] = (
    LayerRule(
        rule=RULE_LAYER_QT,
        scope_dirs=("domain", "services", "storage"),
        scope_files=frozenset(
            {PurePosixPath("reports/model.py"), PurePosixPath("reports/anonymise.py")}
        ),
        forbidden_prefixes=("PySide6", "shiboken6"),
    ),
    LayerRule(
        rule=RULE_LAYER_SQL,
        scope_dirs=("ui",),
        scope_files=frozenset(),
        forbidden_prefixes=("sqlite3",),
    ),
    LayerRule(
        rule=RULE_LAYER_DOMAIN,
        scope_dirs=("domain",),
        scope_files=frozenset(),
        forbidden_prefixes=(f"{ROOT_PACKAGE}.storage", f"{ROOT_PACKAGE}.services"),
    ),
)


# --- results -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """One rule violation at ``path`` (relative to the package root) and ``line``."""

    rule: str
    path: PurePosixPath
    line: int
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.detail}"


type Finding = tuple[str, str]  # (rule id, detail)


# --- helpers -----------------------------------------------------------------------------------


def _has_prefix(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def _is_net_module(name: str) -> bool:
    if any(_has_prefix(name, prefix) for prefix in NET_FORBIDDEN_PREFIXES):
        return True
    parts = name.split(".")
    return len(parts) > 1 and any(
        parts[0] == parent and parts[1].startswith(child)
        for parent, child in NET_FORBIDDEN_COMPONENT_PREFIXES
    )


def _module_findings(name: str, rel_path: PurePosixPath) -> list[Finding]:
    """Rules that a single imported dotted module name can trigger in ``rel_path``."""
    found: list[Finding] = []
    if _is_net_module(name):
        found.append((RULE_NET, f"forbidden import of {name}"))
    if any(_has_prefix(name, prefix) for prefix in HANDOFF_FORBIDDEN_PREFIXES):
        found.append((RULE_HANDOFF, f"forbidden import of {name}"))
    handoff_names = HANDOFF_FORBIDDEN_NAMES.intersection(name.split("."))
    if handoff_names and rel_path not in HANDOFF_ALLOWED_FILES:
        found.append((RULE_HANDOFF, f"hand-off API imported: {name}"))
    for layer in LAYER_RULES:
        if layer.applies_to(rel_path) and any(
            _has_prefix(name, prefix) for prefix in layer.forbidden_prefixes
        ):
            found.append((layer.rule, f"import of {name} is not allowed in {rel_path}"))
    return found


def _resolve_from(node: ast.ImportFrom, package: tuple[str, ...]) -> str | None:
    """Absolute dotted module of a ``from`` import; ``None`` if it leaves the package root."""
    if node.level == 0:
        return node.module
    keep = len(package) - (node.level - 1)
    if keep <= 0:
        return None
    base = list(package[:keep])
    if node.module:
        base.append(node.module)
    return ".".join(base)


def _import_findings(
    node: ast.Import | ast.ImportFrom, rel_path: PurePosixPath, package: tuple[str, ...]
) -> list[Finding]:
    found: list[Finding] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            found.extend(_module_findings(alias.name, rel_path))
        return found
    base = _resolve_from(node, package)
    if base is None:
        return found
    found.extend(_module_findings(base, rel_path))
    if found:
        return found
    # ``from PySide6 import QtNetwork`` / ``from .. import storage``: the names may be modules.
    for alias in node.names:
        if alias.name != "*":
            found.extend(_module_findings(f"{base}.{alias.name}", rel_path))
    return found


def _name_findings(name: str, rel_path: PurePosixPath) -> list[Finding]:
    if name in HANDOFF_FORBIDDEN_NAMES and rel_path not in HANDOFF_ALLOWED_FILES:
        return [(RULE_HANDOFF, f"use of {name}")]
    return []


def _bare_clock_names(tree: ast.AST) -> frozenset[str]:
    """Local names bound by ``from time|datetime import <clock name> [as alias]``."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module in CLOCK_BARE_IMPORT_MODULES
        ):
            names.update(
                alias.asname or alias.name for alias in node.names if alias.name in CLOCK_CALL_NAMES
            )
    return frozenset(names)


def _call_findings(
    node: ast.Call, rel_path: PurePosixPath, bare_clock_names: frozenset[str]
) -> list[Finding]:
    found: list[Finding] = []
    func = node.func
    called: str | None = None
    if isinstance(func, ast.Attribute):
        called = func.attr
        if called in CLOCK_CALL_NAMES and rel_path not in CLOCK_ALLOWED_FILES:
            found.append((RULE_CLOCK, f"wall-clock call .{called}()"))
    elif isinstance(func, ast.Name):
        called = func.id
        if called in bare_clock_names and rel_path not in CLOCK_ALLOWED_FILES:
            found.append((RULE_CLOCK, f"wall-clock call {called}()"))
    if called in DYNAMIC_IMPORT_FUNCTIONS and node.args:
        first = node.args[0]
        if (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
            and not first.value.startswith(".")
        ):
            found.extend(_module_findings(first.value, rel_path))
    return found


# --- public API --------------------------------------------------------------------------------


def check_source(source: str, rel_path: PurePosixPath) -> list[Violation]:
    """Check one module's source; ``rel_path`` is relative to ``src/cbrn_dashboard/``."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Violation(RULE_SYNTAX, rel_path, exc.lineno or 0, f"cannot parse: {exc.msg}")]
    package = (ROOT_PACKAGE, *rel_path.parent.parts)
    bare_clock_names = _bare_clock_names(tree)
    found: dict[Violation, None] = {}
    for node in ast.walk(tree):
        findings: list[Finding]
        if isinstance(node, ast.Import | ast.ImportFrom):
            findings = _import_findings(node, rel_path, package)
        elif isinstance(node, ast.Call):
            findings = _call_findings(node, rel_path, bare_clock_names)
        elif isinstance(node, ast.Name):
            findings = _name_findings(node.id, rel_path)
        elif isinstance(node, ast.Attribute):
            findings = _name_findings(node.attr, rel_path)
        else:
            continue
        for rule, detail in findings:
            found[Violation(rule, rel_path, node.lineno, detail)] = None
    return sorted(found, key=lambda v: (v.line, v.rule, v.detail))


def scan_tree(src_root: Path) -> list[Violation]:
    """Check every ``*.py`` under ``src_root`` (the ``src/cbrn_dashboard`` directory)."""
    if not src_root.is_dir():
        msg = f"package directory not found: {src_root}"
        raise FileNotFoundError(msg)
    violations: list[Violation] = []
    for path in sorted(src_root.rglob("*.py")):
        rel_path = PurePosixPath(path.relative_to(src_root).as_posix())
        violations.extend(check_source(path.read_text(encoding="utf-8"), rel_path))
    return violations
