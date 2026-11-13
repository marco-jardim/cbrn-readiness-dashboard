# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of ``scripts/terminology_sheet.py`` (PLAN.md Q14): offline, files in ``tmp_path``."""

import csv
import hashlib
import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "terminology_sheet.py"

HEADER = '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE TS>\n'

PT_TS = (
    HEADER
    + """<TS version="2.1" language="pt_BR" sourcelanguage="en_US">
<context>
    <name>Demo</name>
    <message>
        <source>Readiness</source>
        <extracomment>The headline of the dashboard.</extracomment>
        <translation type="unfinished">Prontid\u00e3o</translation>
    </message>
    <message>
        <source>Open %1</source>
        <comment>menu</comment>
        <translation type="unfinished">Abrir %1</translation>
    </message>
    <message>
        <source>Open %1</source>
        <comment>button</comment>
        <translation type="unfinished">Abrir %1 agora</translation>
    </message>
    <message numerus="yes">
        <source>%n day(s) left</source>
        <translation type="unfinished">
            <numerusform>%n dia restante</numerusform>
            <numerusform>%n dias restantes</numerusform>
        </translation>
    </message>
    <message>
        <source>Master&apos;s &quot;degree&quot; &amp; more</source>
        <translation type="unfinished">Mestrado</translation>
    </message>
    <message>
        <source>Bay</source>
        <translation>Baia</translation>
    </message>
    <message>
        <source>Gone</source>
        <translation type="obsolete">Sumiu</translation>
    </message>
</context>
<context>
    <name>Other</name>
    <message>
        <source>Recycling</source>
        <translation type="unfinished"></translation>
    </message>
</context>
</TS>
"""
)

ES_TS = (
    HEADER
    + """<TS version="2.1" language="es_ES" sourcelanguage="en_US">
<context>
    <name>Demo</name>
    <message>
        <source>Readiness</source>
        <extracomment>The headline of the dashboard.</extracomment>
        <translation type="unfinished">Preparaci\u00f3n</translation>
    </message>
    <message>
        <source>Open %1</source>
        <comment>menu</comment>
        <translation type="unfinished">Abrir %1</translation>
    </message>
    <message>
        <source>Open %1</source>
        <comment>button</comment>
        <translation type="unfinished">Abrir %1 ahora</translation>
    </message>
    <message numerus="yes">
        <source>%n day(s) left</source>
        <translation type="unfinished">
            <numerusform>queda %n d\u00eda</numerusform>
            <numerusform>quedan %n d\u00edas</numerusform>
        </translation>
    </message>
    <message>
        <source>Master&apos;s &quot;degree&quot; &amp; more</source>
        <translation type="unfinished">M\u00e1ster</translation>
    </message>
    <message>
        <source>Bay</source>
        <translation>Bah\u00eda</translation>
    </message>
</context>
<context>
    <name>Other</name>
    <message>
        <source>Recycling</source>
        <translation type="unfinished">Reciclaje</translation>
    </message>
</context>
</TS>
"""
)

PT_NAME = "demo_pt_BR.ts"
ES_NAME = "demo_es_ES.ts"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    name = "cbrn_terminology_sheet_test_script"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ts_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "i18n"
    folder.mkdir()
    (folder / PT_NAME).write_bytes(PT_TS.encode("utf-8"))
    (folder / ES_NAME).write_bytes(ES_TS.encode("utf-8"))
    return folder


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def _by_english(rows: list[dict[str, str]], english: str, comment: str = "") -> dict[str, str]:
    (row,) = [r for r in rows if r["english"] == english and r["comment"] == comment]
    return row


Rows = list[dict[str, str]]


def _exported(script: ModuleType, ts_dir: Path, tmp_path: Path) -> tuple[Path, Rows]:
    out = tmp_path / "sheet.csv"
    script.export_sheet(ts_dir, out)
    return out, _rows(out)


def _save(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def _translations(path: Path) -> dict[tuple[str, str, str], tuple[str, tuple[str, ...]]]:
    """``(context, source, comment) -> (type, forms)`` of a catalogue."""
    found: dict[tuple[str, str, str], tuple[str, tuple[str, ...]]] = {}
    for context in ET.parse(path).getroot().findall("context"):
        name = context.findtext("name") or ""
        for message in context.findall("message"):
            translation = message.find("translation")
            assert translation is not None
            forms = tuple(f.text or "" for f in translation.findall("numerusform"))
            if not forms:
                forms = (translation.text or "",)
            key = (name, message.findtext("source") or "", message.findtext("comment") or "")
            found[key] = (translation.get("type", ""), forms)
    return found


# --- export ------------------------------------------------------------------------------------


def test_export_writes_utf8_bom_and_semicolons(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    out, rows = _exported(script, ts_dir, tmp_path)
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    header_line = raw.decode("utf-8-sig").splitlines()[0]
    assert header_line == ";".join(script.COLUMNS)
    assert list(rows[0]) == list(script.COLUMNS)
    assert "Prontid\u00e3o" in raw.decode("utf-8")


def test_export_has_one_row_per_live_message_sorted(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    _, rows = _exported(script, ts_dir, tmp_path)
    assert [(r["context"], r["english"], r["comment"]) for r in rows] == [
        ("Demo", "%n day(s) left", ""),
        ("Demo", "Bay", ""),
        ("Demo", 'Master\'s "degree" & more', ""),
        ("Demo", "Open %1", "button"),
        ("Demo", "Open %1", "menu"),
        ("Demo", "Readiness", ""),
        ("Other", "Recycling", ""),
    ]
    assert {r["area"] for r in rows} == {"demo"}


def test_export_fields(script: ModuleType, ts_dir: Path, tmp_path: Path) -> None:
    _, rows = _exported(script, ts_dir, tmp_path)
    readiness = _by_english(rows, "Readiness")
    assert readiness["note"] == "The headline of the dashboard."
    assert readiness["pt_BR_atual"] == "Prontid\u00e3o"
    assert readiness["es_ES_atual"] == "Preparaci\u00f3n"
    assert readiness["pt_BR_revisado"] == readiness["es_ES_revisado"] == ""
    assert readiness["estado"] == "pendente"
    assert _by_english(rows, "Bay")["estado"] == "revisado"
    assert _by_english(rows, "Recycling")["pt_BR_atual"] == ""
    assert _by_english(rows, "Recycling")["estado"] == "pendente"
    assert _by_english(rows, "Open %1", "menu")["pt_BR_atual"] == "Abrir %1"


def test_export_joins_numerus_forms(script: ModuleType, ts_dir: Path, tmp_path: Path) -> None:
    _, rows = _exported(script, ts_dir, tmp_path)
    row = _by_english(rows, "%n day(s) left")
    assert row["pt_BR_atual"] == "%n dia restante | %n dias restantes"
    assert row["es_ES_atual"] == "queda %n d\u00eda | quedan %n d\u00edas"


def test_ids_are_stable_hashes_of_area_context_source_comment(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    _, rows = _exported(script, ts_dir, tmp_path)
    row = _by_english(rows, "Open %1", "menu")
    digest = hashlib.sha256(b"demo|Demo|Open %1|menu").hexdigest()
    assert row["id"] == "m" + digest[:12]
    assert len({r["id"] for r in rows}) == len(rows)
    _, again = _exported(script, ts_dir, tmp_path / "second")
    assert [r["id"] for r in again] == [r["id"] for r in rows]


def test_export_does_not_touch_the_catalogues(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    _exported(script, ts_dir, tmp_path)
    assert (ts_dir / PT_NAME).read_bytes() == PT_TS.encode("utf-8")


def test_real_catalogues_export_with_unique_ids(script: ModuleType, tmp_path: Path) -> None:
    out = tmp_path / "real.csv"
    count = script.export_sheet(script.DEFAULT_TS_DIR, out)
    rows = _rows(out)
    assert count == len(rows) > 100
    assert len({r["id"] for r in rows}) == count


# --- import ------------------------------------------------------------------------------------


def test_import_without_reviewed_cells_changes_nothing(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    out, _ = _exported(script, ts_dir, tmp_path)
    report = script.import_sheet(out, ts_dir)
    assert (report.applied, report.skipped, report.files_changed) == (0, [], [])
    assert (ts_dir / PT_NAME).read_bytes() == PT_TS.encode("utf-8")


def test_round_trip_updates_plain_comment_and_numerus_messages(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    out, rows = _exported(script, ts_dir, tmp_path)
    _by_english(rows, "Readiness")["pt_BR_revisado"] = "Prontid\u00e3o operacional"
    _by_english(rows, "Open %1", "menu")["pt_BR_revisado"] = "Abrir %1"  # same text: unchanged
    _by_english(rows, "Open %1", "button")["es_ES_revisado"] = "Abrir %1 ya"
    numerus = _by_english(rows, "%n day(s) left")
    numerus["pt_BR_revisado"] = "falta %n dia | faltam %n dias"
    numerus["es_ES_revisado"] = "queda %n d\u00eda | quedan %n d\u00edas"  # same text
    _by_english(rows, 'Master\'s "degree" & more')["pt_BR_revisado"] = 'Mestrado "stricto" & co.'
    _save(out, rows)

    report = script.import_sheet(out, ts_dir)

    assert report.skipped == []
    assert report.applied == 4
    assert report.unchanged == 2
    assert [p.name for p in report.files_changed] == [ES_NAME, PT_NAME]
    pt = _translations(ts_dir / PT_NAME)
    assert pt[("Demo", "Readiness", "")] == ("unfinished", ("Prontid\u00e3o operacional",))
    assert pt[("Demo", "Open %1", "menu")] == ("unfinished", ("Abrir %1",))
    assert pt[("Demo", "Open %1", "button")] == ("unfinished", ("Abrir %1 agora",))
    assert pt[("Demo", "%n day(s) left", "")] == (
        "unfinished",
        ("falta %n dia", "faltam %n dias"),
    )
    assert pt[("Demo", 'Master\'s "degree" & more', "")][1] == ('Mestrado "stricto" & co.',)
    es = _translations(ts_dir / ES_NAME)
    assert es[("Demo", "Open %1", "button")] == ("unfinished", ("Abrir %1 ya",))
    assert es[("Demo", "Readiness", "")] == ("unfinished", ("Preparaci\u00f3n",))


def test_import_keeps_the_layout_of_the_file(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    out, rows = _exported(script, ts_dir, tmp_path)
    _by_english(rows, "Readiness")["pt_BR_revisado"] = "Prontid\u00e3o operacional"
    _by_english(rows, "%n day(s) left")["pt_BR_revisado"] = "falta %n dia | faltam %n dias"
    _by_english(rows, 'Master\'s "degree" & more')["pt_BR_revisado"] = 'Mestre\'s "x" & y <z>'
    _save(out, rows)
    script.import_sheet(out, ts_dir)
    expected = (
        PT_TS.replace(
            '<translation type="unfinished">Prontid\u00e3o</translation>',
            '<translation type="unfinished">Prontid\u00e3o operacional</translation>',
        )
        .replace("%n dia restante", "falta %n dia")
        .replace("%n dias restantes", "faltam %n dias")
        .replace(
            '<translation type="unfinished">Mestrado</translation>',
            '<translation type="unfinished">Mestre&apos;s &quot;x&quot; &amp; y &lt;z&gt;'
            "</translation>",
        )
    )
    assert (ts_dir / PT_NAME).read_bytes().decode("utf-8") == expected
    assert (ts_dir / ES_NAME).read_bytes() == ES_TS.encode("utf-8")


def test_import_keeps_crlf_line_endings(script: ModuleType, ts_dir: Path, tmp_path: Path) -> None:
    pt = ts_dir / PT_NAME
    pt.write_bytes(PT_TS.replace("\n", "\r\n").encode("utf-8"))
    out, rows = _exported(script, ts_dir, tmp_path)
    _by_english(rows, "%n day(s) left")["pt_BR_revisado"] = "falta %n dia | faltam %n dias"
    _save(out, rows)
    script.import_sheet(out, ts_dir)
    text = pt.read_bytes().decode("utf-8")
    assert "\n" not in text.replace("\r\n", "")
    assert "            <numerusform>falta %n dia</numerusform>\r\n" in text


def test_mark_finished_clears_unfinished_only_for_reviewed_translations(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    out, rows = _exported(script, ts_dir, tmp_path)
    _by_english(rows, "Readiness")["pt_BR_revisado"] = "Prontid\u00e3o"  # agrees: copied
    _by_english(rows, "%n day(s) left")["pt_BR_revisado"] = "%n dia | %n dias"
    _by_english(rows, "Recycling")["es_ES_revisado"] = "Reciclaje"
    _save(out, rows)

    report = script.import_sheet(out, ts_dir, mark_finished=True)

    assert report.skipped == []
    assert report.applied == 3
    pt = _translations(ts_dir / PT_NAME)
    assert pt[("Demo", "Readiness", "")] == ("", ("Prontid\u00e3o",))
    assert pt[("Demo", "%n day(s) left", "")] == ("", ("%n dia", "%n dias"))
    assert pt[("Demo", "Open %1", "menu")][0] == "unfinished"
    assert pt[("Other", "Recycling", "")][0] == "unfinished"
    es = _translations(ts_dir / ES_NAME)
    assert es[("Other", "Recycling", "")] == ("", ("Reciclaje",))
    assert es[("Demo", "Readiness", "")][0] == "unfinished"


def test_without_mark_finished_the_type_stays(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    out, rows = _exported(script, ts_dir, tmp_path)
    _by_english(rows, "Readiness")["pt_BR_revisado"] = "Prontid\u00e3o"
    _save(out, rows)
    report = script.import_sheet(out, ts_dir)
    assert (report.applied, report.unchanged) == (0, 1)
    assert (ts_dir / PT_NAME).read_bytes() == PT_TS.encode("utf-8")


def test_placeholder_mismatch_is_rejected_with_the_row_id(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    out, rows = _exported(script, ts_dir, tmp_path)
    bad = _by_english(rows, "Open %1", "menu")
    bad["pt_BR_revisado"] = "Abrir"  # %1 lost
    wrong = _by_english(rows, "Open %1", "button")
    wrong["es_ES_revisado"] = "Abrir %2"  # %2 instead of %1
    good = _by_english(rows, "Readiness")
    good["pt_BR_revisado"] = "Prontid\u00e3o operacional"
    _save(out, rows)

    report = script.import_sheet(out, ts_dir, mark_finished=True)

    assert report.applied == 1
    assert len(report.skipped) == 2
    assert any(bad["id"] in item and "placeholders" in item for item in report.skipped)
    assert any(wrong["id"] in item and "placeholders" in item for item in report.skipped)
    pt = _translations(ts_dir / PT_NAME)
    assert pt[("Demo", "Open %1", "menu")] == ("unfinished", ("Abrir %1",))
    assert pt[("Demo", "Readiness", "")] == ("", ("Prontid\u00e3o operacional",))
    assert [p.name for p in report.files_changed] == [PT_NAME]


def test_numerus_row_needs_exactly_two_forms(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    out, rows = _exported(script, ts_dir, tmp_path)
    row = _by_english(rows, "%n day(s) left")
    row["pt_BR_revisado"] = "%n dias"
    row["es_ES_revisado"] = "%n a | %n b | %n c"
    _save(out, rows)
    report = script.import_sheet(out, ts_dir)
    assert report.applied == 0
    assert len(report.skipped) == 2
    assert all(row["id"] in item and "2 forms" in item for item in report.skipped)
    assert (ts_dir / PT_NAME).read_bytes() == PT_TS.encode("utf-8")


def test_numerus_placeholder_must_be_known(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    out, rows = _exported(script, ts_dir, tmp_path)
    _by_english(rows, "%n day(s) left")["pt_BR_revisado"] = "um dia | %n dias %1"
    _save(out, rows)
    report = script.import_sheet(out, ts_dir)
    assert report.applied == 0
    assert len(report.skipped) == 1


def test_numerus_singular_may_omit_the_count(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    out, rows = _exported(script, ts_dir, tmp_path)
    _by_english(rows, "%n day(s) left")["pt_BR_revisado"] = "falta um dia | faltam %n dias"
    _save(out, rows)
    report = script.import_sheet(out, ts_dir)
    assert report.skipped == []
    assert report.applied == 1


def test_unknown_id_and_edited_english_are_rejected(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    out, rows = _exported(script, ts_dir, tmp_path)
    unknown = dict(_by_english(rows, "Bay"), id="m000000000000", pt_BR_revisado="Baia nova")
    edited = _by_english(rows, "Readiness")
    edited["english"] = "Readiness!"
    edited["pt_BR_revisado"] = "Prontid\u00e3o operacional"
    rows.append(unknown)
    _save(out, rows)
    report = script.import_sheet(out, ts_dir)
    assert report.applied == 0
    assert any("m000000000000" in item and "unknown id" in item for item in report.skipped)
    assert any(edited["id"] in item and "english" in item for item in report.skipped)
    assert (ts_dir / PT_NAME).read_bytes() == PT_TS.encode("utf-8")


def test_a_second_row_for_the_same_message_is_skipped(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    out, rows = _exported(script, ts_dir, tmp_path)
    first = _by_english(rows, "Readiness")
    first["pt_BR_revisado"] = "Um"
    rows.append(dict(first, pt_BR_revisado="Dois"))
    _save(out, rows)
    report = script.import_sheet(out, ts_dir)
    assert report.applied == 1
    assert len(report.skipped) == 1
    assert _translations(ts_dir / PT_NAME)[("Demo", "Readiness", "")][1] == ("Um",)


def test_import_reads_a_comma_file_without_bom(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    _, rows = _exported(script, ts_dir, tmp_path)
    target = _by_english(rows, "Readiness")
    target["pt_BR_revisado"] = "Prontid\u00e3o operacional"
    out = tmp_path / "comma.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = script.import_sheet(out, ts_dir)
    assert report.applied == 1
    assert _translations(ts_dir / PT_NAME)[("Demo", "Readiness", "")][1] == (
        "Prontid\u00e3o operacional",
    )


def test_import_reads_a_windows_1252_file_and_says_so(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    out, rows = _exported(script, ts_dir, tmp_path)
    _by_english(rows, "Readiness")["pt_BR_revisado"] = "Prontid\u00e3o operacional"
    _save(out, rows)
    text = out.read_bytes().decode("utf-8-sig")
    out.write_bytes(text.encode("cp1252"))
    report = script.import_sheet(out, ts_dir)
    assert report.applied == 1
    assert any("Windows-1252" in note for note in report.notes)
    assert _translations(ts_dir / PT_NAME)[("Demo", "Readiness", "")][1] == (
        "Prontid\u00e3o operacional",
    )


def test_a_file_that_is_not_a_review_sheet_is_refused(
    script: ModuleType, ts_dir: Path, tmp_path: Path
) -> None:
    bogus = tmp_path / "bogus.csv"
    bogus.write_text("a;b\n1;2\n", encoding="utf-8")
    with pytest.raises(script.SheetError):
        script.import_sheet(bogus, ts_dir)


# --- command line ------------------------------------------------------------------------------


def test_command_line_round_trip(
    script: ModuleType, ts_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "cli.csv"
    assert script.main(["export", "--out", str(out), "--ts-dir", str(ts_dir)]) == 0
    assert "wrote 7 rows" in capsys.readouterr().out
    rows = _rows(out)
    _by_english(rows, "Readiness")["pt_BR_revisado"] = "Prontid\u00e3o operacional"
    _by_english(rows, "Open %1", "menu")["pt_BR_revisado"] = "Abrir"
    _save(out, rows)
    args = ["import", "--csv", str(out), "--ts-dir", str(ts_dir), "--mark-finished"]
    assert script.main(args) == 0
    printed = capsys.readouterr().out
    assert "applied 1, unchanged 0, skipped 1, files changed 1" in printed
    assert "changed demo_pt_BR.ts" in printed
    assert _translations(ts_dir / PT_NAME)[("Demo", "Readiness", "")][0] == ""


def test_command_line_reports_a_missing_folder(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    code = script.main(["export", "--out", str(tmp_path / "x.csv"), "--ts-dir", str(empty)])
    assert code == 1
    assert "No catalogue found" in capsys.readouterr().err
