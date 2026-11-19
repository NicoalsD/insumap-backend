"""Record glucose readings: one, an offline batch or a CGM file."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import final
from uuid import UUID

from insumap.application.common.actor import Actor
from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import (
    TransactionContext,
    UnitOfWork,
    UnitOfWorkPort,
)
from insumap.application.metrics.ports import TargetProfilePort
from insumap.application.monitoring.cgm import CgmCandidate, CgmReadingSource
from insumap.application.monitoring.data import GlucoseData
from insumap.application.monitoring.gate import OwnPatientGate, OwnScope
from insumap.application.monitoring.ports import (
    GlucoseReadingPort,
    SyncBatchPort,
    ValidationSettingsPort,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.monitoring.events import HypoglycemiaLevel
from insumap.domain.monitoring.glucose import (
    GlucoseReading,
    GlucoseUnit,
    GlucoseValue,
    ReadingSource,
)
from insumap.domain.monitoring.sync_batch import SyncBatch, SyncSource
from insumap.domain.monitoring.validation import (
    GlucoseReadingValidationHandler,
    ReadingCandidate,
    ValidationParams,
)
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.time import Clock


class RecordOutcome(StrEnum):
    """What happened to an item of a recording."""

    CREATED = "CREATED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RecordedReading:
    """The saved reading and whether this call created it (``201``) or not (``200``)."""

    reading: GlucoseReading
    outcome: RecordOutcome


@final
class GlucoseReadingRecorder:
    """Validates and saves one reading inside an open transaction.

    The shared core of the single, batch, CGM and correction flows: idempotency
    by ``client_reading_id``, the validation chain (P12) with the clinic
    parameters from the database, the hypoglycemia check against the target
    profile, the insert and the events (published after the commit).
    """

    def __init__(
        self,
        *,
        readings: GlucoseReadingPort,
        chain: GlucoseReadingValidationHandler,
        settings: ValidationSettingsPort,
        targets: TargetProfilePort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._readings = readings
        self._chain = chain
        self._settings = settings
        self._targets = targets
        self._ids = ids
        self._clock = clock

    def load_params(self, clinic_id: UUID) -> ValidationParams:
        """The thresholds of the clinic (read once per request)."""
        return self._settings.active_for(clinic_id)

    def record(
        self,
        uow: UnitOfWork,
        scope: OwnScope,
        client_reading_id: UUID,
        data: GlucoseData,
        params: ValidationParams,
        sync_batch_id: UUID | None = None,
    ) -> RecordedReading:
        """Save the reading or return the one already saved with that client id."""
        value = GlucoseValue.from_input(data.value, data.unit)
        now = self._clock.now()
        existing = self._readings.find_by_client_id(scope.patient_id, client_reading_id)
        if existing is not None:
            same = (
                existing.value_mg_dl == value.mg_dl
                and existing.measured_at == data.measured_at
                and existing.source is data.source
                and existing.context is data.context
                and existing.note == data.note
            )
            if not same:
                raise InsumapError(ErrorCode.CONFLICT)
            return RecordedReading(reading=existing, outcome=RecordOutcome.DUPLICATE)
        issues = self._chain.validate(
            ReadingCandidate(
                value_mg_dl=value.mg_dl,
                measured_at=data.measured_at,
                now=now,
                params=params,
                previous=self._readings.previous_before(
                    scope.patient_id, data.measured_at
                ),
            )
        )
        reading = GlucoseReading.record(
            reading_id=self._ids.new_id(),
            event_id=self._ids.new_id(),
            clinic_id=scope.clinic_id,
            patient_id=scope.patient_id,
            client_reading_id=client_reading_id,
            recorded_by=scope.actor.user_id,
            value=value,
            measured_at=data.measured_at,
            source=data.source,
            context=data.context,
            note=data.note,
            issues=issues,
            now=now,
            sync_batch_id=sync_batch_id,
        )
        reading = self._flag_hypoglycemia(reading)
        self._readings.add(reading)
        uow.collect(reading.pending_events)
        return RecordedReading(reading=reading, outcome=RecordOutcome.CREATED)

    def _flag_hypoglycemia(self, reading: GlucoseReading) -> GlucoseReading:
        """Add ``HypoglycemiaDetected`` when the value is under the profile limits."""
        targets = self._targets.for_patient(reading.patient_id)
        if targets is None:
            return reading
        profile = targets.profile
        if reading.value_mg_dl < profile.very_low_mg_dl:
            level = HypoglycemiaLevel.LEVEL_2
        elif reading.value_mg_dl < profile.range_low_mg_dl:
            level = HypoglycemiaLevel.LEVEL_1
        else:
            return reading
        return reading.with_hypoglycemia(
            level, event_id=self._ids.new_id(), now=self._clock.now()
        )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RecordGlucoseReadingInput:
    actor: Actor
    client_reading_id: UUID
    data: GlucoseData


@final
class RecordGlucoseReadingUseCase:
    """``POST /readings``: record one glucose reading of the patient."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnPatientGate,
        recorder: GlucoseReadingRecorder,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._recorder = recorder

    def execute(self, input: RecordGlucoseReadingInput) -> RecordedReading:
        """Save the reading (``CREATED``) or return the original (``DUPLICATE``)."""
        with self._uow.begin(TransactionContext.for_actor(input.actor)) as uow:
            scope = self._gate.enter(input.actor, PermissionCode.GLUCOSE_WRITE_OWN)
            params = self._recorder.load_params(scope.clinic_id)
            recorded = self._recorder.record(
                uow, scope, input.client_reading_id, input.data, params
            )
            uow.commit()
        return recorded


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class BatchItem:
    client_reading_id: UUID
    data: GlucoseData


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class BatchItemResult:
    client_reading_id: UUID
    outcome: RecordOutcome
    reading_id: UUID | None = None
    reason_code: ErrorCode | None = None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RecordGlucoseReadingsBatchInput:
    actor: Actor
    items: Sequence[BatchItem]


@final
class RecordGlucoseReadingsBatchUseCase:
    """``POST /readings/batch``: the offline queue. Valid items are saved anyway."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnPatientGate,
        recorder: GlucoseReadingRecorder,
        batches: SyncBatchPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._recorder = recorder
        self._batches = batches
        self._ids = ids
        self._clock = clock

    def execute(self, input: RecordGlucoseReadingsBatchInput) -> list[BatchItemResult]:
        """One result per item, in the same order; the batch row keeps the counts."""
        with self._uow.begin(TransactionContext.for_actor(input.actor)) as uow:
            scope = self._gate.enter(input.actor, PermissionCode.GLUCOSE_WRITE_OWN)
            params = self._recorder.load_params(scope.clinic_id)
            batch_id = self._ids.new_id()
            results = [
                self._record_item(uow, scope, item, params, batch_id)
                for item in input.items
            ]
            self._batches.add(
                _batch(
                    batch_id,
                    scope,
                    SyncSource.OFFLINE_QUEUE,
                    results,
                    self._clock.now(),
                    None,
                )
            )
            uow.commit()
        return results

    def _record_item(
        self,
        uow: UnitOfWork,
        scope: OwnScope,
        item: BatchItem,
        params: ValidationParams,
        batch_id: UUID,
    ) -> BatchItemResult:
        try:
            recorded = self._recorder.record(
                uow, scope, item.client_reading_id, item.data, params, batch_id
            )
        except InsumapError as error:
            return BatchItemResult(
                client_reading_id=item.client_reading_id,
                outcome=RecordOutcome.REJECTED,
                reason_code=error.code,
            )
        return BatchItemResult(
            client_reading_id=item.client_reading_id,
            outcome=recorded.outcome,
            reading_id=recorded.reading.id,
        )


def _batch(
    batch_id: UUID,
    scope: OwnScope,
    source: SyncSource,
    results: Sequence[BatchItemResult],
    now: datetime,
    file_sha256: str | None,
) -> SyncBatch:
    count = {outcome: 0 for outcome in RecordOutcome}
    for result in results:
        count[result.outcome] += 1
    return SyncBatch(
        id=batch_id,
        clinic_id=scope.clinic_id,
        patient_id=scope.patient_id,
        source=source,
        submitted_by=scope.actor.user_id,
        total_items=len(results),
        created_count=count[RecordOutcome.CREATED],
        duplicate_count=count[RecordOutcome.DUPLICATE],
        rejected_count=count[RecordOutcome.REJECTED],
        received_at=now,
        file_sha256=file_sha256,
    )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ImportCgmReadingsInput:
    actor: Actor
    content: bytes


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CgmImportResult:
    format: str
    created: int
    duplicates: int
    rejected: int


@final
class ImportCgmReadingsUseCase:
    """``POST /readings/cgm-import``: a sensor export read by a P06 adapter."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnPatientGate,
        recorder: GlucoseReadingRecorder,
        batches: SyncBatchPort,
        source: CgmReadingSource,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._recorder = recorder
        self._batches = batches
        self._source = source
        self._ids = ids
        self._clock = clock

    def execute(self, input: ImportCgmReadingsInput) -> CgmImportResult:
        """Read the file, validate every row in the chain and save the valid ones."""
        with self._uow.begin(TransactionContext.for_actor(input.actor)) as uow:
            scope = self._gate.enter(input.actor, PermissionCode.GLUCOSE_WRITE_OWN)
            parsed = self._source.read(input.content)
            params = self._recorder.load_params(scope.clinic_id)
            batch_id = self._ids.new_id()
            results = [
                self._record_row(uow, scope, row, params, batch_id)
                for row in parsed.rows
            ]
            self._batches.add(
                _batch(
                    batch_id,
                    scope,
                    SyncSource.CGM_CSV,
                    results,
                    self._clock.now(),
                    hashlib.sha256(input.content).hexdigest(),
                )
            )
            uow.commit()
        counts = [result.outcome for result in results]
        return CgmImportResult(
            format=parsed.format,
            created=counts.count(RecordOutcome.CREATED),
            duplicates=counts.count(RecordOutcome.DUPLICATE),
            rejected=counts.count(RecordOutcome.REJECTED) + parsed.invalid_rows,
        )

    def _record_row(
        self,
        uow: UnitOfWork,
        scope: OwnScope,
        row: CgmCandidate,
        params: ValidationParams,
        batch_id: UUID,
    ) -> BatchItemResult:
        client_id = row.client_reading_id(scope.patient_id)
        data = GlucoseData(
            value=row.value,
            unit=GlucoseUnit.MG_DL,
            measured_at=row.measured_at,
            source=ReadingSource.CGM,
        )
        try:
            recorded = self._recorder.record(
                uow, scope, client_id, data, params, batch_id
            )
        except InsumapError as error:
            return BatchItemResult(
                client_reading_id=client_id,
                outcome=RecordOutcome.REJECTED,
                reason_code=error.code,
            )
        return BatchItemResult(
            client_reading_id=client_id,
            outcome=recorded.outcome,
            reading_id=recorded.reading.id,
        )
