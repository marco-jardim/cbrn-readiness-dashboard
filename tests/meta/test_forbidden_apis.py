# SPDX-License-Identifier: GPL-3.0-or-later
"""Layering and forbidden-API guard (PLAN T0.4, control 7.3 "No network code").

``test_source_tree_is_clean`` scans the real ``src/cbrn_dashboard`` tree. The other tests run the
engine on small fictitious snippets: every rule has snippets it must catch and snippets it must
leave alone, so a rule that silently stops matching is detected.

Documented engine behaviours that the tests pin down: clock functions passed by reference are
flagged when they are attributes of an *imported* clock object or a bare imported clock name;
shadowing is not tracked (a parameter named like an imported clock name is still flagged);
``os.system`` and friends are flagged only on the ``os`` module.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from tests.meta._ast_rules import (
    RULE_CLOCK,
    RULE_HANDOFF,
    RULE_LAYER_DOMAIN,
    RULE_LAYER_QT,
    RULE_LAYER_SQL,
    RULE_NET,
    RULE_SYNTAX,
    check_source,
    scan_tree,
)

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "src" / "cbrn_dashboard"

# A neutral location that no layer rule covers, so only NET / HANDOFF / CLOCK can fire.
NEUTRAL = "app.py"

type Case = tuple[str, str, str]  # (source, path relative to the package, expected rule)


def _rules(source: str, path: str) -> set[str]:
    return {v.rule for v in check_source(source, PurePosixPath(path))}


def _catch(rule: str, sources: list[str], path: str = NEUTRAL) -> list[Case]:
    return [(source, path, rule) for source in sources]


# --- the real tree -----------------------------------------------------------------------------


def test_source_tree_is_clean() -> None:
    assert (PACKAGE_DIR / "__init__.py").is_file(), f"package not found at {PACKAGE_DIR}"
    violations = scan_tree(PACKAGE_DIR)
    listing = "\n".join(f"  {v}" for v in violations)
    assert not violations, f"{len(violations)} guard violation(s) in src/cbrn_dashboard:\n{listing}"


def test_scan_tree_requires_the_package_directory(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        scan_tree(tmp_path / "missing")


def test_scan_tree_reports_relative_posix_paths(tmp_path: Path) -> None:
    (tmp_path / "ui" / "shell").mkdir(parents=True)
    (tmp_path / "ui" / "shell" / "bad.py").write_text("import socket\n", encoding="utf-8")
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    found = [(v.rule, str(v.path), v.line) for v in scan_tree(tmp_path)]
    assert found == [(RULE_NET, "ui/shell/bad.py", 1)]


def test_unparseable_source_is_reported() -> None:
    assert _rules("def broken(:\n", NEUTRAL) == {RULE_SYNTAX}


def test_violation_has_a_readable_text() -> None:
    (violation,) = check_source("\n\nimport socket\n", PurePosixPath("app.py"))
    assert str(violation) == "app.py:3: [NET] forbidden import of socket"


# --- NET ---------------------------------------------------------------------------------------

NET_MODULES = (
    "socket",
    "ssl",
    "urllib",
    "urllib3",
    "http",
    "ftplib",
    "smtplib",
    "xmlrpc",
    "imaplib",
    "poplib",
    "asyncio",
    "requests",
    "httpx",
    "webbrowser",
    "subprocess",
    "ctypes",
    "multiprocessing",
    "socketserver",
)

NET_POSITIVE: list[Case] = [
    *[case for module in NET_MODULES for case in _catch(RULE_NET, [f"import {module}\n"])],
    *_catch(
        RULE_NET,
        [
            "import urllib.request\n",
            "import http.client\n",
            "import xmlrpc.client as xc\n",
            "import socket as s\n",
            "import os, socket\n",
            "from socket import socket\n",
            "from urllib.request import urlopen\n",
            "from http.server import HTTPServer\n",
            "from asyncio import run\n",
            "from ssl import create_default_context as ctx\n",
            "import PySide6.QtNetwork\n",
            "import PySide6.QtNetwork as qn\n",
            "import PySide6.QtWebSockets\n",
            "import PySide6.QtNetworkAuth\n",
            "import PySide6.QtNetworkAuth as qna\n",
            "import PySide6.QtHttpServer\n",
            "import socketserver\n",
            "import socketserver as ss\n",
            "from socketserver import TCPServer\n",
            "import multiprocessing.pool\n",
            "from multiprocessing import Process\n",
            "from PySide6 import QtNetworkAuth\n",
            "from PySide6 import QtCore, QtNetworkAuth as auth\n",
            "from PySide6 import QtHttpServer\n",
            "from PySide6.QtNetworkAuth import QOAuth2AuthorizationCodeFlow\n",
            "from PySide6.QtHttpServer import QHttpServer\n",
            'import importlib\nimportlib.import_module("socketserver")\n',
            "import PySide6.QtWebEngineCore\n",
            "import PySide6.QtWebEngineWidgets as w\n",
            "from PySide6 import QtNetwork\n",
            "from PySide6 import QtCore, QtNetwork\n",
            "from PySide6 import QtWebSockets as ws\n",
            "from PySide6 import QtWebEngineWidgets\n",
            "from PySide6.QtNetwork import QTcpSocket\n",
            "from PySide6.QtNetwork.sub import Thing\n",
            "from PySide6.QtWebSockets import QWebSocket\n",
            "from PySide6.QtWebEngineCore import QWebEnginePage\n",
            "from PySide6.QtWebEngineWidgets import QWebEngineView\n",
            "def f():\n    import socket\n",
            "try:\n    import requests\nexcept ImportError:\n    pass\n",
            'import importlib\nimportlib.import_module("socket")\n',
            'import importlib as il\nil.import_module("urllib.request")\n',
            'from importlib import import_module\nimport_module("httpx")\n',
            '__import__("socket")\n',
            '__import__("PySide6.QtNetwork")\n',
            'import importlib\nimportlib.import_module("PySide6.QtWebEngineCore")\n',
        ],
    ),
    # The same forbidden imports are caught in every layer, not just in a neutral file.
    *_catch(RULE_NET, ["import socket\n"], "ui/main.py"),
    *_catch(RULE_NET, ["import socket\n"], "domain/a.py"),
    *_catch(RULE_NET, ["from PySide6 import QtNetwork\n"], "ui/shell/folders.py"),
    *_catch(RULE_NET, ["import socket\n"], "clock.py"),
]


@pytest.mark.parametrize(("source", "path", "rule"), NET_POSITIVE)
def test_net_rule_catches(source: str, path: str, rule: str) -> None:
    assert rule in _rules(source, path)


NET_NEGATIVE = [
    "import httpx_like\n",
    "import socketserver_like\n",
    "import multiprocessing_like\n",
    "from multiprocessing_like import Pool\n",
    "import PySide6.QtHttpServer_like\n",
    "import mysocket\n",
    "from httpx_like import x\n",
    "from . import socket\n",
    "from .http import client\n",
    "from cbrn_dashboard import http_client\n",
    "from PySide6 import QtCore, QtWidgets, QtGui\n",
    "from PySide6.QtCore import QObject\n",
    "import PySide6.QtWebview_like\n",
    "import argparse\nimport sqlite3\nimport json\n",
    "# import socket\nx = 1\n",
    'x = "import socket"\ny = "http://example.invalid"\n',
    '"""Docstring that mentions socket, subprocess and QtNetwork."""\n',
    'import importlib\nimportlib.import_module("json")\n',
    'import importlib\nimportlib.import_module(".socket", "pkg")\n',
    "import importlib\nname = 'sock'\nimportlib.import_module(name)\n",
    "class C:\n    def f(self) -> int:\n        return self.subprocess_count\n",
    "socket_count = 3\nhttp_status = 200\nrequests_total = 1\n",
]


@pytest.mark.parametrize("source", NET_NEGATIVE)
def test_net_rule_ignores(source: str) -> None:
    assert _rules(source, NEUTRAL) == set()


# --- HANDOFF -----------------------------------------------------------------------------------

HANDOFF_PATH = "ui/shell/folders.py"

HANDOFF_POSITIVE: list[Case] = [
    # subprocess / ctypes: no exception anywhere in src/, not even in folders.py
    *_catch(RULE_HANDOFF, ["import subprocess\n"]),
    *_catch(RULE_HANDOFF, ["import subprocess as sp\n"]),
    *_catch(RULE_HANDOFF, ["from subprocess import run\n"]),
    *_catch(RULE_HANDOFF, ["import ctypes\n"]),
    *_catch(RULE_HANDOFF, ["import ctypes.wintypes\n"]),
    *_catch(RULE_HANDOFF, ["from ctypes import windll\n"]),
    *_catch(RULE_HANDOFF, ["import multiprocessing\n"]),
    *_catch(RULE_HANDOFF, ["import multiprocessing.pool as mp\n"]),
    *_catch(RULE_HANDOFF, ["from multiprocessing import Process\n"]),
    *_catch(RULE_HANDOFF, ["import multiprocessing\n"], HANDOFF_PATH),
    *_catch(RULE_HANDOFF, ['import importlib\nimportlib.import_module("multiprocessing")\n']),
    *_catch(RULE_HANDOFF, ["import subprocess\n"], HANDOFF_PATH),
    *_catch(RULE_HANDOFF, ["import ctypes\n"], HANDOFF_PATH),
    # QProcess: no exception anywhere, not even in folders.py
    *_catch(
        RULE_HANDOFF,
        [
            "from PySide6.QtCore import QProcess\n",
            "from PySide6.QtCore import QProcess as P\n",
            "from PySide6.QtCore import QProcess\nQProcess.startDetached('explorer', [p])\n",
            "from PySide6.QtCore import QProcess as P\nP.startDetached('explorer', [p])\n",
            "from PySide6 import QtCore\nQtCore.QProcess.startDetached('explorer', [p])\n",
            "import PySide6.QtCore as qc\nproc = qc.QProcess()\n",
            "QProcess.startDetached('explorer', [p])\n",
            "factory = QProcess\n",
        ],
    ),
    *_catch(RULE_HANDOFF, ["from PySide6.QtCore import QProcess\n"], HANDOFF_PATH),
    *_catch(RULE_HANDOFF, ["QProcess.startDetached('explorer', [p])\n"], HANDOFF_PATH),
    # os.system / popen / spawn* / exec*, resolved through the import table
    *_catch(
        RULE_HANDOFF,
        [
            'import os\nos.system("start " + p)\n',
            "import os\nos.popen(cmd)\n",
            "import os\nrunner = os.system\n",
            "import os as o\no.system(cmd)\n",
            "import os.path\nos.system(cmd)\n",
            "from os import system\n",
            "from os import system as run\nrun(cmd)\n",
            "from os import popen\n",
            "from os import path, spawnl\n",
            *[
                f"import os\nos.{name}(cmd)\n"
                for name in (
                    "spawnl",
                    "spawnle",
                    "spawnlp",
                    "spawnlpe",
                    "spawnv",
                    "spawnve",
                    "spawnvp",
                    "spawnvpe",
                    "execl",
                    "execle",
                    "execlp",
                    "execlpe",
                    "execv",
                    "execve",
                    "execvp",
                    "execvpe",
                )
            ],
        ],
    ),
    *_catch(RULE_HANDOFF, ['import os\nos.system("start " + p)\n'], HANDOFF_PATH),
    *_catch(RULE_HANDOFF, ["from os import system\n"], HANDOFF_PATH),
    *_catch(RULE_HANDOFF, ["import os\nos.popen(cmd)\n"], "domain/a.py"),
    *_catch(RULE_HANDOFF, ["from ctypes import windll\n"], "ui/main.py"),
    # startfile, alias-independent
    *_catch(
        RULE_HANDOFF,
        [
            "import os\nos.startfile(path)\n",
            "import os as o\no.startfile(path)\n",
            "from os import startfile\n",
            "from os import startfile as sf\nsf(path)\n",
            "import os\nopener = os.startfile\n",
            "startfile(path)\n",
            "self.os_module.startfile(path)\n",
        ],
    ),
    *_catch(RULE_HANDOFF, ["import os\nos.startfile(path)\n"], "ui/shell/other.py"),
    *_catch(RULE_HANDOFF, ["import os\nos.startfile(path)\n"], "ui/folders.py"),
    *_catch(RULE_HANDOFF, ["import os\nos.startfile(path)\n"], "services/open.py"),
    *_catch(RULE_HANDOFF, ["import os\nos.startfile(path)\n"], "folders.py"),
    *_catch(RULE_HANDOFF, ["import os\nos.startfile(path)\n"], "other/ui/shell/folders.py"),
    # QDesktopServices
    *_catch(
        RULE_HANDOFF,
        [
            "from PySide6.QtGui import QDesktopServices\n",
            "from PySide6.QtGui import QDesktopServices as Q\n",
            "from PySide6.QtGui import QDesktopServices as Q\nQ.openUrl(url)\n",
            "from PySide6 import QtGui\nQtGui.QDesktopServices.openUrl(url)\n",
            "import PySide6.QtGui as g\ng.QDesktopServices.openUrl(url)\n",
            "QDesktopServices.openUrl(url)\n",
            "service = QDesktopServices\n",
        ],
        "ui/main.py",
    ),
    *_catch(RULE_HANDOFF, ["QDesktopServices.openUrl(url)\n"], "ui/shell/other.py"),
    # dynamic imports of the forbidden modules
    *_catch(RULE_HANDOFF, ['import importlib\nimportlib.import_module("subprocess")\n']),
    *_catch(RULE_HANDOFF, ['__import__("ctypes")\n']),
]


@pytest.mark.parametrize(("source", "path", "rule"), HANDOFF_POSITIVE)
def test_handoff_rule_catches(source: str, path: str, rule: str) -> None:
    assert rule in _rules(source, path)


HANDOFF_ALLOWED_IN_FOLDERS: list[str] = [
    "import os\nos.startfile(path)\n",
    "from os import startfile\nstartfile(path)\n",
    "from PySide6.QtGui import QDesktopServices\n",
    "from PySide6.QtCore import QUrl\nfrom PySide6.QtGui import QDesktopServices\n"
    "QDesktopServices.openUrl(QUrl.fromLocalFile(path))\n",
    "from PySide6 import QtGui\nQtGui.QDesktopServices.openUrl(url)\n",
]


@pytest.mark.parametrize("source", HANDOFF_ALLOWED_IN_FOLDERS)
def test_handoff_rule_allows_the_folders_helper(source: str) -> None:
    assert _rules(source, HANDOFF_PATH) == set()


HANDOFF_NEGATIVE = [
    "class C:\n    def f(self) -> int:\n        return self.subprocess_count\n",
    "subprocess_count = 0\n",
    "ctypes_available = False\n",
    "import subprocess_like\n",
    "import ctypes_helper\n",
    "import multiprocessing_like\n",
    "from multiprocessing_like import Pool\n",
    "class QProcessLike:\n    pass\n",
    # ``system`` / ``popen`` / ``exec*`` are only forbidden on the ``os`` module
    "class C:\n    def __init__(self) -> None:\n        self.system = 1\n",
    "import platform\nname = platform.system()\n",
    "from platform import system\nname = system()\n",
    "x = obj.system\ny = obj.popen(cmd)\n",
    "class Probes:\n    def system(self) -> None: ...\n\n\nProbes().system()\n",
    "import os\nx = os.environ\ny = os.getcwd()\nz = os.path.join(a, b)\n",
    "from os import path, getcwd\n",
    "import os\nclass C:\n    system = 1\n\n\nv = C.system\n",
    "import os\nx = app.exec()\n",
    "start_file = 1\nstartfiles = 2\n",
    "class QDesktopServicesLike:\n    pass\n",
    "def open_folder(path: str) -> None: ...\n",
    '# os.startfile and QDesktopServices are only allowed in folders.py\nx = "startfile"\n',
    '"""Uses subprocess and ctypes in its text only."""\n',
]


@pytest.mark.parametrize("source", HANDOFF_NEGATIVE)
def test_handoff_rule_ignores(source: str) -> None:
    assert _rules(source, "ui/main.py") == set()


# --- CLOCK -------------------------------------------------------------------------------------

CLOCK_POSITIVE_SOURCES = [
    "import datetime\nx = datetime.date.today()\n",
    "from datetime import date\nx = date.today()\n",
    "from datetime import date as d\nx = d.today()\n",
    "from datetime import datetime\nx = datetime.today()\n",
    "from datetime import datetime\nx = datetime.now()\n",
    "from datetime import datetime, UTC\nx = datetime.now(UTC)\n",
    "import datetime as dt\nx = dt.datetime.now()\n",
    "import datetime as dt\nx = dt.datetime.utcnow()\n",
    "from datetime import datetime as D\nx = D.utcnow()\n",
    "import datetime\nx = datetime.datetime.today()\n",
    "import time\nx = time.time()\n",
    "import time as t\nx = t.time()\n",
    "import time\nx = time.time_ns()\n",
    "import time\nx = time.localtime()\n",
    "import time\nx = time.gmtime()\n",
    "from time import time\nx = time()\n",
    "from time import time as clock_s\nx = clock_s()\n",
    "from time import time_ns\nx = time_ns()\n",
    "from time import localtime\nx = localtime()\n",
    "from time import gmtime as g\nx = g()\n",
    "from datetime import today\nx = today()\n",
    "from PySide6.QtCore import QDate\nx = QDate.currentDate()\n",
    "from PySide6.QtCore import QDateTime\nx = QDateTime.currentDateTime()\n",
    "from PySide6.QtCore import QDateTime\nx = QDateTime.currentDateTimeUtc()\n",
    "from PySide6.QtCore import QTime\nx = QTime.currentTime()\n",
    "from PySide6.QtCore import QDate as QD\nx = QD.currentDate()\n",
    # matching is by attribute name, whatever the object
    "x = foo.now()\n",
    "x = self.clock.today()\n",
    "x = get_something().utcnow()\n",
    # nested positions
    "def f():\n    return str(foo.now())\n",
    "class C:\n    def f(self):\n        return [x.today() for x in xs]\n",
    "value = a if cond else b.now()\n",
    # newly covered call names
    "from PySide6.QtCore import QDateTime\nx = QDateTime.currentMSecsSinceEpoch()\n",
    "from PySide6.QtCore import QDateTime\nx = QDateTime.currentSecsSinceEpoch()\n",
    "import time\nx = time.ctime()\n",
    "import time\nx = time.asctime()\n",
    "from time import ctime\nx = ctime()\n",
    "from time import asctime as a\nx = a()\n",
    # time.strftime(fmt) with one argument reads the local clock
    'import time\nx = time.strftime("%Y-%m-%d")\n',
    "import time as t\nx = t.strftime(fmt)\n",
    "import time\nx = time.strftime(format=fmt)\n",
    "from time import strftime\nx = strftime(fmt)\n",
    "from time import strftime as sf\nx = sf(fmt)\n",
]

# Clock functions passed by reference (not called). Each source has exactly one violation.
CLOCK_REFERENCE_SOURCES = [
    # the four accidental patterns of the QA finding, verbatim
    "from dataclasses import dataclass, field\nfrom datetime import date\n\n\n@dataclass\n"
    "class X:\n    as_of: date = field(default_factory=date.today)\n",
    "import functools\nfrom datetime import UTC, datetime\n\n"
    "f = functools.partial(datetime.now, UTC)\n",
    "from PySide6.QtCore import QDateTime\n\n"
    "stamp = QDateTime.currentDateTimeUtc\nvalue = stamp()\n",
    "from time import time\n\nordered = sorted(xs, key=time)\n",
    # aliases and dotted forms
    "from datetime import datetime as dt\nf = dt.now\n",
    "from datetime import date as d\nf = d.today\n",
    "from datetime import datetime\nf = datetime.utcnow\n",
    "import datetime\nf = datetime.datetime.now\n",
    "import datetime\nf = datetime.date.today\n",
    "import datetime as dt\nf = dt.datetime.utcnow\n",
    "import datetime as dt\nf = dt.date.today\n",
    "import time\nf = time.time\n",
    "import time as t\nf = t.time_ns\n",
    "import time\nf = time.localtime\n",
    "import time\nf = time.ctime\n",
    "from time import time as clock_s\nordered = sorted(xs, key=clock_s)\n",
    "from time import time_ns\nf = time_ns\n",
    "from time import localtime\nf = localtime\n",
    "from time import gmtime as g\nf = g\n",
    "from time import ctime\nf = ctime\n",
    "from datetime import today\nf = map(today, xs)\n",
    "from PySide6.QtCore import QDate\nf = QDate.currentDate\n",
    "from PySide6.QtCore import QDateTime as QDT\nf = QDT.currentDateTime\n",
    "from PySide6.QtCore import QTime\nf = QTime.currentTime\n",
    "from PySide6 import QtCore\nf = QtCore.QDateTime.currentDateTime\n",
    "import PySide6.QtCore as qc\nf = qc.QDateTime.currentMSecsSinceEpoch\n",
    "import PySide6.QtCore as qc\nf = qc.QDateTime.currentSecsSinceEpoch\n",
    # nested positions
    "from datetime import date\nitems = [date.today for _ in xs]\n",
    "from datetime import date\n\n\ndef f(g=date.today):\n    return g\n",
]

CLOCK_POSITIVE_SOURCES += CLOCK_REFERENCE_SOURCES

CLOCK_POSITIVE: list[Case] = _catch(RULE_CLOCK, CLOCK_POSITIVE_SOURCES)
CLOCK_POSITIVE += _catch(RULE_CLOCK, ["x = datetime.now()\n"], "services/a.py")
CLOCK_POSITIVE += _catch(RULE_CLOCK, ["x = datetime.now()\n"], "ui/shell/folders.py")
CLOCK_POSITIVE += _catch(RULE_CLOCK, ["x = datetime.now()\n"], "domain/clock.py")
CLOCK_POSITIVE += _catch(RULE_CLOCK, ["x = datetime.now()\n"], "ui/clock.py")
CLOCK_POSITIVE += _catch(RULE_CLOCK, ["x = datetime.now()\n"], "clock_helpers.py")


@pytest.mark.parametrize(("source", "path", "rule"), CLOCK_POSITIVE)
def test_clock_rule_catches(source: str, path: str, rule: str) -> None:
    assert rule in _rules(source, path)


@pytest.mark.parametrize("source", CLOCK_POSITIVE_SOURCES)
def test_clock_module_may_read_the_wall_clock(source: str) -> None:
    assert _rules(source, "clock.py") == set()


@pytest.mark.parametrize("source", CLOCK_REFERENCE_SOURCES)
def test_clock_reference_is_reported_once(source: str) -> None:
    found = check_source(source, PurePosixPath(NEUTRAL))
    assert [v.rule for v in found] == [RULE_CLOCK], [str(v) for v in found]


@pytest.mark.parametrize("source", CLOCK_REFERENCE_SOURCES[:4])
def test_clock_references_are_caught_in_the_domain_layer(source: str) -> None:
    assert RULE_CLOCK in _rules(source, "domain/x.py")


@pytest.mark.parametrize(
    "source",
    [
        "from datetime import datetime\nx = datetime.now()\n",
        "import datetime\nx = datetime.datetime.now(tz)\n",
        "from time import time\nx = time()\n",
        "from PySide6.QtCore import QDateTime\nx = QDateTime.currentDateTimeUtc()\n",
        "import time\nx = time.strftime(fmt)\n",
        "from time import strftime\nx = strftime(fmt)\n",
    ],
)
def test_clock_call_is_reported_once(source: str) -> None:
    found = check_source(source, PurePosixPath(NEUTRAL))
    assert [v.rule for v in found] == [RULE_CLOCK], [str(v) for v in found]


SHADOWING_FLAGGED = [
    # shadowing is not tracked: the file imports ``time``, so the parameter is the import
    "from time import time\n\n\ndef f(time):\n    return time\n",
    "import time\n\n\ndef f(time):\n    return time.now\n",
    "from datetime import date\n\n\ndef f(date):\n    return date.today\n",
]


@pytest.mark.parametrize("source", SHADOWING_FLAGGED)
def test_clock_rule_does_not_track_shadowing(source: str) -> None:
    assert _rules(source, NEUTRAL) == {RULE_CLOCK}


@pytest.mark.parametrize("source", SHADOWING_FLAGGED)
def test_clock_rule_shadowing_in_the_clock_module_is_allowed(source: str) -> None:
    assert _rules(source, "clock.py") == set()


CLOCK_NEGATIVE = [
    "import time\ntime.sleep(1)\n",
    "import time\nx = time.monotonic()\ny = time.perf_counter()\n",
    "from datetime import date, datetime, timedelta\n"
    "x = date(2026, 1, 31)\ny = datetime(2026, 1, 31) + timedelta(days=3)\n",
    "from datetime import datetime\nx = datetime.fromisoformat(s)\ny = datetime.strptime(s, f)\n",
    "from datetime import date\nx = date.fromordinal(5)\n",
    "from PySide6.QtCore import QDate\nx = QDate(2026, 1, 31)\ny = QDate.fromString(s, f)\n",
    "now = 5\ntoday = 'monday'\nx = now + 1\n",
    "def f(today):\n    return today\n",
    "x = obj.now\ny = obj.today\n",
    # uncalled references on arbitrary (not imported) objects stay allowed
    "x = obj.now\n",
    "class C:\n    def f(self):\n        return self.clock.today\n",
    "import platform\nx = platform.time\n",
    "from datetime import datetime\nfactory = datetime(2026, 1, 1).now\n",
    "date = make_date()\nf = date.today\n",
    # not clock names, even on imported clock objects
    "import time\nf = time.sleep\ng = time.monotonic\n",
    "from datetime import date, datetime\nf = date.fromordinal\ng = datetime.fromisoformat\n",
    "from PySide6.QtCore import QDate\nf = QDate.fromString\n",
    "from time import sleep\nf = sleep\n",
    "import datetime\nx: datetime.timedelta\n",
    # strftime: only time.strftime(fmt) with a single argument reads the clock
    "from datetime import datetime\nvalue = datetime(2026, 1, 1)\nx = value.strftime('%Y')\n",
    "x = value.strftime('%Y')\n",
    "import time\nx = time.strftime('%Y', t)\n",
    "import time\nx = time.strftime(fmt, t)\n",
    "from time import strftime\nx = strftime(fmt, t)\n",
    "import time\nf = time.strftime\n",
    "def f(strftime):\n    return strftime('%Y')\n",
    # a name that merely looks like an imported clock name (no such import) is just a name
    "def f(time):\n    return time\n",
    "def f(time):\n    return time.now\n",
    "def f(time_ns):\n    return time_ns\n",
    "ctime = 3\nx = ctime + 1\n",
    "def now_label() -> str: ...\n",
    "from time import sleep\nsleep(1)\n",
    "class C:\n    time_zone = 1\n\n    def f(self):\n        return self.time_zone\n",
    '# datetime.now() is only allowed in clock.py\nx = "time.time()"\n',
    '"""Mentions date.today(), datetime.now() and QDate.currentDate()."""\n',
]


@pytest.mark.parametrize("source", CLOCK_NEGATIVE)
def test_clock_rule_ignores(source: str) -> None:
    assert _rules(source, NEUTRAL) == set()


# --- LAYER-QT ----------------------------------------------------------------------------------

QT_SOURCES = [
    "import PySide6\n",
    "import PySide6.QtCore\n",
    "import PySide6.QtWidgets as w\n",
    "from PySide6 import QtCore\n",
    "from PySide6.QtWidgets import QWidget\n",
    "from PySide6.QtCore import Signal, QObject\n",
    "import shiboken6\n",
    "from shiboken6 import isValid\n",
    "def f():\n    from PySide6.QtGui import QColor\n",
    'import importlib\nimportlib.import_module("PySide6.QtCore")\n',
]
QT_RESTRICTED_PATHS = [
    "domain/a.py",
    "domain/sub/a.py",
    "domain/__init__.py",
    "services/a.py",
    "services/sub/a.py",
    "storage/db.py",
    "storage/migrations/m1.py",
    "reports/model.py",
    "reports/anonymise.py",
]
QT_FREE_PATHS = [
    "ui/x.py",
    "ui/shell/folders.py",
    "reports/pdf.py",
    "reports/__init__.py",
    "i18n/loader.py",
    "app.py",
    "demo/seed.py",
    "reports/sub/model.py",
    "domain.py",
    "services.py",
]

QT_POSITIVE: list[Case] = [
    (source, path, RULE_LAYER_QT) for source in QT_SOURCES for path in QT_RESTRICTED_PATHS
]


@pytest.mark.parametrize(("source", "path", "rule"), QT_POSITIVE)
def test_layer_qt_rule_catches(source: str, path: str, rule: str) -> None:
    assert rule in _rules(source, path)


@pytest.mark.parametrize("path", QT_FREE_PATHS)
@pytest.mark.parametrize("source", QT_SOURCES[:6])
def test_layer_qt_rule_allows_other_places(source: str, path: str) -> None:
    assert RULE_LAYER_QT not in _rules(source, path)


# --- LAYER-SQL ---------------------------------------------------------------------------------

SQL_SOURCES = [
    "import sqlite3\n",
    "import sqlite3 as db\n",
    "from sqlite3 import connect\n",
    "from sqlite3 import Row as R\n",
    "import sqlite3.dbapi2\n",
    "def f():\n    import sqlite3\n",
    'import importlib\nimportlib.import_module("sqlite3")\n',
]
SQL_POSITIVE: list[Case] = [
    (source, path, RULE_LAYER_SQL)
    for source in SQL_SOURCES
    for path in ("ui/x.py", "ui/shell/y.py", "ui/__init__.py", "ui/a/b/c.py")
]


@pytest.mark.parametrize(("source", "path", "rule"), SQL_POSITIVE)
def test_layer_sql_rule_catches(source: str, path: str, rule: str) -> None:
    assert rule in _rules(source, path)


SQL_ALLOWED_PATHS = [
    "storage/db.py",
    "storage/migrations/m1.py",
    "services/a.py",
    "domain/a.py",
    "app.py",
    "ui.py",
]


@pytest.mark.parametrize("path", SQL_ALLOWED_PATHS)
@pytest.mark.parametrize("source", SQL_SOURCES[:4])
def test_layer_sql_rule_allows_other_places(source: str, path: str) -> None:
    assert RULE_LAYER_SQL not in _rules(source, path)


# --- LAYER-DOMAIN ------------------------------------------------------------------------------

DOMAIN_POSITIVE: list[Case] = [
    (source, path, RULE_LAYER_DOMAIN)
    for source, path in [
        ("import cbrn_dashboard.storage\n", "domain/a.py"),
        ("import cbrn_dashboard.storage.db as d\n", "domain/a.py"),
        ("import cbrn_dashboard.services\n", "domain/a.py"),
        ("import cbrn_dashboard.services.foo\n", "domain/sub/a.py"),
        ("from cbrn_dashboard.storage import db\n", "domain/a.py"),
        ("from cbrn_dashboard.storage.db import connect\n", "domain/a.py"),
        ("from cbrn_dashboard.services import foo\n", "domain/a.py"),
        ("from cbrn_dashboard.services.foo import bar\n", "domain/a.py"),
        ("from cbrn_dashboard import storage\n", "domain/a.py"),
        ("from cbrn_dashboard import services as s\n", "domain/a.py"),
        ("from cbrn_dashboard import domain, storage\n", "domain/a.py"),
        # relative imports, resolved against the file's package
        ("from ..storage import x\n", "domain/a.py"),
        ("from ..storage.db import x\n", "domain/a.py"),
        ("from .. import storage\n", "domain/a.py"),
        ("from .. import services\n", "domain/a.py"),
        ("from .. import domain, services\n", "domain/a.py"),
        ("from ..services.foo import bar\n", "domain/a.py"),
        ("from ..services import foo\n", "domain/a.py"),
        ("from ..storage import x\n", "domain/__init__.py"),
        ("from ...storage import x\n", "domain/sub/a.py"),
        ("from ... import storage\n", "domain/sub/a.py"),
        ("from ...services.foo import bar\n", "domain/sub/a.py"),
        ("def f():\n    from ..storage import x\n", "domain/a.py"),
        ('import importlib\nimportlib.import_module("cbrn_dashboard.storage")\n', "domain/a.py"),
    ]
]


@pytest.mark.parametrize(("source", "path", "rule"), DOMAIN_POSITIVE)
def test_layer_domain_rule_catches(source: str, path: str, rule: str) -> None:
    assert rule in _rules(source, path)


DOMAIN_NEGATIVE: list[tuple[str, str]] = [
    ("import cbrn_dashboard.domain.b\n", "domain/a.py"),
    ("from cbrn_dashboard.domain import b\n", "domain/a.py"),
    ("from cbrn_dashboard.domain.b import c\n", "domain/a.py"),
    ("from . import b\n", "domain/a.py"),
    ("from .b import c\n", "domain/a.py"),
    ("from .. import domain\n", "domain/a.py"),
    ("from ..domain import b\n", "domain/a.py"),
    ("from ... import domain\n", "domain/sub/a.py"),
    ("from .. import clock\n", "domain/a.py"),
    ("from ..clock import Clock\n", "domain/a.py"),
    ("from .. import storage_like\n", "domain/a.py"),
    ("import cbrn_dashboard.storage_like\n", "domain/a.py"),
    ("from . import storage\n", "domain/a.py"),
    ("from .storage import x\n", "domain/a.py"),
    ("import dataclasses\nimport enum\n", "domain/a.py"),
    ("x = 'cbrn_dashboard.storage'\n# from ..storage import x\n", "domain/a.py"),
    # other layers may use storage and services
    ("from ..storage import x\n", "services/a.py"),
    ("from .. import storage\n", "services/a.py"),
    ("import cbrn_dashboard.storage\n", "ui/a.py"),
    ("from ..services import foo\n", "ui/a.py"),
    ("from ..domain import foo\n", "services/a.py"),
    ("from ..storage import x\n", "app.py"),
    ("from .storage import x\n", "app.py"),
    ("from ..storage import x\n", "domain.py"),
]


@pytest.mark.parametrize(("source", "path"), DOMAIN_NEGATIVE)
def test_layer_domain_rule_ignores(source: str, path: str) -> None:
    assert RULE_LAYER_DOMAIN not in _rules(source, path)


# --- rules are independent ---------------------------------------------------------------------


def test_clean_module_has_no_violations() -> None:
    source = "import argparse\n\n\ndef main() -> int:\n    return 0\n"
    assert check_source(source, PurePosixPath("__main__.py")) == []


def test_violations_carry_line_numbers_and_are_sorted() -> None:
    source = "import os\n\nimport socket\n\nx = foo.now()\n"
    found = check_source(source, PurePosixPath("app.py"))
    assert [(v.line, v.rule) for v in found] == [(3, RULE_NET), (5, RULE_CLOCK)]


def test_one_import_in_a_restricted_layer_reports_each_rule_once() -> None:
    found = check_source("import sqlite3\nimport PySide6.QtNetwork\n", PurePosixPath("ui/x.py"))
    assert [(v.line, v.rule) for v in found] == [(1, RULE_LAYER_SQL), (2, RULE_NET)]
