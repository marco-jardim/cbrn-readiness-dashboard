# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line entry point (``python -m cbrn_dashboard``)."""

import argparse

from cbrn_dashboard import __version__


def main(argv: list[str] | None = None) -> int:
    """Parse the command line. ``--version`` prints the version and exits with status 0."""
    parser = argparse.ArgumentParser(prog="cbrn-dashboard")
    parser.add_argument(
        "--version",
        action="version",
        version=f"cbrn-dashboard {__version__}",
    )
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
