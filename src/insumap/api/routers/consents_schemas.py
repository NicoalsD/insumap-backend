"""Bodies and views of the consent and privacy endpoints (API.md 8.13)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field

from insumap.api.routers.common import StrictRequest
from insumap.application.consents.ports import PatientConsentStatus, PrivacyNoticeView
from insumap.application.consents.views import OwnConsentView
from insumap.domain.identity.consent import ConsentScope, ConsentStanding
from insumap.domain.privacy.request import (
    PrivacyDecision,
    PrivacyRequest,
    PrivacyRequestType,
)
from insumap.shared.field_limits import FieldLimits

REQUIRED_SCOPE: frozenset[ConsentScope] = frozenset(
    {ConsentScope.SENSITIVE_DATA_PROCESSING}
)


class ConsentScopeItem(BaseModel):
    """One scope of the notice and whether accepting it is mandatory."""

    scope: ConsentScope
    required: bool


class PrivacyNoticeResponse(BaseModel):
    """The notice text the patient reads before logging in (public)."""

    id: UUID
    version: str
    published_at: datetime
    text: str
    scopes: list[ConsentScopeItem]

    @classmethod
    def of(cls, view: PrivacyNoticeView) -> Self:
        return cls(
            id=view.version_id,
            version=view.version,
            published_at=view.effective_from,
            text=view.content,
            scopes=[
                ConsentScopeItem(scope=scope, required=scope in REQUIRED_SCOPE)
                for scope in ConsentScope
            ],
        )


class OwnConsentResponse(BaseModel):
    """The patient's accepted version and whether it must accept again."""

    accepted_version_id: UUID | None
    accepted_at: datetime | None
    scopes: list[ConsentScope]
    current_version_id: UUID | None
    consent_required: bool

    @classmethod
    def of(cls, view: OwnConsentView) -> Self:
        return cls(
            accepted_version_id=view.accepted_version_id,
            accepted_at=view.accepted_at,
            scopes=list(view.scopes),
            current_version_id=view.current_version_id,
            consent_required=view.consent_required,
        )


class AcceptConsentRequest(StrictRequest):
    """Acceptance of the notice version in force."""

    privacy_notice_version_id: UUID
    accepted: Literal[True] = Field(description="Debe ser `true`.")
    ai_external_processing: bool = Field(
        default=False,
        description=(
            "Consentimiento aparte y opcional para el asistente con LLM externo."
        ),
    )


class WithdrawConsentRequest(StrictRequest):
    """The scope the patient withdraws."""

    scope: ConsentScope


class PatientConsentStatusResponse(BaseModel):
    """One patient of the clinic: the standing of its consent, no clinical data."""

    patient_id: UUID
    standing: ConsentStanding
    privacy_notice_version_id: UUID | None
    occurred_at: datetime | None

    @classmethod
    def of(cls, status: PatientConsentStatus) -> Self:
        return cls(
            patient_id=status.patient_id,
            standing=status.standing,
            privacy_notice_version_id=status.privacy_notice_version_id,
            occurred_at=status.occurred_at,
        )


class PrivacyRequestCreateRequest(StrictRequest):
    """A request of access, rectification, erasure or consent withdrawal."""

    request_type: PrivacyRequestType
    description: str | None = Field(
        default=None,
        max_length=FieldLimits.PRIVACY_REQUEST_DESCRIPTION_MAX_LENGTH,
        description="Descripción opcional de lo que se pide.",
    )


class PrivacyRequestResponse(BaseModel):
    """A privacy request with its state and deadline (no clinical content)."""

    id: UUID
    patient_id: UUID
    request_type: PrivacyRequestType
    status: str
    requested_at: datetime
    due_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None

    @classmethod
    def of(cls, request: PrivacyRequest) -> Self:
        return cls(
            id=request.request_id,
            patient_id=request.patient_id,
            request_type=request.request_type,
            status=request.status.value,
            requested_at=request.requested_at,
            due_at=request.due_at,
            resolved_at=request.resolved_at,
            resolution_note=request.resolution_note,
        )


class ResolvePrivacyRequestRequest(StrictRequest):
    """The decision on a request and its reason (10 to 500 characters)."""

    decision: PrivacyDecision
    note: str = Field(
        min_length=FieldLimits.REASON_MIN_LENGTH,
        max_length=FieldLimits.REASON_MAX_LENGTH,
        description="Motivo de la decisión (queda en la auditoría).",
    )
