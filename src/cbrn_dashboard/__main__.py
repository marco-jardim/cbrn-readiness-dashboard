# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line entry point (``python -m cbrn_dashboard``)."""

from cbrn_dashboard.app import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
