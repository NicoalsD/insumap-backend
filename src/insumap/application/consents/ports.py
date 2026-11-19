"""Ports of the consent reads and of the public privacy notice."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.identity.consent import ConsentRecord, ConsentScope, ConsentStanding
from insumap.domain.privacy.request import PrivacyRequest


@dataclass(frozen=True, slots=True, kw_only=True)
class PrivacyNoticeView:
    """A privacy notice version, as the patient reads it before logging in."""

    version_id: UUID
    version: str
    content: str
    effective_from: datetime


class PrivacyNoticeQueryPort(ABC):
    """Reads a notice version by id, under the session context (RLS decides)."""

    @abstractmethod
    def find(self, notice_id: UUID) -> PrivacyNoticeView | None:
        """The notice, or ``None`` when the session may not see it."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientConsentStatus:
    """One patient of the clinic and the standing of its sensitive-data consent."""

    patient_id: UUID
    standing: ConsentStanding
    privacy_notice_version_id: UUID | None
    occurred_at: datetime | None


class ConsentHistoryPort(ABC):
    """Reads the append-only consent acts (``clinic.patient_consents``)."""

    @abstractmethod
    def latest_per_scope(
        self, patient_id: UUID
    ) -> Mapping[ConsentScope, ConsentRecord]:
        """The latest act of each scope the patient has an act for."""

    @abstractmethod
    def history(self, patient_id: UUID) -> list[ConsentRecord]:
        """Every act of the patient, oldest first (proof of authorization)."""

    @abstractmethod
    def statuses(
        self, clinic_id: UUID, page: PageRequest
    ) -> Page[PatientConsentStatus]:
        """One row per patient of the clinic, by patient id, with the standing."""


class PrivacyRequestPort(ABC):
    """Stores privacy requests under the session's row level security."""

    @abstractmethod
    def get(self, request_id: UUID) -> PrivacyRequest | None:
        """The request, or ``None`` if the session may not see it."""

    @abstractmethod
    def list(self, patient_id: UUID | None, page: PageRequest) -> Page[PrivacyRequest]:
        """Requests of one patient (or all of the clinic), oldest first."""

    @abstractmethod
    def add(self, request: PrivacyRequest) -> None:
        """Insert a new request."""

    @abstractmethod
    def save(self, request: PrivacyRequest) -> None:
        """Persist the decision on a request."""
