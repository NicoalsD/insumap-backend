"""The adapters behind the treatment ports, built over the session holder."""

from __future__ import annotations

from dataclasses import dataclass

from insumap.application.metrics.ports import TargetProfilePort
from insumap.application.treatment.ports import (
    ProtocolTemplateRepositoryPort,
    TargetProfileLookupPort,
    TreatmentPlanRepositoryPort,
    TreatmentPlanSnapshotPort,
)
from insumap.infrastructure.persistence.transactions import CurrentSession
from insumap.infrastructure.persistence.treatment_repositories import (
    ProtocolTemplateRepository,
    TreatmentPlanRepository,
    TreatmentPlanSnapshotRepository,
    TreatmentTargetLookup,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class TreatmentAdapters:
    """Ports of the treatment plans slice, wired by ``Container``.

    Tests pass their own doubles; production gets ``build_treatment_adapters``.
    """

    templates: ProtocolTemplateRepositoryPort
    plans: TreatmentPlanRepositoryPort
    snapshots: TreatmentPlanSnapshotPort
    targets: TargetProfileLookupPort


def build_treatment_adapters(
    *, current: CurrentSession, metrics_targets: TargetProfilePort
) -> TreatmentAdapters:
    """The production adapters: PostgreSQL under row level security."""
    return TreatmentAdapters(
        templates=ProtocolTemplateRepository(current),
        plans=TreatmentPlanRepository(current),
        snapshots=TreatmentPlanSnapshotRepository(current),
        targets=TreatmentTargetLookup(metrics_targets),
    )
