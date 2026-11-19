"""Ports of the consent reads and of the public privacy notice."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.identity.consent import ConsentRecord, ConsentScope, ConsentStanding


@dataclass(frozen=True, slots=True, kw_only=True)
class PrivacyNoticeView:
    """A privacy notice version, as the patient reads it before logging in."""

    version_id: UUID
    clinic_id: UUID
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


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsentStatusFilter:
    """The standing asked for; ``None`` lists every patient."""

    standing: ConsentStanding | None = None


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
        self, clinic_id: UUID, query: ConsentStatusFilter, page: PageRequest
    ) -> Page[PatientConsentStatus]:
        """One row per patient of the clinic, by patient id, with the standing."""
