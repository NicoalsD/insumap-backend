"""The adapters behind the patient credential ports, built over the session holder."""

from __future__ import annotations

from dataclasses import dataclass

from insumap.application.credentials.ports import (
    CredentialInvitationPort,
    PatientContactPort,
)
from insumap.infrastructure.persistence.credential_repositories import (
    CredentialInvitationRepository,
    PatientContactRepository,
)
from insumap.infrastructure.persistence.transactions import CurrentSession


@dataclass(frozen=True, slots=True, kw_only=True)
class CredentialsAdapters:
    """Ports of the patient credential slice, wired by ``Container``.

    Tests pass their own doubles; production gets ``build_credentials_adapters``.
    """

    patient_contacts: PatientContactPort
    invitations: CredentialInvitationPort


def build_credentials_adapters(*, current: CurrentSession) -> CredentialsAdapters:
    """Build the production adapters over the session holder of the process."""
    return CredentialsAdapters(
        patient_contacts=PatientContactRepository(current),
        invitations=CredentialInvitationRepository(current),
    )
