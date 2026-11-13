# SPDX-License-Identifier: GPL-3.0-or-later
"""Maintain the Qt Linguist catalogues (PLAN.md section 6).

``python scripts/i18n.py update``
    Run ``lupdate`` over the sources of every area, rewriting ``<area>_<lang>.ts`` without source
    locations (``-locations none``) so that the files do not churn.
``python scripts/i18n.py compile [--out-dir DIR]``
    Run ``lrelease`` on every catalogue. Unfinished messages are shipped. The default output
    folder is the ``i18n`` package folder (``.qm`` files are git-ignored).

The functions are importable (tests load this file by path, since ``scripts/`` is not a package).
"""

import argparse
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cbrn_dashboard import i18n  # noqa: E402

SOURCE_LANGUAGE = "en_US"
_FOUND_RE = re.compile(r"Found (\d+) source text\(s\)")


class ToolError(RuntimeError):
    """A Qt tool could not be found or exited with a non-zero status."""


def find_tool(name: str) -> Path:
    """Locate the Qt tool ``name`` (``"lupdate"`` or ``"lrelease"``).

    The binary shipped next to the installed ``PySide6`` package wins; otherwise the
    ``pyside6-<name>`` launcher on ``PATH`` is used.
    """
    try:
        import PySide6
    except ImportError:
        pass
    else:
        folder = Path(PySide6.__file__).resolve().parent
        for candidate in (folder / f"{name}.exe", folder / name):
            if candidate.is_file():
                return candidate
    found = shutil.which(f"pyside6-{name}")
    if found is not None:
        return Path(found)
    raise ToolError(f"Could not find {name}: neither in the PySide6 package nor on PATH")


def lupdate_command(area: str, lang: str, ts_path: Path) -> list[str]:
    """Return the ``lupdate`` command line for one catalogue, or ``[]`` without sources."""
    sources = i18n.source_paths(area)
    if not sources:
        return []
    # Options first: lupdate applies -extensions only to the directories that follow it.
    return [
        str(find_tool("lupdate")),
        "-extensions",
        "py",
        "-locations",
        "none",
        "-no-obsolete",
        "-source-language",
        SOURCE_LANGUAGE,
        "-target-language",
        i18n.to_catalogue_code(lang),
        *(str(path) for path in sources),
        "-ts",
        str(ts_path),
    ]


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def update_catalogues(
    ts_dir: Path | None = None,
    areas: Iterable[str] | None = None,
    languages: Iterable[str] | None = None,
) -> list[Path]:
    """Run ``lupdate`` for each area and language; return the ``.ts`` files written.

    ``ts_dir`` defaults to the ``i18n`` package folder; the tests pass a temporary copy. Areas
    without any existing source path are skipped. Raises :class:`ToolError` on failure.
    """
    folder = i18n.PACKAGE_DIR if ts_dir is None else ts_dir
    written: list[Path] = []
    for area in i18n.AREAS if areas is None else areas:
        for lang in i18n.LANGUAGES if languages is None else languages:
            ts_path = folder / f"{area}_{i18n.to_catalogue_code(lang)}.ts"
            command = lupdate_command(area, lang, ts_path)
            if not command:
                continue
            result = _run(command)
            if result.returncode != 0:
                output = result.stdout + result.stderr
                raise ToolError(f"lupdate failed for {ts_path.name}:\n{output}")
            found = _FOUND_RE.search(result.stdout + result.stderr)
            if found is not None and int(found.group(1)) == 0:
                # An area with sources always has strings; zero means a tooling error and
                # -no-obsolete has just emptied the catalogue.
                raise ToolError(f"lupdate extracted no strings for {ts_path.name}")
            written.append(ts_path)
    return written


def run_lrelease(ts_path: Path, qm_path: Path) -> subprocess.CompletedProcess[str]:
    """Compile one catalogue (unfinished messages included) and return the finished process."""
    command = [str(find_tool("lrelease")), str(ts_path), "-qm", str(qm_path)]
    return _run(command)


def compile_catalogues(out_dir: Path | None = None, ts_dir: Path | None = None) -> list[Path]:
    """Compile every catalogue of ``ts_dir`` into ``out_dir``; return the ``.qm`` files written.

    Both default to the ``i18n`` package folder. Raises :class:`ToolError` on failure.
    """
    source_folder = i18n.PACKAGE_DIR if ts_dir is None else ts_dir
    target = i18n.qm_dir() if out_dir is None else out_dir
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for area in i18n.AREAS:
        for lang in i18n.LANGUAGES:
            code = i18n.to_catalogue_code(lang)
            ts_path = source_folder / f"{area}_{code}.ts"
            if not ts_path.is_file():
                raise ToolError(f"Missing catalogue: {ts_path}")
            qm_path = target / i18n.qm_name(area, code)
            result = run_lrelease(ts_path, qm_path)
            if result.returncode != 0:
                output = result.stdout + result.stderr
                raise ToolError(f"lrelease failed for {ts_path.name}:\n{output}")
            written.append(qm_path)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(prog="i18n.py", description="Maintain the .ts catalogues.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("update", help="extract source strings into the .ts catalogues")
    compile_parser = commands.add_parser("compile", help="compile the .ts catalogues to .qm")
    compile_parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="output folder (default: the i18n package folder)",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "update":
            for path in update_catalogues():
                print(f"updated {path.name}")
        else:
            for path in compile_catalogues(args.out_dir):
                print(f"compiled {path.name}")
    except ToolError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
