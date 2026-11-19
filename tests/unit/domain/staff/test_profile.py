import pytest

from insumap.domain.common.text import invalid_field
from insumap.domain.identity.roles import Role
from insumap.domain.staff.profile import (
    LICENSE_FIELD,
    ensure_license_for_role,
    is_staff_role,
)
from insumap.shared.errors import ErrorCode, InsumapError


def test_only_doctors_and_clinic_admins_are_staff() -> None:
    assert is_staff_role(Role.DOCTOR)
    assert is_staff_role(Role.CLINIC_ADMIN)
    assert not is_staff_role(Role.PATIENT)
    assert not is_staff_role(Role.PLATFORM_ADMIN)


def test_a_doctor_needs_a_professional_license() -> None:
    with pytest.raises(InsumapError) as missing:
        ensure_license_for_role(Role.DOCTOR, None)
    with pytest.raises(InsumapError) as blank:
        ensure_license_for_role(Role.DOCTOR, "")

    assert missing.value.code is ErrorCode.VALIDATION_ERROR
    assert missing.value.detail == invalid_field(LICENSE_FIELD, "missing").detail
    assert blank.value.code is ErrorCode.VALIDATION_ERROR


def test_a_clinic_admin_does_not_need_a_license() -> None:
    ensure_license_for_role(Role.CLINIC_ADMIN, None)
    ensure_license_for_role(Role.DOCTOR, "RM-12345")
