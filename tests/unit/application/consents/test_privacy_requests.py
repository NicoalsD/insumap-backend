"""Privacy requests: create under consent, resolve with a reason, export audited."""

from datetime import timedelta
from uuid import UUID

import pytest

from insumap.application.access.ports import DataAccessAction, DataAccessOutcome
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import PageRequest
from insumap.application.consents.privacy_requests import (
    CreatePrivacyRequestCommand,
    CreatePrivacyRequestCommandHandler,
    ExportPrivacyRequestUseCase,
    ListPrivacyRequestsUseCase,
    ResolvePrivacyRequestCommand,
    ResolvePrivacyRequestCommandHandler,
)
from insumap.application.monitoring.gate import OwnPatientGate
from insumap.domain.common.errors import ReasonRequiredError, ResourceNotFoundError
from insumap.domain.identity.consent import ConsentAction, ConsentRecord, ConsentScope
from insumap.domain.identity.errors import (
    ConsentRequiredError,
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.privacy.request import (
    PrivacyDecision,
    PrivacyRequest,
    PrivacyRequestStatus,
    PrivacyRequestType,
)
from tests.support.consents_fakes import ConsentsWorld
from tests.support.identity_world import (
    CLINIC,
    DOCTOR_USER,
    NOTICE_ID,
    NOW,
    PATIENT_ID,
    PATIENT_USER,
    IdentityWorld,
)

NOTE = "Solicitud revisada por la clínica"
OTHER_PATIENT = UUID(int=500)
REQUEST_ID = UUID(int=800)
PATIENT_PERMISSIONS = frozenset(
    {PermissionCode.CONSENTS_MANAGE_OWN, PermissionCode.PRIVACY_REQUESTS_CREATE_OWN}
)


def patient() -> Actor:
    return Actor(
        user_id=PATIENT_USER,
        clinic_id=CLINIC.clinic_id,
        role=Role.PATIENT,
        permissions=PATIENT_PERMISSIONS,
        patient_id=PATIENT_ID,
    )


def admin() -> Actor:
    return Actor(
        user_id=DOCTOR_USER,
        clinic_id=CLINIC.clinic_id,
        role=Role.CLINIC_ADMIN,
        permissions=frozenset({PermissionCode.PRIVACY_REQUESTS_MANAGE}),
    )


def give_consent(identity: IdentityWorld) -> None:
    identity.consents.add(
        [
            ConsentRecord(
                consent_id=UUID(int=911),
                clinic_id=CLINIC.clinic_id,
                patient_id=PATIENT_ID,
                privacy_notice_version_id=NOTICE_ID,
                scope=ConsentScope.SENSITIVE_DATA_PROCESSING,
                action=ConsentAction.ACCEPTED,
                occurred_at=NOW,
                recorded_by=PATIENT_USER,
            )
        ]
    )


@pytest.fixture
def world() -> tuple[IdentityWorld, ConsentsWorld]:
    identity = IdentityWorld()
    consents = ConsentsWorld(
        records=identity.consents.records,
        notices=identity.consents.notices,
        patient_ids=[PATIENT_ID],
    )
    return identity, consents


def create(identity: IdentityWorld, consents: ConsentsWorld) -> PrivacyRequest:
    return CreatePrivacyRequestCommandHandler(
        gate=OwnPatientGate(identity.consents),
        requests=consents.requests,
        ids=identity.ids,
        clock=identity.clock,
        due_days=10,
    ).handle(
        CreatePrivacyRequestCommand(
            actor=patient(),
            request_type=PrivacyRequestType.ACCESS,
            description=None,
        )
    )


def resolve(
    identity: IdentityWorld,
    consents: ConsentsWorld,
    request_id: UUID,
    decision: PrivacyDecision,
    note: str = NOTE,
) -> PrivacyRequest:
    return ResolvePrivacyRequestCommandHandler(
        requests=consents.requests, clock=identity.clock
    ).handle(
        ResolvePrivacyRequestCommand(
            actor=admin(), request_id=request_id, decision=decision, note=note
        )
    )


def test_a_patient_with_consent_opens_a_request_with_a_deadline(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world
    give_consent(identity)

    request = create(identity, consents)

    assert request.status is PrivacyRequestStatus.OPEN
    assert request.due_at == NOW + timedelta(days=10)
    assert consents.requests.rows[request.request_id] == request


def test_a_patient_without_consent_cannot_open_a_request(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world

    with pytest.raises(ConsentRequiredError):
        create(identity, consents)


def test_the_clinic_approves_an_open_request_with_a_reason(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world
    give_consent(identity)
    request = create(identity, consents)

    resolved = resolve(identity, consents, request.request_id, PrivacyDecision.APPROVE)

    assert resolved.status is PrivacyRequestStatus.APPROVED
    assert resolved.resolved_by == DOCTOR_USER
    assert resolved.resolution_note == NOTE


def test_a_second_decision_is_refused(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world
    give_consent(identity)
    request = create(identity, consents)
    resolve(identity, consents, request.request_id, PrivacyDecision.APPROVE)

    with pytest.raises(InvalidStateTransitionError):
        resolve(identity, consents, request.request_id, PrivacyDecision.REJECT)


def test_a_reason_must_have_the_canonical_length(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world
    give_consent(identity)
    request = create(identity, consents)

    with pytest.raises(ReasonRequiredError):
        resolve(
            identity,
            consents,
            request.request_id,
            PrivacyDecision.APPROVE,
            note="corto",
        )


def test_resolving_an_unknown_request_is_not_found(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world

    with pytest.raises(ResourceNotFoundError):
        resolve(identity, consents, REQUEST_ID, PrivacyDecision.APPROVE)


def test_the_patient_cannot_resolve_its_own_request(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world
    give_consent(identity)
    request = create(identity, consents)

    with pytest.raises(PermissionDeniedError):
        ResolvePrivacyRequestCommandHandler(
            requests=consents.requests, clock=identity.clock
        ).handle(
            ResolvePrivacyRequestCommand(
                actor=patient(),
                request_id=request.request_id,
                decision=PrivacyDecision.APPROVE,
                note=NOTE,
            )
        )


def test_the_patient_lists_only_its_own_requests(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world
    give_consent(identity)
    mine = create(identity, consents)
    consents.requests.rows[UUID(int=801)] = PrivacyRequest(
        request_id=UUID(int=801),
        clinic_id=CLINIC.clinic_id,
        patient_id=OTHER_PATIENT,
        request_type=PrivacyRequestType.ERASURE,
        status=PrivacyRequestStatus.OPEN,
        requested_at=NOW,
        due_at=NOW + timedelta(days=10),
    )

    page = ListPrivacyRequestsUseCase(
        uow=identity.uow, requests=consents.requests
    ).execute(patient(), PageRequest(limit=10))

    assert [r.request_id for r in page.items] == [mine.request_id]


def export_use_case(
    identity: IdentityWorld, consents: ConsentsWorld
) -> ExportPrivacyRequestUseCase:
    class EmptyTimeline:
        def events(self, *args: object, **kwargs: object) -> list[object]:
            return []

        def effective_events(self, *args: object, **kwargs: object) -> list[object]:
            return []

    return ExportPrivacyRequestUseCase(
        uow=identity.uow,
        gate=OwnPatientGate(identity.consents),
        requests=consents.requests,
        history=consents.history,
        timeline=EmptyTimeline(),  # type: ignore[arg-type]
        access_log=consents.access_log,
        clock=identity.clock,
    )


def test_an_approved_request_exports_and_is_audited_as_export(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world
    give_consent(identity)
    request = create(identity, consents)
    resolve(identity, consents, request.request_id, PrivacyDecision.APPROVE)

    export = export_use_case(identity, consents).execute(patient(), request.request_id)

    assert export.patient_id == PATIENT_ID
    assert export.events == []
    assert export.consents[0]["scope"] == "SENSITIVE_DATA_PROCESSING"
    granted = consents.access_log.granted[-1]
    assert granted.action is DataAccessAction.EXPORT
    assert granted.outcome is DataAccessOutcome.GRANTED


def test_an_open_request_does_not_export(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world
    give_consent(identity)
    request = create(identity, consents)

    with pytest.raises(InvalidStateTransitionError):
        export_use_case(identity, consents).execute(patient(), request.request_id)


def test_another_patients_request_is_not_found(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world
    consents.requests.rows[REQUEST_ID] = PrivacyRequest(
        request_id=REQUEST_ID,
        clinic_id=CLINIC.clinic_id,
        patient_id=OTHER_PATIENT,
        request_type=PrivacyRequestType.ACCESS,
        status=PrivacyRequestStatus.APPROVED,
        requested_at=NOW,
        due_at=NOW + timedelta(days=10),
    )
    give_consent(identity)

    with pytest.raises(ResourceNotFoundError):
        export_use_case(identity, consents).execute(patient(), REQUEST_ID)


def test_the_export_is_not_written_when_its_audit_fails(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world
    give_consent(identity)
    request = create(identity, consents)
    resolve(identity, consents, request.request_id, PrivacyDecision.APPROVE)
    consents.access_log.fail_granted = True

    with pytest.raises(RuntimeError):
        export_use_case(identity, consents).execute(patient(), request.request_id)
