"""Single, batch and CGM recording: idempotency, validation and events."""

from datetime import timedelta
from decimal import Decimal

import pytest

from insumap.application.monitoring.data import GlucoseData
from insumap.application.monitoring.glucose import (
    BatchItem,
    CgmImportResult,
    ImportCgmReadingsInput,
    ImportCgmReadingsUseCase,
    RecordGlucoseReadingInput,
    RecordGlucoseReadingsBatchInput,
    RecordGlucoseReadingsBatchUseCase,
    RecordGlucoseReadingUseCase,
    RecordOutcome,
)
from insumap.domain.identity.errors import ConsentRequiredError, PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.monitoring.errors import GlucoseOutOfRangeError
from insumap.domain.monitoring.events import (
    GlucoseReadingRecorded,
    HypoglycemiaDetected,
    HypoglycemiaLevel,
)
from insumap.domain.monitoring.glucose import (
    GlucoseUnit,
    IssueCode,
    ReadingSource,
    ReadingStatus,
)
from insumap.domain.monitoring.sync_batch import SyncSource
from insumap.infrastructure.integration.cgm.adapter import CgmCsvAdapter
from insumap.shared.errors import ErrorCode, InsumapError
from tests.support.monitoring_factories import NOW, PATIENT_ID, uid
from tests.support.monitoring_fakes import RecordsWorld, doctor_actor, patient_actor

CLIENT_ID = uid(777)


def data(value: str = "110", **overrides: object) -> GlucoseData:
    fields: dict[str, object] = {
        "value": Decimal(value),
        "unit": GlucoseUnit.MG_DL,
        "measured_at": NOW,
        "source": ReadingSource.SMBG,
    }
    return GlucoseData(**{**fields, **overrides})  # type: ignore[arg-type]


@pytest.fixture
def world() -> RecordsWorld:
    return RecordsWorld()


def single(world: RecordsWorld) -> RecordGlucoseReadingUseCase:
    return RecordGlucoseReadingUseCase(
        uow=world.uow, gate=world.own_gate, recorder=world.recorder
    )


def test_records_a_reading_and_publishes_the_event_after_commit(
    world: RecordsWorld,
) -> None:
    recorded = single(world).execute(
        RecordGlucoseReadingInput(
            actor=patient_actor(), client_reading_id=CLIENT_ID, data=data()
        )
    )

    assert recorded.outcome is RecordOutcome.CREATED
    assert recorded.reading.status is ReadingStatus.ACCEPTED
    assert recorded.reading.patient_id == PATIENT_ID
    assert world.uow.commits == 1
    assert [type(e) for e in world.uow.published] == [GlucoseReadingRecorded]


def test_the_patient_comes_from_the_token_and_mmol_is_converted(
    world: RecordsWorld,
) -> None:
    recorded = single(world).execute(
        RecordGlucoseReadingInput(
            actor=patient_actor(),
            client_reading_id=CLIENT_ID,
            data=data("5.5", unit=GlucoseUnit.MMOL_L),
        )
    )

    assert recorded.reading.value_mg_dl == Decimal("99.1")
    assert world.readings.rows[0].patient_id == PATIENT_ID


def test_repeating_the_same_content_returns_the_original_without_duplicating(
    world: RecordsWorld,
) -> None:
    first = single(world).execute(
        RecordGlucoseReadingInput(
            actor=patient_actor(), client_reading_id=CLIENT_ID, data=data()
        )
    )
    again = single(world).execute(
        RecordGlucoseReadingInput(
            actor=patient_actor(), client_reading_id=CLIENT_ID, data=data()
        )
    )

    assert again.outcome is RecordOutcome.DUPLICATE
    assert again.reading.id == first.reading.id
    assert len(world.readings.rows) == 1
    assert len(world.uow.published) == 1


def test_the_same_client_id_with_other_content_is_a_conflict(
    world: RecordsWorld,
) -> None:
    single(world).execute(
        RecordGlucoseReadingInput(
            actor=patient_actor(), client_reading_id=CLIENT_ID, data=data("110")
        )
    )

    with pytest.raises(InsumapError) as caught:
        single(world).execute(
            RecordGlucoseReadingInput(
                actor=patient_actor(), client_reading_id=CLIENT_ID, data=data("111")
            )
        )

    assert caught.value.code is ErrorCode.CONFLICT


def test_an_out_of_range_value_is_not_saved(world: RecordsWorld) -> None:
    with pytest.raises(GlucoseOutOfRangeError):
        single(world).execute(
            RecordGlucoseReadingInput(
                actor=patient_actor(), client_reading_id=CLIENT_ID, data=data("9")
            )
        )

    assert world.readings.rows == []
    assert world.uow.commits == 0


def test_a_suspicious_reading_is_saved_flagged_never_hidden(
    world: RecordsWorld,
) -> None:
    single(world).execute(
        RecordGlucoseReadingInput(
            actor=patient_actor(),
            client_reading_id=uid(1),
            data=data("110", measured_at=NOW - timedelta(minutes=1)),
        )
    )

    recorded = single(world).execute(
        RecordGlucoseReadingInput(
            actor=patient_actor(), client_reading_id=uid(2), data=data("110")
        )
    )

    assert recorded.reading.status is ReadingStatus.FLAGGED
    assert recorded.reading.issues == (IssueCode.DUPLICATE_SUSPECTED,)


@pytest.mark.parametrize(
    ("value", "level"),
    [("65", HypoglycemiaLevel.LEVEL_1), ("50", HypoglycemiaLevel.LEVEL_2)],
)
def test_a_value_under_the_profile_limits_publishes_hypoglycemia(
    world: RecordsWorld, value: str, level: HypoglycemiaLevel
) -> None:
    single(world).execute(
        RecordGlucoseReadingInput(
            actor=patient_actor(), client_reading_id=CLIENT_ID, data=data(value)
        )
    )

    hypo = [e for e in world.uow.published if isinstance(e, HypoglycemiaDetected)]
    assert [e.level for e in hypo] == [level]


def test_the_profile_decides_what_hypoglycemia_is(world: RecordsWorld) -> None:
    assert world.targets.targets is not None
    profile = world.targets.targets.profile
    # The limit at 70 is a value of the profile: a value equal to it is not low.
    single(world).execute(
        RecordGlucoseReadingInput(
            actor=patient_actor(),
            client_reading_id=CLIENT_ID,
            data=data(str(profile.range_low_mg_dl)),
        )
    )

    assert not any(isinstance(e, HypoglycemiaDetected) for e in world.uow.published)


def test_no_profile_means_no_hypoglycemia_event(world: RecordsWorld) -> None:
    world.targets.targets = None

    single(world).execute(
        RecordGlucoseReadingInput(
            actor=patient_actor(), client_reading_id=CLIENT_ID, data=data("40")
        )
    )

    assert len(world.uow.published) == 1


def test_permission_and_consent_are_required(world: RecordsWorld) -> None:
    no_permission = patient_actor(permissions=frozenset())
    with pytest.raises(PermissionDeniedError):
        single(world).execute(
            RecordGlucoseReadingInput(
                actor=no_permission, client_reading_id=CLIENT_ID, data=data()
            )
        )
    world.consents.accepted = False
    with pytest.raises(ConsentRequiredError):
        single(world).execute(
            RecordGlucoseReadingInput(
                actor=patient_actor(), client_reading_id=CLIENT_ID, data=data()
            )
        )
    assert PermissionCode.GLUCOSE_WRITE_OWN in patient_actor().permissions


def test_a_doctor_cannot_record_as_a_patient(world: RecordsWorld) -> None:
    with pytest.raises(PermissionDeniedError):
        single(world).execute(
            RecordGlucoseReadingInput(
                actor=doctor_actor(), client_reading_id=CLIENT_ID, data=data()
            )
        )


def batch(world: RecordsWorld) -> RecordGlucoseReadingsBatchUseCase:
    return RecordGlucoseReadingsBatchUseCase(
        uow=world.uow,
        gate=world.own_gate,
        recorder=world.recorder,
        batches=world.batches,
        ids=world.ids,
        clock=world.clock,
    )


def test_a_batch_saves_the_valid_items_and_reports_each_one(
    world: RecordsWorld,
) -> None:
    items = [
        BatchItem(client_reading_id=uid(1), data=data("100")),
        BatchItem(client_reading_id=uid(2), data=data("9")),
        BatchItem(
            client_reading_id=uid(3),
            data=data("120", measured_at=NOW - timedelta(hours=1)),
        ),
    ]

    results = batch(world).execute(
        RecordGlucoseReadingsBatchInput(actor=patient_actor(), items=items)
    )

    assert [r.outcome for r in results] == [
        RecordOutcome.CREATED,
        RecordOutcome.REJECTED,
        RecordOutcome.CREATED,
    ]
    assert results[1].reason_code is ErrorCode.GLUCOSE_OUT_OF_RANGE
    assert results[1].reading_id is None
    assert [r.client_reading_id for r in results] == [uid(1), uid(2), uid(3)]
    saved = world.batches.batches[0]
    assert (saved.total_items, saved.created_count, saved.rejected_count) == (3, 2, 1)
    assert saved.source is SyncSource.OFFLINE_QUEUE
    assert all(r.sync_batch_id == saved.id for r in world.readings.rows)


def test_resending_the_batch_returns_duplicates_without_duplicating(
    world: RecordsWorld,
) -> None:
    items = [BatchItem(client_reading_id=uid(1), data=data("100"))]
    request = RecordGlucoseReadingsBatchInput(actor=patient_actor(), items=items)
    batch(world).execute(request)

    results = batch(world).execute(request)

    assert results[0].outcome is RecordOutcome.DUPLICATE
    assert len(world.readings.rows) == 1
    assert world.batches.batches[1].duplicate_count == 1


def test_a_conflicting_item_is_rejected_with_conflict(world: RecordsWorld) -> None:
    request = RecordGlucoseReadingsBatchInput(
        actor=patient_actor(),
        items=[BatchItem(client_reading_id=uid(1), data=data("100"))],
    )
    batch(world).execute(request)
    changed = RecordGlucoseReadingsBatchInput(
        actor=patient_actor(),
        items=[BatchItem(client_reading_id=uid(1), data=data("101"))],
    )

    results = batch(world).execute(changed)

    assert results[0].outcome is RecordOutcome.REJECTED
    assert results[0].reason_code is ErrorCode.CONFLICT


def cgm(world: RecordsWorld) -> ImportCgmReadingsUseCase:
    return ImportCgmReadingsUseCase(
        uow=world.uow,
        gate=world.own_gate,
        recorder=world.recorder,
        batches=world.batches,
        source=CgmCsvAdapter(),
        ids=world.ids,
        clock=world.clock,
    )


def import_csv(world: RecordsWorld, content: bytes) -> CgmImportResult:
    return cgm(world).execute(
        ImportCgmReadingsInput(actor=patient_actor(), content=content)
    )


CSV = (
    b"timestamp,glucose_mg_dl\n"
    b"2026-11-19T11:00:00+00:00,100\n"
    b"2026-11-19T11:05:00+00:00,104\n"
    b"2026-11-19T11:10:00+00:00,9\n"
    b"garbage,1\n"
)


def test_a_cgm_import_counts_created_rejected_and_invalid_rows(
    world: RecordsWorld,
) -> None:
    result = cgm(world).execute(
        ImportCgmReadingsInput(actor=patient_actor(), content=CSV)
    )

    assert (result.format, result.created, result.duplicates, result.rejected) == (
        "INSUMAP_MG_DL",
        2,
        0,
        2,
    )
    assert {r.source for r in world.readings.rows} == {ReadingSource.CGM}
    batch_row = world.batches.batches[0]
    assert batch_row.source is SyncSource.CGM_CSV
    assert batch_row.file_sha256 is not None
    assert len(batch_row.file_sha256) == 64


def test_importing_the_same_file_again_creates_nothing(world: RecordsWorld) -> None:
    cgm(world).execute(ImportCgmReadingsInput(actor=patient_actor(), content=CSV))

    again = cgm(world).execute(
        ImportCgmReadingsInput(actor=patient_actor(), content=CSV)
    )

    assert (again.created, again.duplicates) == (0, 2)
    assert len(world.readings.rows) == 2


def test_an_unknown_cgm_format_saves_nothing(world: RecordsWorld) -> None:
    with pytest.raises(InsumapError):
        cgm(world).execute(
            ImportCgmReadingsInput(actor=patient_actor(), content=b"a,b\n1,2\n")
        )

    assert world.readings.rows == []
    assert world.batches.batches == []
