# SPDX-License-Identifier: GPL-3.0-or-later
"""The error report of an import words a code with the module that owns the entity (P11-03).

``TYPE_INACTIVE`` and ``INVALID_KIND`` exist in more than one module with a different meaning; a row
of a stock file must show the stock message, a row of an asset or exercise file its own.
"""

import pytest

from cbrn_dashboard.services.importer import ImportError as ImportIssue
from cbrn_dashboard.ui.exercises.labels import error_label as exercises_label
from cbrn_dashboard.ui.infrastructure.labels import error_label as infrastructure_label
from cbrn_dashboard.ui.reports.labels import error_label
from cbrn_dashboard.ui.reports.models import IssuesModel
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.stock.labels import error_label as stock_label

pytestmark = pytest.mark.ui

PROBLEM_COLUMN = 2


@pytest.mark.parametrize("entity", ["stock_item_type", "stock_lot", "stock_movement"])
def test_an_inactive_stock_type_and_a_bad_movement_kind_show_the_stock_messages(
    app_context: AppContext, entity: str
) -> None:
    assert stock_label("TYPE_INACTIVE") != infrastructure_label("TYPE_INACTIVE")
    assert stock_label("INVALID_KIND") != exercises_label("INVALID_KIND")
    assert error_label("TYPE_INACTIVE", entity) == stock_label("TYPE_INACTIVE")
    assert error_label("INVALID_KIND", entity) == stock_label("INVALID_KIND")


def test_the_other_entities_keep_the_message_of_their_own_module(app_context: AppContext) -> None:
    assert error_label("TYPE_INACTIVE", "asset") == infrastructure_label("TYPE_INACTIVE")
    assert error_label("INVALID_KIND", "exercise_edition") == exercises_label("INVALID_KIND")


def test_a_code_of_this_ui_and_an_unknown_code_do_not_depend_on_the_entity(
    app_context: AppContext,
) -> None:
    assert error_label("DUPLICATE_KEY", "stock_lot") == error_label("DUPLICATE_KEY")
    assert error_label("NOT_A_CODE", "stock_lot") == "NOT_A_CODE"
    assert error_label("NOT_A_CODE", None) == "NOT_A_CODE"
    assert error_label("TYPE_INACTIVE", "not_an_entity") == error_label("TYPE_INACTIVE")


def test_the_issues_model_words_the_problem_with_the_module_of_the_entity(
    app_context: AppContext,
) -> None:
    issues = (
        ImportIssue(2, "type_code", "TYPE_INACTIVE"),
        ImportIssue(3, "kind", "INVALID_KIND"),
    )
    model = IssuesModel()
    model.set_issues(issues, "stock_movement")
    cells = [model.index(row, PROBLEM_COLUMN).data() for row in range(model.rowCount())]
    assert cells == [stock_label("TYPE_INACTIVE"), stock_label("INVALID_KIND")]
    assert [model.index(row, 3).data() for row in range(2)] == ["TYPE_INACTIVE", "INVALID_KIND"]
    model.set_issues(issues, "exercise_edition")
    assert model.index(1, PROBLEM_COLUMN).data() == exercises_label("INVALID_KIND")
    model.set_issues(issues)  # no entity: the old order, whatever module answers first
    assert model.index(1, PROBLEM_COLUMN).data() == error_label("INVALID_KIND")
