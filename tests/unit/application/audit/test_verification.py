"""``POST /audit-log/verifications``: the chain check and its critical event."""

from uuid import UUID

import pytest

from insumap.application.audit.verification import (
    VerifyAuditChainInput,
    VerifyAuditChainUseCase,
)
from insumap.application.security.events import SecurityEventType
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from tests.support.audit_fakes import AuditFakes
from tests.support.commands import ADMIN_ID, CLINIC_ID, clinic_admin
from tests.support.identity_fakes import FakeSecurityEvents, FakeUnitOfWorkPort

BROKEN = UUID(int=77)


@pytest.fixture
def world() -> AuditFakes:
    return AuditFakes()


@pytest.fixture
def events() -> FakeSecurityEvents:
    return FakeSecurityEvents()


@pytest.fixture
def uow() -> FakeUnitOfWorkPort:
    return FakeUnitOfWorkPort()


def _use_case(
    world: AuditFakes, uow: FakeUnitOfWorkPort, events: FakeSecurityEvents
) -> VerifyAuditChainUseCase:
    return VerifyAuditChainUseCase(uow=uow, chain=world.chain, events=events)


def test_an_intact_chain_is_valid_and_records_nothing(
    world: AuditFakes, uow: FakeUnitOfWorkPort, events: FakeSecurityEvents
) -> None:
    result = _use_case(world, uow, events).execute(
        VerifyAuditChainInput(actor=clinic_admin(PermissionCode.AUDIT_READ))
    )

    assert result.is_valid
    assert result.first_inconsistent_row_id is None
    assert events.events == []
    assert world.chain.checked == [CLINIC_ID]


def test_a_broken_chain_reports_the_row_and_records_a_critical_event(
    world: AuditFakes, uow: FakeUnitOfWorkPort, events: FakeSecurityEvents
) -> None:
    world.chain.broken[CLINIC_ID] = BROKEN

    result = _use_case(world, uow, events).execute(
        VerifyAuditChainInput(actor=clinic_admin(PermissionCode.AUDIT_READ))
    )

    assert not result.is_valid
    assert result.first_inconsistent_row_id == BROKEN
    assert [e.event_type for e in events.events] == [SecurityEventType.AUDIT_CHAIN_BROKEN]
    assert events.events[0].clinic_id == CLINIC_ID
    assert events.events[0].user_id == ADMIN_ID
    assert uow.commits == 1


def test_the_clinic_comes_from_the_token_not_the_request(
    world: AuditFakes, uow: FakeUnitOfWorkPort, events: FakeSecurityEvents
) -> None:
    _use_case(world, uow, events).execute(
        VerifyAuditChainInput(actor=clinic_admin(PermissionCode.AUDIT_READ))
    )

    assert world.chain.checked == [CLINIC_ID]


def test_without_audit_read_the_chain_is_not_checked(
    world: AuditFakes, uow: FakeUnitOfWorkPort, events: FakeSecurityEvents
) -> None:
    with pytest.raises(PermissionDeniedError):
        _use_case(world, uow, events).execute(
            VerifyAuditChainInput(actor=clinic_admin())
        )

    assert world.chain.checked == []
