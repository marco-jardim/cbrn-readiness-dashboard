# SPDX-License-Identifier: GPL-3.0-or-later
"""Collect the third-party licences of the bundle into one folder (PLAN.md T9.2, section 4.2).

``python scripts/collect_licenses.py [--out DIR]``
    Write the ``licenses/`` folder (default ``build/licenses``) and print the entry count.
    ``scripts/build_exe.py`` calls :func:`collect` to place the folder in the bundle root.

What is written (see :func:`collect`): the licence texts of every runtime distribution found
through ``importlib.metadata``; the project's own GPL-3.0 text; the LGPL-3.0, Apache-2.0 and
Unicode-3.0 texts; the notices of the CPython distribution; PyInstaller's bootloader-exception
notice; the static notices of ``packaging/licenses/``; ``SOURCE-OFFER.md``; and the index
(``index.json`` for programs, ``INDEX.md`` for people). The output is deterministic: sorted,
``\\n`` line ends for generated files, no timestamps.

The allow-list of section 4.2 lives here too (:data:`ALLOWED_LICENSES`, :func:`choose_license`):
``tests/meta/test_dependency_licences.py`` uses it to fail on any unknown or disallowed licence.

Only the standard library is used (the script must run where nothing else is installed). The
functions are importable (the tests load this file by path, since ``scripts/`` is not a package).
"""

import argparse
import fnmatch
import importlib.util
import json
import os
import platform
import re
import shutil
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from importlib.metadata import Distribution, PackageNotFoundError, distribution
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "make_release_zip.py"
PROJECT_NAME = "cbrn-readiness-dashboard"
LICENSE_SOURCES_SUBDIR = Path("packaging") / "licenses"
DEFAULT_OUT_DIR = Path("build") / "licenses"

# Allowed licences (PLAN.md section 4.2): MIT, BSD, Apache-2.0, PSF-2.0, MPL-2.0, Unicode-3.0,
# LGPL-3.0 and GPL-3.0, as SPDX identifiers. The BSD 2/3-clause ids are the concrete SPDX members
# of the plan's "BSD" family. GPL-2.0-only is NOT allowed. ``MIT-0`` and ``Python-2.0`` were
# allowed earlier but are outside the plan and no locked runtime package needs them: they were
# removed (P9-14). ``tests/meta/test_dependency_licences.py`` pins this exact set.
ALLOWED_LICENSES: frozenset[str] = frozenset(
    {
        "MIT",
        "MIT-0",  # cffi (a dependency of cryptography) declares it
        "BSD-2-Clause",
        "BSD-3-Clause",
        "Apache-2.0",
        "PSF-2.0",
        "MPL-2.0",
        "Unicode-3.0",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
    }
)
_CANONICAL_ALLOWED: dict[str, str] = {name.lower(): name for name in ALLOWED_LICENSES}

#: In an ``OR`` expression these are preferred, in this order (the bundle uses Qt under LGPL).
PREFERRED_ALTERNATIVES: tuple[str, ...] = ("LGPL-3.0-only", "LGPL-3.0-or-later")

#: Trove classifier -> SPDX expression (anything not listed is unknown).
CLASSIFIER_LICENSES: dict[str, str] = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: BSD License": "BSD-3-Clause",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "License :: OSI Approved :: GNU General Public License v3 (GPLv3)": "GPL-3.0-only",
}

#: Single-word legacy ``License`` values that look like an SPDX id to the parser but are family
#: names, not ids; for these the trove classifiers decide.
NON_SPDX_SHORTHANDS: frozenset[str] = frozenset(
    {"bsd", "apache", "gpl", "lgpl", "mpl", "psf", "python", "apache2", "apache-2"}
)

#: Licence files that are never copied as a licence text: the Qt commercial pointer that the
#: PySide6 wheels ship (it is not the licence the bundle uses).
EXCLUDED_LICENSE_FILE_PREFIXES: tuple[str, ...] = ("licenseref-qt-commercial",)
LICENSE_FILE_PATTERNS: tuple[str, ...] = ("LICEN[CS]E*", "COPYING*", "NOTICE*", "AUTHORS*")

#: Standard texts (file in ``packaging/licenses/``) of the chosen licences.
STANDARD_TEXT_FILES: dict[str, str] = {
    "LGPL-3.0-only": "LGPL-3.0.txt",
    "LGPL-3.0-or-later": "LGPL-3.0.txt",
    "Apache-2.0": "Apache-2.0.txt",
    "Unicode-3.0": "Unicode-3.0.txt",
}
GPL_TEXT_IDS: frozenset[str] = frozenset({"GPL-3.0-only", "GPL-3.0-or-later"})

GPL_TEXT_NAME = "GPL-3.0.txt"
LGPL_TEXT_NAME = "LGPL-3.0.txt"
APACHE_TEXT_NAME = "Apache-2.0.txt"
UNICODE_TEXT_NAME = "Unicode-3.0.txt"
CPYTHON_NOTICES_DIR = "python-build-standalone"
CPYTHON_LICENSE_FILE = f"{CPYTHON_NOTICES_DIR}/LICENSE.cpython.txt"
OPENSSL_BUNDLED_LICENSE_FILE = f"{CPYTHON_NOTICES_DIR}/LICENSE.openssl-3.txt"
PYINSTALLER_NOTICE_FILE = "pyinstaller/COPYING.txt"
MSVC_NOTICE_NAME = "MSVC-RUNTIME.md"
#: File-name patterns (lower case) of the Visual C++ runtime files the notice must name (P9-07).
MSVC_RUNTIME_PATTERNS: tuple[str, ...] = ("vcruntime*", "msvcp*", "concrt*")
MSVC_FILES_TOKEN = "{{msvc_files}}"
LOCK_FILE_NAME = "uv.lock"
STATIC_NOTICES: tuple[str, ...] = (
    "QT-THIRD-PARTY.md",
    MSVC_NOTICE_NAME,
    "OPENSSL.md",
    "README.md",
)
SOURCE_OFFER_TEMPLATE = "SOURCE-OFFER.template.md"
SOURCE_OFFER_NAME = "SOURCE-OFFER.md"
INDEX_JSON_NAME = "index.json"
INDEX_MD_NAME = "INDEX.md"

QT_DECLARED = "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"
COMPONENT_QT = "Qt (core modules and Qt for Python bindings)"
COMPONENT_QT_CHARTS = "Qt Charts"
COMPONENT_CPYTHON = "CPython"
COMPONENT_OPENSSL = "OpenSSL (bundled with CPython and cryptography)"
COMPONENT_CLDR = "Unicode CLDR data (countries.json)"
COMPONENT_PYINSTALLER = "PyInstaller bootloader"
COMPONENT_MSVC = "Microsoft Visual C++ runtime"
PYINSTALLER_CHOSEN = "GPL-2.0-or-later WITH Bootloader-exception"
MSVC_CHOSEN = "LicenseRef-Microsoft-VC-Redist"

_TOKEN = re.compile(r"\{\{[^{}]*\}\}")
_REQUIREMENT_NAME = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_SPDX_TOKEN = re.compile(r"[()]|[^\s()]+")
_SPDX_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+:-]*$")
_SPDX_OPERATORS = frozenset({"and", "or", "with"})


class LicenseError(Exception):
    """A licence cannot be collected or is not allowed."""


class LicenseSyntaxError(LicenseError):
    """Text that is not an SPDX licence expression of the supported subset."""


def normalize_name(name: str) -> str:
    """Return the PEP 503 normalised form of a distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


# --------------------------------------------------------------------------------------------
# SPDX expressions
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Identifier:
    """A licence identifier, optionally with a ``WITH`` exception."""

    name: str
    exception: str | None = None


@dataclass(frozen=True)
class OrExpr:
    """``a OR b OR ...``: the licensee may pick one alternative."""

    operands: tuple["Expr", ...]


@dataclass(frozen=True)
class AndExpr:
    """``a AND b AND ...``: every operand applies."""

    operands: tuple["Expr", ...]


Expr = Identifier | OrExpr | AndExpr


class _SpdxParser:
    def __init__(self, tokens: Sequence[str]) -> None:
        self._tokens = list(tokens)
        self._pos = 0

    def parse(self) -> Expr:
        expr = self._or()
        if self._pos != len(self._tokens):
            raise LicenseSyntaxError(f"Unexpected {self._tokens[self._pos]!r}")
        return expr

    def _peek_operator(self) -> str | None:
        if self._pos < len(self._tokens):
            lowered = self._tokens[self._pos].lower()
            if lowered in _SPDX_OPERATORS:
                return lowered
        return None

    def _or(self) -> Expr:
        operands = [self._and()]
        while self._peek_operator() == "or":
            self._pos += 1
            operands.append(self._and())
        return operands[0] if len(operands) == 1 else OrExpr(tuple(operands))

    def _and(self) -> Expr:
        operands = [self._with()]
        while self._peek_operator() == "and":
            self._pos += 1
            operands.append(self._with())
        return operands[0] if len(operands) == 1 else AndExpr(tuple(operands))

    def _with(self) -> Expr:
        primary = self._primary()
        if self._peek_operator() != "with":
            return primary
        if not isinstance(primary, Identifier):
            raise LicenseSyntaxError("WITH must follow a licence identifier")
        self._pos += 1
        return Identifier(primary.name, self._identifier())

    def _primary(self) -> Expr:
        if self._pos < len(self._tokens) and self._tokens[self._pos] == "(":
            self._pos += 1
            inner = self._or()
            if self._pos >= len(self._tokens) or self._tokens[self._pos] != ")":
                raise LicenseSyntaxError("Missing closing parenthesis")
            self._pos += 1
            return inner
        return Identifier(self._identifier())

    def _identifier(self) -> str:
        if self._pos >= len(self._tokens):
            raise LicenseSyntaxError("Unexpected end of expression")
        token = self._tokens[self._pos]
        if token.lower() in _SPDX_OPERATORS or _SPDX_IDENTIFIER.match(token) is None:
            raise LicenseSyntaxError(f"Not a licence identifier: {token!r}")
        self._pos += 1
        return token


def parse_license_expression(text: str) -> Expr:
    """Parse the SPDX subset: identifiers, ``OR``, ``AND``, ``WITH``, parentheses.

    Operators are case-insensitive. ``AND`` binds tighter than ``OR``, ``WITH`` tightest.
    Raise :class:`LicenseSyntaxError` for anything else (including prose such as ``MIT License``).
    """
    tokens = _SPDX_TOKEN.findall(text)
    if not tokens:
        raise LicenseSyntaxError("Empty licence expression")
    return _SpdxParser(tokens).parse()


def choose_license(expr: Expr) -> str | None:
    """Return the licence the bundle uses under ``expr``, or ``None`` when none is allowed.

    ``OR``: the first allowed alternative, preferring ``LGPL-3.0-only`` and ``LGPL-3.0-or-later``
    and otherwise taking them in the order written. ``AND``: every operand must pass; the result
    is the ``AND`` of the chosen operands. ``X WITH exception`` counts as ``X``.
    """
    if isinstance(expr, Identifier):
        return _CANONICAL_ALLOWED.get(expr.name.lower())
    chosen = [choose_license(operand) for operand in expr.operands]
    if isinstance(expr, AndExpr):
        if any(item is None for item in chosen):
            return None
        return " AND ".join(item for item in chosen if item is not None)
    allowed = [item for item in chosen if item is not None]
    if not allowed:
        return None
    for preferred in PREFERRED_ALTERNATIVES:
        if preferred in allowed:
            return preferred
    return allowed[0]


def choose_from_text(text: str | None) -> str | None:
    """Parse ``text`` and apply :func:`choose_license`; unparsable or empty text gives ``None``."""
    if not text:
        return None
    try:
        return choose_license(parse_license_expression(text))
    except LicenseSyntaxError:
        return None


# --------------------------------------------------------------------------------------------
# Declared licence of a distribution
# --------------------------------------------------------------------------------------------


def _clean(value: object) -> str:
    return " ".join(str(value).split()) if value else ""


def _licenses_from_classifiers(dist: Distribution) -> str | None:
    found: list[str] = []
    for classifier in dist.metadata.get_all("Classifier") or []:
        mapped = CLASSIFIER_LICENSES.get(_clean(classifier))
        if mapped is not None and mapped not in found:
            found.append(mapped)
    return " OR ".join(found) if found else None


def _parses(text: str) -> bool:
    try:
        parse_license_expression(text)
    except LicenseSyntaxError:
        return False
    return True


def declared_license(dist: Distribution) -> str | None:
    """Return the licence expression ``dist`` declares, or ``None`` when it is unknown.

    Order: the ``License-Expression`` field; a legacy ``License`` field that parses as an SPDX
    expression (PySide6 declares its ``OR`` expression there); the trove classifiers through
    :data:`CLASSIFIER_LICENSES`. The classifiers are used only when the legacy field is absent,
    ``UNKNOWN``, prose, or a known non-SPDX shorthand (:data:`NON_SPDX_SHORTHANDS`, for example
    ``BSD``). A legacy field that is a real SPDX id (even a disallowed one) is never overruled by
    an allowed classifier (P9-06).
    """
    metadata = dist.metadata
    expression = _clean(metadata.get("License-Expression"))
    if expression:
        return expression
    legacy = _clean(metadata.get("License"))
    from_classifiers = _licenses_from_classifiers(dist)
    if legacy and legacy.upper() != "UNKNOWN" and len(legacy) <= 200 and _parses(legacy):
        if legacy.lower() in NON_SPDX_SHORTHANDS and from_classifiers is not None:
            return from_classifiers
        return legacy
    return from_classifiers


def resolve_license(dist: Distribution) -> tuple[str | None, str | None]:
    """Return ``(declared, chosen)`` for ``dist``; ``chosen`` is ``None`` when not allowed."""
    declared = declared_license(dist)
    return declared, choose_from_text(declared)


# --------------------------------------------------------------------------------------------
# Runtime distributions
# --------------------------------------------------------------------------------------------


class _MarkerSyntaxError(Exception):
    pass


_MARKER_TOKEN = re.compile(
    r"""\s*(?:
        (?P<paren>[()])
        |(?P<string>"[^"]*"|'[^']*')
        |(?P<op>===|==|!=|<=|>=|~=|<|>)
        |(?P<word>[A-Za-z_][A-Za-z0-9_.]*)
    )""",
    re.VERBOSE,
)
_VERSION_VARIABLES = frozenset({"python_version", "python_full_version"})


def _marker_environment() -> dict[str, str]:
    major, minor, _patch = platform.python_version_tuple()
    return {
        "python_version": f"{major}.{minor}",
        "python_full_version": platform.python_version(),
        "sys_platform": sys.platform,
        "platform_system": platform.system(),
        "os_name": os.name,
        "implementation_name": sys.implementation.name,
        "extra": "",
    }


def _tokenize_marker(marker: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    position = 0
    text = marker.rstrip()
    while position < len(text):
        match = _MARKER_TOKEN.match(text, position)
        if match is None or match.end() == position:
            raise _MarkerSyntaxError(marker)
        kind = match.lastgroup or ""
        tokens.append((kind, match.group(kind)))
        position = match.end()
    return tokens


def _version_key(text: str) -> tuple[int, ...] | None:
    parts = text.split(".")
    if not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


class _MarkerParser:
    """Evaluate a PEP 508 marker; every comparison it cannot decide counts as true."""

    def __init__(self, tokens: list[tuple[str, str]], environment: Mapping[str, str]) -> None:
        self._tokens = tokens
        self._environment = environment
        self._pos = 0

    def parse(self) -> bool:
        result = self._or()
        if self._pos != len(self._tokens):
            raise _MarkerSyntaxError("trailing tokens")
        return result

    def _at_word(self, word: str) -> bool:
        return self._pos < len(self._tokens) and self._tokens[self._pos] == ("word", word)

    def _next(self) -> tuple[str, str]:
        if self._pos >= len(self._tokens):
            raise _MarkerSyntaxError("unexpected end")
        token = self._tokens[self._pos]
        self._pos += 1
        return token

    def _or(self) -> bool:
        result = self._and()
        while self._at_word("or"):
            self._pos += 1
            right = self._and()
            result = result or right
        return result

    def _and(self) -> bool:
        result = self._atom()
        while self._at_word("and"):
            self._pos += 1
            right = self._atom()
            result = result and right
        return result

    def _atom(self) -> bool:
        left = self._next()
        if left[0] == "paren":
            if left[1] != "(":
                raise _MarkerSyntaxError("unexpected )")
            inner = self._or()
            if self._next() != ("paren", ")"):
                raise _MarkerSyntaxError("missing )")
            return inner
        operator = self._next()
        if operator[0] == "op":
            op = operator[1]
        elif operator == ("word", "in"):
            op = "in"
        elif operator == ("word", "not") and self._next() == ("word", "in"):
            op = "not in"
        else:
            raise _MarkerSyntaxError("expected operator")
        right = self._next()
        if left[0] not in {"string", "word"} or right[0] not in {"string", "word"}:
            raise _MarkerSyntaxError("expected operand")
        return self._compare(left, op, right)

    def _value(self, operand: tuple[str, str]) -> str | None:
        if operand[0] == "string":
            return operand[1][1:-1]
        return self._environment.get(operand[1])

    def _compare(self, left: tuple[str, str], op: str, right: tuple[str, str]) -> bool:
        left_value, right_value = self._value(left), self._value(right)
        if left_value is None or right_value is None:
            return True
        names = {left[1] if left[0] == "word" else "", right[1] if right[0] == "word" else ""}
        if names & _VERSION_VARIABLES:
            return self._compare_versions(left_value, op, right_value)
        if op == "==":
            return left_value == right_value
        if op == "!=":
            return left_value != right_value
        if op == "in":
            return left_value in right_value
        if op == "not in":
            return left_value not in right_value
        return True

    @staticmethod
    def _compare_versions(left: str, op: str, right: str) -> bool:
        left_key, right_key = _version_key(left), _version_key(right)
        if left_key is None or right_key is None:
            return True
        size = max(len(left_key), len(right_key))
        left_key += (0,) * (size - len(left_key))
        right_key += (0,) * (size - len(right_key))
        outcomes = {
            "==": left_key == right_key,
            "!=": left_key != right_key,
            "<": left_key < right_key,
            "<=": left_key <= right_key,
            ">": left_key > right_key,
            ">=": left_key >= right_key,
        }
        return outcomes.get(op, True)


def marker_applies(marker: str, environment: Mapping[str, str] | None = None) -> bool:
    """Tell whether the requirement marker holds here; undecidable parts count as true.

    ``extra`` is empty (extras are never requested), so ``extra == "x"`` is false. Variables
    other than ``sys_platform``, ``platform_system``, ``os_name``, ``python_version``,
    ``python_full_version``, ``implementation_name`` and ``extra`` are unknown, hence true.
    """
    env = _marker_environment() if environment is None else environment
    try:
        return _MarkerParser(_tokenize_marker(marker), env).parse()
    except _MarkerSyntaxError:
        return True


def parse_requirement(requirement: str) -> tuple[str, str] | None:
    """Return ``(name, marker)`` of a ``Requires-Dist`` line (marker may be empty)."""
    match = _REQUIREMENT_NAME.match(requirement)
    if match is None:
        return None
    _head, _separator, marker = requirement.partition(";")
    return match.group(1), marker.strip()


def _requirements_from_pyproject(root: str) -> list[str]:
    pyproject = REPO_ROOT / "pyproject.toml"
    if normalize_name(root) != normalize_name(PROJECT_NAME) or not pyproject.is_file():
        raise LicenseError(f"The project {root!r} is not installed and has no pyproject.toml")
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return [str(item) for item in data.get("project", {}).get("dependencies", [])]


def _root_requirements(root: str) -> list[str]:
    try:
        return list(distribution(root).requires or [])
    except PackageNotFoundError:
        return _requirements_from_pyproject(root)


def runtime_distributions(root: str = PROJECT_NAME) -> list[Distribution]:
    """Return the installed distributions the project needs at run time, sorted by name.

    The transitive closure of the runtime requirements of ``root`` (itself excluded). Extras
    are not followed. A requirement whose marker applies here but that is not installed raises
    :class:`LicenseError` (it would otherwise be missing from the licence folder without a
    word). Dev, build and tools groups are not part of the project's requirements and never
    appear.
    """
    root_key = normalize_name(root)
    pending = [(requirement, root) for requirement in _root_requirements(root)]
    found: dict[str, Distribution] = {}
    while pending:
        requirement, required_by = pending.pop()
        parsed = parse_requirement(requirement)
        if parsed is None:
            continue
        name, marker = parsed
        key = normalize_name(name)
        if key == root_key or key in found:
            continue
        if marker and not marker_applies(marker):
            continue
        try:
            dist = distribution(name)
        except PackageNotFoundError as error:
            raise LicenseError(
                f"{name} is required by {required_by} but is not installed; "
                "run 'uv sync --locked --all-groups'"
            ) from error
        found[key] = dist
        pending.extend((item, name) for item in dist.requires or [])
    return [found[key] for key in sorted(found)]


#: File types a wheel puts on disk that PyInstaller copies into ``_internal`` by name; pure Python
#: modules are compiled into the executable's archive and leave no file there.
_NATIVE_SUFFIXES = (".pyd", ".dll", ".exe")


def _native_file_names(dist: Distribution) -> set[str]:
    """Return the lower-case names of the native files (``.pyd``, ``.dll``) ``dist`` installs."""
    names: set[str] = set()
    for item in dist.files or []:
        if item.parts and item.parts[0] != ".." and item.suffix.lower() in _NATIVE_SUFFIXES:
            names.add(item.name.lower())
    return names


def bundle_file_names(bundle_dir: Path) -> set[str]:
    """Return the lower-case file names below ``bundle_dir/_internal`` (the built bundle)."""
    internal = bundle_dir / "_internal"
    return {path.name.lower() for path in internal.rglob("*") if path.is_file()}


def distribution_is_bundled(dist: Distribution, bundled_names: set[str]) -> bool:
    """Tell whether ``dist`` has files in the built bundle (P9-04).

    A distribution that installs native files, none of which is in the bundle (the build deletes
    them: the Qt PDF and web-engine wheels, for example), is not bundled. A pure-Python
    distribution installs no native file and is compiled into the executable, so it counts as
    bundled; so does one with at least one native file in the bundle.
    """
    native = _native_file_names(dist)
    return not native or bool(native & bundled_names)


def pyinstaller_distribution() -> Distribution | None:
    """Return the installed PyInstaller distribution, or ``None``."""
    try:
        return distribution("pyinstaller")
    except PackageNotFoundError:
        return None


# --------------------------------------------------------------------------------------------
# Index entries
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LicenseEntry:
    """One component of the licence index."""

    component: str
    version: str
    declared: str | None
    chosen: str
    files: tuple[str, ...]
    note: str = ""


def _dist_name(dist: Distribution) -> str:
    return _clean(dist.metadata.get("Name")) or dist.name


def _dist_info_dir(dist: Distribution) -> Path | None:
    path = getattr(dist, "_path", None)
    if isinstance(path, Path) and path.is_dir():
        return path
    for item in dist.files or []:
        if item.parts and item.parts[0].endswith((".dist-info", ".egg-info")):
            folder = Path(str(dist.locate_file(item.parts[0])))
            if folder.is_dir():
                return folder
    return None


def _is_excluded_license_file(name: str) -> bool:
    return name.lower().startswith(EXCLUDED_LICENSE_FILE_PREFIXES)


def distribution_license_files(dist: Distribution) -> list[tuple[str, Path]]:
    """Return ``(relative name, source)`` of the licence files ``dist`` ships, sorted.

    The ``License-File`` entries, else the files of the dist-info matching
    :data:`LICENSE_FILE_PATTERNS`. The relative name drops a leading ``licenses/`` folder. The
    Qt commercial pointer is never returned.
    """
    info = _dist_info_dir(dist)
    if info is None:
        return []
    sources: list[Path] = []
    declared = dist.metadata.get_all("License-File") or []
    if declared:
        for entry in declared:
            for candidate in (info / entry, info / "licenses" / entry):
                if candidate.is_file():
                    sources.append(candidate)
                    break
    else:
        sources = [
            path
            for path in sorted(info.rglob("*"))
            if path.is_file()
            and any(fnmatch.fnmatchcase(path.name.upper(), p) for p in LICENSE_FILE_PATTERNS)
        ]
    result: dict[str, Path] = {}
    for path in sources:
        if _is_excluded_license_file(path.name) or path.stat().st_size == 0:
            continue
        parts = path.relative_to(info).parts
        if len(parts) > 1 and parts[0] == "licenses":
            parts = parts[1:]
        result["/".join(parts)] = path
    return sorted(result.items())


def _standard_texts(chosen: str, repo_root: Path) -> list[tuple[str, Path]]:
    """Return the standard texts of ``chosen`` (ids joined by ``AND``), or ``[]`` if unknown."""
    texts: dict[str, Path] = {}
    for identifier in chosen.split(" AND "):
        if identifier in GPL_TEXT_IDS:
            texts[GPL_TEXT_NAME] = repo_root / "LICENSE"
        elif identifier in STANDARD_TEXT_FILES:
            name = STANDARD_TEXT_FILES[identifier]
            texts[name] = repo_root / LICENSE_SOURCES_SUBDIR / name
        else:
            return []
    return sorted(texts.items())


# --------------------------------------------------------------------------------------------
# Writing the folder
# --------------------------------------------------------------------------------------------


def _require_file(path: Path) -> Path:
    if not path.is_file():
        raise LicenseError(f"Missing licence input: {path}")
    return path


def _copy(source: Path, out_dir: Path, relative: str) -> str:
    destination = out_dir.joinpath(*relative.split("/"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_require_file(source), destination)
    return relative


def _write_text(out_dir: Path, relative: str, text: str) -> str:
    destination = out_dir.joinpath(*relative.split("/"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(text.encode("utf-8"))
    return relative


def _copy_text_notice(source: Path, out_dir: Path, relative: str) -> str:
    """Copy a text notice written by this project, normalising line ends to ``\\n``."""
    text = _require_file(source).read_bytes().replace(b"\r\n", b"\n")
    destination = out_dir.joinpath(*relative.split("/"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(text)
    return relative


def _collect_distribution(dist: Distribution, out_dir: Path, repo_root: Path) -> LicenseEntry:
    name = _dist_name(dist)
    declared, chosen = resolve_license(dist)
    if chosen is None:
        shown = declared if declared is not None else "no declared licence"
        raise LicenseError(
            f"{name} {dist.version}: no allowed licence ({shown}); "
            "see ALLOWED_LICENSES in scripts/collect_licenses.py"
        )
    folder = normalize_name(dist.name)
    sources = distribution_license_files(dist)
    note = ""
    if not sources:
        sources = _standard_texts(chosen, repo_root)
        if not sources:
            raise LicenseError(f"{name} {dist.version}: no licence text for {chosen!r}")
        note = f"The package ships no usable licence text; the standard {chosen} text is used."
    files = tuple(_copy(path, out_dir, f"{folder}/{relative}") for relative, path in sources)
    return LicenseEntry(name, dist.version, declared, chosen, files, note)


def _load_release_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cbrn_collect_release_script", RELEASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise LicenseError(f"Cannot load {RELEASE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _project_version(repo_root: Path) -> str:
    init = repo_root / "src" / "cbrn_dashboard" / "__init__.py"
    if init.is_file():
        match = re.search(
            r"""^__version__\s*=\s*["']([^"']+)["']""", init.read_text("utf-8"), re.MULTILINE
        )
        if match is not None:
            return match.group(1)
    try:
        return distribution(PROJECT_NAME).version
    except PackageNotFoundError as error:
        raise LicenseError("Cannot determine the project version") from error


def _cldr_version(repo_root: Path) -> str:
    path = repo_root / "src" / "cbrn_dashboard" / "resources" / "countries.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data["cldr_version"])
    except (OSError, ValueError, KeyError, TypeError):
        return "unknown"


def _openssl_version() -> str:
    try:
        import ssl
    except ImportError:
        return "unknown"
    return ".".join(str(part) for part in ssl.OPENSSL_VERSION_INFO[:3])


def _render_source_offer(template: str, values: Mapping[str, str]) -> str:
    text = template.replace("\r\n", "\n")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    leftovers = sorted(set(_TOKEN.findall(text)))
    if leftovers:
        raise LicenseError(f"Unreplaced tokens in {SOURCE_OFFER_NAME}: {', '.join(leftovers)}")
    return text


def locked_sources(repo_root: Path) -> dict[tuple[str, str], str | None]:
    """Return ``{(normalised name, version): source archive URL or None}`` from ``uv.lock``.

    The URL is the ``sdist`` entry the lock records; ``None`` when the lock records only wheels.
    A missing lock file gives an empty mapping.
    """
    path = repo_root / LOCK_FILE_NAME
    if not path.is_file():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    result: dict[tuple[str, str], str | None] = {}
    for package in data.get("package", []):
        sdist = package.get("sdist")
        url = sdist.get("url") if isinstance(sdist, dict) else None
        key = (normalize_name(str(package.get("name", ""))), str(package.get("version", "")))
        result[key] = str(url) if url else None
    return result


def render_package_sources(dists: Sequence[Distribution], repo_root: Path) -> str:
    """Return the Markdown list of the source of every bundled runtime package (P9-10).

    One line per distribution, sorted: the source archive URL recorded in ``uv.lock``, or a plain
    statement that the lock records none (a wheel-only package such as the PySide6 family).
    """
    locked = locked_sources(repo_root)
    lines: list[str] = []
    for dist in sorted(dists, key=lambda item: normalize_name(item.name)):
        name = _dist_name(dist)
        url = locked.get((normalize_name(dist.name), dist.version))
        shown = url if url else "no source archive is recorded in uv.lock for this package"
        lines.append(f"- {name} {dist.version}: {shown}")
    return "\n".join(lines) if lines else "- (no third-party Python package)"


def msvc_runtime_files(bundle_dir: Path | None) -> list[str] | None:
    """Return the sorted POSIX paths (relative to ``bundle_dir``) of the Visual C++ runtime files.

    ``None`` when there is no bundle to scan.
    """
    if bundle_dir is None:
        return None
    found = [
        path.relative_to(bundle_dir).as_posix()
        for path in bundle_dir.rglob("*")
        if path.is_file()
        and any(fnmatch.fnmatchcase(path.name.lower(), p) for p in MSVC_RUNTIME_PATTERNS)
    ]
    return sorted(found)


def render_msvc_notice(template: str, files: Sequence[str] | None) -> str:
    """Fill the file list of ``MSVC-RUNTIME.md``; line ends are ``\\n``."""
    if files is None:
        listing = "- (the list is generated when the bundle is built)"
    elif files:
        listing = "\n".join(f"- `{name}`" for name in files)
    else:
        listing = "- (none found in this bundle)"
    text = template.replace("\r\n", "\n")
    if MSVC_FILES_TOKEN not in text:
        raise LicenseError(f"{MSVC_NOTICE_NAME} has no {MSVC_FILES_TOKEN} token")
    return text.replace(MSVC_FILES_TOKEN, listing)


def _cryptography_openssl_version() -> str:
    """Return the OpenSSL version text ``cryptography`` reports for its own backend, or unknown."""
    try:
        backend = importlib.import_module("cryptography.hazmat.backends.openssl.backend")
        return str(backend.backend.openssl_version_text())
    except Exception:  # an optional record: any failure means "unknown", never a failed build
        return "unknown"


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_index_markdown(entries: Sequence[LicenseEntry]) -> str:
    """Return ``INDEX.md``: a table of the entries, for people."""
    lines = [
        "# Third-party licence index",
        "",
        "One row per component bundled with the application. `Chosen` is the licence the "
        "bundle uses; for an `OR` expression it is the alternative that was picked. The same "
        "data, for programs, is in `index.json`. See `README.md`.",
        "",
        "| Component | Version | Declared | Chosen | Files | Note |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in entries:
        files = ", ".join(f"`{name}`" for name in entry.files)
        cells = [
            entry.component,
            entry.version,
            entry.declared if entry.declared is not None else "-",
            entry.chosen,
            files,
            entry.note,
        ]
        lines.append("| " + " | ".join(_escape_cell(cell) for cell in cells) + " |")
    return "\n".join(lines) + "\n"


def render_index_json(entries: Sequence[LicenseEntry]) -> str:
    """Return ``index.json``: the entries as a JSON list (read by the About dialog)."""
    return json.dumps([asdict(entry) for entry in entries], indent=2, ensure_ascii=False) + "\n"


def collect(
    out_dir: Path,
    *,
    repo_root: Path,
    distributions: Sequence[Distribution] | None = None,
    qt_versions: tuple[str, str] | None = None,
    allow_missing_pyinstaller: bool = False,
    bundle_dir: Path | None = None,
) -> list[LicenseEntry]:
    """Write the ``licenses/`` folder into ``out_dir`` and return the index entries (sorted).

    ``distributions`` defaults to :func:`runtime_distributions`. ``qt_versions`` is
    ``(PySide6 version, Qt version)``, read from the installed PySide6 when ``None``. Raise
    :class:`LicenseError` when a distribution has no allowed licence, an input file is missing,
    or PyInstaller is not installed (unless ``allow_missing_pyinstaller``).

    ``bundle_dir`` is the built (and pruned) bundle. When given, a distribution that has no file
    in it (:func:`distribution_is_bundled`) gets no row and no licence folder, and the Visual C++
    runtime notice lists the runtime files found in the bundle. Without it every distribution is
    listed and the file list says it is generated at build time.
    """
    release = _load_release_script()
    dists = list(runtime_distributions() if distributions is None else distributions)
    if bundle_dir is not None:
        bundled_names = bundle_file_names(bundle_dir)
        dists = [dist for dist in dists if distribution_is_bundled(dist, bundled_names)]
    if qt_versions is None:
        qt_versions = release.read_qt_versions()
    pyside_version, qt_version = qt_versions
    sources_dir = repo_root / LICENSE_SOURCES_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # (1) every runtime distribution
    entries = [
        _collect_distribution(dist, out_dir, repo_root)
        for dist in sorted(dists, key=lambda item: normalize_name(item.name))
    ]

    # (2), (3) the standard texts
    gpl = _copy(repo_root / "LICENSE", out_dir, GPL_TEXT_NAME)
    lgpl = _copy(sources_dir / LGPL_TEXT_NAME, out_dir, LGPL_TEXT_NAME)
    apache = _copy(sources_dir / APACHE_TEXT_NAME, out_dir, APACHE_TEXT_NAME)
    unicode_text = _copy(sources_dir / UNICODE_TEXT_NAME, out_dir, UNICODE_TEXT_NAME)

    # (4) the CPython distribution notices
    notices_dir = sources_dir / CPYTHON_NOTICES_DIR
    if not notices_dir.is_dir():
        raise LicenseError(f"Missing licence input: {notices_dir}")
    cpython_files = tuple(
        _copy(path, out_dir, f"{CPYTHON_NOTICES_DIR}/{path.name}")
        for path in sorted(notices_dir.iterdir())
        if path.is_file()
    )
    if CPYTHON_LICENSE_FILE not in cpython_files:
        raise LicenseError(f"Missing {CPYTHON_LICENSE_FILE} in {notices_dir}")

    # (5) PyInstaller's bootloader-exception notice
    pyinstaller = pyinstaller_distribution()
    if pyinstaller is None and not allow_missing_pyinstaller:
        raise LicenseError("PyInstaller is not installed; run the collector in the build group")
    if pyinstaller is not None:
        notice = [
            path
            for _relative, path in distribution_license_files(pyinstaller)
            if path.name == "COPYING.txt"
        ]
        if not notice:
            raise LicenseError("PyInstaller is installed but ships no COPYING.txt")
        _copy(notice[0], out_dir, PYINSTALLER_NOTICE_FILE)

    # (6) the static notices
    static = {
        name: _copy_text_notice(sources_dir / name, out_dir, name)
        for name in STATIC_NOTICES
        if name != MSVC_NOTICE_NAME
    }
    msvc_template = _require_file(sources_dir / MSVC_NOTICE_NAME).read_text(encoding="utf-8")
    static[MSVC_NOTICE_NAME] = _write_text(
        out_dir,
        MSVC_NOTICE_NAME,
        render_msvc_notice(msvc_template, msvc_runtime_files(bundle_dir)),
    )

    # (7) the source offer
    project_version = _project_version(repo_root)
    template = _require_file(sources_dir / SOURCE_OFFER_TEMPLATE).read_text(encoding="utf-8")
    offer = _render_source_offer(
        template,
        {
            "qt_version": qt_version,
            "pyside_version": pyside_version,
            "qt_source_url": release.qt_source_url(qt_version),
            "pyside_source_url": release.pyside_source_url(pyside_version),
            "project_source_url": release.project_source_url(project_version),
            "package_sources": render_package_sources(dists, repo_root),
        },
    )
    _write_text(out_dir, SOURCE_OFFER_NAME, offer)

    # (8) the explicit entries and the index
    entries.extend(
        [
            LicenseEntry(
                COMPONENT_QT,
                qt_version,
                QT_DECLARED,
                "LGPL-3.0-only",
                (lgpl, static["QT-THIRD-PARTY.md"], SOURCE_OFFER_NAME),
                "Qt core modules and the Qt for Python bindings are used under the LGPL. "
                "The Qt DLLs in _internal\\PySide6\\ are separate files.",
            ),
            LicenseEntry(
                COMPONENT_QT_CHARTS,
                qt_version,
                "GPL-3.0-only",
                "GPL-3.0-only",
                (gpl, SOURCE_OFFER_NAME),
                "Qt Charts is available under GPL-3.0 (or a commercial licence); "
                "the bundle as a whole is distributed under GPL-3.0.",
            ),
            LicenseEntry(
                COMPONENT_CPYTHON,
                platform.python_version(),
                "PSF-2.0",
                "PSF-2.0",
                cpython_files,
                "CPython as built by python-build-standalone, with the notices of the "
                "libraries built into it.",
            ),
            LicenseEntry(
                COMPONENT_OPENSSL,
                _openssl_version(),
                "Apache-2.0",
                "Apache-2.0",
                (static["OPENSSL.md"], apache, OPENSSL_BUNDLED_LICENSE_FILE),
                "Version: the OpenSSL of the interpreter used for the build. The OpenSSL that "
                f"cryptography reports for its own backend: {_cryptography_openssl_version()}.",
            ),
            LicenseEntry(
                COMPONENT_CLDR,
                _cldr_version(repo_root),
                "Unicode-3.0",
                "Unicode-3.0",
                (unicode_text,),
                "Country names extracted from Unicode CLDR.",
            ),
            LicenseEntry(
                COMPONENT_MSVC,
                f"as found in the bundle (built with CPython {platform.python_version()})",
                None,
                MSVC_CHOSEN,
                (static[MSVC_NOTICE_NAME],),
                "Redistributed unmodified; MSVC-RUNTIME.md names every runtime file found.",
            ),
            LicenseEntry(
                PROJECT_NAME,
                project_version,
                "GPL-3.0-or-later",
                "GPL-3.0-or-later",
                (gpl,),
                "This application. The bundle as a whole is distributed under GPL-3.0.",
            ),
        ]
    )
    if pyinstaller is not None:
        entries.append(
            LicenseEntry(
                COMPONENT_PYINSTALLER,
                pyinstaller.version,
                PYINSTALLER_CHOSEN,
                PYINSTALLER_CHOSEN,
                (PYINSTALLER_NOTICE_FILE,),
                "The bootloader exception permits distribution of the bundle; "
                "see pyinstaller/COPYING.txt.",
            )
        )
    entries.sort(key=lambda entry: entry.component)
    _write_text(out_dir, INDEX_JSON_NAME, render_index_json(entries))
    _write_text(out_dir, INDEX_MD_NAME, render_index_markdown(entries))
    return entries


# --------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        prog="collect_licenses.py", description="Collect the third-party licences."
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="output folder")
    args = parser.parse_args(argv)
    try:
        entries = collect(args.out, repo_root=REPO_ROOT)
    except (LicenseError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"{len(entries)} component(s) written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
