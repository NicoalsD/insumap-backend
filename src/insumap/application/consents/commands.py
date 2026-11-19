"""Decisions of the patient about its consent: accept and withdraw (P13)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, final, override
from uuid import UUID

from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.commands.transactional import CurrentUnitOfWork
from insumap.application.common.ids import IdGenerator
from insumap.application.consents.gate import OwnConsentGate
from insumap.application.consents.ports import ConsentHistoryPort
from insumap.application.consents.views import OwnConsentView, own_view
from insumap.application.identity.ports import ConsentRepositoryPort, PrivacyNotice
from insumap.application.monitoring.gate import OwnScope
from insumap.domain.identity.consent import (
    ConsentAction,
    ConsentRecord,
    ConsentScope,
)
from insumap.domain.identity.consent_events import SensitiveConsentWithdrawn
from insumap.domain.identity.errors import (
    ConsentVersionOutdatedError,
    InvalidStateTransitionError,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.time import Clock

CONSENT_MACHINE: str = "PATIENT_CONSENT"
CONSENT_ENTITY: str = "PATIENT_CONSENT"


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptConsentCommand(Command[OwnConsentView]):
    """The patient accepts the notice version in force, and maybe the external AI."""

    audit_action: ClassVar[str] = "CONSENT_ACCEPTED"
    audit_entity_type: ClassVar[str] = CONSENT_ENTITY

    privacy_notice_version_id: UUID
    ai_external_processing: bool

    @override
    def audit_subject(self, result: OwnConsentView) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=self.actor.own_patient_id(),
            changed_fields=("privacy_notice_version_id", "scope"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class WithdrawConsentCommand(Command[OwnConsentView]):
    """The patient withdraws one scope of its consent."""

    audit_action: ClassVar[str] = "CONSENT_WITHDRAWN"
    audit_entity_type: ClassVar[str] = CONSENT_ENTITY

    scope: ConsentScope

    @override
    def audit_subject(self, result: OwnConsentView) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=self.actor.own_patient_id(),
            changed_fields=("scope", "action"),
        )


@final
class AcceptConsentCommandHandler(CommandHandler[AcceptConsentCommand, OwnConsentView]):
    """Appends the acceptance on the version in force; the old ones stay.

    An outdated version answers ``409 CONSENT_VERSION_OUTDATED``. Accepting
    without external AI after accepting it clears that scope with a withdrawal
    row, so the latest act always reflects the patient's last choice.
    """

    def __init__(
        self,
        *,
        gate: OwnConsentGate,
        consents: ConsentRepositoryPort,
        history: ConsentHistoryPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._gate = gate
        self._consents = consents
        self._history = history
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: AcceptConsentCommand) -> OwnConsentView:
        scope = self._gate.enter(command.actor, PermissionCode.CONSENTS_MANAGE_OWN)
        notice = self._consents.current_notice(scope.clinic_id)
        if notice is None or notice.version_id != command.privacy_notice_version_id:
            raise ConsentVersionOutdatedError
        latest = dict(self._history.latest_per_scope(scope.patient_id))
        now = self._clock.now()
        records = [
            self._act(
                command,
                scope,
                notice,
                ConsentScope.SENSITIVE_DATA_PROCESSING,
                ConsentAction.ACCEPTED,
                now,
            )
        ]
        external = latest.get(ConsentScope.AI_EXTERNAL_PROCESSING)
        if command.ai_external_processing:
            records.append(
                self._act(
                    command,
                    scope,
                    notice,
                    ConsentScope.AI_EXTERNAL_PROCESSING,
                    ConsentAction.ACCEPTED,
                    now,
                )
            )
        elif external is not None and external.action is ConsentAction.ACCEPTED:
            records.append(
                self._act(
                    command,
                    scope,
                    notice,
                    ConsentScope.AI_EXTERNAL_PROCESSING,
                    ConsentAction.WITHDRAWN,
                    now,
                )
            )
        self._consents.add(records)
        latest.update({record.scope: record for record in records})
        return own_view(latest, notice.version_id)

    def _act(
        self,
        command: AcceptConsentCommand,
        scope: OwnScope,
        notice: PrivacyNotice,
        consent_scope: ConsentScope,
        action: ConsentAction,
        now: datetime,
    ) -> ConsentRecord:
        return ConsentRecord(
            consent_id=self._ids.new_id(),
            clinic_id=scope.clinic_id,
            patient_id=scope.patient_id,
            privacy_notice_version_id=notice.version_id,
            scope=consent_scope,
            action=action,
            occurred_at=now,
            recorded_by=command.actor.user_id,
        )


@final
class WithdrawConsentCommandHandler(
    CommandHandler[WithdrawConsentCommand, OwnConsentView]
):
    """Appends a withdrawal of an accepted scope; nothing is deleted.

    Withdrawing the sensitive-data scope stops new records (``CONSENT_REQUIRED``
    from then on) and collects ``SensitiveConsentWithdrawn`` (P17), published
    after the commit. Withdrawing a scope that is not accepted is a
    ``409 INVALID_STATE_TRANSITION``.
    """

    def __init__(
        self,
        *,
        gate: OwnConsentGate,
        consents: ConsentRepositoryPort,
        history: ConsentHistoryPort,
        ids: IdGenerator,
        clock: Clock,
        events: CurrentUnitOfWork,
    ) -> None:
        self._gate = gate
        self._consents = consents
        self._history = history
        self._ids = ids
        self._clock = clock
        self._events = events

    @override
    def handle(self, command: WithdrawConsentCommand) -> OwnConsentView:
        scope = self._gate.enter(command.actor, PermissionCode.CONSENTS_MANAGE_OWN)
        latest = dict(self._history.latest_per_scope(scope.patient_id))
        accepted = latest.get(command.scope)
        if accepted is None or accepted.action is not ConsentAction.ACCEPTED:
            status = "NONE" if accepted is None else accepted.action.value
            raise InvalidStateTransitionError(CONSENT_MACHINE, status, "WITHDRAW")
        now = self._clock.now()
        withdrawal = ConsentRecord(
            consent_id=self._ids.new_id(),
            clinic_id=scope.clinic_id,
            patient_id=scope.patient_id,
            privacy_notice_version_id=accepted.privacy_notice_version_id,
            scope=command.scope,
            action=ConsentAction.WITHDRAWN,
            occurred_at=now,
            recorded_by=command.actor.user_id,
        )
        self._consents.add([withdrawal])
        if command.scope is ConsentScope.SENSITIVE_DATA_PROCESSING:
            self._events.collect(
                [
                    SensitiveConsentWithdrawn(
                        event_id=self._ids.new_id(),
                        occurred_at=now,
                        clinic_id=scope.clinic_id,
                        patient_id=scope.patient_id,
                    )
                ]
            )
        latest[command.scope] = withdrawal
        notice = self._consents.current_notice(scope.clinic_id)
        return own_view(latest, None if notice is None else notice.version_id)
