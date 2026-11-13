# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared fixtures: offscreen Qt, an isolated data folder and compiled test catalogues."""

import os

# Must happen before any Qt import (also through the imports below).
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication

from cbrn_dashboard import i18n
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from tests.i18n._ts import catalogue_files, load_script, write_pseudo_ts

#: The text right after the opening mark of the pseudo catalogue, per language.
PSEUDO_PREFIX: dict[str, str] = {"pt_BR": "", "en_US": "en:", "es_ES": "es:"}


@pytest.fixture(scope="session", autouse=True)
def _isolated_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Point ``CBRN_DASHBOARD_DATA_DIR`` at a temporary folder for the whole session."""
    folder = tmp_path_factory.mktemp("data")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CBRN_DASHBOARD_DATA_DIR", str(folder))
        yield folder


@pytest.fixture(scope="session")
def qm_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Every ``.ts`` catalogue compiled into a temporary folder (never into the source tree)."""
    folder = tmp_path_factory.mktemp("qm")
    load_script().compile_catalogues(folder)
    return folder


@pytest.fixture(scope="session")
def pseudo_qm_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Pseudo-locale catalogues: every translation is ``⟦<prefix><source text>⟧``.

    The files keep the regular ``<area>_<lang>.qm`` names, so a ``TranslatorManager`` created
    with this folder loads them for any language. The markers are LANGUAGE-SPECIFIC
    (:data:`PSEUDO_PREFIX`): pt_BR ``⟦…⟧``, en_US ``⟦en:…⟧``, es_ES ``⟦es:…⟧``, so a text that was
    not re-applied after a language switch still carries the OLD language's marker.
    """
    script = load_script()
    ts_folder = tmp_path_factory.mktemp("pseudo_ts")
    out_folder = tmp_path_factory.mktemp("pseudo_qm")
    for area, lang, path in catalogue_files():
        target = ts_folder / f"{area}_{lang}.ts"
        write_pseudo_ts(path, target)
        prefix = PSEUDO_PREFIX[lang]
        if prefix:
            text = target.read_text(encoding="utf-8")
            target.write_text(text.replace("\u27e6", "\u27e6" + prefix), encoding="utf-8")
    script.compile_catalogues(out_folder, ts_dir=ts_folder)
    for area, lang, _ in catalogue_files():
        assert (out_folder / i18n.qm_name(area, lang)).is_file()
    return out_folder


@pytest.fixture
def translator_manager_factory(
    qapp: QCoreApplication,
) -> Iterator[Callable[[Path | None], TranslatorManager]]:
    """Build managers bound to a given ``.qm`` folder; all are reset on teardown."""
    created: list[TranslatorManager] = []

    def make(folder: Path | None) -> TranslatorManager:
        manager = TranslatorManager(qapp, folder)
        created.append(manager)
        return manager

    yield make
    for manager in reversed(created):
        manager.clear()
        manager.setParent(None)


@pytest.fixture
def translator_manager(
    translator_manager_factory: Callable[[Path | None], TranslatorManager], qm_dir: Path
) -> TranslatorManager:
    """A manager bound to the compiled catalogues of the test session."""
    return translator_manager_factory(qm_dir)
