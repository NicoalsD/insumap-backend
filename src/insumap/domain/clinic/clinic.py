"""A contracting clinic (tenant): identity, time zone and ``ACTIVE <-> SUSPENDED``."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Final, assert_never, final, override
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from insumap.domain.common.reason import Reason
from insumap.domain.common.text import clean_text, invalid_field
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.shared.field_limits import FieldLimits

MACHINE_NAME: Final = "clinic"
INVALID_TIMEZONE: Final = "invalid_timezone"


class ClinicStatus(StrEnum):
    """Persisted value of the state (``clinic.clinics.status``)."""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ClinicState(ABC):
    """Base of the clinic machine: every action is refused unless a state allows it.

    Pattern: P18 State
    """

    status: ClassVar[ClinicStatus]

    def suspend(self) -> ClinicState:
        """Block the clinic: its staff and patients cannot sign in."""
        raise self._invalid("suspend")

    def reactivate(self) -> ClinicState:
        """Lift the suspension."""
        raise self._invalid("reactivate")

    @final
    def _invalid(self, action: str) -> InvalidStateTransitionError:
        return InvalidStateTransitionError(MACHINE_NAME, self.status.value, action)

    @staticmethod
    def from_status(status: ClinicStatus) -> ClinicState:
        """The state object of a persisted status."""
        match status:
            case ClinicStatus.ACTIVE:
                return ActiveClinicState()
            case ClinicStatus.SUSPENDED:
                return SuspendedClinicState()
            case _:  # pragma: no cover - exhaustiveness guard for mypy
                assert_never(status)


@final
class ActiveClinicState(ClinicState):
    """Open for business; it can be suspended."""

    status = ClinicStatus.ACTIVE

    @override
    def suspend(self) -> ClinicState:
        return SuspendedClinicState()


@final
class SuspendedClinicState(ClinicState):
    """Blocked; only a reactivation brings it back."""

    status = ClinicStatus.SUSPENDED

    @override
    def reactivate(self) -> ClinicState:
        return ActiveClinicState()


def parse_timezone(raw: str, *, field: str = "body.timezone") -> str:
    """A valid IANA zone name, or a ``422`` on ``field``."""
    name = clean_text(raw, field=field, max_length=FieldLimits.TIMEZONE_MAX_LENGTH)
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise invalid_field(field, INVALID_TIMEZONE) from None
    return name


@dataclass(frozen=True, slots=True, kw_only=True)
class Clinic:
    """The tenant. ``is_demo`` marks the clinic of simulated data."""

    clinic_id: UUID
    name: str
    tax_id: str
    timezone: str
    status: ClinicStatus
    is_demo: bool
    created_at: datetime
    suspended_at: datetime | None = None
    suspended_reason: str | None = None
    lock_version: int = 0

    @classmethod
    def create(
        cls,
        *,
        clinic_id: UUID,
        name: str,
        tax_id: str,
        timezone: str,
        is_demo: bool,
        at: datetime,
    ) -> Clinic:
        """A new ``ACTIVE`` clinic from raw input."""
        return cls(
            clinic_id=clinic_id,
            name=clean_text(
                name, field="body.name", max_length=FieldLimits.CLINIC_NAME_MAX_LENGTH
            ),
            tax_id=clean_text(
                tax_id, field="body.tax_id", max_length=FieldLimits.TAX_ID_MAX_LENGTH
            ),
            timezone=parse_timezone(timezone),
            status=ClinicStatus.ACTIVE,
            is_demo=is_demo,
            created_at=at,
        )

    @property
    def state(self) -> ClinicState:
        """The state object (P18) of the persisted status."""
        return ClinicState.from_status(self.status)

    @property
    def is_active(self) -> bool:
        """``True`` while the clinic is not suspended."""
        return self.status is ClinicStatus.ACTIVE

    def updated(
        self,
        *,
        name: str | None = None,
        tax_id: str | None = None,
        timezone: str | None = None,
        is_demo: bool | None = None,
    ) -> Clinic:
        """This clinic with the given fields replaced (``None`` keeps the value)."""
        return replace(
            self,
            name=self.name
            if name is None
            else clean_text(
                name, field="body.name", max_length=FieldLimits.CLINIC_NAME_MAX_LENGTH
            ),
            tax_id=self.tax_id
            if tax_id is None
            else clean_text(
                tax_id, field="body.tax_id", max_length=FieldLimits.TAX_ID_MAX_LENGTH
            ),
            timezone=self.timezone if timezone is None else parse_timezone(timezone),
            is_demo=self.is_demo if is_demo is None else is_demo,
        )

    def suspended(self, *, reason: Reason, at: datetime) -> Clinic:
        """This clinic suspended at ``at`` for ``reason``."""
        next_state = self.state.suspend()
        return replace(
            self,
            status=next_state.status,
            suspended_at=at,
            suspended_reason=reason.text,
        )

    def reactivated(self) -> Clinic:
        """This clinic open again; the suspension is cleared."""
        next_state = self.state.reactivate()
        return replace(
            self, status=next_state.status, suspended_at=None, suspended_reason=None
        )
