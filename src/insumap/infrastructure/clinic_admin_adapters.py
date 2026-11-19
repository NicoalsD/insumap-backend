"""The adapters behind the clinic administrator ports, built over the session holder."""

from __future__ import annotations

from dataclasses import dataclass

from insumap.application.clinic_admins.ports import ClinicAdminProvisioningPort
from insumap.infrastructure.persistence.clinic_admin_repository import (
    ClinicAdminProvisioningRepository,
)
from insumap.infrastructure.persistence.transactions import CurrentSession


@dataclass(frozen=True, slots=True, kw_only=True)
class ClinicAdminAdapters:
    """Ports of the clinic administrator slice, wired by ``Container``.

    Tests pass their own doubles; production gets ``build_clinic_admin_adapters``.
    """

    provisioning: ClinicAdminProvisioningPort


def build_clinic_admin_adapters(*, current: CurrentSession) -> ClinicAdminAdapters:
    """Build the production adapters over the session holder of the process."""
    return ClinicAdminAdapters(
        provisioning=ClinicAdminProvisioningRepository(current),
    )
