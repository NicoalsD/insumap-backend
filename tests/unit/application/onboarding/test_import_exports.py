"""CSV documents of the import: formula guard, template and error report."""

from uuid import UUID

import pytest

from insumap.application.onboarding.export import (
    csv_cell,
    render_error_report,
    render_template,
)
from insumap.application.onboarding.ports import ImportRowRecord
from insumap.domain.onboarding.vocabulary import CSV_COLUMNS, ImportIssue, RowStatus


@pytest.mark.parametrize("value", ["=HYPERLINK(1)", "+1", "-2", "@cmd", "\tx", "\rx"])
def test_cells_that_spreadsheets_run_as_formulas_are_prefixed(value: str) -> None:
    assert csv_cell(value) == "'" + value


def test_ordinary_cells_are_left_alone() -> None:
    assert csv_cell("Pedro Paciente") == "Pedro Paciente"
    assert csv_cell(None) == ""


def test_the_template_has_the_columns_of_the_import() -> None:
    assert render_template().strip().split(",") == list(CSV_COLUMNS)


def test_the_error_report_names_row_column_and_cause_only() -> None:
    record = ImportRowRecord(
        row_id=UUID(int=1),
        row_number=7,
        resource_type=None,
        status=RowStatus.REJECTED,
        issues=(ImportIssue.BIRTH_DATE_MISSING, ImportIssue.MRN_INVALID),
        patient_id=None,
    )

    report = render_error_report([record])

    assert report.splitlines() == [
        "row,column,cause",
        "7,birth_date,BIRTH_DATE_MISSING",
        "7,mrn,MRN_INVALID",
    ]
