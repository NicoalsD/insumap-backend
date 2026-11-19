"""Decisions about clinics: create, update, suspend and reactivate (P13, P18).

Each command runs behind the transaction and the audit of ``CommandGuard``
(P09). The audit row names the target clinic, because a platform administrator
has no clinic of its own in the session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final, final, override
from uuid import UUID

from insumap.application.clinics.ports import ClinicRepositoryPort
from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.common.ids import IdGenerator
from insumap.domain.clinic.clinic import Clinic
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.common.reason import Reason
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.time import Clock

CLINIC_ENTITY: Final = "CLINIC"
CREATED_FIELDS: Final = ("name", "tax_id", "timezone", "is_demo")
STATE_FIELDS: Final = ("status", "suspended_at", "suspended_reason")


def _load(clinics: ClinicRepositoryPort, clinic_id: UUID) -> Clinic:
    """The clinic, or the same ``404`` as a clinic that does not exist."""
    clinic = clinics.get(clinic_id)
    if clinic is None:
        raise ResourceNotFoundError
    return clinic


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateClinicCommand(Command[Clinic]):
    """The platform administrator registers a new clinic (tenant)."""

    audit_action: ClassVar[str] = "CLINIC_CREATED"
    audit_entity_type: ClassVar[str] = CLINIC_ENTITY

    name: str
    tax_id: str
    timezone: str
    is_demo: bool

    @override
    def audit_subject(self, result: Clinic) -> AuditSubject:
        return AuditSubject(
            clinic_id=result.clinic_id,
            entity_id=result.clinic_id,
            changed_fields=CREATED_FIELDS,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateClinicCommand(Command[Clinic]):
    """The platform administrator changes some fields of a clinic."""

    audit_action: ClassVar[str] = "CLINIC_UPDATED"
    audit_entity_type: ClassVar[str] = CLINIC_ENTITY

    clinic_id: UUID
    name: str | None
    tax_id: str | None
    timezone: str | None
    is_demo: bool | None

    @override
    def audit_subject(self, result: Clinic) -> AuditSubject:
        given = (
            ("name", self.name),
            ("tax_id", self.tax_id),
            ("timezone", self.timezone),
            ("is_demo", self.is_demo),
        )
        return AuditSubject(
            clinic_id=result.clinic_id,
            entity_id=result.clinic_id,
            changed_fields=tuple(field for field, value in given if value is not None),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SuspendClinicCommand(Command[Clinic]):
    """The platform administrator blocks a clinic, with the reason in the audit."""

    audit_action: ClassVar[str] = "CLINIC_SUSPENDED"
    audit_entity_type: ClassVar[str] = CLINIC_ENTITY

    clinic_id: UUID
    reason: str | None

    @override
    def audit_subject(self, result: Clinic) -> AuditSubject:
        return AuditSubject(
            clinic_id=result.clinic_id,
            entity_id=result.clinic_id,
            reason=Reason.parse(self.reason).text,
            changed_fields=STATE_FIELDS,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReactivateClinicCommand(Command[Clinic]):
    """The platform administrator lifts the suspension of a clinic."""

    audit_action: ClassVar[str] = "CLINIC_REACTIVATED"
    audit_entity_type: ClassVar[str] = CLINIC_ENTITY

    clinic_id: UUID

    @override
    def audit_subject(self, result: Clinic) -> AuditSubject:
        return AuditSubject(
            clinic_id=result.clinic_id,
            entity_id=result.clinic_id,
            changed_fields=STATE_FIELDS,
        )


@final
class CreateClinicCommandHandler(CommandHandler[CreateClinicCommand, Clinic]):
    """Validates the data, then stores an ``ACTIVE`` clinic."""

    def __init__(
        self, *, clinics: ClinicRepositoryPort, ids: IdGenerator, clock: Clock
    ) -> None:
        self._clinics = clinics
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: CreateClinicCommand) -> Clinic:
        command.actor.require(PermissionCode.CLINICS_MANAGE)
        clinic = Clinic.create(
            clinic_id=self._ids.new_id(),
            name=command.name,
            tax_id=command.tax_id,
            timezone=command.timezone,
            is_demo=command.is_demo,
            at=self._clock.now(),
        )
        self._clinics.add(clinic)
        return clinic


@final
class UpdateClinicCommandHandler(CommandHandler[UpdateClinicCommand, Clinic]):
    """Replaces the fields given and keeps the rest."""

    def __init__(self, *, clinics: ClinicRepositoryPort, clock: Clock) -> None:
        self._clinics = clinics
        self._clock = clock

    @override
    def handle(self, command: UpdateClinicCommand) -> Clinic:
        command.actor.require(PermissionCode.CLINICS_MANAGE)
        clinic = _load(self._clinics, command.clinic_id)
        updated = clinic.updated(
            name=command.name,
            tax_id=command.tax_id,
            timezone=command.timezone,
            is_demo=command.is_demo,
        )
        self._clinics.save(updated, now=self._clock.now())
        return updated


@final
class SuspendClinicCommandHandler(CommandHandler[SuspendClinicCommand, Clinic]):
    """Suspends an active clinic; the sessions of its users are revoked by the DB."""

    def __init__(self, *, clinics: ClinicRepositoryPort, clock: Clock) -> None:
        self._clinics = clinics
        self._clock = clock

    @override
    def handle(self, command: SuspendClinicCommand) -> Clinic:
        command.actor.require(PermissionCode.CLINICS_MANAGE)
        reason = Reason.parse(command.reason)
        clinic = _load(self._clinics, command.clinic_id)
        now = self._clock.now()
        suspended = clinic.suspended(reason=reason, at=now)
        self._clinics.save(suspended, now=now)
        return suspended


@final
class ReactivateClinicCommandHandler(CommandHandler[ReactivateClinicCommand, Clinic]):
    """Lifts a suspension; an active clinic answers ``409``."""

    def __init__(self, *, clinics: ClinicRepositoryPort, clock: Clock) -> None:
        self._clinics = clinics
        self._clock = clock

    @override
    def handle(self, command: ReactivateClinicCommand) -> Clinic:
        command.actor.require(PermissionCode.CLINICS_MANAGE)
        clinic = _load(self._clinics, command.clinic_id)
        reactivated = clinic.reactivated()
        self._clinics.save(reactivated, now=self._clock.now())
        return reactivated
