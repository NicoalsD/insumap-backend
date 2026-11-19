"""The adapters behind the goals and reminders ports, built over the session holder."""

from __future__ import annotations

from dataclasses import dataclass

from insumap.application.reminders.ports import ReminderRepositoryPort
from insumap.application.targets.ports import (
    PatientTargetAssignmentPort,
    TargetProfileCatalogPort,
)
from insumap.infrastructure.persistence.reminder_repository import ReminderRepository
from insumap.infrastructure.persistence.target_repositories import (
    PatientTargetAssignmentRepository,
    TargetProfileCatalogRepository,
)
from insumap.infrastructure.persistence.transactions import CurrentSession


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetsAdapters:
    """Ports of the target profiles and the reminders, wired by ``Container``.

    Tests pass their own doubles; production gets ``build_targets_adapters``.
    """

    catalog: TargetProfileCatalogPort
    assignments: PatientTargetAssignmentPort
    reminders: ReminderRepositoryPort


def build_targets_adapters(*, current: CurrentSession) -> TargetsAdapters:
    """Build the production adapters over the session holder of the process."""
    return TargetsAdapters(
        catalog=TargetProfileCatalogRepository(current),
        assignments=PatientTargetAssignmentRepository(current),
        reminders=ReminderRepository(current),
    )
