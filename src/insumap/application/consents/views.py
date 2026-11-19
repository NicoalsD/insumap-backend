"""What a patient sees of its own consent: built from the latest acts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import final
from uuid import UUID

from insumap.domain.identity.consent import (
    ConsentAction,
    ConsentRecord,
    ConsentScope,
    ConsentStanding,
    standing_of,
)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class OwnConsentView:
    """The accepted version, its scopes and whether the patient must accept again."""

    accepted_version_id: UUID | None
    accepted_at: datetime | None
    scopes: tuple[ConsentScope, ...]
    current_version_id: UUID | None
    consent_required: bool


def own_view(
    latest: Mapping[ConsentScope, ConsentRecord], current_version_id: UUID | None
) -> OwnConsentView:
    """The view of the latest acts; ``consent_required`` mirrors ``OwnPatientGate``."""
    sensitive = latest.get(ConsentScope.SENSITIVE_DATA_PROCESSING)
    accepted = (
        sensitive
        if sensitive is not None and sensitive.action is ConsentAction.ACCEPTED
        else None
    )
    scopes = tuple(
        sorted(
            (
                scope
                for scope, record in latest.items()
                if record.action is ConsentAction.ACCEPTED
            ),
            key=lambda scope: scope.value,
        )
    )
    standing = standing_of(sensitive, current_version_id)
    return OwnConsentView(
        accepted_version_id=None
        if accepted is None
        else accepted.privacy_notice_version_id,
        accepted_at=None if accepted is None else accepted.occurred_at,
        scopes=scopes,
        current_version_id=current_version_id,
        consent_required=standing is not ConsentStanding.GRANTED,
    )
