"""Accept and withdraw the consent (P13), with the outdated and refused cases."""

from uuid import UUID

import pytest

from insumap.application.commands.transactional import CurrentUnitOfWork
from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import TransactionContext
from insumap.application.consents.commands import (
    AcceptConsentCommand,
    AcceptConsentCommandHandler,
    WithdrawConsentCommand,
    WithdrawConsentCommandHandler,
)
from insumap.application.consents.gate import OwnConsentGate
from insumap.application.consents.queries import GetOwnConsentUseCase
from insumap.application.consents.views import own_view
from insumap.domain.identity.consent import ConsentScope
from insumap.domain.identity.consent_events import SensitiveConsentWithdrawn
from insumap.domain.identity.errors import (
    ConsentVersionOutdatedError,
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from tests.support.consents_fakes import ConsentsWorld
from tests.support.identity_world import (
    CLINIC,
    NOTICE_ID,
    PATIENT_ID,
    PATIENT_USER,
    IdentityWorld,
)

OLD_NOTICE = UUID(int=99)
PATIENT_PERMISSIONS = frozenset(
    {PermissionCode.CONSENTS_MANAGE_OWN, PermissionCode.PRIVACY_REQUESTS_CREATE_OWN}
)


def patient(permissions: frozenset[PermissionCode] = PATIENT_PERMISSIONS) -> Actor:
    return Actor(
        user_id=PATIENT_USER,
        clinic_id=CLINIC.clinic_id,
        role=Role.PATIENT,
        permissions=permissions,
        patient_id=PATIENT_ID,
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


def accept_handler(
    identity: IdentityWorld, consents: ConsentsWorld
) -> AcceptConsentCommandHandler:
    return AcceptConsentCommandHandler(
        gate=OwnConsentGate(),
        consents=identity.consents,
        history=consents.history,
        ids=identity.ids,
        clock=identity.clock,
    )


def withdraw_handler(
    identity: IdentityWorld, consents: ConsentsWorld, events: CurrentUnitOfWork
) -> WithdrawConsentCommandHandler:
    return WithdrawConsentCommandHandler(
        gate=OwnConsentGate(),
        consents=identity.consents,
        history=consents.history,
        ids=identity.ids,
        clock=identity.clock,
        events=events,
    )


def test_accepting_the_notice_in_force_grants_the_consent(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world

    view = accept_handler(identity, consents).handle(
        AcceptConsentCommand(
            actor=patient(),
            privacy_notice_version_id=NOTICE_ID,
            ai_external_processing=False,
        )
    )

    assert view.consent_required is False
    assert view.accepted_version_id == NOTICE_ID
    assert [r.scope for r in identity.consents.records] == [
        ConsentScope.SENSITIVE_DATA_PROCESSING
    ]


def test_accepting_an_outdated_notice_is_a_conflict(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world

    with pytest.raises(ConsentVersionOutdatedError):
        accept_handler(identity, consents).handle(
            AcceptConsentCommand(
                actor=patient(),
                privacy_notice_version_id=OLD_NOTICE,
                ai_external_processing=False,
            )
        )
    assert identity.consents.records == []


def test_accepting_external_ai_adds_its_own_scope(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world

    view = accept_handler(identity, consents).handle(
        AcceptConsentCommand(
            actor=patient(),
            privacy_notice_version_id=NOTICE_ID,
            ai_external_processing=True,
        )
    )

    assert set(view.scopes) == {
        ConsentScope.SENSITIVE_DATA_PROCESSING,
        ConsentScope.AI_EXTERNAL_PROCESSING,
    }


def test_the_consent_routes_need_their_permission(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world

    with pytest.raises(PermissionDeniedError):
        accept_handler(identity, consents).handle(
            AcceptConsentCommand(
                actor=patient(frozenset()),
                privacy_notice_version_id=NOTICE_ID,
                ai_external_processing=False,
            )
        )


def test_withdrawing_stops_the_consent_and_collects_the_event(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world
    accept_handler(identity, consents).handle(
        AcceptConsentCommand(
            actor=patient(),
            privacy_notice_version_id=NOTICE_ID,
            ai_external_processing=False,
        )
    )
    current = CurrentUnitOfWork()

    with identity.uow.begin(TransactionContext.anonymous()) as unit, current.bind(unit):
        view = withdraw_handler(identity, consents, current).handle(
            WithdrawConsentCommand(
                actor=patient(), scope=ConsentScope.SENSITIVE_DATA_PROCESSING
            )
        )
        unit.commit()

    assert view.consent_required is True
    assert identity.uow.published
    assert isinstance(identity.uow.published[0], SensitiveConsentWithdrawn)
    assert identity.uow.published[0].patient_id == PATIENT_ID


def test_withdrawing_a_scope_never_accepted_is_refused(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world
    current = CurrentUnitOfWork()

    with (
        identity.uow.begin(TransactionContext.anonymous()) as unit,
        current.bind(unit),
        pytest.raises(InvalidStateTransitionError),
    ):
        withdraw_handler(identity, consents, current).handle(
            WithdrawConsentCommand(
                actor=patient(), scope=ConsentScope.AI_EXTERNAL_PROCESSING
            )
        )


def test_the_own_consent_view_is_readable_without_a_current_consent(
    world: tuple[IdentityWorld, ConsentsWorld],
) -> None:
    identity, consents = world
    use_case = GetOwnConsentUseCase(
        uow=identity.uow,
        gate=OwnConsentGate(),
        consents=identity.consents,
        history=consents.history,
    )

    view = use_case.execute(patient())

    assert view.consent_required is True
    assert own_view({}, NOTICE_ID).consent_required is True
