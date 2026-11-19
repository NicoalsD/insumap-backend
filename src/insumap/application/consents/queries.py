"""Reads of the consent: the public notice, the own consent and the clinic statuses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.access.ports import (
    AccessPurpose,
    DataAccessLogPort,
    DataAccessOutcome,
    DataAccessRecord,
    DataResource,
)
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.consents.gate import OwnConsentGate
from insumap.application.consents.ports import (
    ConsentHistoryPort,
    ConsentStatusFilter,
    PatientConsentStatus,
    PrivacyNoticeQueryPort,
    PrivacyNoticeView,
)
from insumap.application.consents.views import OwnConsentView, own_view
from insumap.application.identity.ports import ConsentRepositoryPort
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.request_context import current_request_id
from insumap.shared.time import Clock


@final
class GetPrivacyNoticeUseCase:
    """``GET /public/privacy-notices/{id}``: no session, so no clinic context.

    The notice lives in ``clinic.privacy_notice_versions``, whose row level
    security needs a clinic. Until the database offers a ``SECURITY DEFINER``
    lookup, the session sees nothing and the answer is ``NOT_FOUND``.
    """

    def __init__(self, *, uow: UnitOfWorkPort, notices: PrivacyNoticeQueryPort) -> None:
        self._uow = uow
        self._notices = notices

    def execute(self, notice_id: UUID) -> PrivacyNoticeView:
        with self._uow.begin(TransactionContext.anonymous()):
            view = self._notices.find(notice_id)
        if view is None:
            raise ResourceNotFoundError
        return view


@final
class GetOwnConsentUseCase:
    """``GET /consents/own``: the patient's accepted version; never blocked by C3."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnConsentGate,
        consents: ConsentRepositoryPort,
        history: ConsentHistoryPort,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._consents = consents
        self._history = history

    def execute(self, actor: Actor) -> OwnConsentView:
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            scope = self._gate.enter(actor, PermissionCode.CONSENTS_MANAGE_OWN)
            notice = self._consents.current_notice(scope.clinic_id)
            view = own_view(
                self._history.latest_per_scope(scope.patient_id),
                None if notice is None else notice.version_id,
            )
            unit.commit()
        return view


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ListConsentStatusesInput:
    """The administrator asking, the standing filter and the page."""

    actor: Actor
    query: ConsentStatusFilter
    page: PageRequest


@final
class ListConsentStatusesUseCase:
    """``GET /consents``: the clinic's patients with their consent, no clinical data.

    Each read leaves a ``PATIENT_LIST`` row in ``audit.data_access_log``.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        history: ConsentHistoryPort,
        access_log: DataAccessLogPort,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._history = history
        self._log = access_log
        self._clock = clock

    def execute(self, input: ListConsentStatusesInput) -> Page[PatientConsentStatus]:
        actor = input.actor
        actor.require(PermissionCode.CONSENTS_READ_STATUS)
        if actor.clinic_id is None:
            raise PermissionDeniedError
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            page = self._history.statuses(actor.clinic_id, input.query, input.page)
            self._log.record_granted(
                DataAccessRecord(
                    occurred_at=self._clock.now(),
                    clinic_id=actor.clinic_id,
                    actor_user_id=actor.user_id,
                    actor_role=actor.role,
                    patient_id=None,
                    resource=DataResource.PATIENT_LIST,
                    purpose=AccessPurpose.ADMINISTRATION,
                    outcome=DataAccessOutcome.GRANTED,
                    request_id=current_request_id(),
                )
            )
            # A read commits its audit row: without it the transaction rolls back.
            unit.commit()
        return page
