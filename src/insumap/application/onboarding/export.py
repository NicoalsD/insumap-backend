"""CSV documents of the import: the column template and the error report.

Every cell that a spreadsheet could read as a formula is prefixed with an
apostrophe. The report never carries personal data: it names a row, a column
and an issue code.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from typing import Final

from insumap.application.onboarding.ports import ImportRowRecord
from insumap.domain.onboarding.vocabulary import CSV_COLUMNS

FORMULA_TRIGGERS: Final[tuple[str, ...]] = ("=", "+", "-", "@", "\t", "\r")
"""Leading characters that spreadsheets evaluate as formulas (OWASP CSV injection)."""
GUARD: Final = "'"


def csv_cell(value: object) -> str:
    """Text of one cell, neutralized when a spreadsheet would run it as a formula."""
    text = "" if value is None else str(value)
    return f"{GUARD}{text}" if text.startswith(FORMULA_TRIGGERS) else text


def render_csv(header: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    """A CSV document with the header and the rows, every cell neutralized."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([csv_cell(cell) for cell in row])
    return buffer.getvalue()


def render_template() -> str:
    """The header of a patient CSV: the columns the import reads."""
    return render_csv(CSV_COLUMNS, [])


ERROR_REPORT_HEADER: Final = ("row", "column", "cause")


def render_error_report(rows: Iterable[ImportRowRecord]) -> str:
    """One line per issue of every rejected row."""
    lines = [
        (record.row_number, issue.column, issue.value)
        for record in rows
        for issue in record.issues
    ]
    return render_csv(ERROR_REPORT_HEADER, lines)
