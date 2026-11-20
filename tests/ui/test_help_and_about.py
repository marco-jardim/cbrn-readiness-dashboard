# SPDX-License-Identifier: GPL-3.0-or-later
"""The in-app help in three languages and the About dialog (PLAN.md T10.2).

The help files are checked as plain text (same topics and heading structure in every language, a
topic for every registered page, no link and no image, the UI names they quote are the ones the
catalogues give) and through the viewer (loads in each language, follows a language switch, renders
without anchors). The About dialog is checked against ``__version__``, the licence notice, the
preliminary notice and a licence index written by the real ``scripts/collect_licenses.py`` renderer.
The pseudo-locale walks at the end need the new ``Shell`` strings in the catalogues (run
``python scripts/i18n.py update`` first, as for every new string).
"""

import importlib.util
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QListWidget, QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard import __version__, i18n
from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.prefs import PreferencesStore
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.about import (
    SOURCE_URL,
    AboutDialog,
    Component,
    LicenceIndexError,
    component_line,
    licence_index_path,
    read_licence_index,
)
from cbrn_dashboard.ui.shell.banners import BannerCode, banner_text
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.help import (
    HelpDialog,
    HelpFormatError,
    HelpTopic,
    load_topics,
    parse_help,
    read_help_text,
)
from cbrn_dashboard.ui.shell.main_window import MainWindow
from cbrn_dashboard.ui.shell.registry import PageSpec
from tests.ui._fakes import FakePrompts, expect_handle
from tests.ui._walk import CLOSE_MARK, OPEN_MARK, assert_fully_translated, collect_texts
from tests.ui.conftest import NOW, StartApp

pytestmark = pytest.mark.ui

ROOT = Path(__file__).resolve().parents[2]
LANGUAGES = ("pt_BR", "en_US", "es_ES")
HELP_DIR = ROOT / "src" / "cbrn_dashboard" / "help"
#: The module whose ``read_help_text`` the fallback tests replace (named by path: no import alias).
HELP_MODULE = "cbrn_dashboard.ui.shell.help"

#: What the help must not contain: a link, an image, an address of any kind, raw HTML.
EXTERNAL_CONTENT = re.compile(r"https?://|ftp://|file:|mailto:|www\.|\]\(|<a[ >]|<img|!\[|<script")


def _t(text: str) -> str:
    return f"{OPEN_MARK}{text}{CLOSE_MARK}"


def _help_text(language: str) -> str:
    return (HELP_DIR / f"{language}.md").read_text(encoding="utf-8")


def _heading_levels(text: str) -> list[int]:
    return [len(m.group(1)) for m in re.finditer(r"^(#{1,6}) \S", text, flags=re.MULTILINE)]


def _pages_without_help(topics: tuple[HelpTopic, ...]) -> list[str]:
    keys = {topic.key for topic in topics}
    return [spec.key for spec in registry.pages() if spec.key not in keys]


def _items(widget: QListWidget) -> list[str]:
    texts: list[str] = []
    for row in range(widget.count()):
        item = widget.item(row)
        assert item is not None
        texts.append(item.text())
    return texts


# --------------------------------------------------------------------------- the files


def test_the_three_help_files_exist_as_package_data() -> None:
    assert sorted(path.name for path in HELP_DIR.glob("*")) == ["en_US.md", "es_ES.md", "pt_BR.md"]
    for language in LANGUAGES:
        text = read_help_text(language)
        assert text is not None
        assert text == _help_text(language)
        assert len(text.splitlines()) > 50


def test_a_language_without_a_catalogue_has_no_help_file() -> None:
    assert read_help_text("fr_FR") is None
    assert read_help_text("../en_US") is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_help_file_parses_into_topics(language: str) -> None:
    topics = parse_help(_help_text(language))
    assert topics
    assert all(topic.title for topic in topics)
    assert all(topic.markdown.startswith("#") for topic in topics)
    assert all("topic:" not in topic.markdown for topic in topics)


def test_the_three_files_have_the_same_heading_structure() -> None:
    reference = _heading_levels(_help_text("en_US"))
    assert reference[0] == 1
    assert len(reference) > 15
    for language in LANGUAGES:
        assert _heading_levels(_help_text(language)) == reference, language


def test_the_three_files_have_the_same_topics_in_the_same_order() -> None:
    reference = [(t.key, t.level) for t in parse_help(_help_text("en_US"))]
    expected_keys = {
        "overview",
        "as_of",
        "dashboard",
        "personnel",
        "infrastructure",
        "antidotes",
        "exercises",
        "budget",
        "alerts",
        "reports",
        "import",
        "snapshots",
        "backup",
        "backup_make",
        "backup_restore",
        "backup_folder",
        "settings",
        "privacy",
        "preliminary",
        "infrastructure_stock",
    }
    assert {key for key, _level in reference} == expected_keys
    for language in LANGUAGES:
        found = [(t.key, t.level) for t in parse_help(_help_text(language))]
        assert found == reference, language


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_registered_page_has_a_help_topic(language: str) -> None:
    assert _pages_without_help(parse_help(_help_text(language))) == []
    assert {spec.key for spec in registry.pages()} >= {
        "dashboard",
        "personnel",
        "infrastructure",
        "antidotes",
        "exercises",
        "budget",
        "alerts",
        "reports",
        "settings",
    }


def test_a_new_page_without_help_is_reported() -> None:
    def title() -> str:
        return "A new page"

    def create(_context: AppContext) -> QWidget:
        return QWidget()

    topics = parse_help(_help_text("en_US"))
    with registry.registered(PageSpec("brand_new_page", 95, title, create)):
        assert _pages_without_help(topics) == ["brand_new_page"]
    assert _pages_without_help(topics) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_help_contains_no_link_image_or_address(language: str) -> None:
    found = EXTERNAL_CONTENT.findall(_help_text(language))
    assert found == []


def test_the_external_content_pattern_is_not_vacuous() -> None:
    for sample in (
        "[x](https://example.org)",
        "see https://example.org",
        "![i](a.png)",
        '<a href="x">',
        "<img src='x'>",
        "mail mailto:a@b",
        "www.example.org",
        "file:///c:/x",
    ):
        assert EXTERNAL_CONTENT.search(sample), sample


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_help_does_not_state_a_version_a_release_or_a_signature(language: str) -> None:
    text = _help_text(language).lower()
    for needle in ("0.0.1", __version__, "released on", "is signed", "code-signed"):
        assert needle not in text, needle


# --------------------------------------------------------------------------- the parser


def test_the_parser_strips_the_marker_and_keeps_the_body() -> None:
    text = (
        "# T\n\n## One\n<!-- topic: one -->\n\nBody one.\n\n### Sub\n<!-- topic: sub -->\nBody.\n"
    )
    topics = parse_help(text)
    assert topics == (
        HelpTopic("one", 2, "One", "## One\n\nBody one.\n"),
        HelpTopic("sub", 3, "Sub", "### Sub\nBody.\n"),
    )


@pytest.mark.parametrize(
    "text",
    [
        "# T\n## One\nBody without a marker\n",
        "# T\n## One\n\n<!-- topic: one -->\n",
        "# T\n## One\n<!-- topic: one -->\n## Two\n<!-- topic: one -->\n",
        "# T\n## One\n",
    ],
)
def test_the_parser_rejects_a_badly_formed_file(text: str) -> None:
    with pytest.raises(HelpFormatError):
        parse_help(text)


# --------------------------------------------------------------------------- the UI names it quotes


#: (translation context, source text) of every UI name the help puts in double quotes.
QUOTED_NAMES: tuple[tuple[str, str], ...] = (
    ("Dashboard", "No target"),
    ("Dashboard", "No data"),
    ("Dashboard", "Show as table"),
    ("Dashboard", "Record snapshot"),
    ("Personnel", "Set no renewal"),
    ("Personnel", "Clear no renewal"),
    ("Personnel", "Pseudonymise person"),
    ("Alerts", "Open record"),
    ("ReportsUi", "Create report..."),
    ("ReportsUi", "Export CSV files..."),
    ("ReportsUi", "Validation export..."),
    ("ReportsUi", "Import CSV file..."),
    ("ReportsUi", "Write templates..."),
    ("ReportsUi", "Record snapshot"),
    ("ReportsUi", "Withdraw snapshot..."),
    ("ReportsUi", "Show withdrawn snapshots"),
    ("ReportsUi", "Placeholder - to be confirmed"),
    ("Backup", "Back up..."),
    ("Backup", "Restore..."),
    ("Backup", "Open data folder"),
)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_help_quotes_the_names_the_interface_shows(
    app_context: AppContext, language: str
) -> None:
    app_context.translator_manager.set_language(language)
    text = _help_text(language)
    for context, source in QUOTED_NAMES:
        shown = QCoreApplication.translate(context, source)
        assert f'"{shown}"' in text, (language, context, source, shown)
    assert f'"{banner_text(BannerCode.PRELIMINARY)}"' in text


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_help_titles_of_the_pages_are_the_navigation_titles(
    app_context: AppContext, language: str
) -> None:
    app_context.translator_manager.set_language(language)
    titles = {topic.key: topic.title for topic in parse_help(_help_text(language))}
    for spec in registry.pages():
        assert titles[spec.key] == spec.title(), (language, spec.key)


# --------------------------------------------------------------------------- the viewer


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_help_loads_in_each_language(
    app_context: AppContext, qtbot: QtBot, language: str
) -> None:
    app_context.translator_manager.set_language(language)
    dialog = HelpDialog(app_context)
    qtbot.addWidget(dialog)
    expected = parse_help(_help_text(language))
    assert dialog.loaded_language == language
    assert dialog.topics() == expected
    assert [text.strip() for text in _items(dialog.topic_list)] == [t.title for t in expected]
    assert dialog.current_topic_key() == "overview"
    assert expected[0].title in dialog.viewer.toPlainText()


def test_the_viewer_shows_every_topic_without_markers_links_or_images(
    app_context: AppContext, qtbot: QtBot
) -> None:
    for language in LANGUAGES:
        app_context.translator_manager.set_language(language)
        dialog = HelpDialog(app_context)
        qtbot.addWidget(dialog)
        for topic in dialog.topics():
            assert dialog.show_topic(topic.key)
            assert dialog.current_topic_key() == topic.key
            plain = dialog.viewer.toPlainText()
            assert topic.title in plain
            assert "topic:" not in plain
            html = dialog.viewer.toHtml()
            assert "href" not in html
            assert "<img" not in html
            assert "<a " not in html


def test_the_viewer_does_not_follow_links(app_context: AppContext, qtbot: QtBot) -> None:
    dialog = HelpDialog(app_context)
    qtbot.addWidget(dialog)
    assert not dialog.viewer.openLinks()
    assert not dialog.viewer.openExternalLinks()
    assert dialog.viewer.isReadOnly()


def test_the_help_follows_the_ui_language_and_keeps_the_topic(
    app_context: AppContext, qtbot: QtBot
) -> None:
    manager = app_context.translator_manager
    manager.set_language("en_US")
    dialog = HelpDialog(app_context)
    qtbot.addWidget(dialog)
    assert dialog.show_topic("budget")
    assert dialog.loaded_language == "en_US"
    for language in ("pt_BR", "es_ES", "en_US"):
        manager.set_language(language)
        assert dialog.loaded_language == language
        assert dialog.current_topic_key() == "budget"
        titles = [text.strip() for text in _items(dialog.topic_list)]
        assert titles == [t.title for t in load_topics(language)]
        assert dialog.viewer.toPlainText().startswith(
            next(t.title for t in load_topics(language) if t.key == "budget")
        )


def test_an_unknown_topic_changes_nothing(app_context: AppContext, qtbot: QtBot) -> None:
    dialog = HelpDialog(app_context)
    qtbot.addWidget(dialog)
    assert dialog.show_topic("alerts")
    assert not dialog.show_topic("no_such_topic")
    assert dialog.current_topic_key() == "alerts"


def test_a_broken_help_file_falls_back_to_english(
    app_context: AppContext, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = read_help_text

    def read(language: str) -> str | None:
        return "no topics here" if language == "pt_BR" else real(language)

    monkeypatch.setattr(f"{HELP_MODULE}.read_help_text", read)
    assert load_topics("pt_BR") == load_topics("en_US")
    assert load_topics("pt_BR")[0].key == "overview"
    app_context.translator_manager.set_language("pt_BR")
    dialog = HelpDialog(app_context)
    qtbot.addWidget(dialog)
    assert dialog.loaded_language == "pt_BR"
    assert dialog.topics() == load_topics("en_US")


def test_without_any_help_file_the_viewer_says_so(
    app_context: AppContext, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    def read(language: str) -> str | None:
        return None

    monkeypatch.setattr(f"{HELP_MODULE}.read_help_text", read)
    assert load_topics("en_US") == ()
    dialog = HelpDialog(app_context)
    qtbot.addWidget(dialog)
    assert dialog.topics() == ()
    assert dialog.current_topic_key() is None
    assert dialog.viewer.toPlainText() == "The help text could not be loaded."


# --------------------------------------------------------------------------- the About dialog


@pytest.fixture
def collect_licenses() -> Iterator[ModuleType]:
    """``scripts/collect_licenses.py`` loaded by path (``scripts/`` is not a package)."""
    path = ROOT / "scripts" / "collect_licenses.py"
    name = "cbrn_t10_2_collect_licenses"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(name, None)


def _write_index(collect_licenses: ModuleType, folder: Path) -> Path:
    """An ``index.json`` rendered by the real script from fictitious entries."""
    entries = [
        collect_licenses.LicenseEntry(
            "Example Library", "1.2.3", "MIT", "MIT", ("example-library/LICENSE",), ""
        ),
        collect_licenses.LicenseEntry(
            "Example Runtime",
            "as found in the bundle (built with CPython 3.12.0)",
            None,
            "LicenseRef-Example",
            ("NOTICE.md",),
            "A note.",
        ),
        collect_licenses.LicenseEntry(
            "Example Toolkit", "4.5", "A OR B", "Apache-2.0", ("Apache-2.0.txt",), ""
        ),
    ]
    path = folder / "index.json"
    path.write_text(collect_licenses.render_index_json(entries), encoding="utf-8")
    return path


def test_the_index_of_the_script_has_the_fields_the_dialog_reads(
    collect_licenses: ModuleType, tmp_path: Path
) -> None:
    data = json.loads(_write_index(collect_licenses, tmp_path).read_text(encoding="utf-8"))
    assert [item["component"] for item in data] == [
        "Example Library",
        "Example Runtime",
        "Example Toolkit",
    ]
    for item in data:
        assert isinstance(item["version"], str)
        assert isinstance(item["chosen"], str)


def test_the_index_is_read_in_file_order(collect_licenses: ModuleType, tmp_path: Path) -> None:
    components = read_licence_index(_write_index(collect_licenses, tmp_path))
    assert components == (
        Component("Example Library", "1.2.3", "MIT"),
        Component(
            "Example Runtime",
            "as found in the bundle (built with CPython 3.12.0)",
            "LicenseRef-Example",
        ),
        Component("Example Toolkit", "4.5", "Apache-2.0"),
    )
    assert component_line(components[0]) == "Example Library (1.2.3) - MIT"
    assert component_line(Component("Bare", "", "")) == "Bare"


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        "{}",
        '["text"]',
        '[{"component": "A", "version": "1"}]',
        '[{"component": "", "version": "1", "chosen": "MIT"}]',
        '[{"component": "A", "version": 1, "chosen": "MIT"}]',
    ],
)
def test_a_malformed_index_is_refused(tmp_path: Path, content: str) -> None:
    path = tmp_path / "index.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(LicenceIndexError):
        read_licence_index(path)
    with pytest.raises(LicenceIndexError):
        read_licence_index(tmp_path / "missing.json")


def test_the_index_is_looked_up_beside_the_frozen_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert licence_index_path() is None  # from source there is no built index
    folder = tmp_path / "licenses"
    folder.mkdir()
    index = folder / "index.json"
    index.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "cbrn-dashboard.exe"))
    assert licence_index_path() == index
    index.unlink()
    assert licence_index_path() is None


def test_the_about_dialog_shows_version_licence_notice_and_source(
    app_context: AppContext, qtbot: QtBot
) -> None:
    dialog = AboutDialog(app_context, locate_index=lambda: None)
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "About"
    assert dialog.name_label.text() == "CBRN Readiness Dashboard"
    assert dialog.version_label.text() == f"Version {__version__}"
    assert dialog.licence_label.text() == "Licence: GPL-3.0-or-later"
    assert "GNU General Public License" in dialog.gpl_label.text()
    assert "either version 3 of the License, or (at your option) any later" in (
        dialog.gpl_label.text()
    )
    assert dialog.warranty_label.text().startswith("This program comes with ABSOLUTELY NO WARRANTY")
    assert dialog.notice_label.text() == banner_text(BannerCode.PRELIMINARY)
    assert dialog.notice_label.text().startswith("Preliminary version")
    assert dialog.source_label.text() == SOURCE_URL
    assert SOURCE_URL == "https://github.com/marco-jardim/cbrn-readiness-dashboard"


def test_the_source_url_is_plain_selectable_text(app_context: AppContext, qtbot: QtBot) -> None:
    dialog = AboutDialog(app_context, locate_index=lambda: None)
    qtbot.addWidget(dialog)
    label = dialog.source_label
    assert label.textFormat() == Qt.TextFormat.PlainText
    flags = label.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse
    assert not flags & Qt.TextInteractionFlag.LinksAccessibleByMouse
    assert not label.openExternalLinks()
    assert "<a" not in label.text()


def test_without_an_index_the_dialog_invents_no_component(
    app_context: AppContext, qtbot: QtBot
) -> None:
    dialog = AboutDialog(app_context)  # from source: no built index
    qtbot.addWidget(dialog)
    assert dialog.components() == ()
    assert dialog.components_list.count() == 0
    assert dialog.components_list.isHidden()
    assert not dialog.components_status.isHidden()
    assert dialog.components_status.text() == (
        "The list of third-party components is not available in this build."
    )


@pytest.mark.parametrize("content", ["not json", "[]", '[{"component": "A"}]'])
def test_an_unusable_index_is_reported_and_lists_nothing(
    app_context: AppContext, qtbot: QtBot, tmp_path: Path, content: str
) -> None:
    path = tmp_path / "index.json"
    path.write_text(content, encoding="utf-8")
    dialog = AboutDialog(app_context, locate_index=lambda: path)
    qtbot.addWidget(dialog)
    assert dialog.components() == ()
    assert dialog.components_list.count() == 0
    assert dialog.components_status.text() == (
        "The list of third-party components could not be read."
    )


def test_the_dialog_shows_one_line_per_component_of_the_index(
    app_context: AppContext, qtbot: QtBot, tmp_path: Path, collect_licenses: ModuleType
) -> None:
    path = _write_index(collect_licenses, tmp_path)
    dialog = AboutDialog(app_context, locate_index=lambda: path)
    qtbot.addWidget(dialog)
    assert _items(dialog.components_list) == [
        "Example Library (1.2.3) - MIT",
        "Example Runtime (as found in the bundle (built with CPython 3.12.0)) - LicenseRef-Example",
        "Example Toolkit (4.5) - Apache-2.0",
    ]
    assert dialog.components_list.count() == len(json.loads(path.read_text(encoding="utf-8")))
    assert not dialog.components_list.isHidden()
    assert dialog.components_status.isHidden()


def test_the_about_text_follows_the_language(app_context: AppContext, qtbot: QtBot) -> None:
    dialog = AboutDialog(app_context, locate_index=lambda: None)
    qtbot.addWidget(dialog)
    manager = app_context.translator_manager
    for language in ("pt_BR", "es_ES", "en_US"):
        manager.set_language(language)
        assert dialog.windowTitle() == QCoreApplication.translate("Shell", "About")
        assert dialog.version_label.text() == (
            QCoreApplication.translate("Shell", "Version %1").replace("%1", __version__)
        )
        assert dialog.notice_label.text() == banner_text(BannerCode.PRELIMINARY)
        assert __version__ in dialog.version_label.text()


# --------------------------------------------------------------------------- no service, no prompt


def test_both_dialogs_build_without_services_and_without_prompting(
    app_context: AppContext, qtbot: QtBot, tmp_path: Path
) -> None:
    prompts = FakePrompts()
    bare = AppContext(
        conn=None,
        clock=FixedClock.at(NOW),
        location=app_context.location,
        prompts=prompts,
        preferences=PreferencesStore(tmp_path, writable=False),
        translator_manager=app_context.translator_manager,
    )
    assert bare.services.personnel is None
    for key in ("shell.help", "shell.about"):
        spec = next(spec for spec in registry.dialogs() if spec.key == key)
        dialog = spec.factory(bare, None)
        qtbot.addWidget(dialog)
    assert prompts.calls == []


def test_both_dialogs_are_registered_for_the_generic_walks() -> None:
    keys = [spec.key for spec in registry.dialogs()]
    assert "shell.help" in keys
    assert "shell.about" in keys


# --------------------------------------------------------------------------- the Help menu


def _window(qtbot: QtBot, context: AppContext) -> MainWindow:
    window = MainWindow(context)
    qtbot.addWidget(window)
    return window


def test_the_help_menu_holds_the_help_and_about_actions(
    app_context: AppContext, qtbot: QtBot
) -> None:
    window = _window(qtbot, app_context)
    assert window.help_menu.objectName() == "menu_help"
    assert window.help_menu.title() == "&Help"
    entries = window.help_menu.actions()
    assert [entry.objectName() for entry in entries] == ["action_help", "action_about"]
    assert [entry.text() for entry in entries] == ["Help &contents", "&About"]
    assert entries[0] is window.help_action
    assert entries[1] is window.about_action
    assert window.help_action.shortcuts()
    assert window.help_dialog is None  # built on the first request
    assert window.about_dialog is None


def test_the_about_action_opens_one_non_modal_dialog(app_context: AppContext, qtbot: QtBot) -> None:
    window = _window(qtbot, app_context)
    window.about_action.trigger()
    dialog = window.about_dialog
    assert isinstance(dialog, AboutDialog)
    assert dialog.isVisible()
    assert not dialog.isModal()
    assert dialog.parent() is window
    window.about_action.trigger()
    assert window.about_dialog is dialog


def test_the_help_action_opens_the_topic_of_the_page_shown(
    app_context: AppContext, qtbot: QtBot
) -> None:
    window = _window(qtbot, app_context)
    window.show_page("budget")
    window.help_action.trigger()
    dialog = window.help_dialog
    assert isinstance(dialog, HelpDialog)
    assert dialog.isVisible()
    assert not dialog.isModal()
    assert dialog.parent() is window
    assert dialog.current_topic_key() == "budget"
    window.show_page("alerts")
    window.help_action.trigger()
    assert window.help_dialog is dialog
    assert dialog.current_topic_key() == "alerts"


def test_every_page_opens_its_own_help_topic(app_context: AppContext, qtbot: QtBot) -> None:
    window = _window(qtbot, app_context)
    for key in window.page_keys():
        window.show_page(key)
        assert window.current_page_key() == key
        window.help_action.trigger()
        assert window.help_dialog is not None
        assert window.help_dialog.current_topic_key() == key


def test_a_page_without_a_topic_leaves_the_help_where_it_was(
    app_context: AppContext, qtbot: QtBot
) -> None:
    def title() -> str:
        return "A new page"

    def create(_context: AppContext) -> QWidget:
        return QWidget()

    with registry.registered(PageSpec("brand_new_page", 95, title, create)):
        window = _window(qtbot, app_context)
        window.show_page("alerts")
        window.help_action.trigger()
        window.show_page("brand_new_page")
        window.help_action.trigger()
    assert window.help_dialog is not None
    assert window.help_dialog.current_topic_key() == "alerts"


def test_the_window_help_follows_the_language_switch(app_context: AppContext, qtbot: QtBot) -> None:
    window = _window(qtbot, app_context)
    window.show_page("personnel")
    dialog = window.show_help("personnel")
    window.language_actions["pt_BR"].trigger()
    assert dialog.loaded_language == "pt_BR"
    assert dialog.current_topic_key() == "personnel"
    assert window.help_menu.title() == QCoreApplication.translate("Shell", "&Help")


# --------------------------------------------------------------------------- the pseudo-locale walk
# These tests need the new Shell strings in the catalogues (lupdate), like every pseudo-locale walk.


def test_the_pseudo_locale_walk_passes_on_both_dialogs(
    started_app: StartApp, pseudo_qm_dir: Path, qtbot: QtBot, tmp_path: Path
) -> None:
    handle = expect_handle(started_app(qm=pseudo_qm_dir, lang="pt-BR"))
    window = handle.window
    help_dialog = window.show_help()
    about = window.show_about()
    assert_fully_translated(window, "pt_BR")  # includes the Help menu
    assert_fully_translated(help_dialog, "pt_BR")
    assert_fully_translated(about, "pt_BR")
    texts = {item.text for item in collect_texts(about)}
    assert {
        _t("About"),
        _t("Source code:"),
        _t("Third-party components"),
        _t("Licence: GPL-3.0-or-later"),
        _t(f"Version {__version__}"),
        _t("The list of third-party components is not available in this build."),
    } <= texts
    assert not any(SOURCE_URL in text for text in texts)  # the URL is data, not a translation
    help_texts = {item.text for item in collect_texts(help_dialog)}
    assert {_t("Help"), _t("Help topics"), _t("Help text")} <= help_texts


def test_the_walk_passes_on_the_about_dialog_with_an_index_and_after_each_switch(
    started_app: StartApp,
    pseudo_qm_dir: Path,
    qtbot: QtBot,
    tmp_path: Path,
    collect_licenses: ModuleType,
) -> None:
    handle = expect_handle(started_app(qm=pseudo_qm_dir, lang="pt-BR"))
    path = _write_index(collect_licenses, tmp_path)
    about = AboutDialog(handle.context, handle.window, locate_index=lambda: path)
    help_dialog = handle.window.show_help()
    assert about.components_list.count() == 3
    for language in ("pt_BR", "es_ES", "en_US", "pt_BR"):
        handle.window.language_actions[language].trigger()
        assert_fully_translated(about, language)
        assert_fully_translated(help_dialog, language)
        assert_fully_translated(handle.window, language)
        assert help_dialog.loaded_language == language
        assert about.components_list.count() == 3


def test_there_is_one_help_file_per_supported_language() -> None:
    assert set(i18n.LANGUAGES) == set(LANGUAGES)
    assert {path.stem for path in HELP_DIR.glob("*.md")} == set(i18n.LANGUAGES)
