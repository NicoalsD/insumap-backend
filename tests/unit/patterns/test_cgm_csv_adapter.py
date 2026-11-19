"""P06 Adapter: the CGM CSV layouts become glucose rows in mg/dL."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from insumap.infrastructure.integration.cgm.adapter import (
    FORMAT_MG_DL,
    FORMAT_WITH_UNIT,
    CgmCsvAdapter,
)
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits

ADAPTER = CgmCsvAdapter()


def test_reads_the_mg_dl_layout_skipping_comment_lines() -> None:
    csv_text = (
        '# data_origin=SIMULATED; label="Datos simulados"\n'
        "timestamp,glucose_mg_dl\n"
        "2026-11-19T10:00:00-05:00,110.4\n"
        "2026-11-19T10:05:00-05:00,112\n"
    )

    parsed = ADAPTER.read(csv_text.encode())

    assert parsed.format == FORMAT_MG_DL
    assert [row.value for row in parsed.rows] == [Decimal("110.4"), Decimal("112.0")]
    assert parsed.rows[0].measured_at == datetime.fromisoformat(
        "2026-11-19T15:00:00+00:00"
    )
    assert parsed.invalid_rows == 0


def test_converts_mmol_l_to_mg_dl() -> None:
    parsed = ADAPTER.read(
        b"timestamp,value,unit\n2026-11-19T10:00:00+00:00,5.5,mmol/L\n"
        b"2026-11-19T10:05:00+00:00,100,mg/dL\n"
    )

    assert parsed.format == FORMAT_WITH_UNIT
    assert [row.value for row in parsed.rows] == [Decimal("99.1"), Decimal("100.0")]


def test_counts_unreadable_rows_as_invalid_instead_of_guessing() -> None:
    parsed = ADAPTER.read(
        b"timestamp,value,unit\n"
        b"2026-11-19T10:00:00+00:00,abc,mg/dL\n"
        b"2026-11-19T10:00:00,100,mg/dL\n"
        b"2026-11-19T10:00:00+00:00,100,furlongs\n"
        b"2026-11-19T10:00:00+00:00,-3,mg/dL\n"
        b"2026-11-19T10:00:00+00:00,NaN,mg/dL\n"
        b"not a date,100,mg/dL\n"
        b"2026-11-19T10:00:00+00:00,100,mg/dL\n"
    )

    assert len(parsed.rows) == 1
    assert parsed.invalid_rows == 6


def test_an_unknown_layout_lists_the_supported_formats() -> None:
    with pytest.raises(InsumapError) as caught:
        ADAPTER.read(b"a,b\n1,2\n")

    assert caught.value.code is ErrorCode.VALIDATION_ERROR
    assert caught.value.detail["supported_formats"] == [FORMAT_MG_DL, FORMAT_WITH_UNIT]


def test_bytes_that_are_not_utf8_are_a_validation_error() -> None:
    with pytest.raises(InsumapError) as caught:
        ADAPTER.read(b"\xff\xfe\x00")

    assert caught.value.code is ErrorCode.VALIDATION_ERROR


def test_too_many_rows_is_a_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FieldLimits, "CGM_CSV_MAX_ROWS", 2)
    rows = "".join(f"2026-11-19T10:0{n}:00+00:00,100\n" for n in range(3))

    with pytest.raises(InsumapError):
        ADAPTER.read(("timestamp,glucose_mg_dl\n" + rows).encode())


def test_the_client_id_of_a_row_is_stable_per_patient_and_instant() -> None:
    row = ADAPTER.read(
        b"timestamp,glucose_mg_dl\n2026-11-19T10:00:00+00:00,100\n"
    ).rows[0]
    patient = UUID(int=1)

    assert row.client_reading_id(patient) == row.client_reading_id(patient)
    assert row.client_reading_id(patient) != row.client_reading_id(UUID(int=2))
    assert row.measured_at == datetime(2026, 11, 19, 10, tzinfo=UTC)
