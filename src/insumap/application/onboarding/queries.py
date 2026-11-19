"""Reads of the patient import: batches, rows, the error report and the template."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.onboarding.export import render_error_report, render_template
from insumap.application.onboarding.ports import (
    BatchFilter,
    ImportBatchRepositoryPort,
    ImportRowRecord,
)
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.onboarding.batch import ImportBatch
from insumap.domain.onboarding.vocabulary import RowStatus, SourceFormat


@dataclass(frozen=True, slots=True, kw_only=True)
class ListImportBatchesInput:
    """The caller, the optional source filter and the page asked for."""

    actor: Actor
    source: SourceFormat | None
    page: PageRequest


@dataclass(frozen=True, slots=True, kw_only=True)
class ListImportRowsInput:
    """The caller, the batch, the optional status filter and the page asked for."""

    actor: Actor
    batch_id: UUID
    status: RowStatus | None
    page: PageRequest


@final
class ListImportBatchesUseCase:
    """A page of the clinic's batches, most recent first."""

    def __init__(
        self, *, uow: UnitOfWorkPort, batches: ImportBatchRepositoryPort
    ) -> None:
        self._uow = uow
        self._batches = batches

    def execute(self, input: ListImportBatchesInput) -> Page[ImportBatch]:
        """The page asked for (permission first, then the query)."""
        input.actor.require(PermissionCode.IMPORT_BATCHES_READ)
        with self._uow.begin(TransactionContext.for_actor(input.actor)):
            return self._batches.list_batches(
                BatchFilter(source=input.source), input.page
            )


@final
class GetImportBatchUseCase:
    """One batch with its totals; another clinic's batch is a ``404``."""

    def __init__(
        self, *, uow: UnitOfWorkPort, batches: ImportBatchRepositoryPort
    ) -> None:
        self._uow = uow
        self._batches = batches

    def execute(self, actor: Actor, batch_id: UUID) -> ImportBatch:
        """The batch, or ``ResourceNotFoundError``."""
        actor.require(PermissionCode.IMPORT_BATCHES_READ)
        with self._uow.begin(TransactionContext.for_actor(actor)):
            batch = self._batches.get_batch(batch_id)
        if batch is None:
            raise ResourceNotFoundError
        return batch


@final
class ListImportRowsUseCase:
    """The stored rows of a batch (problems, and the created rows after a confirm)."""

    def __init__(
        self, *, uow: UnitOfWorkPort, batches: ImportBatchRepositoryPort
    ) -> None:
        self._uow = uow
        self._batches = batches

    def execute(self, input: ListImportRowsInput) -> Page[ImportRowRecord]:
        """A page of rows; the batch must be visible to the caller."""
        input.actor.require(PermissionCode.IMPORT_BATCHES_READ)
        with self._uow.begin(TransactionContext.for_actor(input.actor)):
            if self._batches.get_batch(input.batch_id) is None:
                raise ResourceNotFoundError
            return self._batches.list_rows(input.batch_id, input.status, input.page)


@final
class ExportImportErrorsUseCase:
    """The error report of a batch: row, column and cause, as CSV text."""

    def __init__(
        self, *, uow: UnitOfWorkPort, batches: ImportBatchRepositoryPort
    ) -> None:
        self._uow = uow
        self._batches = batches

    def execute(self, actor: Actor, batch_id: UUID) -> str:
        """The CSV document; the batch must be visible to the caller."""
        actor.require(PermissionCode.IMPORT_BATCHES_READ)
        with self._uow.begin(TransactionContext.for_actor(actor)):
            if self._batches.get_batch(batch_id) is None:
                raise ResourceNotFoundError
            rejected = self._batches.rejected_rows(batch_id)
        return render_error_report(rejected)


@final
class DownloadCsvTemplateUseCase:
    """The header of the patient CSV; needs the permission to import."""

    def execute(self, actor: Actor) -> str:
        """The template as CSV text."""
        actor.require(PermissionCode.PATIENTS_IMPORT)
        return render_template()
