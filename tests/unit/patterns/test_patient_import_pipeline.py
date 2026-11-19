"""P20 Template Method: the import pipeline runs its steps in a fixed order."""

from pathlib import Path
from typing import override
from uuid import UUID

import pytest

from insumap.application.onboarding.integration import ClinicIntegrationFactory
from insumap.application.onboarding.pipeline import ImportRequest, PatientImportPipeline
from insumap.domain.onboarding.vocabulary import ImportIssue, RowStatus
from insumap.infrastructure.integration.csv.family import CsvIntegrationFactory
from insumap.infrastructure.integration.csv.pipeline import CsvPatientImportPipeline
from insumap.infrastructure.integration.fhir.pipeline import FhirPatientImportPipeline
from insumap.shared.errors import InsumapError
from tests.support.identity_world import CLINIC
from tests.support.onboarding_fakes import (
    FakeAccountWriter,
    FakeBatchRepository,
    FakeDocumentVault,
    FixedClock,
    SequentialIds,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
ADMIN = UUID(int=500)


class RecordingPipeline(PatientImportPipeline):
    """A pipeline that records its primitive steps, to check their order."""

    def __init__(self, batches: FakeBatchRepository) -> None:
        super().__init__(
            batches=batches,
            vault=FakeDocumentVault(),
            ids=SequentialIds(),
            clock=FixedClock(),
        )
        self.calls: list[str] = []

    @override
    def read(self, content: bytes) -> bytes:
        self.calls.append("read")
        return content

    @override
    def integration_factory(self) -> ClinicIntegrationFactory:
        self.calls.append("integration_factory")
        return CsvIntegrationFactory()


def request(content: bytes, *, demo: bool = False) -> ImportRequest:
    return ImportRequest(
        clinic_id=CLINIC.clinic_id,
        created_by=ADMIN,
        clinic_is_demo=demo,
        content=content,
        file_sha256="0" * 64,
    )


def batches() -> FakeBatchRepository:
    return FakeBatchRepository(accounts=FakeAccountWriter())


def test_the_steps_run_in_order_and_the_family_is_asked_once() -> None:
    pipeline = RecordingPipeline(batches())

    pipeline.run(request((FIXTURES / "pacientes_validos.csv").read_bytes()))

    assert pipeline.calls == ["read", "integration_factory"]


def test_a_bad_row_does_not_stop_the_others() -> None:
    store = batches()
    pipeline = CsvPatientImportPipeline(
        batches=store,
        vault=FakeDocumentVault(),
        ids=SequentialIds(),
        clock=FixedClock(),
    )

    prepared = pipeline.run(
        request((FIXTURES / "pacientes_con_errores.csv").read_bytes())
    )

    # Valid rows are only staged until the confirmation; the others are stored now.
    assert [patient.row_number for patient in prepared.staged] == [1]
    stored = {row.row_number: row.status for _, _, row, _ in store.rows}
    assert stored == {
        2: RowStatus.REJECTED,
        3: RowStatus.REJECTED,
        4: RowStatus.SKIPPED_DUPLICATE,
        5: RowStatus.REJECTED,
    }
    assert prepared.batch.totals.total == 5
    assert prepared.batch.totals.valid == 1
    assert prepared.batch.totals.error == 3
    assert prepared.batch.totals.skipped == 1


def test_a_repeated_mrn_inside_the_file_is_a_duplicate_with_its_issue() -> None:
    store = batches()
    pipeline = CsvPatientImportPipeline(
        batches=store,
        vault=FakeDocumentVault(),
        ids=SequentialIds(),
        clock=FixedClock(),
    )

    pipeline.run(request((FIXTURES / "pacientes_con_errores.csv").read_bytes()))

    duplicate = next(row for _, _, row, _ in store.rows if row.row_number == 4)
    assert ImportIssue.MRN_DUPLICATE in duplicate.issues


def test_fhir_bundle_stages_only_its_valid_patients() -> None:
    store = batches()
    pipeline = FhirPatientImportPipeline(
        batches=store,
        vault=FakeDocumentVault(),
        ids=SequentialIds(),
        clock=FixedClock(),
    )

    prepared = pipeline.run(
        request((FIXTURES / "bundle_fhir_valido.json").read_bytes())
    )

    assert [patient.mrn for patient in prepared.staged] == [
        "DEMO-000020",
        "DEMO-000021",
    ]
    unsupported = [
        row for _, _, row, _ in store.rows if row.status is RowStatus.UNSUPPORTED
    ]
    assert len(unsupported) == 1


def test_a_simulated_bundle_is_refused_outside_a_demo_clinic() -> None:
    pipeline = FhirPatientImportPipeline(
        batches=batches(),
        vault=FakeDocumentVault(),
        ids=SequentialIds(),
        clock=FixedClock(),
    )

    with pytest.raises(InsumapError) as error:
        pipeline.run(
            request((FIXTURES / "bundle_fhir_simulado.json").read_bytes(), demo=False)
        )

    assert error.value.detail == {
        "errors": [{"field": "body", "type": "simulated_data_not_allowed"}]
    }


def test_a_simulated_bundle_is_accepted_in_a_demo_clinic() -> None:
    pipeline = FhirPatientImportPipeline(
        batches=batches(),
        vault=FakeDocumentVault(),
        ids=SequentialIds(),
        clock=FixedClock(),
    )

    prepared = pipeline.run(
        request((FIXTURES / "bundle_fhir_simulado.json").read_bytes(), demo=True)
    )

    assert prepared.batch.simulated
    assert len(prepared.staged) == 1


def test_an_empty_file_is_a_422() -> None:
    pipeline = CsvPatientImportPipeline(
        batches=batches(),
        vault=FakeDocumentVault(),
        ids=SequentialIds(),
        clock=FixedClock(),
    )

    with pytest.raises(InsumapError):
        pipeline.run(request(b""))
