# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line parsing (T0.7): options, defaults and exit codes."""

import pytest

import cbrn_dashboard
from cbrn_dashboard.cli import LANG_CHOICES, CliOptions, parse_args


def test_defaults() -> None:
    assert parse_args([]) == CliOptions(data_dir=None, lang=None, self_test=False)


def test_data_dir_is_kept_verbatim() -> None:
    assert parse_args(["--data-dir", r"C:\some folder\data"]).data_dir == r"C:\some folder\data"


def test_self_test_flag() -> None:
    assert parse_args(["--self-test"]).self_test is True


def test_all_options_together() -> None:
    options = parse_args(["--self-test", "--lang", "es-ES", "--data-dir", "x"])
    assert options == CliOptions(data_dir="x", lang="es-ES", self_test=True)


def test_lang_choices_are_exactly_the_three_bcp47_codes() -> None:
    assert set(LANG_CHOICES) == {"pt-BR", "en-US", "es-ES"}


@pytest.mark.parametrize("code", ["pt-BR", "en-US", "es-ES"])
def test_lang_accepts_each_language(code: str) -> None:
    assert parse_args(["--lang", code]).lang == code


@pytest.mark.parametrize("code", ["fr-FR", "pt_BR", "pt-br", "pt", ""])
def test_lang_rejects_other_values(code: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        parse_args(["--lang", code])
    assert excinfo.value.code == 2
    assert "--lang" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv", [["--unknown"], ["--data-dir"], ["--lang"], ["positional"], ["--self-test=yes"]]
)
def test_invalid_command_lines_exit_with_code_two(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        parse_args(argv)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err


def test_demo_is_not_available_yet(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        parse_args(["--demo"])
    assert excinfo.value.code == 2


def test_version_prints_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        parse_args(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"cbrn-dashboard {cbrn_dashboard.__version__}"
