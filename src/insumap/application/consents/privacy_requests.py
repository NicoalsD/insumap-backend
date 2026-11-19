"""Privacy requests of the patient: create, list, resolve and export (RF-93)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar, final, override
from uuid import UUID

from insumap.application.access.ports import (
    AccessPurpose,
    DataAccessAction,
    DataAccessLogPort,
    DataAccessOutcome,
    DataAccessRecord,
    DataResource,
)
from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.common.actor import Actor
from insumap.application.common.ids import IdGenerator
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.consents.export import events_as_json
from insumap.application.consents.ports import ConsentHistoryPort, PrivacyRequestPort
from insumap.application.monitoring.gate import OwnPatientGate
from insumap.application.monitoring.paging import PageQuery
from insumap.application.monitoring.ports import TimelinePort
from insumap.domain.common.errors import ConflictError, ResourceNotFoundError
from insumap.domain.common.reason import Reason
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.monitoring.clinical_event import ClinicalEvent
from insumap.domain.privacy.request import (
    MACHINE_NAME,
    PrivacyDecision,
    PrivacyRequest,
    PrivacyRequestStatus,
    PrivacyRequestType,
    state_of,
)
from insumap.shared.field_limits import FieldLimits
from insumap.shared.request_context import current_request_id
from insumap.shared.time import Clock

REQUEST_ENTITY: str = "PRIVACY_REQUEST"
EXPORT_TOO_LARGE_REASON: str = "export_too_large"


@dataclass(frozen=True, slots=True, kw_only=True)
class CreatePrivacyRequestCommand(Command[PrivacyRequest]):
    """The patient asks for access, rectification, erasure or consent withdrawal."""

    audit_action: ClassVar[str] = "PRIVACY_REQUEST_CREATED"
    audit_entity_type: ClassVar[str] = REQUEST_ENTITY

    request_type: PrivacyRequestType
    description: str | None

    @override
    def audit_subject(self, result: PrivacyRequest) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.request_id,
            changed_fields=("request_type",),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvePrivacyRequestCommand(Command[PrivacyRequest]):
    """The clinic approves or rejects a request, with the reason (RF-70)."""

    audit_action: ClassVar[str] = "PRIVACY_REQUEST_RESOLVED"
    audit_entity_type: ClassVar[str] = REQUEST_ENTITY

    request_id: UUID
    decision: PrivacyDecision
    note: str

    @override
    def audit_subject(self, result: PrivacyRequest) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.request_id,
            reason=Reason.parse(self.note).text,
            changed_fields=("status", "resolved_by", "resolution_note"),
        )


@final
class CreatePrivacyRequestCommandHandler(
    CommandHandler[CreatePrivacyRequestCommand, PrivacyRequest]
):
    """Stores an open request whose deadline comes from the settings.

    The deadline is provisional: the legal term is pending verification
    (``docs/Cumplimiento-y-privacidad.md``, 6.2).
    """

    def __init__(
        self,
        *,
        gate: OwnPatientGate,
        requests: PrivacyRequestPort,
        ids: IdGenerator,
        clock: Clock,
        due_days: int,
    ) -> None:
        self._gate = gate
        self._requests = requests
        self._ids = ids
        self._clock = clock
        self._due_days = due_days

    @override
    def handle(self, command: CreatePrivacyRequestCommand) -> PrivacyRequest:
        scope = self._gate.enter(
            command.actor, PermissionCode.PRIVACY_REQUESTS_CREATE_OWN
        )
        now = self._clock.now()
        request = PrivacyRequest(
            request_id=self._ids.new_id(),
            clinic_id=scope.clinic_id,
            patient_id=scope.patient_id,
            request_type=command.request_type,
            status=PrivacyRequestStatus.OPEN,
            requested_at=now,
            due_at=now + timedelta(days=self._due_days),
        )
        self._requests.add(request)
        return request


@final
class ResolvePrivacyRequestCommandHandler(
    CommandHandler[ResolvePrivacyRequestCommand, PrivacyRequest]
):
    """Applies the decision through the state machine (P18); bad moves are 409."""

    def __init__(self, *, requests: PrivacyRequestPort, clock: Clock) -> None:
        self._requests = requests
        self._clock = clock

    @override
    def handle(self, command: ResolvePrivacyRequestCommand) -> PrivacyRequest:
        actor = command.actor
        actor.require(PermissionCode.PRIVACY_REQUESTS_MANAGE)
        if actor.clinic_id is None:
            raise PermissionDeniedError
        current = self._requests.get(command.request_id)
        if current is None:
            raise ResourceNotFoundError
        note = Reason.parse(command.note).text
        resolved = current.decide(
            command.decision,
            note=note,
            resolver=actor.user_id,
            at=self._clock.now(),
        )
        self._requests.save(resolved)
        return resolved


@final
class ListPrivacyRequestsUseCase:
    """The patient sees its own requests; the clinic administrator, its clinic's."""

    def __init__(self, *, uow: UnitOfWorkPort, requests: PrivacyRequestPort) -> None:
        self._uow = uow
        self._requests = requests

    def execute(self, actor: Actor, page: PageRequest) -> Page[PrivacyRequest]:
        if actor.clinic_id is None:
            raise PermissionDeniedError
        if PermissionCode.PRIVACY_REQUESTS_MANAGE in actor.permissions:
            patient_id = None
        else:
            actor.require(PermissionCode.PRIVACY_REQUESTS_CREATE_OWN)
            patient_id = actor.own_patient_id()
        with self._uow.begin(TransactionContext.for_actor(actor)):
            return self._requests.list(patient_id, page)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class PatientDataExport:
    """The patient's own data, ready to serialize as JSON."""

    request_id: UUID
    patient_id: UUID
    generated_at: datetime
    events: list[dict[str, object]]
    consents: list[dict[str, object]]


@final
class ExportPrivacyRequestUseCase:
    """``GET /privacy-requests/{id}/export``: only for an approved request.

    The read is audited as ``EXPORT`` in ``audit.data_access_log`` in the same
    transaction, so a failed audit fails the export.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnPatientGate,
        requests: PrivacyRequestPort,
        history: ConsentHistoryPort,
        timeline: TimelinePort,
        access_log: DataAccessLogPort,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._requests = requests
        self._history = history
        self._timeline = timeline
        self._log = access_log
        self._clock = clock

    def execute(self, actor: Actor, request_id: UUID) -> PatientDataExport:
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            scope = self._gate.enter(actor, PermissionCode.PRIVACY_REQUESTS_CREATE_OWN)
            request = self._requests.get(request_id)
            if request is None or request.patient_id != scope.patient_id:
                raise ResourceNotFoundError
            if not state_of(request.status).exportable:
                raise InvalidStateTransitionError(
                    MACHINE_NAME, request.status.value, "EXPORT"
                )
            events: list[ClinicalEvent] = list(
                self._timeline.effective_events(
                    scope.patient_id, PageQuery(limit=FieldLimits.EXPORT_MAX_EVENTS + 1)
                )
            )
            if len(events) > FieldLimits.EXPORT_MAX_EVENTS:
                raise ConflictError(EXPORT_TOO_LARGE_REASON)
            consents = self._history.history(scope.patient_id)
            now = self._clock.now()
            self._log.record_granted(
                DataAccessRecord(
                    occurred_at=now,
                    clinic_id=scope.clinic_id,
                    actor_user_id=actor.user_id,
                    actor_role=actor.role,
                    patient_id=scope.patient_id,
                    resource=DataResource.PATIENT_TIMELINE,
                    purpose=AccessPurpose.SELF,
                    outcome=DataAccessOutcome.GRANTED,
                    request_id=current_request_id(),
                    action=DataAccessAction.EXPORT,
                )
            )
            # The export commits its audit row with the read (P09).
            unit.commit()
        return PatientDataExport(
            request_id=request.request_id,
            patient_id=scope.patient_id,
            generated_at=now,
            events=events_as_json(events),
            consents=[
                {
                    "scope": record.scope.value,
                    "action": record.action.value,
                    "privacy_notice_version_id": str(record.privacy_notice_version_id),
                    "occurred_at": record.occurred_at.isoformat(),
                }
                for record in consents
            ],
        )
