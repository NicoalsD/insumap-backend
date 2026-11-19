"""Patient credential commands (P13) and batch issue, with transaction and audit (P09).

Each test runs the handler the way the container wires it: transaction around
audit around the handler. The doubles keep the database rules (one open
invitation per account) and the audit rows keep identifiers and field names only.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from insumap.application.commands.auditing import AuditingCommandHandler
from insumap.application.commands.base import (
    Command,
    CommandHandler,
    InMemoryCommandBus,
    bind,
)
from insumap.application.commands.transactional import (
    CurrentUnitOfWork,
    TransactionalCommandHandler,
)
from insumap.application.common.actor import Actor
from insumap.application.credentials.commands import (
    IssueCredentialsCommand,
    IssueCredentialsCommandHandler,
    IssuedCredential,
    RevokeCredentialInvitationCommand,
    RevokeCredentialInvitationCommandHandler,
)
from insumap.application.credentials.issuance import (
    IssueCredentialInput,
    IssueCredentialsBatchInput,
    IssueCredentialsBatchUseCase,
    IssueCredentialUseCase,
)
from insumap.application.credentials.ports import PatientContact
from insumap.application.security.rate_limit import RateLimitCheck, RateLimitRule
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.identity.invitation import (
    DeliveryStatus,
    InvitationChannel,
    InvitationPurpose,
    InvitationStatus,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.identity.user import ClinicSummary
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.i18n import MessageCatalog
from tests.support.commands import InMemoryAuditLog
from tests.support.credentials_fakes import (
    FakeCredentialInvitations,
    FakePatientContacts,
    SequenceActivationCodes,
)
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import (
    FakeCodeHasher,
    FakeIds,
    FakeRateLimiter,
    FakeUnitOfWorkPort,
    FakeUsers,
)
from tests.support.identity_world import make_account
from tests.support.notifications import InMemoryChannel

NOW = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)
CLINIC_ID = UUID(int=10)
OTHER_CLINIC_ID = UUID(int=20)
ADMIN = UUID(int=11)
PATIENT_USER = UUID(int=41)
PATIENT = UUID(int=42)
ACTIVE_PATIENT = UUID(int=43)
ACTIVE_USER = UUID(int=44)
OUTSIDE_PATIENT = UUID(int=45)
OUTSIDE_USER = UUID(int=46)
MISSING = UUID(int=999)
CONTACT_EMAIL = "ana@example.test"
FIRST_CODE = "ABCDEFGHJKMNPQRS"
SECOND_CODE = "TVWXYZ0123456789"
ISSUE_PERMISSIONS = frozenset(
    {PermissionCode.CREDENTIALS_ISSUE, PermissionCode.CREDENTIALS_REVOKE}
)
TTL = timedelta(hours=168)


def admin_actor(
    permissions: frozenset[PermissionCode] = ISSUE_PERMISSIONS,
    clinic_id: UUID | None = CLINIC_ID,
) -> Actor:
    return Actor(
        user_id=ADMIN,
        clinic_id=clinic_id,
        role=Role.CLINIC_ADMIN,
        permissions=permissions,
        requires_mfa=True,
        mfa_verified=True,
    )


class Credentials:
    """The credential use cases over in-memory doubles, wired as the container does."""

    def __init__(self, *codes: str) -> None:
        self.clock = FixedClock(NOW)
        self.uow = FakeUnitOfWorkPort()
        self.current = CurrentUnitOfWork()
        self.audit = InMemoryAuditLog()
        self.users = FakeUsers()
        self.contacts = FakePatientContacts()
        self.invitations = FakeCredentialInvitations()
        self.mail = InMemoryChannel()
        self.messages = MessageCatalog.load_spanish()
        self.ids = FakeIds()
        self.codes = SequenceActivationCodes(*(codes or (FIRST_CODE,)))
        self.hasher = FakeCodeHasher()
        self.limiter = FakeRateLimiter()
        self.users.add(
            make_account(ADMIN, "admin@example.test", role=Role.CLINIC_ADMIN)
        )
        self._seed()

    def _seed(self) -> None:
        self.users.add(
            make_account(
                PATIENT_USER,
                None,
                status=AccountStatus.IMPORTED,
                password=None,
                patient_id=PATIENT,
            )
        )
        self.contacts.add(
            PatientContact(
                patient_id=PATIENT,
                clinic_id=CLINIC_ID,
                user_id=PATIENT_USER,
                contact_email=CONTACT_EMAIL,
            )
        )
        self.users.add(
            make_account(
                ACTIVE_USER,
                "activa@example.test",
                status=AccountStatus.ACTIVE,
                patient_id=ACTIVE_PATIENT,
            )
        )
        self.contacts.add(
            PatientContact(
                patient_id=ACTIVE_PATIENT,
                clinic_id=CLINIC_ID,
                user_id=ACTIVE_USER,
                contact_email="activa@example.test",
            )
        )
        outside = make_account(
            OUTSIDE_USER,
            None,
            status=AccountStatus.IMPORTED,
            password=None,
            patient_id=OUTSIDE_PATIENT,
        )
        self.users.add(
            replace(
                outside,
                clinic=ClinicSummary(
                    clinic_id=OTHER_CLINIC_ID,
                    name="Otra Clínica de Prueba",
                    is_demo=True,
                    is_active=True,
                ),
            )
        )
        self.contacts.add(
            PatientContact(
                patient_id=OUTSIDE_PATIENT,
                clinic_id=OTHER_CLINIC_ID,
                user_id=OUTSIDE_USER,
                contact_email="fuera@example.test",
            )
        )

    def run[R](self, handler: CommandHandler[Any, R], command: Command[R]) -> R:
        """Execute like the container: transaction around audit around the handler."""
        guarded = TransactionalCommandHandler(
            AuditingCommandHandler(handler, self.audit, self.clock),
            self.uow,
            self.current,
        )
        return guarded.handle(command)

    def issue_handler(self) -> IssueCredentialsCommandHandler:
        return IssueCredentialsCommandHandler(
            contacts=self.contacts,
            users=self.users,
            invitations=self.invitations,
            codes=self.codes,
            code_hasher=self.hasher,
            channel=self.mail,
            messages=self.messages,
            base_url="https://app.example.test",
            ids=self.ids,
            clock=self.clock,
            current=self.current,
            code_ttl=TTL,
        )

    def issue(
        self,
        patient: UUID = PATIENT,
        channel: InvitationChannel = InvitationChannel.PRINT,
        actor: Actor | None = None,
    ) -> IssuedCredential:
        return self.run(
            self.issue_handler(),
            IssueCredentialsCommand(
                actor=actor or admin_actor(), patient_id=patient, channel=channel
            ),
        )

    def revoke(self, invitation_id: UUID, actor: Actor | None = None) -> None:
        return self.run(
            RevokeCredentialInvitationCommandHandler(
                users=self.users, invitations=self.invitations, clock=self.clock
            ),
            RevokeCredentialInvitationCommand(
                actor=actor or admin_actor(), invitation_id=invitation_id
            ),
        )

    def batch(
        self, *, batch_limit: int = 10, issue_limit: int = 300
    ) -> IssueCredentialsBatchUseCase:
        bus = InMemoryCommandBus(
            [bind(IssueCredentialsCommand, self.guard(self.issue_handler()))]
        )
        return IssueCredentialsBatchUseCase(
            commands=bus,
            issue_limit=RateLimitCheck(
                self.limiter,
                RateLimitRule(
                    family="issue", limit=issue_limit, window=timedelta(hours=1)
                ),
            ),
            batch_limit=RateLimitCheck(
                self.limiter,
                RateLimitRule(
                    family="batch", limit=batch_limit, window=timedelta(hours=1)
                ),
            ),
        )

    def guard(self, handler: CommandHandler[Any, Any]) -> CommandHandler[Any, Any]:
        return TransactionalCommandHandler(
            AuditingCommandHandler(handler, self.audit, self.clock),
            self.uow,
            self.current,
        )

    def batch_run(
        self,
        patients: tuple[UUID, ...],
        channel: InvitationChannel = InvitationChannel.PRINT,
    ) -> Any:
        return self.batch().execute(
            IssueCredentialsBatchInput(
                actor=admin_actor(), patient_ids=patients, channel=channel
            )
        )


def test_p13_issue_prints_a_code_and_moves_the_account_to_invited() -> None:
    """Pattern: P13 Command. The code is in the result, never in the stored row."""
    world = Credentials()

    issued = world.issue()

    assert issued.activation_code == "ABCD-EFGH-JKMN-PQRS"
    assert issued.delivery_status is DeliveryStatus.NOT_APPLICABLE
    assert issued.expires_at == NOW + TTL
    row = world.invitations.row(issued.invitation_id)
    assert row.invitation.status is InvitationStatus.PENDING
    assert row.invitation.purpose is InvitationPurpose.PATIENT_ACTIVATION
    assert row.code_hash == f"hmac-ACTIVATION-{FIRST_CODE}"
    assert world.users.get(PATIENT_USER).status is AccountStatus.INVITED  # type: ignore[union-attr]
    assert world.mail.delivered == []


def test_the_code_is_not_in_the_audit_log_or_in_repr() -> None:
    world = Credentials()

    issued = world.issue()

    (entry,) = world.audit.entries
    assert entry.action == "CREDENTIALS_ISSUED"
    assert entry.entity_type == "CREDENTIAL_INVITATION"
    assert entry.entity_id == issued.invitation_id
    assert entry.changed_fields == ("status", "expires_at")
    assert "ABCD" not in repr(entry)
    assert "ABCD" not in repr(issued)


def test_email_channel_sends_the_link_after_commit_and_returns_no_code() -> None:
    world = Credentials()

    issued = world.issue(channel=InvitationChannel.EMAIL)

    assert issued.activation_code is None
    assert issued.delivery_status is DeliveryStatus.PENDING
    (sent,) = world.mail.delivered
    assert sent.recipient.address == CONTACT_EMAIL
    assert "https://app.example.test/activar#code=ABCD-EFGH-JKMN-PQRS" in sent.body
    assert "7" in sent.body


def test_a_failed_email_does_not_fail_the_issue() -> None:
    world = Credentials()
    world.mail.fail = True

    issued = world.issue(channel=InvitationChannel.EMAIL)

    assert issued.invitation_id in world.invitations.rows
    assert (
        world.invitations.row(issued.invitation_id).delivery_status
        is DeliveryStatus.PENDING
    )


def test_reissue_revokes_the_open_invitation_and_links_the_replacement() -> None:
    world = Credentials(FIRST_CODE, SECOND_CODE)
    first = world.issue()

    second = world.issue()

    old = world.invitations.row(first.invitation_id)
    assert old.invitation.status is InvitationStatus.REVOKED
    assert old.invitation.revoked_at == NOW
    assert old.revoked_by == ADMIN
    assert old.replaced_by_id == second.invitation_id
    new = world.invitations.row(second.invitation_id)
    assert new.invitation.status is InvitationStatus.PENDING
    assert new.code_hash == f"hmac-ACTIVATION-{SECOND_CODE}"
    assert world.users.get(PATIENT_USER).status is AccountStatus.INVITED  # type: ignore[union-attr]
    assert len(world.invitations.open_for(PATIENT_USER)) == 1


@pytest.mark.parametrize(
    "status",
    [AccountStatus.ACTIVE, AccountStatus.SUSPENDED, AccountStatus.DEACTIVATED],
)
def test_accounts_past_activation_are_refused_without_writes(
    status: AccountStatus,
) -> None:
    world = Credentials()
    account = world.users.get(ACTIVE_USER)
    assert account is not None
    world.users.save(replace(account, status=status))

    with pytest.raises(InvalidStateTransitionError) as refused:
        world.issue(patient=ACTIVE_PATIENT)

    assert refused.value.code is ErrorCode.INVALID_STATE_TRANSITION
    assert world.invitations.rows == {}
    assert world.audit.entries == []


def test_email_without_a_contact_address_is_a_field_error_and_writes_nothing() -> None:
    world = Credentials()
    world.contacts.add(
        PatientContact(
            patient_id=PATIENT,
            clinic_id=CLINIC_ID,
            user_id=PATIENT_USER,
            contact_email=None,
        )
    )

    with pytest.raises(InsumapError) as refused:
        world.issue(channel=InvitationChannel.EMAIL)

    assert refused.value.code is ErrorCode.VALIDATION_ERROR
    assert refused.value.detail == {
        "errors": [{"field": "body.channel", "type": "missing_contact_email"}]
    }
    assert world.invitations.rows == {}


def test_print_still_works_for_a_patient_without_contact_address() -> None:
    world = Credentials()
    world.contacts.add(
        PatientContact(
            patient_id=PATIENT,
            clinic_id=CLINIC_ID,
            user_id=PATIENT_USER,
            contact_email=None,
        )
    )

    issued = world.issue(channel=InvitationChannel.PRINT)

    assert issued.activation_code is not None


def test_a_patient_of_another_clinic_or_a_missing_one_is_not_found() -> None:
    world = Credentials()

    with pytest.raises(ResourceNotFoundError):
        world.issue(patient=OUTSIDE_PATIENT)
    with pytest.raises(ResourceNotFoundError):
        world.issue(patient=MISSING)
    assert world.invitations.rows == {}


def test_missing_permission_is_refused_before_any_lookup() -> None:
    world = Credentials()

    with pytest.raises(PermissionDeniedError):
        world.issue(actor=admin_actor(permissions=frozenset()))
    assert world.invitations.rows == {}


def test_revoke_returns_the_account_to_imported() -> None:
    world = Credentials()
    issued = world.issue()

    world.revoke(issued.invitation_id)

    row = world.invitations.row(issued.invitation_id)
    assert row.invitation.status is InvitationStatus.REVOKED
    assert row.revoked_by == ADMIN
    assert world.users.get(PATIENT_USER).status is AccountStatus.IMPORTED  # type: ignore[union-attr]
    entry = world.audit.entries[-1]
    assert entry.action == "CREDENTIAL_INVITATION_REVOKED"
    assert entry.entity_id == issued.invitation_id


def test_revoking_a_closed_invitation_is_an_invalid_transition() -> None:
    world = Credentials()
    issued = world.issue()
    world.revoke(issued.invitation_id)

    with pytest.raises(InvalidStateTransitionError):
        world.revoke(issued.invitation_id)


def test_revoke_hides_other_clinics_and_other_purposes() -> None:
    world = Credentials()
    issued = world.issue()
    row = world.invitations.row(issued.invitation_id)
    world.invitations.rows[issued.invitation_id] = replace(
        row,
        invitation=replace(row.invitation, purpose=InvitationPurpose.STAFF_ACTIVATION),
    )

    with pytest.raises(ResourceNotFoundError):
        world.revoke(issued.invitation_id)
    with pytest.raises(ResourceNotFoundError):
        world.revoke(UUID(int=12345))


def test_batch_reports_each_patient_and_keeps_going_after_a_failure() -> None:
    world = Credentials(FIRST_CODE, SECOND_CODE)

    results = world.batch_run((PATIENT, ACTIVE_PATIENT, MISSING))

    assert [r.patient_id for r in results] == [PATIENT, ACTIVE_PATIENT, MISSING]
    assert results[0].issued is not None
    assert results[0].issued.activation_code == "ABCD-EFGH-JKMN-PQRS"
    assert results[1].issued is None
    assert results[1].error_code is ErrorCode.INVALID_STATE_TRANSITION
    assert results[2].error_code is ErrorCode.NOT_FOUND


def test_batch_refused_by_the_batch_limit_creates_no_code() -> None:
    world = Credentials()
    world.limiter.blocked = True

    with pytest.raises(InsumapError) as refused:
        world.batch_run((PATIENT,))

    assert refused.value.code is ErrorCode.RATE_LIMITED
    assert world.invitations.rows == {}
    assert world.audit.entries == []


def test_single_issue_use_case_counts_against_the_clinic_limit() -> None:
    world = Credentials()
    use_case = IssueCredentialUseCase(
        commands=InMemoryCommandBus(
            [bind(IssueCredentialsCommand, world.guard(world.issue_handler()))]
        ),
        issue_limit=RateLimitCheck(
            world.limiter,
            RateLimitRule(family="issue", limit=300, window=timedelta(hours=1)),
        ),
    )

    issued = use_case.execute(
        IssueCredentialInput(
            actor=admin_actor(), patient_id=PATIENT, channel=InvitationChannel.PRINT
        )
    )

    assert issued.activation_code is not None
    assert world.limiter.hits == [("issue", f"clinic:{CLINIC_ID}")]
