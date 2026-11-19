"""The adapters behind the patient record ports, built over the session holder."""

from __future__ import annotations

from dataclasses import dataclass

from insumap.application.access.ports import PatientRecordPort
from insumap.application.common.unit_of_work import TransactionFactory
from insumap.application.metrics.ports import TargetProfilePort
from insumap.application.monitoring.cgm import CgmReadingSource
from insumap.application.monitoring.ports import (
    ActivePlanPort,
    ClinicalRecordPort,
    GlucoseReadingPort,
    SymptomCatalogPort,
    SyncBatchPort,
    TimelinePort,
    ValidationSettingsPort,
)
from insumap.application.monitoring.queries import ExportFormat, TimelineExporterPort
from insumap.domain.access.policy import PatientAccessPolicy
from insumap.infrastructure.access.access_proxy import PatientRecordAccessProxy
from insumap.infrastructure.access.audit_decorator import PhiAccessAuditDecorator
from insumap.infrastructure.access.patient_record_repository import (
    PatientRecordRepository,
)
from insumap.infrastructure.access.sql_data_access_log import SqlDataAccessLog
from insumap.infrastructure.integration.cgm.adapter import CgmCsvAdapter
from insumap.infrastructure.monitoring.exporters import (
    CsvTimelineExporter,
    FhirTimelineExporter,
)
from insumap.infrastructure.persistence.care_repositories import (
    ActivePlanRepository,
    SymptomCatalogRepository,
    ValidationSettingsRepository,
)
from insumap.infrastructure.persistence.care_team_repository import (
    CareTeamRepository,
    PatientDirectoryRepository,
)
from insumap.infrastructure.persistence.metrics_repositories import (
    TargetProfileRepository,
)
from insumap.infrastructure.persistence.monitoring_repositories import (
    ClinicalRecordRepository,
    GlucoseReadingRepository,
    SyncBatchRepository,
    TimelineRepository,
)
from insumap.infrastructure.persistence.transactions import CurrentSession
from insumap.shared.time import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class MonitoringAdapters:
    """Ports of the patient records slice, wired by ``Container``.

    ``patient_records`` is the audited access chain (P09 over P11), the only
    way a doctor reaches a patient. Tests pass their own doubles; production
    gets ``build_monitoring_adapters``.
    """

    patient_records: PatientRecordPort
    readings: GlucoseReadingPort
    clinical_records: ClinicalRecordPort
    sync_batches: SyncBatchPort
    timeline: TimelinePort
    validation: ValidationSettingsPort
    targets: TargetProfilePort
    symptoms: SymptomCatalogPort
    active_plans: ActivePlanPort
    cgm: CgmReadingSource
    exporters: dict[ExportFormat, TimelineExporterPort]


def build_monitoring_adapters(
    *,
    current: CurrentSession,
    clock: Clock,
    transactions: TransactionFactory,
) -> MonitoringAdapters:
    """Build the production adapters: PostgreSQL, the access chain and the exporters.

    ``transactions`` writes the denied-access rows in their own short transaction;
    the granted ones join the transaction of the read.
    """
    patients = PatientDirectoryRepository(current)
    assignments = CareTeamRepository(current)
    readings = GlucoseReadingRepository(current)
    records = ClinicalRecordRepository(current)
    patient_records = PhiAccessAuditDecorator(
        PatientRecordAccessProxy(
            PatientRecordRepository(patients),
            patients,
            assignments,
            PatientAccessPolicy(),
            clock,
        ),
        SqlDataAccessLog(current, transactions),
        clock,
    )
    return MonitoringAdapters(
        patient_records=patient_records,
        readings=readings,
        clinical_records=records,
        sync_batches=SyncBatchRepository(current),
        timeline=TimelineRepository(readings, records),
        validation=ValidationSettingsRepository(current),
        targets=TargetProfileRepository(current),
        symptoms=SymptomCatalogRepository(current),
        active_plans=ActivePlanRepository(current),
        cgm=CgmCsvAdapter(),
        exporters={
            ExportFormat.CSV: CsvTimelineExporter(),
            ExportFormat.FHIR: FhirTimelineExporter(),
        },
    )
