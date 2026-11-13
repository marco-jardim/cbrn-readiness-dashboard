# SPDX-License-Identifier: GPL-3.0-or-later
"""Fictitious alerts written out by hand for the alerts UI tests (PLAN.md T6.3).

Dates are relative to the as-of date 2026-03-05; ``days_remaining`` is signed as in the rules
(negative when overdue or expired). The list is in the order the alert service returns: severity
first (critical, warning, information), then the due date with undated alerts last.
"""

from datetime import date

from cbrn_dashboard.domain.alerts import Alert, AlertKind, Severity, SubjectKind
from cbrn_dashboard.domain.indicators import Module

MAINT_OVERDUE = Alert(
    kind=AlertKind.MAINT_OVERDUE,
    severity=Severity.CRITICAL,
    module=Module.INFRASTRUCTURE,
    subject_kind=SubjectKind.ASSET,
    subject_ref="DEMO-A001",
    subject_id=1,
    due_on=date(2025, 3, 10),
    days_remaining=-360,
)
CERT_EXPIRED = Alert(
    kind=AlertKind.CERT_EXPIRED,
    severity=Severity.CRITICAL,
    module=Module.PERSONNEL,
    subject_kind=SubjectKind.STAFF,
    subject_ref="DEMO-P001",
    subject_id=1,
    dimension="level=A",
    due_on=date(2026, 1, 10),
    days_remaining=-54,
)
INDICATOR_CRITICAL = Alert(
    kind=AlertKind.INDICATOR_CRITICAL,
    severity=Severity.CRITICAL,
    module=Module.INFRASTRUCTURE,
    subject_kind=SubjectKind.INDICATOR,
    subject_ref="INFRA_MAINT_OVERDUE",
    dimension="type=bed",
    value=3.0,
    threshold=0.0,
)
MAINT_DUE_SOON = Alert(
    kind=AlertKind.MAINT_DUE_SOON,
    severity=Severity.WARNING,
    module=Module.INFRASTRUCTURE,
    subject_kind=SubjectKind.ASSET,
    subject_ref="DEMO-A002",
    subject_id=2,
    due_on=date(2026, 3, 25),
    days_remaining=20,
)
CERT_EXPIRING = Alert(
    kind=AlertKind.CERT_EXPIRING,
    severity=Severity.WARNING,
    module=Module.PERSONNEL,
    subject_kind=SubjectKind.STAFF,
    subject_ref="DEMO-P002",
    subject_id=2,
    dimension="level=B",
    due_on=date(2026, 4, 1),
    days_remaining=27,
)
INDICATOR_WARNING = Alert(
    kind=AlertKind.INDICATOR_WARNING,
    severity=Severity.WARNING,
    module=Module.PERSONNEL,
    subject_kind=SubjectKind.INDICATOR,
    subject_ref="PERS_CERT_VALID",
    dimension="level=A",
    value=0.75,
    threshold=0.8,
)
MAINT_SCHEDULE_UNKNOWN = Alert(
    kind=AlertKind.MAINT_SCHEDULE_UNKNOWN,
    severity=Severity.INFO,
    module=Module.INFRASTRUCTURE,
    subject_kind=SubjectKind.ASSET,
    subject_ref="DEMO-A003",
    subject_id=3,
)

#: One alert of every kind, in service order.
ALERTS: list[Alert] = [
    MAINT_OVERDUE,
    CERT_EXPIRED,
    INDICATOR_CRITICAL,
    MAINT_DUE_SOON,
    CERT_EXPIRING,
    INDICATOR_WARNING,
    MAINT_SCHEDULE_UNKNOWN,
]

#: The message of each alert of :data:`ALERTS`, per language.
MESSAGES: dict[str, list[str]] = {
    "en_US": [
        "Maintenance of asset DEMO-A001 is overdue by 360 days.",
        "The level A certificate of DEMO-P001 expired 54 days ago.",
        "Indicator Units with overdue maintenance (Type Bed) is at 3 (critical threshold: 0).",
        "Maintenance of asset DEMO-A002 is due in 20 days.",
        "The level B certificate of DEMO-P002 expires in 27 days.",
        "Indicator Staff with a valid certificate (Level A) is at 0.75 (warning threshold: 0.8).",
        "The maintenance schedule of asset DEMO-A003 is unknown.",
    ],
    "pt_BR": [
        "A manutenção do ativo DEMO-A001 está atrasada em 360 dias.",
        "O certificado de nível A de DEMO-P001 venceu há 54 dias.",
        "O indicador Unidades com manutenção atrasada (Tipo Leito) está em 3 (limite crítico: 0).",
        "A manutenção do ativo DEMO-A002 vence em 20 dias.",
        "O certificado de nível B de DEMO-P002 vence em 27 dias.",
        "O indicador Pessoal com certificado válido (Nível A) está em 0,75 (limite de aviso: 0,8).",
        "O prazo de manutenção do ativo DEMO-A003 é desconhecido.",
    ],
    "es_ES": [
        "El mantenimiento del activo DEMO-A001 está vencido desde hace 360 días.",
        "El certificado de nivel A de DEMO-P001 caducó hace 54 días.",
        "El indicador Unidades con mantenimiento vencido (Tipo Cama) está en 3 "
        "(umbral crítico: 0).",
        "El mantenimiento del activo DEMO-A002 vence en 20 días.",
        "El certificado de nivel B de DEMO-P002 caduca en 27 días.",
        "El indicador Personal con certificado válido (Nivel A) está en 0,75 "
        "(umbral de advertencia: 0,8).",
        "El plazo de mantenimiento del activo DEMO-A003 es desconocido.",
    ],
}
