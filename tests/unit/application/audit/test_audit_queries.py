"""Scope and paging of the audit reads, with in-memory doubles (no FastAPI, no DB)."""

from uuid import UUID

import pytest

from insumap.application.audit.ports import (
    AuditLogFilter,
    DataAccessFilter,
    SecurityEventKind,
)
from insumap.application.audit.queries import (
    ListAuditLogInput,
    ListAuditLogUseCase,
    ListDataAccessInput,
    ListDataAccessUseCase,
    ListSecurityEventsInput,
    ListSecurityEventsUseCase,
)
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import PageRequest
from insumap.application.security.events import SecuritySeverity
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.infrastructure.audit_adapters import AuditAdapters
from tests.support.audit_fakes import (
    AuditFakes,
    access_row,
    audit_row,
    event_row,
)
from tests.support.commands import CLINIC_ID, clinic_admin
from tests.support.identity_fakes import FakeUnitOfWorkPort

OTHER_CLINIC = UUID(int=900)
PATIENT = UUID(int=500)
PAGE = PageRequest(limit=20)


def platform_admin(*permissions: PermissionCode) -> Actor:
    return Actor(
        user_id=UUID(int=11),
        clinic_id=None,
        role=Role.PLATFORM_ADMIN,
        permissions=frozenset(permissions),
        requires_mfa=True,
        mfa_verified=True,
    )


@pytest.fixture
def world() -> AuditFakes:
    return AuditFakes()


@pytest.fixture
def uow() -> FakeUnitOfWorkPort:
    return FakeUnitOfWorkPort()


def test_audit_log_lists_only_the_callers_clinic(
    world: AuditFakes, uow: FakeUnitOfWorkPort
) -> None:
    world.audit_log.add(CLINIC_ID, audit_row(UUID(int=1)))
    world.audit_log.add(OTHER_CLINIC, audit_row(UUID(int=2)))
    use_case = ListAuditLogUseCase(uow=uow, reader=world.audit_log)

    page = use_case.execute(
        ListAuditLogInput(
            actor=clinic_admin(PermissionCode.AUDIT_READ),
            filters=AuditLogFilter(),
            page=PAGE,
        )
    )

    assert [row.id for row in page.items] == [UUID(int=1)]
    assert page.next_cursor is None


def test_audit_log_denies_a_caller_without_audit_read(
    world: AuditFakes, uow: FakeUnitOfWorkPort
) -> None:
    use_case = ListAuditLogUseCase(uow=uow, reader=world.audit_log)

    with pytest.raises(PermissionDeniedError):
        use_case.execute(
            ListAuditLogInput(actor=clinic_admin(), filters=AuditLogFilter(), page=PAGE)
        )


def test_audit_log_filters_by_action(
    world: AuditFakes, uow: FakeUnitOfWorkPort
) -> None:
    world.audit_log.add(CLINIC_ID, audit_row(UUID(int=1), action="CREDENTIALS_ISSUED"))
    world.audit_log.add(CLINIC_ID, audit_row(UUID(int=2), action="ALERT_RESOLVED"))
    use_case = ListAuditLogUseCase(uow=uow, reader=world.audit_log)

    page = use_case.execute(
        ListAuditLogInput(
            actor=clinic_admin(PermissionCode.AUDIT_READ),
            filters=AuditLogFilter(action="ALERT_RESOLVED"),
            page=PAGE,
        )
    )

    assert [row.id for row in page.items] == [UUID(int=2)]


def test_audit_log_pages_newest_first_with_a_cursor(
    world: AuditFakes, uow: FakeUnitOfWorkPort
) -> None:
    for number in (1, 2, 3):
        world.audit_log.add(CLINIC_ID, audit_row(UUID(int=number)))
    use_case = ListAuditLogUseCase(uow=uow, reader=world.audit_log)
    actor = clinic_admin(PermissionCode.AUDIT_READ)

    first = use_case.execute(
        ListAuditLogInput(
            actor=actor, filters=AuditLogFilter(), page=PageRequest(limit=2)
        )
    )
    assert [row.id for row in first.items] == [UUID(int=3), UUID(int=2)]
    assert first.next_cursor is not None

    second = use_case.execute(
        ListAuditLogInput(
            actor=actor,
            filters=AuditLogFilter(),
            page=PageRequest(limit=2, after=UUID(int=2)),
        )
    )
    assert [row.id for row in second.items] == [UUID(int=1)]
    assert second.next_cursor is None


def test_data_access_is_scoped_to_the_clinic_and_filters_by_patient(
    world: AuditFakes, uow: FakeUnitOfWorkPort
) -> None:
    world.data_access.add(CLINIC_ID, access_row(UUID(int=1), patient_id=PATIENT))
    world.data_access.add(CLINIC_ID, access_row(UUID(int=2), patient_id=UUID(int=7)))
    world.data_access.add(OTHER_CLINIC, access_row(UUID(int=3), patient_id=PATIENT))
    use_case = ListDataAccessUseCase(uow=uow, reader=world.data_access)

    page = use_case.execute(
        ListDataAccessInput(
            actor=clinic_admin(PermissionCode.AUDIT_READ),
            filters=DataAccessFilter(patient_id=PATIENT),
            page=PAGE,
        )
    )

    assert [row.id for row in page.items] == [UUID(int=1)]


def test_security_events_of_a_clinic_admin_stay_in_its_clinic(
    world: AuditFakes, uow: FakeUnitOfWorkPort
) -> None:
    world.security_events.add(event_row(UUID(int=1), clinic_id=CLINIC_ID))
    world.security_events.add(event_row(UUID(int=2), clinic_id=OTHER_CLINIC))
    world.security_events.add(event_row(UUID(int=3), clinic_id=None))
    use_case = ListSecurityEventsUseCase(uow=uow, reader=world.security_events)

    page = use_case.execute(
        ListSecurityEventsInput(
            actor=clinic_admin(PermissionCode.AUDIT_READ), page=PAGE
        )
    )

    assert [row.id for row in page.items] == [UUID(int=1)]


def test_platform_admin_sees_every_security_event(
    world: AuditFakes, uow: FakeUnitOfWorkPort
) -> None:
    world.security_events.add(event_row(UUID(int=1), clinic_id=CLINIC_ID))
    world.security_events.add(event_row(UUID(int=2), clinic_id=None))
    use_case = ListSecurityEventsUseCase(uow=uow, reader=world.security_events)

    page = use_case.execute(
        ListSecurityEventsInput(
            actor=platform_admin(PermissionCode.AUDIT_READ_PLATFORM), page=PAGE
        )
    )

    assert [row.id for row in page.items] == [UUID(int=2), UUID(int=1)]


def test_security_events_filter_by_type_and_severity(
    world: AuditFakes, uow: FakeUnitOfWorkPort
) -> None:
    world.security_events.add(
        event_row(
            UUID(int=1),
            clinic_id=CLINIC_ID,
            event_type=SecurityEventKind.AUDIT_CHAIN_BROKEN,
            severity=SecuritySeverity.CRITICAL,
        )
    )
    world.security_events.add(event_row(UUID(int=2), clinic_id=CLINIC_ID))
    use_case = ListSecurityEventsUseCase(uow=uow, reader=world.security_events)

    page = use_case.execute(
        ListSecurityEventsInput(
            actor=clinic_admin(PermissionCode.AUDIT_READ),
            event_type=SecurityEventKind.AUDIT_CHAIN_BROKEN,
            severity=None,
            page=PAGE,
        )
    )

    assert [row.id for row in page.items] == [UUID(int=1)]


def test_platform_scope_needs_audit_read_platform(
    world: AuditFakes, uow: FakeUnitOfWorkPort
) -> None:
    use_case = ListSecurityEventsUseCase(uow=uow, reader=world.security_events)

    with pytest.raises(PermissionDeniedError):
        use_case.execute(ListSecurityEventsInput(actor=platform_admin(), page=PAGE))


def test_clinic_scope_needs_audit_read_not_only_the_platform_permission(
    world: AuditFakes, uow: FakeUnitOfWorkPort
) -> None:
    use_case = ListSecurityEventsUseCase(uow=uow, reader=world.security_events)

    with pytest.raises(PermissionDeniedError):
        use_case.execute(
            ListSecurityEventsInput(
                actor=clinic_admin(PermissionCode.AUDIT_READ_PLATFORM), page=PAGE
            )
        )


def test_adapters_bundle_has_the_four_ports(world: AuditFakes) -> None:
    adapters = world.adapters()

    assert isinstance(adapters, AuditAdapters)
    assert adapters.chain is world.chain
