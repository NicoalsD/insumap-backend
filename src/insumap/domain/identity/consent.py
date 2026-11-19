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


class ConsentStanding(StrEnum):
    """Where a patient stands on the sensitive-data consent of the notice in force."""

    GRANTED = "GRANTED"
    """Accepted on the notice version in force and not withdrawn since."""
    PENDING = "PENDING"
    """Never accepted, or accepted on a version that is no longer in force."""
    WITHDRAWN = "WITHDRAWN"
    """The latest act is a withdrawal."""


def standing_of(
    latest: ConsentRecord | None, current_version_id: UUID | None
) -> ConsentStanding:
    """The standing given the latest act of the scope and the notice in force.

    The database holds only acts: this reads the latest one (API.md 8.13).
    """
    if latest is None:
        return ConsentStanding.PENDING
    if latest.action is ConsentAction.WITHDRAWN:
        return ConsentStanding.WITHDRAWN
    if latest.privacy_notice_version_id == current_version_id:
        return ConsentStanding.GRANTED
    return ConsentStanding.PENDING
