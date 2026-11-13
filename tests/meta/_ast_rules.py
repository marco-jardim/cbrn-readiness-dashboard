# SPDX-License-Identifier: GPL-3.0-or-later
"""Reusable AST rule engine for the layering and forbidden-API guard (PLAN T0.4).

The engine parses Python source with the standard-library ``ast`` module and never imports or
executes the code it checks. Paths handed to the engine are *relative to* ``src/cbrn_dashboard/``
and written with forward slashes (``PurePosixPath("ui/shell/folders.py")``).

Rules (ids are the ``Violation.rule`` values):

``NET``
    Imports of network, event-loop, browser and process modules anywhere in ``src/``
    (``socket``, ``socketserver``, ``urllib``, ``asyncio``, ``multiprocessing``, every
    ``PySide6.QtNetwork*`` / ``QtWebEngine*`` component, ``QtWebSockets``, ``QtHttpServer`` ...).
    Besides plain ``import x`` and ``from x import y`` the engine sees
    ``from PySide6 import QtNetwork`` / ``QtNetworkAuth`` and the dynamic forms
    ``importlib.import_module("socket")`` / ``__import__("socket")`` with a string-literal
    argument.
``HANDOFF``
    Hand-offs to the shell or to other programs. ``subprocess``, ``ctypes`` and ``multiprocessing``
    may not be imported anywhere in ``src/`` (the plan's exceptions are for ``tests/`` and
    ``scripts/``, which are not scanned). ``QProcess`` (import, name or attribute) is forbidden
    everywhere too. ``os.system``, ``os.popen``, ``os.spawn*`` and ``os.exec*`` are forbidden
    whenever they are accessed on the ``os`` module, resolved through the file's imports
    (``import os as o`` -> ``o.system``; ``from os import system`` is flagged at the import); an
    unrelated ``.system`` attribute (``platform.system()``, ``self.system``) is not touched. Any
    use of the name ``startfile`` or ``QDesktopServices`` (import, name or attribute, whatever the
    alias) is allowed only in ``ui/shell/folders.py``.
``CLOCK``
    Wall-clock reads outside ``clock.py``. The clock names are ``today``, ``now``, ``utcnow``,
    ``time``, ``time_ns``, ``localtime``, ``gmtime``, ``ctime``, ``asctime``, ``currentDate``,
    ``currentDateTime``, ``currentDateTimeUtc``, ``currentTime``, ``currentMSecsSinceEpoch`` and
    ``currentSecsSinceEpoch``. Three matching modes:

    * **Calls** are matched by **attribute name**, whatever the import alias or the object it is
      called on: ``foo.now()`` is flagged even when ``foo`` is not a datetime. This is intended.
      Bare calls of such names imported with ``from time import ...`` / ``from datetime import
      ...`` are flagged too.
    * **References** (the function is not called, e.g. ``field(default_factory=date.today)``,
      ``functools.partial(datetime.now, UTC)``, ``stamp = QDateTime.currentDateTimeUtc``) are
      flagged when the clock name is an attribute of an *imported* clock-bearing object: the
      ``time`` module, ``datetime`` / ``datetime.date`` / ``datetime.datetime`` / ``datetime.time``
      (also the dotted forms and aliases such as ``from datetime import datetime as dt``), and
      ``QDate`` / ``QDateTime`` / ``QTime`` from PySide6. A bare ``Name`` that was imported as a
      clock name (``from time import time``) is flagged on every load, called or not. A reference
      on any other object (``x = obj.now``, ``self.clock.today``) is **allowed** when not called.
      A called reference is reported once.
    * ``time.strftime(fmt)`` (also ``from time import strftime``) with exactly **one** argument
      reads the local clock and is flagged; ``time.strftime(fmt, t)`` and
      ``datetime_obj.strftime(fmt)`` are allowed.

    Shadowing is *not* tracked: the engine works on the file's import table, not on scopes. If a
    file imports ``time`` (module or function) a parameter or variable of the same name is still
    treated as the import (``from time import time`` + ``def f(time): return time`` is flagged;
    ``import time`` + ``def f(time): return time.now`` too). Without the import the name is just a
    name and is ignored. False positives are resolved by renaming, never by adding an exception.
    The same holds for ``datetime.time(12, 0)`` or an annotation ``x: datetime.time``.

Deliberate-evasion bypasses that remain out of scope (nobody writes these by accident):
``getattr(os, "startfile")`` / ``getattr(os, "system")``, ``import_module(variable)`` with a
non-literal argument, and clock functions fetched from containers or ``vars()``.
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
    "multiprocessing",
    "socketserver",
    "PySide6.QtWebSockets",
    "PySide6.QtHttpServer",
)

# (parent module, prefix of the next component): ``PySide6`` + ``QtWebEngine`` matches
# ``PySide6.QtWebEngineCore``, ``PySide6.QtWebEngineWidgets`` and so on; ``PySide6`` + ``QtNetwork``
# matches ``QtNetwork`` and ``QtNetworkAuth``.
NET_FORBIDDEN_COMPONENT_PREFIXES: tuple[tuple[str, str], ...] = (
    ("PySide6", "QtWebEngine"),
    ("PySide6", "QtNetwork"),
)

# Functions whose first string-literal argument names a module that is imported dynamically.
DYNAMIC_IMPORT_FUNCTIONS: frozenset[str] = frozenset({"import_module", "__import__"})

# --- HANDOFF -----------------------------------------------------------------------------------

# Modules that may not be imported anywhere in ``src/`` (no exceptions).
HANDOFF_FORBIDDEN_PREFIXES: tuple[str, ...] = ("subprocess", "ctypes", "multiprocessing")

# Names that may not be used (as name, attribute or part of an imported dotted name) ...
HANDOFF_FORBIDDEN_NAMES: frozenset[str] = frozenset({"startfile", "QDesktopServices"})

# ... except in these files.
HANDOFF_ALLOWED_FILES: frozenset[PurePosixPath] = frozenset({PurePosixPath("ui/shell/folders.py")})

# Names that may not be used anywhere in ``src/`` (same forms as above, no exception).
HANDOFF_NEVER_NAMES: frozenset[str] = frozenset({"QProcess"})

# Attributes of this module (resolved through the import table) that start another program.
HANDOFF_OS_MODULE = "os"
HANDOFF_OS_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "system",
        "popen",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "execv",
        "execve",
        "execvp",
        "execvpe",
    }
)

# --- CLOCK -------------------------------------------------------------------------------------

# Attribute (or bare) names that read the wall clock when called (calls match by attribute name).
CLOCK_CALL_NAMES: frozenset[str] = frozenset(
    {
        "today",
        "now",
        "utcnow",
        "time",
        "time_ns",
        "localtime",
        "gmtime",
        "ctime",
        "asctime",
        "currentDate",
        "currentDateTime",
        "currentDateTimeUtc",
        "currentTime",
        "currentMSecsSinceEpoch",
        "currentSecsSinceEpoch",
    }
)

# ``from <module> import <clock name>``: the imported local name is then flagged on every load.
CLOCK_BARE_IMPORT_MODULES: frozenset[str] = frozenset({"time", "datetime"})

# Imported objects whose clock-named attributes are flagged even when only referenced. Dotted
# origins as resolved through the import table (``from datetime import datetime as dt`` -> ``dt``
# is ``datetime.datetime``) ...
CLOCK_OBJECT_ORIGINS: frozenset[str] = frozenset(
    {"time", "datetime", "datetime.date", "datetime.datetime", "datetime.time"}
)

# ... plus these classes from any PySide6 module (``PySide6.QtCore.QDateTime`` ...).
CLOCK_QT_ROOT = "PySide6"
CLOCK_QT_CLASSES: frozenset[str] = frozenset({"QDate", "QDateTime", "QTime"})

# Functions that read the local clock only when called with exactly one argument.
CLOCK_ONE_ARGUMENT_FUNCTIONS: frozenset[str] = frozenset({"time.strftime"})

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
    parts = name.split(".")
    handoff_names = HANDOFF_FORBIDDEN_NAMES.intersection(parts)
    if (
        (handoff_names and rel_path not in HANDOFF_ALLOWED_FILES)
        or HANDOFF_NEVER_NAMES.intersection(parts)
        or (len(parts) == 2 and parts[0] == HANDOFF_OS_MODULE and parts[1] in HANDOFF_OS_ATTRIBUTES)
    ):
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
    if name in HANDOFF_NEVER_NAMES or (
        name in HANDOFF_FORBIDDEN_NAMES and rel_path not in HANDOFF_ALLOWED_FILES
    ):
        return [(RULE_HANDOFF, f"use of {name}")]
    return []


type ImportTable = dict[str, frozenset[str]]  # local name -> dotted origins it was imported from


@dataclass(frozen=True)
class _Scan:
    """File-wide facts computed once per module (the engine does not track scopes)."""

    imports: ImportTable
    bare_clock_names: frozenset[str]
    called_funcs: frozenset[int]  # ``id()`` of every node that is the ``func`` of a ``Call``


def _import_table(tree: ast.AST) -> ImportTable:
    """Map each imported local name to the dotted names it may stand for.

    ``import a.b`` binds ``a``; ``import a.b as c`` binds ``c`` to ``a.b``;
    ``from a import b as c`` binds ``c`` to ``a.b``. Relative imports are ignored (they are never
    the stdlib or PySide6).
    """
    table: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                table.setdefault(alias.asname or top, set()).add(
                    alias.name if alias.asname else top
                )
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                if alias.name != "*":
                    origin = f"{node.module}.{alias.name}"
                    table.setdefault(alias.asname or alias.name, set()).add(origin)
    return {name: frozenset(origins) for name, origins in table.items()}


def _origins(expr: ast.expr, imports: ImportTable) -> frozenset[str]:
    """Dotted names an expression stands for through the imports (empty if not an import)."""
    if isinstance(expr, ast.Name):
        return imports.get(expr.id, frozenset())
    if isinstance(expr, ast.Attribute):
        return frozenset(f"{origin}.{expr.attr}" for origin in _origins(expr.value, imports))
    return frozenset()


def _bare_clock_names(imports: ImportTable) -> frozenset[str]:
    """Local names bound by ``from time|datetime import <clock name> [as alias]``."""
    names: set[str] = set()
    for local, origins in imports.items():
        for origin in origins:
            module, _, member = origin.rpartition(".")
            if module in CLOCK_BARE_IMPORT_MODULES and member in CLOCK_CALL_NAMES:
                names.add(local)
    return frozenset(names)


def _is_clock_object(origin: str) -> bool:
    if origin in CLOCK_OBJECT_ORIGINS:
        return True
    parts = origin.split(".")
    return parts[0] == CLOCK_QT_ROOT and len(parts) > 1 and parts[-1] in CLOCK_QT_CLASSES


def _has_single_argument(node: ast.Call) -> bool:
    total = len(node.args) + len(node.keywords)
    return total == 1 and not any(isinstance(arg, ast.Starred) for arg in node.args)


def _attribute_findings(node: ast.Attribute, rel_path: PurePosixPath, scan: _Scan) -> list[Finding]:
    found: list[Finding] = []
    attr = node.attr
    base = _origins(node.value, scan.imports)
    if attr in HANDOFF_OS_ATTRIBUTES and HANDOFF_OS_MODULE in base:
        found.append((RULE_HANDOFF, f"hand-off API {HANDOFF_OS_MODULE}.{attr}"))
    if (
        attr in CLOCK_CALL_NAMES
        and isinstance(node.ctx, ast.Load)
        and id(node) not in scan.called_funcs  # a call is reported once, by the call rule
        and rel_path not in CLOCK_ALLOWED_FILES
        and any(_is_clock_object(origin) for origin in base)
    ):
        found.append((RULE_CLOCK, f"wall-clock reference .{attr}"))
    return found


def _bare_name_findings(node: ast.Name, rel_path: PurePosixPath, scan: _Scan) -> list[Finding]:
    if (
        node.id in scan.bare_clock_names
        and isinstance(node.ctx, ast.Load)
        and id(node) not in scan.called_funcs  # a call is reported once, by the call rule
        and rel_path not in CLOCK_ALLOWED_FILES
    ):
        return [(RULE_CLOCK, f"wall-clock reference {node.id}")]
    return []


def _call_findings(node: ast.Call, rel_path: PurePosixPath, scan: _Scan) -> list[Finding]:
    found: list[Finding] = []
    func = node.func
    clock_checked = rel_path not in CLOCK_ALLOWED_FILES
    called: str | None = None
    if isinstance(func, ast.Attribute):
        called = func.attr
        if clock_checked and called in CLOCK_CALL_NAMES:
            found.append((RULE_CLOCK, f"wall-clock call .{called}()"))
    elif isinstance(func, ast.Name):
        called = func.id
        if clock_checked and called in scan.bare_clock_names:
            found.append((RULE_CLOCK, f"wall-clock call {called}()"))
    if (
        clock_checked
        and _origins(func, scan.imports) & CLOCK_ONE_ARGUMENT_FUNCTIONS
        and _has_single_argument(node)
    ):
        found.append((RULE_CLOCK, "wall-clock call time.strftime(fmt) with one argument"))
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
    imports = _import_table(tree)
    scan = _Scan(
        imports=imports,
        bare_clock_names=_bare_clock_names(imports),
        called_funcs=frozenset(id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)),
    )
    found: dict[Violation, None] = {}
    for node in ast.walk(tree):
        findings: list[Finding]
        if isinstance(node, ast.Import | ast.ImportFrom):
            findings = _import_findings(node, rel_path, package)
        elif isinstance(node, ast.Call):
            findings = _call_findings(node, rel_path, scan)
        elif isinstance(node, ast.Name):
            findings = _name_findings(node.id, rel_path)
            findings += _bare_name_findings(node, rel_path, scan)
        elif isinstance(node, ast.Attribute):
            findings = _name_findings(node.attr, rel_path)
            findings += _attribute_findings(node, rel_path, scan)
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
