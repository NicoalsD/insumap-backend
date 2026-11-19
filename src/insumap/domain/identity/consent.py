"""Consent of a patient to the processing of personal and health data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ConsentScope(StrEnum):
    """What the patient consents to (``clinic.patient_consents.scope``)."""

    SENSITIVE_DATA_PROCESSING = "SENSITIVE_DATA_PROCESSING"
    AI_EXTERNAL_PROCESSING = "AI_EXTERNAL_PROCESSING"


class ConsentAction(StrEnum):
    """Acceptance or withdrawal; each one is a new row."""

    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsentRecord:
    """One append-only consent act."""

    consent_id: UUID
    clinic_id: UUID
    patient_id: UUID
    privacy_notice_version_id: UUID
    scope: ConsentScope
    action: ConsentAction
    occurred_at: datetime
    recorded_by: UUID
