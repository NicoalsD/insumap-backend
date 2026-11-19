"""Domain events of the consent of a patient (P17)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from insumap.domain.common.events import DomainEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class SensitiveConsentWithdrawn(DomainEvent):
    """A patient withdrew the sensitive-data consent: the clinic must act on it.

    Identifiers only. The clinic decides whether to start the removal or the
    retention (Cumplimiento-y-privacidad.md, 14.4).
    """

    clinic_id: UUID
    patient_id: UUID
