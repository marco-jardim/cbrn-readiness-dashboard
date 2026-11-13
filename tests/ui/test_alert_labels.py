# SPDX-License-Identifier: GPL-3.0-or-later
"""The translated alert texts: messages, plural forms, severity and module names (PLAN.md T6.3)."""

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication

from cbrn_dashboard.domain.alerts import Alert, AlertKind, Severity, SubjectKind
from cbrn_dashboard.domain.indicators import Module
from cbrn_dashboard.ui.alerts.labels import (
    ALL_KIND_CODES,
    ALL_MODULE_CODES,
    ALL_SEVERITY_CODES,
    alert_message,
    kind_message,
    module_label,
    severity_icon,
    severity_label,
    subject_text,
)
from cbrn_dashboard.ui.shell.context import AppContext
from tests.ui._alert_samples import (
    ALERTS,
    CERT_EXPIRED,
    CERT_EXPIRING,
    INDICATOR_CRITICAL,
    INDICATOR_WARNING,
    MAINT_DUE_SOON,
    MAINT_OVERDUE,
    MAINT_SCHEDULE_UNKNOWN,
    MESSAGES,
)

pytestmark = pytest.mark.ui

LANGUAGES = ("pt_BR", "en_US", "es_ES")

#: (message for 1 day, message for 2 days) of the four kinds that count days, per language.
PLURALS: dict[str, dict[AlertKind, tuple[str, str]]] = {
    "en_US": {
        AlertKind.CERT_EXPIRED: (
            "The level A PPE qualification of DEMO-P001 expired 1 day ago.",
            "The level A PPE qualification of DEMO-P001 expired 2 days ago.",
        ),
        AlertKind.CERT_EXPIRING: (
            "The level B PPE qualification of DEMO-P002 expires in 1 day.",
            "The level B PPE qualification of DEMO-P002 expires in 2 days.",
        ),
        AlertKind.MAINT_OVERDUE: (
            "Maintenance of asset DEMO-A001 is overdue by 1 day.",
            "Maintenance of asset DEMO-A001 is overdue by 2 days.",
        ),
        AlertKind.MAINT_DUE_SOON: (
            "Maintenance of asset DEMO-A002 is due in 1 day.",
            "Maintenance of asset DEMO-A002 is due in 2 days.",
        ),
    },
    "pt_BR": {
        AlertKind.CERT_EXPIRED: (
            "A habilitação de EPI de nível A de DEMO-P001 venceu há 1 dia.",
            "A habilitação de EPI de nível A de DEMO-P001 venceu há 2 dias.",
        ),
        AlertKind.CERT_EXPIRING: (
            "A habilitação de EPI de nível B de DEMO-P002 vence em 1 dia.",
            "A habilitação de EPI de nível B de DEMO-P002 vence em 2 dias.",
        ),
        AlertKind.MAINT_OVERDUE: (
            "A manutenção do ativo DEMO-A001 está atrasada em 1 dia.",
            "A manutenção do ativo DEMO-A001 está atrasada em 2 dias.",
        ),
        AlertKind.MAINT_DUE_SOON: (
            "A manutenção do ativo DEMO-A002 vence em 1 dia.",
            "A manutenção do ativo DEMO-A002 vence em 2 dias.",
        ),
    },
    "es_ES": {
        AlertKind.CERT_EXPIRED: (
            "La habilitación de EPP de nivel A de DEMO-P001 caducó hace 1 día.",
            "La habilitación de EPP de nivel A de DEMO-P001 caducó hace 2 días.",
        ),
        AlertKind.CERT_EXPIRING: (
            "La habilitación de EPP de nivel B de DEMO-P002 caduca en 1 día.",
            "La habilitación de EPP de nivel B de DEMO-P002 caduca en 2 días.",
        ),
        AlertKind.MAINT_OVERDUE: (
            "El mantenimiento del activo DEMO-A001 está vencido desde hace 1 día.",
            "El mantenimiento del activo DEMO-A001 está vencido desde hace 2 días.",
        ),
        AlertKind.MAINT_DUE_SOON: (
            "El mantenimiento del activo DEMO-A002 vence en 1 día.",
            "El mantenimiento del activo DEMO-A002 vence en 2 días.",
        ),
    },
}

#: The alert of each plural kind and the sign of its days (negative: overdue or expired).
PLURAL_BASES: dict[AlertKind, tuple[Alert, int]] = {
    AlertKind.CERT_EXPIRED: (CERT_EXPIRED, -1),
    AlertKind.CERT_EXPIRING: (CERT_EXPIRING, 1),
    AlertKind.MAINT_OVERDUE: (MAINT_OVERDUE, -1),
    AlertKind.MAINT_DUE_SOON: (MAINT_DUE_SOON, 1),
}


# --------------------------------------------------------------------------- messages


def test_the_samples_cover_every_alert_kind() -> None:
    assert {alert.kind.value for alert in ALERTS} == set(ALL_KIND_CODES)
    assert set(ALL_KIND_CODES) == {
        "CERT_EXPIRED",
        "CERT_EXPIRING",
        "MAINT_OVERDUE",
        "MAINT_DUE_SOON",
        "MAINT_SCHEDULE_UNKNOWN",
        "INDICATOR_WARNING",
        "INDICATOR_CRITICAL",
    }
    assert {kind.value for kind in AlertKind} == set(ALL_KIND_CODES)


@pytest.mark.parametrize("lang", LANGUAGES)
def test_every_kind_gives_a_message_with_every_placeholder_filled(
    app_context: AppContext, lang: str
) -> None:
    app_context.translator_manager.set_language(lang)
    for alert, expected in zip(ALERTS, MESSAGES[lang], strict=True):
        text = alert_message(alert, lang)
        assert text == expected, alert.kind
        assert text.strip()
        assert "%" not in text, (lang, alert.kind, text)
        if alert.kind in (AlertKind.INDICATOR_WARNING, AlertKind.INDICATOR_CRITICAL):
            # an indicator is named in words, never by its code and the encoded dimension
            assert alert.subject_ref not in text
            assert "=" not in text
        else:
            assert alert.subject_ref in text


def test_the_messages_differ_between_the_languages() -> None:
    for position in range(len(ALERTS)):
        texts = {MESSAGES[lang][position] for lang in LANGUAGES}
        assert len(texts) == 3


@pytest.mark.parametrize("lang", LANGUAGES)
@pytest.mark.parametrize("kind", list(PLURAL_BASES))
def test_plural_forms_are_correct_for_1_and_for_2_days(
    app_context: AppContext, lang: str, kind: AlertKind
) -> None:
    app_context.translator_manager.set_language(lang)
    base, sign = PLURAL_BASES[kind]
    one, two = PLURALS[lang][kind]
    assert alert_message(replace(base, days_remaining=sign * 1), lang) == one
    assert alert_message(replace(base, days_remaining=sign * 2), lang) == two


def test_an_indicator_without_values_shows_a_dash(app_context: AppContext) -> None:
    alert = replace(INDICATOR_WARNING, value=None, threshold=None)
    assert alert_message(alert, "en_US") == (
        "Indicator Staff with a valid PPE qualification (Level A) is at - (warning threshold: -)."
    )


def test_numbers_follow_the_language_and_are_rounded_to_two_places(
    app_context: AppContext,
) -> None:
    alert = replace(INDICATOR_CRITICAL, dimension="", value=66.66666666666667, threshold=1234.5)
    app_context.translator_manager.set_language("en_US")
    assert alert_message(alert, "en_US") == (
        "Indicator Units with overdue maintenance is at 66.67 (critical threshold: 1,234.5)."
    )
    app_context.translator_manager.set_language("pt_BR")
    assert alert_message(alert, "pt_BR") == (
        "O indicador Unidades com manutenção atrasada está em 66,67 (limite crítico: 1.234,5)."
    )


BUDGET_RATE = Alert(
    kind=AlertKind.INDICATOR_WARNING,
    severity=Severity.WARNING,
    module=Module.BUDGET,
    subject_kind=SubjectKind.INDICATOR,
    subject_ref="BUD_EXEC_RATE",
    dimension="currency=BRL;source=DIRSA",
    value=0.45,
    threshold=0.5,
)


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        (
            "en_US",
            "Indicator Budget execution rate (Currency BRL, Source DIRSA) is at 45.0% "
            "(warning threshold: 50.0%).",
        ),
        (
            "pt_BR",
            "O indicador Taxa de execução orçamentária (Moeda BRL, Fonte DIRSA) está em 45,0% "
            "(limite de aviso: 50,0%).",
        ),
        (
            "es_ES",
            "El indicador Tasa de ejecución presupuestaria (Moneda BRL, Fuente DIRSA) está en "
            "45,0\xa0% (umbral de advertencia: 50,0\xa0%).",
        ),
    ],
)
def test_a_ratio_indicator_is_named_in_words_and_shown_as_percent(
    app_context: AppContext, lang: str, expected: str
) -> None:
    """P6-08: no raw code, no encoded dimension, and 0.45 is 45 % (not "0,45")."""
    app_context.translator_manager.set_language(lang)
    assert alert_message(BUDGET_RATE, lang) == expected


def test_the_subject_is_the_reference_and_for_indicators_also_the_dimension() -> None:
    assert subject_text(MAINT_OVERDUE) == "DEMO-A001"
    assert subject_text(CERT_EXPIRED) == "DEMO-P001"
    assert subject_text(MAINT_SCHEDULE_UNKNOWN) == "DEMO-A003"
    assert subject_text(INDICATOR_WARNING) == "PERS_CERT_VALID (level=A)"
    assert subject_text(replace(INDICATOR_WARNING, dimension="")) == "PERS_CERT_VALID"


# --------------------------------------------------------------------------- codes


def test_severity_and_module_codes_are_the_ones_of_the_rules() -> None:
    assert ALL_SEVERITY_CODES == ("CRITICAL", "WARNING", "INFO")
    assert set(ALL_SEVERITY_CODES) == {severity.value for severity in Severity}
    assert ALL_MODULE_CODES == ("PERSONNEL", "INFRASTRUCTURE", "EXERCISES", "BUDGET")
    assert set(ALL_MODULE_CODES) == {module.value for module in Module}


@pytest.mark.parametrize(
    ("lang", "severities", "modules"),
    [
        (
            "en_US",
            ["Critical", "Warning", "Information"],
            ["Personnel", "Infrastructure", "Exercises", "Budget"],
        ),
        (
            "pt_BR",
            ["Crítico", "Aviso", "Informação"],
            ["Pessoal", "Infraestrutura", "Exercícios", "Orçamento"],
        ),
        (
            "es_ES",
            ["Crítico", "Advertencia", "Información"],
            ["Personal", "Infraestructura", "Ejercicios", "Presupuesto"],
        ),
    ],
)
def test_severities_and_modules_are_named_in_each_language(
    app_context: AppContext, lang: str, severities: list[str], modules: list[str]
) -> None:
    app_context.translator_manager.set_language(lang)
    assert [severity_label(code) for code in ALL_SEVERITY_CODES] == severities
    assert [module_label(code) for code in ALL_MODULE_CODES] == modules


def test_an_unknown_code_is_shown_as_itself(app_context: AppContext) -> None:
    assert severity_label("NOT_A_SEVERITY") == "NOT_A_SEVERITY"
    assert module_label("NOT_A_MODULE") == "NOT_A_MODULE"
    assert kind_message("NOT_A_KIND", MAINT_OVERDUE, "en_US") == "NOT_A_KIND"


def test_each_severity_has_an_icon_and_an_unknown_one_has_none(qapp: QApplication) -> None:
    for code in ALL_SEVERITY_CODES:
        assert not severity_icon(code).isNull(), code
    assert severity_icon("NOT_A_SEVERITY").isNull()
