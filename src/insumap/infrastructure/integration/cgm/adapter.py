"""CGM export reader: the only place that knows the CSV layouts of the sensors."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Final, final, override

from insumap.application.monitoring.cgm import CgmCandidate, CgmReadingSource, ParsedCgm
from insumap.domain.monitoring.glucose import GlucoseUnit, GlucoseValue
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits

COMMENT_PREFIX: Final = "#"
TIMESTAMP_COLUMN: Final = "timestamp"
MG_DL_COLUMN: Final = "glucose_mg_dl"
VALUE_COLUMN: Final = "value"
UNIT_COLUMN: Final = "unit"
FORMAT_MG_DL: Final = "INSUMAP_MG_DL"
FORMAT_WITH_UNIT: Final = "GENERIC_WITH_UNIT"
SUPPORTED_FORMATS: Final = (FORMAT_MG_DL, FORMAT_WITH_UNIT)
FORMAT_COLUMNS: Final = {
    FORMAT_MG_DL: frozenset({TIMESTAMP_COLUMN, MG_DL_COLUMN}),
    FORMAT_WITH_UNIT: frozenset({TIMESTAMP_COLUMN, VALUE_COLUMN, UNIT_COLUMN}),
}
MAX_CELL_LENGTH: Final = 64


def _validation_error(issue: str, **detail: object) -> InsumapError:
    return InsumapError(
        ErrorCode.VALIDATION_ERROR,
        detail={
            "errors": [{"field": "body", "type": issue}],
            "supported_formats": list(SUPPORTED_FORMATS),
            **detail,
        },
    )


@final
class CgmCsvAdapter(CgmReadingSource):
    """Adapts a sensor CSV (mg/dL or mmol/L) to glucose rows in mg/dL.

    Recognizes the formats of ``SUPPORTED_FORMATS`` by their header; lines that
    start with ``#`` are comments (the simulator writes its data origin there).
    A row it cannot read is counted as invalid, never guessed.

    Pattern: P06 Adapter
    """

    @override
    def read(self, content: bytes) -> ParsedCgm:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise _validation_error("invalid_encoding") from error
        lines = [
            line for line in text.splitlines() if not line.startswith(COMMENT_PREFIX)
        ]
        reader = csv.DictReader(io.StringIO("\n".join(lines)))
        header = frozenset(reader.fieldnames or ())
        found = next(
            (name for name, cols in FORMAT_COLUMNS.items() if cols <= header), None
        )
        if found is None:
            raise _validation_error("unknown_format")
        parse = self._row_parser(found)
        rows: list[CgmCandidate] = []
        invalid = 0
        for index, row in enumerate(reader):
            if index >= FieldLimits.CGM_CSV_MAX_ROWS:
                raise _validation_error("too_many_rows")
            candidate = parse(row)
            if candidate is None:
                invalid += 1
            else:
                rows.append(candidate)
        return ParsedCgm(format=found, rows=tuple(rows), invalid_rows=invalid)

    @staticmethod
    def _row_parser(
        format_name: str,
    ) -> Callable[[dict[str, str]], CgmCandidate | None]:
        def parse(row: dict[str, str]) -> CgmCandidate | None:
            cells = [row.get(column) or "" for column in _columns(format_name)]
            if any(len(cell) > MAX_CELL_LENGTH for cell in cells):
                return None
            try:
                measured_at = datetime.fromisoformat(cells[0].strip())
                number = Decimal(cells[1].strip())
            except (ValueError, InvalidOperation):
                return None
            unit = (
                GlucoseUnit.MG_DL
                if format_name == FORMAT_MG_DL
                else _unit(cells[2].strip())
            )
            if (
                measured_at.tzinfo is None
                or unit is None
                or not number.is_finite()
                or number <= 0
            ):
                return None
            return CgmCandidate(
                measured_at=measured_at,
                value=GlucoseValue.from_input(number, unit).mg_dl,
            )

        return parse


def _columns(format_name: str) -> Iterable[str]:
    if format_name == FORMAT_MG_DL:
        return (TIMESTAMP_COLUMN, MG_DL_COLUMN)
    return (TIMESTAMP_COLUMN, VALUE_COLUMN, UNIT_COLUMN)


def _unit(text: str) -> GlucoseUnit | None:
    try:
        return GlucoseUnit(text)
    except ValueError:
        return None
