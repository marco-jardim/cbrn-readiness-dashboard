# SPDX-License-Identifier: GPL-3.0-or-later
"""The SignPath artifact configuration kept in the repository signs one file and nothing else."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATION = ROOT / ".signpath" / "artifact-configurations" / "release.xml"
NAMESPACE = "http://signpath.io/artifact-configuration/v1"
BUILD_SCRIPT = ROOT / "scripts" / "build_exe.py"


def _tag(name: str) -> str:
    return f"{{{NAMESPACE}}}{name}"


def _root() -> ET.Element:
    return ET.parse(CONFIGURATION).getroot()


def _version_resource_product_name() -> str:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r'^VERSION_FILE_PRODUCT_NAME = "([^"]+)"', source, re.MULTILINE)
    assert match is not None, "VERSION_FILE_PRODUCT_NAME not found in scripts/build_exe.py"
    return match.group(1)


def test_the_artifact_configuration_exists_and_parses_in_the_signpath_namespace() -> None:
    assert CONFIGURATION.is_file()
    assert _root().tag == _tag("artifact-configuration")


def test_the_configuration_has_a_required_version_parameter() -> None:
    parameters = _root().findall(f"{_tag('parameters')}/{_tag('parameter')}")
    assert [(item.get("name"), item.get("required")) for item in parameters] == [
        ("version", "true")
    ]


def test_the_root_element_is_the_zip_file_of_the_bundle() -> None:
    children = [child.tag for child in _root() if child.tag != _tag("parameters")]
    assert children == [_tag("zip-file")]


def test_exactly_one_file_is_signed_and_it_is_our_executable() -> None:
    zip_file = _root().find(_tag("zip-file"))
    assert zip_file is not None
    assert [child.tag for child in zip_file] == [_tag("pe-file")]
    signed = list(_root().iter(_tag("authenticode-sign")))
    assert len(signed) == 1
    pe_files = list(_root().iter(_tag("pe-file")))
    assert len(pe_files) == 1
    assert pe_files[0].get("path") == "cbrn-dashboard.exe"
    assert [child.tag for child in pe_files[0]] == [_tag("authenticode-sign")]
    assert not [element for element in _root().iter() if element.tag == _tag("directory")]
    assert "*" not in (pe_files[0].get("path") or "")


def test_the_product_name_equals_the_one_of_the_version_resource() -> None:
    (pe_file,) = _root().iter(_tag("pe-file"))
    assert pe_file.get("product-name") == _version_resource_product_name()


def test_the_product_version_is_the_version_parameter_as_the_resource_writes_it() -> None:
    (pe_file,) = _root().iter(_tag("pe-file"))
    assert pe_file.get("product-version") == "${version}"
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert '("ProductVersion", version)' in source


def test_the_file_name_matches_the_executable_the_build_makes() -> None:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert re.search(r'^APP_NAME = "cbrn-dashboard"', source, re.MULTILINE)
