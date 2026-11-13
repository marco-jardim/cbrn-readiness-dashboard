# SPDX-License-Identifier: GPL-3.0-or-later
"""Self-test (T0.7): registry, ``selftest.json``, throwaway folder and database safety."""

import json
import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import cbrn_dashboard
from cbrn_dashboard import selftest
from cbrn_dashboard.app import main
from cbrn_dashboard.paths import DATABASE_FILE_NAME, DataLocation, LocationSource

pytestmark = pytest.mark.ui

EXPECTED_CHECKS = [
    "python",
    "qt",
    "paths",
    "i18n.pt-BR",
    "i18n.en-US",
    "i18n.es-ES",
    "main_window",
    "database",
]


def _run(data: Path, qm_dir: Path) -> int:
    return main(["--self-test", "--data-dir", str(data)], qm_dir=qm_dir)


def _result(data: Path) -> dict[str, object]:
    loaded: dict[str, object] = json.loads((data / "selftest.json").read_text(encoding="utf-8"))
    return loaded


def test_registry_holds_the_t07_checks() -> None:
    names = [name for name, _ in selftest.CHECKS]
    assert len(names) == len(set(names))
    assert set(EXPECTED_CHECKS) <= set(names)


def test_self_test_passes_and_lists_every_check(
    qapp: QApplication, qm_dir: Path, tmp_path: Path
) -> None:
    data = tmp_path / "data"
    assert _run(data, qm_dir) == 0
    result = _result(data)
    assert result["version"] == cbrn_dashboard.__version__
    assert result["passed"] is True
    assert set(result) == {"version", "passed", "checks"}
    checks = result["checks"]
    assert isinstance(checks, list)
    assert [c["name"] for c in checks] == [name for name, _ in selftest.CHECKS]
    assert all(c["passed"] is True and c["error"] is None for c in checks)


def test_only_selftest_json_is_left_in_the_data_folder(
    qapp: QApplication, qm_dir: Path, tmp_path: Path
) -> None:
    data = tmp_path / "data"
    assert _run(data, qm_dir) == 0
    assert [entry.name for entry in data.iterdir()] == ["selftest.json"]


def test_json_is_utf8_and_has_no_timestamps(
    qapp: QApplication, qm_dir: Path, tmp_path: Path
) -> None:
    data = tmp_path / "data"
    assert _run(data, qm_dir) == 0
    text = (data / "selftest.json").read_text(encoding="utf-8")
    assert text.startswith('{\n  "version"')
    assert "time" not in text.lower()
    assert "date" not in text.lower()


def test_existing_database_is_left_untouched(
    qapp: QApplication, qm_dir: Path, tmp_path: Path
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    database = data / DATABASE_FILE_NAME
    content = b"not really SQLite \x00\x01\xff" * 100
    database.write_bytes(content)
    os.utime(database, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    before = database.stat().st_mtime_ns

    assert _run(data, qm_dir) == 0

    assert database.read_bytes() == content
    assert database.stat().st_mtime_ns == before
    assert list(data.glob("tmp/selftest-*")) == []
    assert sorted(entry.name for entry in data.iterdir()) == [DATABASE_FILE_NAME, "selftest.json"]


def test_a_failing_check_gives_exit_one_and_hides_the_message(
    qapp: QApplication, qm_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    seen: list[Path] = []

    def boom(context: selftest.SelfTestContext) -> None:
        assert context.workdir.is_dir()
        seen.append(context.workdir)
        raise RuntimeError("DEMO-SECRET")

    patched = [(name, boom if name == "qt" else check) for name, check in selftest.CHECKS]
    monkeypatch.setattr(selftest, "CHECKS", patched)

    assert _run(data, qm_dir) == 1

    text = (data / "selftest.json").read_text(encoding="utf-8")
    assert "DEMO-SECRET" not in text
    result = _result(data)
    assert result["passed"] is False
    checks = result["checks"]
    assert isinstance(checks, list)
    by_name = {c["name"]: c for c in checks}
    assert by_name["qt"] == {"name": "qt", "passed": False, "error": "RuntimeError"}
    assert all(c["passed"] for name, c in by_name.items() if name != "qt")
    assert len(seen) == 1
    assert not seen[0].exists()
    assert list(data.glob("tmp/selftest-*")) == []


def _checks_by_name(data: Path) -> dict[str, dict[str, object]]:
    checks = _result(data)["checks"]
    assert isinstance(checks, list)
    return {c["name"]: c for c in checks}


def test_failed_cleanup_gives_exit_one_and_names_only_the_exception_type(
    qapp: QApplication, qm_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    calls: list[Path] = []

    def locked(path: Path, *args: object, **kwargs: object) -> None:
        calls.append(path)
        raise PermissionError("DEMO-SECRET")

    monkeypatch.setattr(selftest.shutil, "rmtree", locked)

    assert _run(data, qm_dir) == 1

    assert len(calls) == 2  # one retry, no more
    text = (data / "selftest.json").read_text(encoding="utf-8")
    assert "DEMO-SECRET" not in text
    result = _result(data)
    assert result["passed"] is False
    by_name = _checks_by_name(data)
    assert by_name["cleanup"] == {"name": "cleanup", "passed": False, "error": "PermissionError"}
    assert all(c["passed"] for name, c in by_name.items() if name != "cleanup")


def test_cleanup_that_succeeds_on_the_retry_passes(
    qapp: QApplication, qm_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    real_rmtree = selftest.shutil.rmtree
    calls: list[Path] = []

    def flaky(path: Path, *args: object, **kwargs: object) -> None:
        calls.append(path)
        if len(calls) == 1:
            raise PermissionError("DEMO-SECRET")
        real_rmtree(path)

    monkeypatch.setattr(selftest.shutil, "rmtree", flaky)

    assert _run(data, qm_dir) == 0

    assert len(calls) == 2
    assert "cleanup" not in _checks_by_name(data)
    assert _result(data)["passed"] is True
    assert [entry.name for entry in data.iterdir()] == ["selftest.json"]


def test_qt_check_passes_with_matching_runtime(qapp: QApplication) -> None:
    location = DataLocation(path=Path("unused"), source=LocationSource.CLI, writable=True)
    dict(selftest.CHECKS)["qt"](selftest.SelfTestContext(location, Path("unused"), None))


def test_qt_check_fails_when_the_runtime_version_differs(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("PySide6.QtCore.qVersion", lambda: "0.0.0")
    location = DataLocation(path=Path("unused"), source=LocationSource.CLI, writable=True)
    with pytest.raises(selftest.SelfTestError):
        dict(selftest.CHECKS)["qt"](selftest.SelfTestContext(location, Path("unused"), None))


def test_an_existing_tmp_folder_is_kept(qapp: QApplication, qm_dir: Path, tmp_path: Path) -> None:
    data = tmp_path / "data"
    (data / "tmp").mkdir(parents=True)
    keep = data / "tmp" / "keep.txt"
    keep.write_text("keep", encoding="utf-8")

    assert _run(data, qm_dir) == 0

    assert keep.read_text(encoding="utf-8") == "keep"
    assert [entry.name for entry in (data / "tmp").iterdir()] == ["keep.txt"]


def test_unwritable_data_folder_returns_one_without_raising(
    qapp: QApplication, qm_dir: Path, tmp_path: Path
) -> None:
    location = DataLocation(path=tmp_path / "ro", source=LocationSource.CLI, writable=False)
    assert selftest.run(location, qm_dir=qm_dir) == 1
    assert not (tmp_path / "ro").exists()


def test_database_check_works_inside_the_throwaway_folder(tmp_path: Path) -> None:
    location = DataLocation(path=tmp_path / "data", source=LocationSource.CLI, writable=True)
    workdir = tmp_path / "work"
    workdir.mkdir()
    check = dict(selftest.CHECKS)["database"]

    check(selftest.SelfTestContext(location, workdir, None))

    assert [entry.name for entry in workdir.iterdir()] == ["selftest.sqlite3"]
    assert not (tmp_path / "data").exists()


def test_register_appends_a_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selftest, "CHECKS", [])

    @selftest.register("demo")
    def _demo(context: selftest.SelfTestContext) -> None:
        return None

    assert [name for name, _ in selftest.CHECKS] == ["demo"]
