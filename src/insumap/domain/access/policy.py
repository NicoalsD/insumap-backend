"""Who may read the clinical record of a patient (``Seguridad.md``, 6.3).

Pure rules: the policy takes the caller, the patient and the care team as
arguments. It does not read the database or the clock.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import final
from uuid import UUID

from insumap.domain.care_team.assignment import CareAssignment
from insumap.domain.identity.roles import Role


class AccessDecision(StrEnum):
    """Outcome of the policy."""

    GRANTED = "GRANTED"
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientRef:
    """The minimum of a patient the policy needs: who it is and whose account it is."""

    patient_id: UUID
    clinic_id: UUID
    user_id: UUID | None


@final
class PatientAccessPolicy:
    """The patient reads only their own record; a doctor only an assigned patient.

    A doctor who is not assigned and a patient who reads another one get
    ``NOT_FOUND``, so the answer never reveals the patient exists. The
    administrators have no clinical read permission: ``FORBIDDEN``.
    """

    def decide(
        self,
        *,
        user_id: UUID,
        role: Role,
        patient: PatientRef,
        assignments: Sequence[CareAssignment],
        at: datetime,
    ) -> AccessDecision:
        """Decide whether ``user_id`` may read the record of ``patient``."""
        match role:
            case Role.PATIENT:
                return (
                    AccessDecision.GRANTED
                    if patient.user_id is not None and patient.user_id == user_id
                    else AccessDecision.NOT_FOUND
                )
            case Role.DOCTOR:
                assigned = any(
                    a.doctor_user_id == user_id
                    and a.patient_id == patient.patient_id
                    and a.is_active(at)
                    for a in assignments
                )
                return AccessDecision.GRANTED if assigned else AccessDecision.NOT_FOUND
            case Role.CLINIC_ADMIN | Role.PLATFORM_ADMIN:
                return AccessDecision.FORBIDDEN
