from datetime import UTC, datetime
from uuid import UUID

import pytest

from insumap.domain.clinic.clinic import Clinic, ClinicStatus, parse_timezone
from insumap.domain.common.errors import ReasonRequiredError
from insumap.domain.common.reason import Reason
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def clinic(
    *,
    name: str = "  Clínica Norte ",
    tax_id: str = "900.123.456-7",
    timezone: str = "America/Bogota",
) -> Clinic:
    return Clinic.create(
        clinic_id=UUID(int=1),
        name=name,
        tax_id=tax_id,
        timezone=timezone,
        is_demo=False,
        at=NOW,
    )


def test_a_new_clinic_is_active_and_its_text_is_normalized() -> None:
    created = clinic(name="  Clínica\u00a0Norte ")

    assert created.status is ClinicStatus.ACTIVE
    assert created.name == "Clínica Norte"
    assert created.created_at == NOW
    assert created.suspended_at is None
    assert created.is_active


@pytest.mark.parametrize(
    ("overrides", "field", "kind"),
    [
        ({"name": "   "}, "body.name", "blank"),
        (
            {"name": "x" * (FieldLimits.CLINIC_NAME_MAX_LENGTH + 1)},
            "body.name",
            "too_long",
        ),
        ({"tax_id": ""}, "body.tax_id", "blank"),
        (
            {"tax_id": "9" * (FieldLimits.TAX_ID_MAX_LENGTH + 1)},
            "body.tax_id",
            "too_long",
        ),
        ({"timezone": "Mars/Olympus"}, "body.timezone", "invalid_timezone"),
        ({"timezone": "../etc/passwd"}, "body.timezone", "invalid_timezone"),
    ],
)
def test_invalid_input_is_a_422_on_its_field(
    overrides: dict[str, str], field: str, kind: str
) -> None:
    with pytest.raises(InsumapError) as error:
        clinic(**overrides)

    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert error.value.detail["errors"] == [{"field": field, "type": kind}]


def test_the_zones_of_the_tzdata_package_are_accepted() -> None:
    assert parse_timezone("America/Bogota") == "America/Bogota"
    assert parse_timezone("UTC") == "UTC"


def test_updated_replaces_only_the_given_fields() -> None:
    changed = clinic().updated(name="Clínica Sur", is_demo=True)

    assert (changed.name, changed.is_demo) == ("Clínica Sur", True)
    assert changed.tax_id == "900.123.456-7"
    assert changed.timezone == "America/Bogota"
    assert clinic().updated(timezone="UTC", tax_id=" 1 ").timezone == "UTC"


def test_updated_validates_what_it_replaces() -> None:
    with pytest.raises(InsumapError):
        clinic().updated(timezone="Nowhere/Land")


def test_suspension_records_when_and_why_and_reactivation_clears_it() -> None:
    reason = Reason.parse("Contrato vencido, pendiente de pago")

    suspended = clinic().suspended(reason=reason, at=LATER)

    assert suspended.status is ClinicStatus.SUSPENDED
    assert suspended.suspended_at == LATER
    assert suspended.suspended_reason == reason.text
    assert not suspended.is_active
    reopened = suspended.reactivated()
    assert reopened.status is ClinicStatus.ACTIVE
    assert (reopened.suspended_at, reopened.suspended_reason) == (None, None)


def test_the_machine_rejects_the_transitions_it_does_not_allow() -> None:
    reason = Reason.parse("Contrato vencido, pendiente de pago")
    suspended = clinic().suspended(reason=reason, at=LATER)

    with pytest.raises(InvalidStateTransitionError):
        suspended.suspended(reason=reason, at=LATER)
    with pytest.raises(InvalidStateTransitionError):
        clinic().reactivated()


def test_a_missing_reason_is_not_a_reason() -> None:
    with pytest.raises(ReasonRequiredError):
        Reason.parse(None)
