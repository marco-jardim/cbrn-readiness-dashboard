# SPDX-License-Identifier: GPL-3.0-or-later
"""The dependency-licence allow-list (PLAN.md section 4.2, task T9.2).

The runtime environment may contain only the licences of ``ALLOWED_LICENSES`` in
``scripts/collect_licenses.py``. SPDX ``OR`` expressions pass when one alternative is allowed.
"""

import importlib.util
import sys
import tomllib
from collections.abc import Sequence
from importlib.metadata import Distribution
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "collect_licenses.py"

PYSIDE_DECLARED = "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"
NOT_RUNTIME = ("pytest", "ruff", "mypy", "pyinstaller", "babel", "pypdf")


@pytest.fixture(scope="module")
def script() -> ModuleType:
    name = "cbrn_collect_licenses_meta_script"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def make_distribution(
    folder: Path,
    name: str,
    *,
    license_expression: str | None = None,
    license_field: str | None = None,
    classifiers: Sequence[str] = (),
    requires: Sequence[str] = (),
    version: str = "1.0",
) -> Distribution:
    """Write a minimal ``*.dist-info/METADATA`` below ``folder`` and load it."""
    info = folder / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True)
    lines = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
    if license_expression is not None:
        lines.append(f"License-Expression: {license_expression}")
    if license_field is not None:
        lines.append(f"License: {license_field}")
    lines.extend(f"Classifier: {item}" for item in classifiers)
    lines.extend(f"Requires-Dist: {item}" for item in requires)
    (info / "METADATA").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Distribution.at(info)


def choose_text(script: ModuleType, text: str) -> str | None:
    result = script.choose_license(script.parse_license_expression(text))
    assert result is None or isinstance(result, str)
    return result


# --------------------------------------------------------------------------------------------
# The real environment
# --------------------------------------------------------------------------------------------


def test_every_runtime_distribution_has_an_allowed_licence(script: ModuleType) -> None:
    dists = script.runtime_distributions()
    assert dists, "no runtime distribution found"
    offenders: list[str] = []
    for dist in dists:
        declared, chosen = script.resolve_license(dist)
        if chosen is None:
            offenders.append(f"{dist.name} {dist.version}: declared {declared!r}")
    assert not offenders, "licences outside the allow-list:\n" + "\n".join(offenders)


def _locked_runtime_closure(script: ModuleType) -> set[str]:
    """The names reachable from the project's own runtime dependencies in ``uv.lock``.

    Dev, build and tools groups are not followed. A dependency edge with a marker counts when the
    marker holds here (the build is Windows-only; markers are written with single quotes).
    """
    data = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    packages: dict[str, list[dict[str, object]]] = {}
    for package in data["package"]:
        packages.setdefault(script.normalize_name(package["name"]), []).append(package)
    pending = [script.normalize_name(script.PROJECT_NAME)]
    reached: set[str] = set()
    while pending:
        for package in packages.get(pending.pop(), []):
            dependencies = package.get("dependencies", [])
            assert isinstance(dependencies, list)
            for edge in dependencies:
                marker = edge.get("marker")
                if marker and not script.marker_applies(marker):
                    continue
                name = script.normalize_name(edge["name"])
                if name not in reached:
                    reached.add(name)
                    pending.append(name)
    return reached


def test_collected_distributions_are_exactly_the_locked_runtime_closure(
    script: ModuleType,
) -> None:
    """P9-05: nothing of the locked runtime closure is silently left out, and nothing extra."""
    collected = {script.normalize_name(dist.name) for dist in script.runtime_distributions()}
    locked = _locked_runtime_closure(script)
    assert {"cryptography", "pyside6", "shiboken6"} <= locked
    assert collected == locked


def test_an_applicable_requirement_that_is_not_installed_is_an_error(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = "definitely-not-installed-package-xyz"
    monkeypatch.setattr(script, "_root_requirements", lambda root: [f"{missing}>=1"])
    with pytest.raises(script.LicenseError, match=missing):
        script.runtime_distributions()


def test_a_requirement_whose_marker_does_not_apply_may_be_missing(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = "definitely-not-installed-package-xyz"
    requirements = [f'{missing}>=1; sys_platform == "plan9"', f'{missing}; extra == "docs"']
    monkeypatch.setattr(script, "_root_requirements", lambda root: requirements)
    assert script.runtime_distributions() == []


def test_runtime_set_has_pyside_and_no_dev_tools(script: ModuleType) -> None:
    names = {script.normalize_name(dist.name) for dist in script.runtime_distributions()}
    assert {"pyside6", "shiboken6", "cryptography"} <= names
    assert not names & set(NOT_RUNTIME)
    assert "cbrn-readiness-dashboard" not in names


def test_runtime_distributions_are_sorted_by_normalised_name(script: ModuleType) -> None:
    names = [script.normalize_name(dist.name) for dist in script.runtime_distributions()]
    assert names == sorted(names)
    assert len(names) == len(set(names))


def test_pyside6_declares_the_or_expression_and_lgpl_is_chosen(script: ModuleType) -> None:
    by_name = {script.normalize_name(d.name): d for d in script.runtime_distributions()}
    for name in ("pyside6", "shiboken6"):
        declared, chosen = script.resolve_license(by_name[name])
        assert declared == PYSIDE_DECLARED
        assert chosen == "LGPL-3.0-only"


# --------------------------------------------------------------------------------------------
# Fake distributions
# --------------------------------------------------------------------------------------------


def test_fake_distribution_without_licence_is_unknown(script: ModuleType, tmp_path: Path) -> None:
    dist = make_distribution(tmp_path, "mystery")
    assert script.resolve_license(dist) == (None, None)


@pytest.mark.parametrize(
    "unknown",
    ["UNKNOWN", "Proprietary", "Some Company EULA 2024", "LicenseRef-Mystery"],
)
def test_fake_distribution_with_unknown_licence_text_fails(
    script: ModuleType, tmp_path: Path, unknown: str
) -> None:
    dist = make_distribution(tmp_path, "mystery", license_field=unknown)
    assert script.resolve_license(dist)[1] is None


@pytest.mark.parametrize(
    "disallowed", ["GPL-2.0-only", "AGPL-3.0-only", "LicenseRef-Proprietary", "GPL-2.0-or-later"]
)
def test_fake_distribution_with_disallowed_licence_fails(
    script: ModuleType, tmp_path: Path, disallowed: str
) -> None:
    for index, field in enumerate(("expression", "legacy")):
        folder = tmp_path / str(index)
        folder.mkdir()
        if field == "expression":
            dist = make_distribution(folder, "bad", license_expression=disallowed)
        else:
            dist = make_distribution(folder, "bad", license_field=disallowed)
        declared, chosen = script.resolve_license(dist)
        assert declared == disallowed
        assert chosen is None


def test_fake_or_expression_with_one_allowed_alternative_passes(
    script: ModuleType, tmp_path: Path
) -> None:
    dist = make_distribution(tmp_path, "dual", license_expression="GPL-2.0-only OR MIT")
    assert script.resolve_license(dist) == ("GPL-2.0-only OR MIT", "MIT")


def test_license_expression_field_wins_over_the_legacy_field(
    script: ModuleType, tmp_path: Path
) -> None:
    dist = make_distribution(
        tmp_path, "both", license_expression="Apache-2.0", license_field="GPL-2.0-only"
    )
    assert script.declared_license(dist) == "Apache-2.0"


def test_legacy_field_holding_an_or_expression_is_used(script: ModuleType, tmp_path: Path) -> None:
    dist = make_distribution(tmp_path, "qt-like", license_field=PYSIDE_DECLARED)
    assert script.resolve_license(dist) == (PYSIDE_DECLARED, "LGPL-3.0-only")


def test_prose_in_the_legacy_field_falls_back_to_classifiers(
    script: ModuleType, tmp_path: Path
) -> None:
    dist = make_distribution(
        tmp_path,
        "prose",
        license_field="MIT License - Permission is hereby granted, free of charge",
        classifiers=["License :: OSI Approved :: MIT License"],
    )
    assert script.resolve_license(dist) == ("MIT", "MIT")


@pytest.mark.parametrize(
    ("classifier", "expected"),
    [
        ("License :: OSI Approved :: MIT License", "MIT"),
        ("License :: OSI Approved :: BSD License", "BSD-3-Clause"),
        ("License :: OSI Approved :: Apache Software License", "Apache-2.0"),
        ("License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)", "MPL-2.0"),
        ("License :: OSI Approved :: Python Software Foundation License", "PSF-2.0"),
        (
            "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)",
            "LGPL-3.0-only",
        ),
        ("License :: OSI Approved :: GNU General Public License v3 (GPLv3)", "GPL-3.0-only"),
    ],
)
def test_classifier_only_distribution_is_resolved_through_the_map(
    script: ModuleType, tmp_path: Path, classifier: str, expected: str
) -> None:
    dist = make_distribution(tmp_path, "classified", classifiers=[classifier, "Topic :: Utilities"])
    assert script.resolve_license(dist) == (expected, expected)


def test_unmapped_classifier_is_unknown(script: ModuleType, tmp_path: Path) -> None:
    dist = make_distribution(
        tmp_path,
        "old-gpl",
        classifiers=["License :: OSI Approved :: GNU General Public License v2 (GPLv2)"],
    )
    assert script.resolve_license(dist) == (None, None)


def test_two_license_classifiers_are_alternatives(script: ModuleType, tmp_path: Path) -> None:
    dist = make_distribution(
        tmp_path,
        "dual-classified",
        classifiers=[
            "License :: OSI Approved :: Apache Software License",
            "License :: OSI Approved :: BSD License",
        ],
    )
    assert script.resolve_license(dist) == ("Apache-2.0 OR BSD-3-Clause", "Apache-2.0")


# --------------------------------------------------------------------------------------------
# SPDX expressions
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("MIT", "MIT"),
        ("MIT-0", "MIT-0"),
        ("Python-2.0", None),
        ("GPL-2.0-only OR MIT", "MIT"),
        ("LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only", "LGPL-3.0-only"),
        ("GPL-3.0-only OR GPL-2.0-only OR LGPL-3.0-only", "LGPL-3.0-only"),
        ("GPL-3.0-only OR LGPL-3.0-or-later", "LGPL-3.0-or-later"),
        ("Apache-2.0 OR BSD-3-Clause", "Apache-2.0"),
        ("BSD-3-Clause OR Apache-2.0", "BSD-3-Clause"),
        ("MIT AND BSD-3-Clause", "MIT AND BSD-3-Clause"),
        ("MIT AND GPL-2.0-only", None),
        ("GPL-2.0-only OR AGPL-3.0-only", None),
        ("GPL-2.0-only", None),
        ("AGPL-3.0-only", None),
        ("LicenseRef-Proprietary", None),
        ("Unicode-3.0", "Unicode-3.0"),
        ("MPL-2.0", "MPL-2.0"),
        ("PSF-2.0", "PSF-2.0"),
    ],
)
def test_choose_license(script: ModuleType, text: str, expected: str | None) -> None:
    assert choose_text(script, text) == expected


def test_parentheses(script: ModuleType) -> None:
    assert choose_text(script, "(MIT OR GPL-2.0-only) AND BSD-3-Clause") == "MIT AND BSD-3-Clause"
    assert choose_text(script, "(GPL-2.0-only OR AGPL-3.0-only) AND MIT") is None
    assert choose_text(script, "((MIT))") == "MIT"
    assert choose_text(script, "MIT AND (GPL-2.0-only OR Apache-2.0)") == "MIT AND Apache-2.0"


def test_and_binds_tighter_than_or(script: ModuleType) -> None:
    # GPL-2.0-only OR (MIT AND GPL-2.0-only) has no allowed alternative.
    assert choose_text(script, "GPL-2.0-only OR MIT AND GPL-2.0-only") is None
    assert choose_text(script, "GPL-2.0-only OR MIT AND BSD-2-Clause") == "MIT AND BSD-2-Clause"


def test_operators_are_case_insensitive(script: ModuleType) -> None:
    assert choose_text(script, "gpl-2.0-only or MIT") == "MIT"
    assert choose_text(script, "mit and bsd-3-clause") == "MIT AND BSD-3-Clause"
    assert choose_text(script, "Apache-2.0 Or MIT") == "Apache-2.0"


def test_with_exception_is_treated_as_the_licence(script: ModuleType) -> None:
    expr = script.parse_license_expression("GPL-3.0-or-later WITH Classpath-exception-2.0")
    assert expr == script.Identifier("GPL-3.0-or-later", "Classpath-exception-2.0")
    assert script.choose_license(expr) == "GPL-3.0-or-later"
    assert choose_text(script, "GPL-2.0-only WITH Classpath-exception-2.0") is None
    assert choose_text(script, "gpl-3.0-only with Foo-exception OR MIT") == "GPL-3.0-only"


@pytest.mark.parametrize(
    "text",
    ["", "   ", "MIT License", "MIT OR", "OR MIT", "(MIT", "MIT)", "MIT AND AND BSD", "WITH"],
)
def test_malformed_expressions_are_rejected(script: ModuleType, text: str) -> None:
    with pytest.raises(script.LicenseSyntaxError):
        script.parse_license_expression(text)


def test_choose_from_text_gives_none_for_prose(script: ModuleType) -> None:
    assert script.choose_from_text("Permission is hereby granted, free of charge") is None
    assert script.choose_from_text(None) is None
    assert script.choose_from_text("") is None


def test_allow_list_follows_the_plan(script: ModuleType) -> None:
    allowed: frozenset[str] = script.ALLOWED_LICENSES
    assert {"MIT", "BSD-3-Clause", "Apache-2.0", "PSF-2.0", "MPL-2.0", "Unicode-3.0"} <= allowed
    assert {"LGPL-3.0-only", "GPL-3.0-only"} <= allowed
    assert not allowed & {"GPL-2.0-only", "AGPL-3.0-only", "GPL-2.0-or-later"}


def test_allow_list_is_exactly_the_plan_list(script: ModuleType) -> None:
    """P9-14: PLAN.md section 4.2 (MIT, BSD, Apache-2.0, PSF-2.0, MPL-2.0, Unicode-3.0, LGPL-3.0,
    GPL-3.0), with BSD as its 2- and 3-clause ids and the LGPL/GPL ids in their two SPDX forms,
    plus ``MIT-0``, which the locked ``cffi`` declares. Any other id, ``Python-2.0`` included,
    needs a plan change first."""
    assert (
        frozenset(
            {
                "MIT",
                "MIT-0",
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
        == script.ALLOWED_LICENSES
    )


# --------------------------------------------------------------------------------------------
# The legacy License field and the classifiers (P9-06)
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("disallowed", ["GPL-2.0-only", "AGPL-3.0-only", "GPL-2.0-or-later"])
def test_an_allowed_classifier_does_not_overrule_a_disallowed_spdx_legacy_field(
    script: ModuleType, tmp_path: Path, disallowed: str
) -> None:
    dist = make_distribution(
        tmp_path,
        "mixed",
        license_field=disallowed,
        classifiers=["License :: OSI Approved :: MIT License"],
    )
    assert script.resolve_license(dist) == (disallowed, None)


def test_a_shorthand_in_the_legacy_field_defers_to_the_classifiers(
    script: ModuleType, tmp_path: Path
) -> None:
    dist = make_distribution(
        tmp_path,
        "shorthand",
        license_field="BSD",
        classifiers=["License :: OSI Approved :: BSD License"],
    )
    assert script.resolve_license(dist) == ("BSD-3-Clause", "BSD-3-Clause")


def test_a_shorthand_without_classifiers_stays_unresolved(
    script: ModuleType, tmp_path: Path
) -> None:
    dist = make_distribution(tmp_path, "shorthand", license_field="BSD")
    assert script.resolve_license(dist) == ("BSD", None)


def test_an_unknown_legacy_field_defers_to_the_classifiers(
    script: ModuleType, tmp_path: Path
) -> None:
    dist = make_distribution(
        tmp_path,
        "unknown",
        license_field="UNKNOWN",
        classifiers=["License :: OSI Approved :: Apache Software License"],
    )
    assert script.resolve_license(dist) == ("Apache-2.0", "Apache-2.0")


# --------------------------------------------------------------------------------------------
# Distributions that the build removed (P9-04)
# --------------------------------------------------------------------------------------------


def make_distribution_with_files(folder: Path, name: str, files: Sequence[str]) -> Distribution:
    """A fake distribution whose ``RECORD`` lists ``files`` (relative to the site folder)."""
    make_distribution(folder, name, license_expression="Apache-2.0")  # its standard text exists
    info = folder / f"{name.replace('-', '_')}-1.0.dist-info"
    (info / "RECORD").write_text("".join(f"{item},,\n" for item in files), encoding="utf-8")
    for item in files:  # importlib.metadata lists only the recorded files that exist
        installed = folder / item
        installed.parent.mkdir(parents=True, exist_ok=True)
        installed.write_bytes(b"")
    return Distribution.at(info)


def test_a_distribution_whose_native_files_were_all_pruned_is_not_bundled(
    script: ModuleType, tmp_path: Path
) -> None:
    pruned = make_distribution_with_files(
        tmp_path / "site",
        "pyside6-pdf",
        ["PySide6/QtPdf.pyd", "PySide6/Qt6Pdf.dll", "PySide6/a.py"],
    )
    kept = make_distribution_with_files(
        tmp_path / "site2", "pyside6-essentials", ["PySide6/QtCore.pyd", "PySide6/Qt6Core.dll"]
    )
    pure = make_distribution_with_files(tmp_path / "site3", "pure", ["pure/__init__.py"])
    bundle = tmp_path / "bundle"
    (bundle / "_internal" / "PySide6").mkdir(parents=True)
    (bundle / "_internal" / "PySide6" / "QtCore.pyd").write_bytes(b"x")

    names = script.bundle_file_names(bundle)

    assert names == {"qtcore.pyd"}
    assert script.distribution_is_bundled(pruned, names) is False
    assert script.distribution_is_bundled(kept, names) is True
    assert script.distribution_is_bundled(pure, names) is True


def test_the_index_of_a_built_bundle_has_no_row_for_a_pruned_distribution(
    script: ModuleType, tmp_path: Path
) -> None:
    pruned = make_distribution_with_files(tmp_path / "a", "gone-pkg", ["gone/gone.pyd"])
    kept = make_distribution_with_files(tmp_path / "b", "kept-pkg", ["kept/kept.pyd"])
    bundle = tmp_path / "bundle"
    (bundle / "_internal" / "kept").mkdir(parents=True)
    (bundle / "_internal" / "kept" / "kept.pyd").write_bytes(b"x")

    entries = script.collect(
        tmp_path / "out",
        repo_root=ROOT,
        distributions=[pruned, kept],
        qt_versions=("6.12.0", "6.12.0"),
        allow_missing_pyinstaller=True,
        bundle_dir=bundle,
    )

    components = {entry.component for entry in entries}
    assert "kept-pkg" in components
    assert "gone-pkg" not in components
    assert not (tmp_path / "out" / "gone-pkg").exists()


# --------------------------------------------------------------------------------------------
# Requirements and markers
# --------------------------------------------------------------------------------------------


def test_parse_requirement(script: ModuleType) -> None:
    assert script.parse_requirement("PySide6>=6.8,<6.13") == ("PySide6", "")
    assert script.parse_requirement('cffi>=1.12; platform_python_implementation != "PyPy"') == (
        "cffi",
        'platform_python_implementation != "PyPy"',
    )
    assert script.parse_requirement("shiboken6==6.12.0") == ("shiboken6", "")


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        ('extra == "test"', False),
        ('extra == "test" and python_version >= "3.8"', False),
        ('extra != "test"', True),
        ('sys_platform == "win32"', True),
        ('sys_platform == "linux"', False),
        ('sys_platform != "win32"', False),
        ('platform_system == "Windows" or platform_system == "Linux"', True),
        ('platform_system == "Darwin"', False),
        ('python_version < "3.8"', False),
        ('python_version >= "3.8"', True),
        ('python_version < "3.10" or sys_platform == "win32"', True),
        ('(sys_platform == "linux" or os_name == "posix") and python_version > "3"', False),
        ('platform_python_implementation != "PyPy"', True),
        ('implementation_name == "unknown-impl"', True),
        ("this is not a marker", True),
        ('sys_platform == "win32" and', True),
    ],
)
def test_marker_applies_on_windows_python_3_12(
    script: ModuleType, marker: str, expected: bool
) -> None:
    environment = {
        "python_version": "3.12",
        "python_full_version": "3.12.4",
        "sys_platform": "win32",
        "platform_system": "Windows",
        "os_name": "nt",
        "extra": "",
    }
    assert script.marker_applies(marker, environment) is expected


def test_normalize_name(script: ModuleType) -> None:
    assert script.normalize_name("PySide6_Essentials") == "pyside6-essentials"
    assert script.normalize_name("Foo.Bar__baz") == "foo-bar-baz"
