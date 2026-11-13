# SPDX-License-Identifier: GPL-3.0-or-later
"""Terminology review sheet for the translation catalogues (PLAN.md Q14).

``python scripts/terminology_sheet.py export --out sheet.csv``
    Write one CSV with a row per message of the ``<area>_<lang>.ts`` catalogues, for the committee
    to review in a spreadsheet. The file is UTF-8 with a byte order mark (so that Excel shows the
    accents correctly) and uses ';' as the separator.
``python scripts/terminology_sheet.py import --csv sheet.csv [--mark-finished]``
    Write the reviewed texts (the non-empty ``pt_BR_revisado`` / ``es_ES_revisado`` cells) back
    into the catalogues, and print what was applied and what was skipped.

Columns of the sheet: ``id``, ``area``, ``context``, ``english``, ``comment``, ``note``,
``estado``, ``pt_BR_atual``, ``es_ES_atual``, ``pt_BR_revisado``, ``es_ES_revisado`` and
``observacoes``.

* ``id`` is the stable key of a message: ``m`` followed by the first 12 hex digits of the SHA-256
  of ``area|context|source|comment`` (UTF-8). The letter keeps Excel from reading an id such as
  ``0123456789e1`` as a number. The same message has the same id on every export.
* ``comment`` is the disambiguation comment of the message and ``note`` the translator note
  (``<extracomment>``); both may be empty.
* ``estado`` is ``pendente`` while a translation is still ``type="unfinished"``, else ``revisado``.
* A plural (``numerus``) message shows its forms joined with `` | `` (singular | plural), and the
  same format is expected back.

The import changes only the ``<translation>`` element of the matched ``<message>``, in place (text
replacement, not a re-serialised XML), so that the rest of the file stays byte-identical. Run
``python scripts/i18n.py update`` afterwards, as usual.

The functions are importable (tests load this file by path, since ``scripts/`` is not a package).
Only the standard library is used.
"""

import argparse
import csv
import hashlib
import io
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax import saxutils

LANGUAGES: tuple[str, ...] = ("pt_BR", "es_ES")
DEFAULT_TS_DIR = Path(__file__).resolve().parent.parent / "src" / "cbrn_dashboard" / "i18n"

CSV_ENCODING = "utf-8-sig"
CSV_DELIMITER = ";"
FALLBACK_ENCODING = "cp1252"
FORM_SEPARATOR = " | "
ID_PREFIX = "m"
ID_DIGITS = 12

STATE_PENDING = "pendente"
STATE_REVIEWED = "revisado"

COLUMNS: tuple[str, ...] = (
    "id",
    "area",
    "context",
    "english",
    "comment",
    "note",
    "estado",
    "pt_BR_atual",
    "es_ES_atual",
    "pt_BR_revisado",
    "es_ES_revisado",
    "observacoes",
)

PLACEHOLDER_RE = re.compile(r"%(?:L?[1-9]|n)")
PLURAL_PLACEHOLDER = "%n"
SKIPPED_STATUSES = frozenset({"obsolete", "vanished"})

_CONTEXT_RE = re.compile(r"<context>(.*?)</context>", re.DOTALL)
_NAME_RE = re.compile(r"<name>.*?</name>", re.DOTALL)
_MESSAGE_RE = re.compile(r"<message\b[^>]*>.*?</message>", re.DOTALL)
_TRANSLATION_RE = re.compile(
    r"(?P<indent>[ \t]*)"
    r"(?P<elem><translation(?P<attrs>[^>]*?)(?:/>|>(?P<inner>.*?)</translation>))",
    re.DOTALL,
)
_UNFINISHED_RE = re.compile(r'\s+type="unfinished"')


class SheetError(RuntimeError):
    """The catalogues or the CSV cannot be read, or the CSV is not a review sheet."""


@dataclass(frozen=True)
class Message:
    """One ``<message>`` of a catalogue, with the place of its ``<translation>`` element."""

    area: str
    context: str
    source: str
    comment: str
    extracomment: str
    numerus: bool
    forms: tuple[str, ...]
    status: str
    element_start: int
    element_end: int
    indent: str
    attrs: str

    @property
    def id(self) -> str:
        return message_id(self.area, self.context, self.source, self.comment)

    @property
    def text(self) -> str:
        """The translation as shown in the sheet (numerus forms joined with `` | ``)."""
        if self.numerus:
            return FORM_SEPARATOR.join(self.forms)
        return self.forms[0] if self.forms else ""


@dataclass(frozen=True)
class Catalogue:
    """The text of one ``.ts`` file and its messages."""

    path: Path
    area: str
    language: str
    text: str
    messages: tuple[Message, ...]


@dataclass
class ImportReport:
    """What :func:`import_sheet` did."""

    applied: int = 0
    unchanged: int = 0
    skipped: list[str] = field(default_factory=list)
    files_changed: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def message_id(area: str, context: str, source: str, comment: str) -> str:
    """Return the stable key of a message (see the module docstring)."""
    key = "|".join((area, context, source, comment))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return ID_PREFIX + digest[:ID_DIGITS]


def _xml_text(element: ET.Element, tag: str) -> str:
    return element.findtext(tag) or ""


def _parse_message(area: str, context: str, text: str, offset: int) -> Message | None:
    try:
        element = ET.fromstring(text)
    except ET.ParseError as error:
        raise SheetError(f"Invalid XML in a message of area {area!r}: {error}") from error
    translation = element.find("translation")
    found = _TRANSLATION_RE.search(text)
    if translation is None or found is None:
        return None
    numerus = element.get("numerus") == "yes"
    if numerus:
        forms = tuple(form.text or "" for form in translation.findall("numerusform"))
    else:
        forms = (translation.text or "",)
    return Message(
        area=area,
        context=context,
        source=_xml_text(element, "source"),
        comment=_xml_text(element, "comment"),
        extracomment=_xml_text(element, "extracomment"),
        numerus=numerus,
        forms=forms,
        status=translation.get("type", ""),
        element_start=offset + found.start("elem"),
        element_end=offset + found.end("elem"),
        indent=found.group("indent"),
        attrs=found.group("attrs"),
    )


def parse_catalogue(path: Path, area: str, language: str) -> Catalogue:
    """Read one ``.ts`` file; obsolete and vanished messages are left out."""
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SheetError(f"Cannot read {path}: {error}") from error
    messages: list[Message] = []
    for block in _CONTEXT_RE.finditer(text):
        body = block.group(1)
        name_match = _NAME_RE.search(body)
        if name_match is None:
            raise SheetError(f"A context of {path.name} has no <name>")
        context = ET.fromstring(name_match.group(0)).text or ""
        for found in _MESSAGE_RE.finditer(body):
            offset = block.start(1) + found.start()
            message = _parse_message(area, context, found.group(0), offset)
            if message is not None and message.status not in SKIPPED_STATUSES:
                messages.append(message)
    return Catalogue(path, area, language, text, tuple(messages))


def load_catalogues(ts_dir: Path) -> dict[tuple[str, str], Catalogue]:
    """Read every ``<area>_<lang>.ts`` of ``ts_dir`` for the reviewed languages."""
    catalogues: dict[tuple[str, str], Catalogue] = {}
    for language in LANGUAGES:
        suffix = f"_{language}.ts"
        for path in sorted(ts_dir.glob(f"*{suffix}")):
            area = path.name[: -len(suffix)]
            catalogues[(area, language)] = parse_catalogue(path, area, language)
    if not catalogues:
        raise SheetError(f"No catalogue found in {ts_dir}")
    return catalogues


def _index(catalogues: Mapping[tuple[str, str], Catalogue]) -> dict[str, dict[str, Message]]:
    """Messages by id, then by language."""
    index: dict[str, dict[str, Message]] = {}
    for (_area, language), catalogue in catalogues.items():
        for message in catalogue.messages:
            index.setdefault(message.id, {})[language] = message
    return index


def build_rows(ts_dir: Path) -> list[dict[str, str]]:
    """Return the rows of the sheet, sorted by area, context and English text."""
    rows: list[dict[str, str]] = []
    for versions in _index(load_catalogues(ts_dir)).values():
        base = versions.get("pt_BR") or versions["es_ES"]
        pending = any(
            message.status == "unfinished" or not message.text.strip()
            for message in versions.values()
        )
        row = dict.fromkeys(COLUMNS, "")
        row.update(
            id=base.id,
            area=base.area,
            context=base.context,
            english=base.source,
            comment=base.comment,
            note=base.extracomment,
            estado=STATE_PENDING if pending else STATE_REVIEWED,
        )
        for language in LANGUAGES:
            message = versions.get(language)
            row[f"{language}_atual"] = "" if message is None else message.text
        rows.append(row)
    rows.sort(key=lambda row: (row["area"], row["context"], row["english"], row["comment"]))
    return rows


def write_sheet(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    """Write the sheet: UTF-8 with BOM, ';' separator, fields quoted when needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=CSV_ENCODING, newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(COLUMNS),
            delimiter=CSV_DELIMITER,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\r\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def read_sheet(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Read a sheet; return ``(rows, notes)``.

    The BOM is optional and the separator is ';' or ',' (taken from the header line). A file that
    is not UTF-8 is read as Windows-1252, which is what Excel writes for "CSV (comma delimited)";
    a note says so.
    """
    notes: list[str] = []
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise SheetError(f"Cannot read {path}: {error}") from error
    try:
        text = raw.decode(CSV_ENCODING)
    except UnicodeDecodeError:
        try:
            text = raw.decode(FALLBACK_ENCODING)
        except UnicodeDecodeError as error:
            raise SheetError(f"{path.name} is not UTF-8; save it as 'CSV UTF-8'") from error
        notes.append(f"{path.name} is not UTF-8; it was read as Windows-1252")
    header = text.split("\n", 1)[0]
    delimiter = CSV_DELIMITER if header.count(";") >= header.count(",") else ","
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    names = [name.strip() for name in reader.fieldnames or []]
    if "id" not in names or not any(f"{lang}_revisado" in names for lang in LANGUAGES):
        raise SheetError(f"{path.name} is not a review sheet (columns id, *_revisado expected)")
    reader.fieldnames = names
    rows = [{key: value or "" for key, value in row.items() if key} for row in reader]
    return rows, notes


def placeholders(text: str) -> frozenset[str]:
    """Return the set of ``%1``..``%9``, ``%L1``..``%L9`` and ``%n`` placeholders of ``text``."""
    return frozenset(PLACEHOLDER_RE.findall(text))


def split_forms(text: str, numerus: bool) -> tuple[str, ...]:
    """Split a reviewed cell into the forms of the translation."""
    normal = text.replace("\r\n", "\n")
    return tuple(normal.split(FORM_SEPARATOR)) if numerus else (normal,)


def check_forms(source: str, forms: Sequence[str], numerus: bool) -> str | None:
    """Return why ``forms`` cannot replace the translation of ``source``, or ``None``."""
    if numerus and len(forms) != 2:
        return f"a plural message needs exactly 2 forms separated by '{FORM_SEPARATOR}'"
    expected = placeholders(source)
    for form in forms:
        if not form.strip():
            return "a form is empty"
        found = placeholders(form)
        # A singular form may say "one day" instead of "%n day", so %n is optional there.
        required = expected - {PLURAL_PLACEHOLDER} if numerus else expected
        if not required <= found <= expected:
            return f"placeholders differ: expected {sorted(expected)}, found {sorted(found)}"
    return None


def _escape(text: str) -> str:
    """Escape text the way Qt Linguist writes it."""
    return saxutils.escape(text, {"'": "&apos;", '"': "&quot;"})


def render_translation(
    message: Message, forms: Sequence[str], mark_finished: bool, newline: str
) -> str:
    """Return the new ``<translation>`` element of ``message``."""
    attrs = _UNFINISHED_RE.sub("", message.attrs) if mark_finished else message.attrs
    if not message.numerus:
        return f"<translation{attrs}>{_escape(forms[0])}</translation>"
    inner = "".join(
        f"{newline}{message.indent}    <numerusform>{_escape(form)}</numerusform>" for form in forms
    )
    return f"<translation{attrs}>{inner}{newline}{message.indent}</translation>"


def _same(first: str, second: str) -> bool:
    return first.replace("\r\n", "\n") == second.replace("\r\n", "\n")


def _row_problem(row: Mapping[str, str], message: Message) -> str | None:
    """Return why the identifying columns of ``row`` do not match ``message``."""
    for column, value in (
        ("area", message.area),
        ("context", message.context),
        ("english", message.source),
    ):
        if column in row and not _same(row[column], value):
            return f"the {column} column was changed"
    return None


def import_sheet(csv_path: Path, ts_dir: Path, mark_finished: bool = False) -> ImportReport:
    """Apply the reviewed cells of ``csv_path`` to the catalogues of ``ts_dir``."""
    rows, notes = read_sheet(csv_path)
    catalogues = load_catalogues(ts_dir)
    index = _index(catalogues)
    report = ImportReport(notes=notes)
    edits: dict[tuple[str, str], list[tuple[int, int, str]]] = {}
    seen: set[tuple[str, str]] = set()
    for number, row in enumerate(rows, start=1):
        row_id = row.get("id", "").strip()
        for language in LANGUAGES:
            revised = row.get(f"{language}_revisado", "")
            if not revised.strip():
                continue
            label = f"{row_id or '(no id)'} ({language}, row {number})"
            message = index.get(row_id, {}).get(language)
            if message is None:
                report.skipped.append(f"{label}: unknown id")
                continue
            if (row_id, language) in seen:
                report.skipped.append(f"{label}: duplicate row for this message")
                continue
            seen.add((row_id, language))
            problem = _row_problem(row, message)
            forms = split_forms(revised, message.numerus)
            problem = problem or check_forms(message.source, forms, message.numerus)
            if problem is not None:
                report.skipped.append(f"{label}: {problem}")
                continue
            catalogue = catalogues[(message.area, language)]
            newline = "\r\n" if "\r\n" in catalogue.text else "\n"
            current = catalogue.text[message.element_start : message.element_end]
            new = render_translation(message, forms, mark_finished, newline)
            if new == current:
                report.unchanged += 1
                continue
            edits.setdefault((message.area, language), []).append(
                (message.element_start, message.element_end, new)
            )
            report.applied += 1
    for key in sorted(edits):
        catalogue = catalogues[key]
        text = catalogue.text
        for start, end, new in sorted(edits[key], reverse=True):
            text = text[:start] + new + text[end:]
        catalogue.path.write_bytes(text.encode("utf-8"))
        report.files_changed.append(catalogue.path)
    return report


def export_sheet(ts_dir: Path, out: Path) -> int:
    """Write the sheet to ``out`` and return the number of rows."""
    rows = build_rows(ts_dir)
    write_sheet(out, rows)
    return len(rows)


def _print_report(report: ImportReport) -> None:
    for note in report.notes:
        print(f"note: {note}")
    for item in report.skipped:
        print(f"skipped {item}")
    print(
        f"applied {report.applied}, unchanged {report.unchanged}, "
        f"skipped {len(report.skipped)}, files changed {len(report.files_changed)}"
    )
    for path in report.files_changed:
        print(f"changed {path.name}")


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        prog="terminology_sheet.py", description="Terminology review sheet of the catalogues."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="write the review sheet (CSV)")
    export.add_argument("--out", type=Path, required=True, help="CSV file to write")
    import_ = commands.add_parser("import", help="apply the reviewed sheet to the catalogues")
    import_.add_argument("--csv", type=Path, required=True, help="the reviewed CSV file")
    import_.add_argument(
        "--mark-finished",
        action="store_true",
        help='remove type="unfinished" from the translations that were reviewed',
    )
    for sub in (export, import_):
        sub.add_argument(
            "--ts-dir",
            type=Path,
            default=DEFAULT_TS_DIR,
            help="folder of the .ts catalogues (default: the i18n package folder)",
        )
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            count = export_sheet(args.ts_dir, args.out)
            print(f"wrote {count} rows to {args.out}")
        else:
            _print_report(import_sheet(args.csv, args.ts_dir, args.mark_finished))
    except SheetError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
