"""Writes the doctor's dismissal of a pattern finding (ai.pattern_finding_reviews)."""

from __future__ import annotations

from typing import Final, final, override

from sqlalchemy.exc import IntegrityError

from insumap.application.ai.records import PatternFindingReviewPort
from insumap.domain.ai.finding_review import FindingDismissal
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.infrastructure.persistence.orm import PatternFindingReviewOrm
from insumap.infrastructure.persistence.transactions import CurrentSession

DISMISSED: Final = "DISMISSED"
FINDING_UNIQUE: Final = "uq_pattern_finding_reviews_finding_id"
FINDING_MACHINE: Final = "PATTERN_FINDING"


@final
class SqlPatternFindingReviews(PatternFindingReviewPort):
    """Appends one dismissal. The table has no UPDATE or DELETE for anyone."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def add(self, dismissal: FindingDismissal) -> None:
        session = self._current.get()
        session.add(
            PatternFindingReviewOrm(
                id=dismissal.dismissal_id,
                clinic_id=dismissal.clinic_id,
                patient_id=dismissal.patient_id,
                finding_id=dismissal.finding_id,
                action=DISMISSED,
                reason=dismissal.note,
                reviewed_by=dismissal.reviewed_by,
                reviewed_at=dismissal.reviewed_at,
            )
        )
        try:
            session.flush()
        except IntegrityError as error:
            # A second dismissal of the same finding, from a concurrent request.
            diag = getattr(error.orig, "diag", None)
            if getattr(diag, "constraint_name", None) != FINDING_UNIQUE:
                raise
            raise InvalidStateTransitionError(
                FINDING_MACHINE, DISMISSED, "DISMISS"
            ) from error
