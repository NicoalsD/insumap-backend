"""P13 Command: the doctor dismisses a pattern finding, without a database (RF-68)."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from insumap.application.ai.assessments import AiExplanation
from insumap.application.ai.finding_dismissal import (
    DismissPatternFindingCommand,
    DismissPatternFindingCommandHandler,
)
from insumap.application.ai.records import (
    PatternFindingReadPort,
    PatternFindingReviewPort,
    PatternFindingView,
)
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.ai.finding_review import (
    FindingDismissal,
    FindingNoteInvalidError,
    parse_dismissal_note,
)
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits
from tests.support.identity_fakes import FakeIds

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
CLINIC = UUID(int=9)
DOCTOR = UUID(int=1)
PATIENT = UUID(int=100)
OTHER_PATIENT = UUID(int=101)
FINDING = UUID(int=500)
NOTE = "Hipoglucemia por un ayuno de la noche, ya explicada."
DOCTOR_PERMISSIONS = frozenset({PermissionCode.AI_RISK_READ_ASSIGNED})


def _finding(finding_id: UUID = FINDING) -> PatternFindingView:
    return PatternFindingView(
        finding_id=finding_id,
        patient_id=PATIENT,
        pattern_type="NOCTURNAL_HYPOGLYCEMIA",
        window_start=NOW,
        window_end=NOW,
        confidence=None,
        evidence={},
        explanation=_explanation(),
        model_version="0.2.0",
        is_fallback=True,
        fallback_reason="AI_ERROR",
        generated_at=NOW,
    )


def _explanation() -> AiExplanation:
    return AiExplanation(summary="Cuatro noches bajo meta.")


class InMemoryFindings(PatternFindingReadPort):
    def __init__(self, items: list[PatternFindingView]) -> None:
        self.items = items

    def list_for_patient(
        self, patient_id: UUID, page: PageRequest
    ) -> Page[PatternFindingView]:
        del patient_id, page
        return Page(items=list(self.items), next_cursor=None)

    def get_for_patient(
        self, patient_id: UUID, finding_id: UUID
    ) -> PatternFindingView | None:
        for item in self.items:
            if item.finding_id == finding_id and item.patient_id == patient_id:
                return item
        return None


class InMemoryReviews(PatternFindingReviewPort):
    """Refuses a second dismissal of the same finding, as the table does."""

    def __init__(self, findings: InMemoryFindings) -> None:
        self.findings = findings
        self.rows: list[FindingDismissal] = []

    def add(self, dismissal: FindingDismissal) -> None:
        if any(row.finding_id == dismissal.finding_id for row in self.rows):
            raise InvalidStateTransitionError("PATTERN_FINDING", "DISMISSED", "DISMISS")
        self.rows.append(dismissal)
        self.findings.items = [
            replace(
                item,
                dismissed_at=dismissal.reviewed_at,
                dismissed_by=dismissal.reviewed_by,
            )
            if item.finding_id == dismissal.finding_id
            else item
            for item in self.findings.items
        ]


class FixedPatientGate:
    def __init__(self, assigned: set[UUID]) -> None:
        self.assigned = assigned

    def enter(
        self,
        actor: Actor,
        permission: PermissionCode,
        patient_id: UUID,
        resource: object,
    ) -> UUID:
        del resource
        actor.require(permission)
        if patient_id not in self.assigned:
            raise InsumapError(ErrorCode.NOT_FOUND)
        return patient_id


class FixedClock:
    def now(self) -> datetime:
        return NOW


class Harness:
    def __init__(
        self,
        *,
        findings: list[PatternFindingView] | None = None,
        assigned: set[UUID] | None = None,
    ) -> None:
        self.findings = InMemoryFindings([_finding()] if findings is None else findings)
        self.reviews = InMemoryReviews(self.findings)
        self.gate = FixedPatientGate({PATIENT} if assigned is None else assigned)

    def handler(self) -> DismissPatternFindingCommandHandler:
        return DismissPatternFindingCommandHandler(
            assigned_gate=self.gate,  # type: ignore[arg-type]
            findings=self.findings,
            reviews=self.reviews,
            clock=FixedClock(),
            ids=FakeIds(),
        )


def _doctor(permissions: frozenset[PermissionCode] = DOCTOR_PERMISSIONS) -> Actor:
    return Actor(
        user_id=DOCTOR,
        clinic_id=CLINIC,
        role=Role.DOCTOR,
        permissions=permissions,
    )


def _command(
    *,
    note: str = NOTE,
    patient_id: UUID = PATIENT,
    finding_id: UUID = FINDING,
    actor: Actor | None = None,
) -> DismissPatternFindingCommand:
    return DismissPatternFindingCommand(
        actor=_doctor() if actor is None else actor,
        patient_id=patient_id,
        finding_id=finding_id,
        note=note,
    )


# Pattern: P13 Command
def test_dismissing_appends_one_review_with_the_doctors_identity_and_time() -> None:
    harness = Harness()

    result = harness.handler().handle(_command(note=f"  {NOTE}  "))

    assert result.status == "DISMISSED"
    assert result.dismissed_at == NOW
    assert result.dismissed_by == DOCTOR
    (row,) = harness.reviews.rows
    assert row.finding_id == FINDING
    assert row.patient_id == PATIENT
    assert row.clinic_id == CLINIC
    assert row.reviewed_by == DOCTOR
    assert row.reviewed_at == NOW
    assert row.note == NOTE


# Pattern: P13 Command
def test_a_second_dismissal_is_a_state_conflict_and_writes_nothing() -> None:
    harness = Harness()
    harness.handler().handle(_command())

    with pytest.raises(InvalidStateTransitionError):
        harness.handler().handle(_command())

    assert len(harness.reviews.rows) == 1


# Pattern: P13 Command
def test_a_finding_of_another_patient_is_refused_like_a_missing_one() -> None:
    harness = Harness(assigned={PATIENT, OTHER_PATIENT})

    with pytest.raises(ResourceNotFoundError):
        harness.handler().handle(_command(patient_id=OTHER_PATIENT))

    assert harness.reviews.rows == []


# Pattern: P13 Command
def test_a_patient_who_is_not_assigned_is_404_and_nothing_is_read_or_written() -> None:
    harness = Harness(assigned=set())

    with pytest.raises(InsumapError) as refused:
        harness.handler().handle(_command())

    assert refused.value.code is ErrorCode.NOT_FOUND
    assert harness.reviews.rows == []


# Pattern: P13 Command
def test_an_unknown_finding_is_not_found() -> None:
    harness = Harness()

    with pytest.raises(ResourceNotFoundError):
        harness.handler().handle(_command(finding_id=UUID(int=999)))

    assert harness.reviews.rows == []


# Pattern: P13 Command
def test_without_the_permission_nothing_is_written() -> None:
    harness = Harness()

    with pytest.raises(PermissionDeniedError):
        harness.handler().handle(_command(actor=_doctor(frozenset())))

    assert harness.reviews.rows == []


# Pattern: P13 Command
def test_a_blank_note_is_refused_before_any_read() -> None:
    harness = Harness()

    with pytest.raises(FindingNoteInvalidError):
        harness.handler().handle(_command(note="   "))

    assert harness.reviews.rows == []


def test_the_audit_keeps_the_trimmed_note_and_the_finding_not_the_patient() -> None:
    command = _command(note=f"  {NOTE}  ")
    result = replace(_finding(), dismissed_at=NOW, dismissed_by=DOCTOR)

    subject = command.audit_subject(result)

    assert subject.clinic_id == CLINIC
    assert subject.entity_id == FINDING
    assert subject.reason == NOTE
    assert "status" in subject.changed_fields


def test_the_note_is_bounded_by_field_limits() -> None:
    longest = "x" * FieldLimits.PATTERN_FINDING_NOTE_MAX_LENGTH

    assert parse_dismissal_note(longest) == longest
    with pytest.raises(FindingNoteInvalidError):
        parse_dismissal_note(longest + "x")
    with pytest.raises(FindingNoteInvalidError):
        parse_dismissal_note(" \t ")


def test_the_dismissed_status_follows_the_dismissal_time() -> None:
    assert _finding().status == "NEW"
    assert replace(_finding(), dismissed_at=NOW).status == "DISMISSED"
