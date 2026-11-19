"""The adapters of the patient import, built over the session holder.

Tests pass their own doubles through ``Container``; production gets
``build_onboarding_adapters``. Same shape as ``monitoring_adapters.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from insumap.application.onboarding.ports import (
    ImportBatchRepositoryPort,
    PatientAccountWriterPort,
    PatientDocumentVaultPort,
    StagedImportStorePort,
)
from insumap.infrastructure.onboarding.document_vault import PatientDocumentVault
from insumap.infrastructure.onboarding.repositories import (
    ImportBatchRepository,
    PatientAccountWriter,
)
from insumap.infrastructure.onboarding.staging import ProcessStagedImportStore
from insumap.infrastructure.persistence.transactions import CurrentSession
from insumap.infrastructure.security.keys import KeyRing
from insumap.shared.time import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class OnboardingAdapters:
    """Ports of the patient import, wired by ``Container``."""

    batches: ImportBatchRepositoryPort
    accounts: PatientAccountWriterPort
    vault: PatientDocumentVaultPort
    staged: StagedImportStorePort


def build_onboarding_adapters(
    *,
    current: CurrentSession,
    clock: Clock,
    app_hmac_key: bytes,
    encryption: KeyRing,
) -> OnboardingAdapters:
    """Production adapters: PostgreSQL repositories, the vault and the staging store."""
    return OnboardingAdapters(
        batches=ImportBatchRepository(current),
        accounts=PatientAccountWriter(current),
        vault=PatientDocumentVault(app_hmac_key=app_hmac_key, encryption=encryption),
        staged=ProcessStagedImportStore(clock=clock),
    )
