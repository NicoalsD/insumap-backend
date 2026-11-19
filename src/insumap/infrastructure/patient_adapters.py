"""The adapters of the patient administration, built over the session holder.

``Container`` builds them with ``build_patient_adapters``. Tests pass their own
doubles through ``Container(patient_adapters=...)``.
"""

from __future__ import annotations

from dataclasses import dataclass

from insumap.application.access.ports import DataAccessLogPort
from insumap.application.common.unit_of_work import TransactionFactory
from insumap.application.patients.ports import PatientRosterPort, PendingInvitationPort
from insumap.infrastructure.access.sql_data_access_log import SqlDataAccessLog
from insumap.infrastructure.persistence.patient_roster_repository import (
    PatientRosterRepository,
    PendingInvitationRepository,
)
from insumap.infrastructure.persistence.transactions import CurrentSession


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientAdapters:
    """Ports of the patient administration and of the access log of its reads."""

    roster: PatientRosterPort
    invitations: PendingInvitationPort
    access_log: DataAccessLogPort


def build_patient_adapters(
    *, current: CurrentSession, transactions: TransactionFactory
) -> PatientAdapters:
    """Production adapters: PostgreSQL, scoped by the row level security context."""
    return PatientAdapters(
        roster=PatientRosterRepository(current),
        invitations=PendingInvitationRepository(current),
        access_log=SqlDataAccessLog(current, transactions),
    )
