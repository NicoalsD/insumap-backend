"""Rules of the professional profile of the staff (``clinic.staff_profiles``).

Only ``DOCTOR`` and ``CLINIC_ADMIN`` are staff. A doctor must have a
professional license; the database only makes it unique per clinic.
"""

from __future__ import annotations

from typing import Final

from insumap.domain.common.text import invalid_field
from insumap.domain.identity.roles import Role

STAFF_ROLES: Final = frozenset({Role.DOCTOR, Role.CLINIC_ADMIN})
LICENSE_FIELD: Final = "body.professional_license"
MISSING: Final = "missing"


def is_staff_role(role: Role) -> bool:
    """``True`` for the roles that belong to a clinic's staff."""
    return role in STAFF_ROLES


def ensure_license_for_role(role: Role, professional_license: str | None) -> None:
    """A doctor cannot be left without a professional license (``422``)."""
    if role is Role.DOCTOR and not professional_license:
        raise invalid_field(LICENSE_FIELD, MISSING)
