# SPDX-License-Identifier: GPL-3.0-or-later
"""Self-test (T0.7): registry, ``selftest.json``, throwaway folder and database safety."""

import json
import os
import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import cbrn_dashboard
from cbrn_dashboard import selftest
from cbrn_dashboard.app import main
from cbrn_dashboard.paths import DATABASE_FILE_NAME, DataLocation, LocationSource
from cbrn_dashboard.storage import crypto_backup
from cbrn_dashboard.storage.crypto_backup import DEFAULT_PARAMS, BackupHeader, DecryptedBackup

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
    "chart",
    "encrypted_backup",
    "pdf",
    "demo",
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


def test_the_encrypted_backup_check_is_registered_after_the_earlier_ones() -> None:
    names = [name for name, _ in selftest.CHECKS]
    assert names.index("database") < names.index("chart") < names.index("encrypted_backup")


def test_encrypted_backup_check_passes_inside_the_throwaway_folder(tmp_path: Path) -> None:
    location = DataLocation(path=tmp_path / "data", source=LocationSource.CLI, writable=True)
    workdir = tmp_path / "work"
    workdir.mkdir()
    check = dict(selftest.CHECKS)["encrypted_backup"]

    check(selftest.SelfTestContext(location, workdir, None))

    assert (workdir / "selftest.cbrnbak").is_file()
    assert not (tmp_path / "data").exists()
    assert [entry.name for entry in tmp_path.iterdir()] == ["work"]
    shutil.rmtree(workdir)  # every handle is closed, so the folder can be removed (Windows)
    assert not workdir.exists()


def test_a_run_with_the_encrypted_backup_check_leaves_only_the_result_file(
    qapp: QApplication, qm_dir: Path, tmp_path: Path
) -> None:
    data = tmp_path / "data"
    assert _run(data, qm_dir) == 0
    assert _checks_by_name(data)["encrypted_backup"] == {
        "name": "encrypted_backup",
        "passed": True,
        "error": None,
    }
    assert [entry.name for entry in data.iterdir()] == ["selftest.json"]


def test_encrypted_backup_check_fails_with_the_type_name_only_when_the_bytes_differ(
    qapp: QApplication, qm_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"

    def wrong_bytes(path: Path, passphrase: str, **kwargs: object) -> DecryptedBackup:
        header = BackupHeader(1, DEFAULT_PARAMS, b"", "DEMO-SECRET", 1)
        return DecryptedBackup(header, b"DEMO-SECRET")

    monkeypatch.setattr(crypto_backup, "read_backup", wrong_bytes)

    assert _run(data, qm_dir) == 1

    text = (data / "selftest.json").read_text(encoding="utf-8")
    assert "DEMO-SECRET" not in text
    by_name = _checks_by_name(data)
    assert by_name["encrypted_backup"] == {
        "name": "encrypted_backup",
        "passed": False,
        "error": "SelfTestError",
    }
    assert all(c["passed"] for name, c in by_name.items() if name != "encrypted_backup")
    assert [entry.name for entry in data.iterdir()] == ["selftest.json"]


def test_the_pdf_check_is_registered_after_the_encrypted_backup_check() -> None:
    names = [name for name, _ in selftest.CHECKS]
    assert names.index("encrypted_backup") < names.index("pdf")


def test_pdf_check_passes_and_leaves_nothing_in_the_throwaway_folder(
    qapp: QApplication, qm_dir: Path, tmp_path: Path
) -> None:
    location = DataLocation(path=tmp_path / "data", source=LocationSource.CLI, writable=True)
    workdir = tmp_path / "work"
    workdir.mkdir()

    dict(selftest.CHECKS)["pdf"](selftest.SelfTestContext(location, workdir, qm_dir))

    assert list(workdir.iterdir()) == []
    assert not (tmp_path / "data").exists()


def test_pdf_check_draws_a_chart(
    qapp: QApplication, qm_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P8-11: the frozen self-test must exercise Qt Charts and ``render_to_image``."""
    from PySide6.QtCore import QLocale
    from PySide6.QtGui import QImage

    from cbrn_dashboard.reports import pdf
    from cbrn_dashboard.ui.shell.charts import ChartData

    real_render = pdf.render_to_image
    drawn: list[ChartData] = []

    def spy_render(
        data: ChartData, width: int, height: int, *, locale: QLocale | None = None
    ) -> QImage:
        drawn.append(data)
        return real_render(data, width, height, locale=locale)

    monkeypatch.setattr(pdf, "render_to_image", spy_render)
    location = DataLocation(path=tmp_path / "data", source=LocationSource.CLI, writable=True)
    workdir = tmp_path / "work"
    workdir.mkdir()

    dict(selftest.CHECKS)["pdf"](selftest.SelfTestContext(location, workdir, qm_dir))

    assert len(drawn) == 1
    assert not drawn[0].is_empty


def test_the_demo_check_is_registered_after_the_pdf_check() -> None:
    names = [name for name, _ in selftest.CHECKS]
    assert names.index("pdf") < names.index("demo")


def test_demo_check_seeds_a_demo_database_inside_the_throwaway_folder(tmp_path: Path) -> None:
    location = DataLocation(path=tmp_path / "data", source=LocationSource.CLI, writable=True)
    workdir = tmp_path / "work"
    workdir.mkdir()

    dict(selftest.CHECKS)["demo"](selftest.SelfTestContext(location, workdir, None))

    assert not (tmp_path / "data").exists()
    assert [entry.name for entry in tmp_path.iterdir()] == ["work"]
    assert (workdir / "demo-selftest" / "demo" / "demo.sqlite3").is_file()
    shutil.rmtree(workdir)  # every handle is closed, so the folder can be removed (Windows)
    assert not workdir.exists()


def test_a_run_with_the_demo_check_leaves_only_the_result_file(
    qapp: QApplication, qm_dir: Path, tmp_path: Path
) -> None:
    data = tmp_path / "data"
    assert _run(data, qm_dir) == 0
    assert _checks_by_name(data)["demo"] == {"name": "demo", "passed": True, "error": None}
    assert [entry.name for entry in data.iterdir()] == ["selftest.json"]


def test_demo_check_fails_when_the_database_is_not_a_demo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cbrn_dashboard import demo
    from cbrn_dashboard.clock import Clock
    from cbrn_dashboard.storage.db import DatabaseConnection
    from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate

    def not_a_demo(data_dir: Path, clock: Clock) -> DatabaseConnection:
        return open_and_migrate(
            data_dir / "other.sqlite3",
            data_dir=data_dir,
            identity=DatabaseIdentity.REAL,
            backup=False,
        )

    monkeypatch.setattr(demo, "open_demo_database", not_a_demo)
    location = DataLocation(path=tmp_path / "data", source=LocationSource.CLI, writable=True)
    workdir = tmp_path / "work"
    workdir.mkdir()

    with pytest.raises(selftest.SelfTestError):
        dict(selftest.CHECKS)["demo"](selftest.SelfTestContext(location, workdir, None))


def test_register_appends_a_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(selftest, "CHECKS", [])

    @selftest.register("demo")
    def _demo(context: selftest.SelfTestContext) -> None:
        return None

    assert [name for name, _ in selftest.CHECKS] == ["demo"]
