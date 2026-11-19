"""The privacy request state machine (P18 State) and the consent standing."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from insumap.domain.identity.consent import (
    ConsentAction,
    ConsentRecord,
    ConsentScope,
    ConsentStanding,
    standing_of,
)
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.privacy.request import (
    PrivacyDecision,
    PrivacyRequest,
    PrivacyRequestStatus,
    PrivacyRequestType,
    state_of,
)

AT = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
NOTICE = UUID(int=60)
NEW_NOTICE = UUID(int=61)


def request(status: PrivacyRequestStatus) -> PrivacyRequest:
    return PrivacyRequest(
        request_id=UUID(int=7),
        clinic_id=UUID(int=1),
        patient_id=UUID(int=2),
        request_type=PrivacyRequestType.ACCESS,
        status=status,
        requested_at=AT,
        due_at=AT + timedelta(days=10),
    )


def act(action: ConsentAction, *, at: datetime, notice: UUID = NOTICE) -> ConsentRecord:
    return ConsentRecord(
        consent_id=UUID(int=9),
        clinic_id=UUID(int=1),
        patient_id=UUID(int=2),
        privacy_notice_version_id=notice,
        scope=ConsentScope.SENSITIVE_DATA_PROCESSING,
        action=action,
        occurred_at=at,
        recorded_by=UUID(int=3),
    )


@pytest.mark.parametrize(
    ("status", "decision", "expected"),
    [
        (
            PrivacyRequestStatus.OPEN,
            PrivacyDecision.APPROVE,
            PrivacyRequestStatus.APPROVED,
        ),
        (
            PrivacyRequestStatus.OPEN,
            PrivacyDecision.REJECT,
            PrivacyRequestStatus.REJECTED,
        ),
        (
            PrivacyRequestStatus.IN_PROGRESS,
            PrivacyDecision.APPROVE,
            PrivacyRequestStatus.APPROVED,
        ),
        (
            PrivacyRequestStatus.IN_PROGRESS,
            PrivacyDecision.REJECT,
            PrivacyRequestStatus.REJECTED,
        ),
    ],
)
def test_an_open_request_takes_the_clinic_decision(
    status: PrivacyRequestStatus,
    decision: PrivacyDecision,
    expected: PrivacyRequestStatus,
) -> None:
    resolved = request(status).decide(
        decision, note="Solicitud revisada por la clínica", resolver=UUID(int=5), at=AT
    )

    assert resolved.status is expected
    assert resolved.resolved_by == UUID(int=5)
    assert resolved.resolution_note == "Solicitud revisada por la clínica"


@pytest.mark.parametrize(
    "status",
    [
        PrivacyRequestStatus.APPROVED,
        PrivacyRequestStatus.REJECTED,
        PrivacyRequestStatus.COMPLETED,
    ],
)
def test_a_decided_request_refuses_another_decision(
    status: PrivacyRequestStatus,
) -> None:
    with pytest.raises(InvalidStateTransitionError):
        request(status).decide(
            PrivacyDecision.APPROVE,
            note="Motivo suficientemente largo",
            resolver=UUID(int=5),
            at=AT,
        )


def test_only_an_approved_request_is_exportable() -> None:
    assert request(PrivacyRequestStatus.APPROVED).exportable
    for status in (
        PrivacyRequestStatus.OPEN,
        PrivacyRequestStatus.IN_PROGRESS,
        PrivacyRequestStatus.REJECTED,
        PrivacyRequestStatus.COMPLETED,
    ):
        assert not request(status).exportable
        assert not state_of(status).exportable


def test_every_stored_status_has_a_state() -> None:
    for status in PrivacyRequestStatus:
        assert state_of(status).status is status


def test_no_act_means_pending() -> None:
    assert standing_of(None, NOTICE) is ConsentStanding.PENDING


def test_an_acceptance_on_the_notice_in_force_is_granted() -> None:
    assert standing_of(act(ConsentAction.ACCEPTED, at=AT), NOTICE) is (
        ConsentStanding.GRANTED
    )


def test_an_acceptance_of_an_outdated_notice_is_pending() -> None:
    assert standing_of(act(ConsentAction.ACCEPTED, at=AT), NEW_NOTICE) is (
        ConsentStanding.PENDING
    )


def test_a_withdrawal_is_the_latest_word() -> None:
    latest = act(ConsentAction.WITHDRAWN, at=AT + timedelta(minutes=1))

    assert standing_of(latest, NOTICE) is ConsentStanding.WITHDRAWN
