# SPDX-License-Identifier: GPL-3.0-or-later
"""The three one-line registries of the shell (PLAN.md T1.9, section 10.2): pages, settings
sections and dialogs.

A module task registers itself by adding ONE line to the tuple that concerns it. Titles are
callables, so the translated text is produced at call time and follows a language switch.

Tests register temporarily with :func:`registered` (a context manager) or the explicit
``register_*`` / ``unregister_*`` functions; temporary entries never touch the tuples below. A
duplicate key is rejected with :class:`DuplicateKeyError`.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtWidgets import QDialog, QWidget

from cbrn_dashboard.ui.shell.context import AppContext

__all__ = [
    "DIALOGS",
    "PAGES",
    "SETTINGS_SECTIONS",
    "DialogSpec",
    "DuplicateKeyError",
    "PageSpec",
    "SettingsSectionSpec",
    "dialogs",
    "pages",
    "register_dialog",
    "register_page",
    "register_settings_section",
    "registered",
    "settings_sections",
    "unregister_dialog",
    "unregister_page",
    "unregister_settings_section",
]


class DuplicateKeyError(ValueError):
    """A spec with this key is already registered in the same registry."""


@dataclass(frozen=True)
class PageSpec:
    """A navigation page. ``title`` returns the translated navigation label at call time."""

    key: str
    order: int
    title: Callable[[], str]
    factory: Callable[[AppContext], QWidget]


@dataclass(frozen=True)
class SettingsSectionSpec:
    """A section of the Settings page (T6.1 renders them).

    ``group`` is a code: ``general``, ``personnel``, ``infrastructure``, ``exercises``,
    ``budget``, ``backup``, ``reports`` or ``snapshots``.
    """

    key: str
    group: str
    title: Callable[[], str]
    factory: Callable[[AppContext], QWidget]


@dataclass(frozen=True)
class DialogSpec:
    """A dialog. ``factory`` builds it with FICTITIOUS data so the walks can open it."""

    key: str
    factory: Callable[[AppContext, QWidget | None], QDialog]


# Pages, one line per module: T2.4 (personnel), T3.4 (infrastructure), T4.5 (exercises),
# T5.4 (budget), T6.2 (dashboard), T6.3 (alerts), T6.1 (settings), T7.4 / T8.x where they add one.
PAGES: tuple[PageSpec, ...] = ()

# Settings sections, one line per section: T2.4, T3.4, T4.5, T5.4, T7.4, T8.7 (T6.1 only renders).
SETTINGS_SECTIONS: tuple[SettingsSectionSpec, ...] = ()

# Dialogs, one line per dialog (each factory fills the dialog with fictitious data): T2.4, T3.4,
# T4.5, T5.4 and every later task that adds a dialog.
DIALOGS: tuple[DialogSpec, ...] = ()

# Temporary registrations made by tests, in registration order.
_extra_pages: list[PageSpec] = []
_extra_sections: list[SettingsSectionSpec] = []
_extra_dialogs: list[DialogSpec] = []


class _Keyed(Protocol):
    """Anything with a registry key (the three spec classes)."""

    @property
    def key(self) -> str: ...


def _checked[T: _Keyed](fixed: tuple[T, ...], extra: list[T]) -> list[T]:
    """``fixed`` then ``extra``; raises :class:`DuplicateKeyError` for a repeated key."""
    everything = [*fixed, *extra]
    seen: set[str] = set()
    for spec in everything:
        if spec.key in seen:
            msg = f"Duplicate registry key: {spec.key!r}"
            raise DuplicateKeyError(msg)
        seen.add(spec.key)
    return everything


def pages() -> tuple[PageSpec, ...]:
    """The registered pages, ordered by ``order`` and then by registration order."""
    return tuple(sorted(_checked(PAGES, _extra_pages), key=lambda spec: spec.order))


def settings_sections(group: str | None = None) -> tuple[SettingsSectionSpec, ...]:
    """The registered settings sections in registration order, optionally of one ``group``."""
    found = _checked(SETTINGS_SECTIONS, _extra_sections)
    return tuple(spec for spec in found if group is None or spec.group == group)


def dialogs() -> tuple[DialogSpec, ...]:
    """The registered dialogs in registration order."""
    return tuple(_checked(DIALOGS, _extra_dialogs))


def register_page(spec: PageSpec) -> None:
    """Register ``spec`` temporarily (tests); rejects a duplicate key."""
    _checked(PAGES, [*_extra_pages, spec])
    _extra_pages.append(spec)


def register_settings_section(spec: SettingsSectionSpec) -> None:
    """Register ``spec`` temporarily (tests); rejects a duplicate key."""
    _checked(SETTINGS_SECTIONS, [*_extra_sections, spec])
    _extra_sections.append(spec)


def register_dialog(spec: DialogSpec) -> None:
    """Register ``spec`` temporarily (tests); rejects a duplicate key."""
    _checked(DIALOGS, [*_extra_dialogs, spec])
    _extra_dialogs.append(spec)


def unregister_page(spec: PageSpec) -> None:
    """Remove a temporary registration made by :func:`register_page`."""
    _extra_pages.remove(spec)


def unregister_settings_section(spec: SettingsSectionSpec) -> None:
    """Remove a temporary registration made by :func:`register_settings_section`."""
    _extra_sections.remove(spec)


def unregister_dialog(spec: DialogSpec) -> None:
    """Remove a temporary registration made by :func:`register_dialog`."""
    _extra_dialogs.remove(spec)


@contextmanager
def registered(*specs: PageSpec | SettingsSectionSpec | DialogSpec) -> Iterator[None]:
    """Register ``specs`` for the duration of the ``with`` block; always unregisters them."""
    done: list[PageSpec | SettingsSectionSpec | DialogSpec] = []
    try:
        for spec in specs:
            if isinstance(spec, PageSpec):
                register_page(spec)
            elif isinstance(spec, SettingsSectionSpec):
                register_settings_section(spec)
            else:
                register_dialog(spec)
            done.append(spec)
        yield
    finally:
        for spec in reversed(done):
            if isinstance(spec, PageSpec):
                unregister_page(spec)
            elif isinstance(spec, SettingsSectionSpec):
                unregister_settings_section(spec)
            else:
                unregister_dialog(spec)
