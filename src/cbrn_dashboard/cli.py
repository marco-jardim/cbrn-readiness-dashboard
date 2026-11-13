# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line parsing (PLAN.md task T0.7). Qt-free: ``--version`` must not need a display.

The help texts are plain English on purpose: they are shown on a console, not in the window, and
are therefore not part of the translated user interface.
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass

from cbrn_dashboard import __version__
from cbrn_dashboard.i18n import LANGUAGES, to_bcp47

PROG = "cbrn-dashboard"

#: Values accepted by ``--lang`` (BCP-47 form).
LANG_CHOICES: tuple[str, ...] = tuple(to_bcp47(code) for code in LANGUAGES)


@dataclass(frozen=True)
class CliOptions:
    """The parsed command line."""

    data_dir: str | None = None
    lang: str | None = None
    self_test: bool = False
    demo: bool = False


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="CBRN readiness dashboard (offline desktop application).",
    )
    parser.add_argument(
        "--data-dir",
        metavar="PATH",
        default=None,
        help="folder that holds the database and the other application data",
    )
    parser.add_argument(
        "--lang",
        choices=LANG_CHOICES,
        default=None,
        help="user-interface language for this run",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run the built-in checks, write selftest.json to the data folder and exit",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="open the separate demo database with fictitious data (never the real database)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{PROG} {__version__}",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> CliOptions:
    """Parse ``argv`` (default: ``sys.argv[1:]``).

    ``--version`` prints the version and exits with status 0; an invalid option or value exits
    with status 2 (argparse behaviour).
    """
    namespace = build_parser().parse_args(None if argv is None else list(argv))
    data_dir: str | None = namespace.data_dir
    lang: str | None = namespace.lang
    self_test: bool = namespace.self_test
    demo: bool = namespace.demo
    return CliOptions(data_dir=data_dir, lang=lang, self_test=self_test, demo=demo)
