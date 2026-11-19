"""Port of the follow-up controls under row level security (``care.follow_ups``)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.follow_ups.follow_up import FollowUp, FollowUpStatus


class FollowUpRepositoryPort(ABC):
    """Controls of the session's clinic; a patient sees only its own (RLS)."""

    @abstractmethod
    def insert(self, follow_up: FollowUp) -> None:
        """Insert a scheduled control in the current transaction."""

    @abstractmethod
    def get(self, follow_up_id: UUID) -> FollowUp | None:
        """A control, or ``None`` if it does not exist or is not visible."""

    @abstractmethod
    def update(self, follow_up: FollowUp) -> None:
        """Write the status, result note and close time of a control."""

    @abstractmethod
    def list_for_patient(
        self,
        patient_id: UUID,
        *,
        status: FollowUpStatus | None,
        page: PageRequest,
    ) -> Page[FollowUp]:
        """A page of the controls of a patient, newest first."""
