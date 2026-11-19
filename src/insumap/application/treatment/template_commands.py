"""Decisions about protocol templates: create, version and retire (P13, P09)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final, final, override
from uuid import UUID

from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.common.ids import IdGenerator
from insumap.application.treatment.ports import ProtocolTemplateRepositoryPort
from insumap.domain.common.errors import ConflictError, ResourceNotFoundError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.treatment.content import TemplateContent
from insumap.domain.treatment.template import (
    ProtocolTemplate,
    TemplateStatus,
    derive_template_code,
)
from insumap.shared.field_limits import FieldLimits
from insumap.shared.time import Clock

TEMPLATE_ENTITY: Final = "PROTOCOL_TEMPLATE"
CODE_TAKEN: Final = "code_taken"


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateProtocolTemplateCommand(Command[ProtocolTemplate]):
    """The clinic administrator creates a template; its code comes from its name."""

    audit_action: ClassVar[str] = "PROTOCOL_TEMPLATE_CREATED"
    audit_entity_type: ClassVar[str] = TEMPLATE_ENTITY

    name: str
    content: TemplateContent

    @override
    def audit_subject(self, result: ProtocolTemplate) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.template_id,
            changed_fields=("code", "name", "content", "version", "status"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateProtocolTemplateVersionCommand(Command[ProtocolTemplate]):
    """The clinic administrator publishes a new version of a template."""

    audit_action: ClassVar[str] = "PROTOCOL_TEMPLATE_VERSIONED"
    audit_entity_type: ClassVar[str] = TEMPLATE_ENTITY

    template_id: UUID
    content: TemplateContent

    @override
    def audit_subject(self, result: ProtocolTemplate) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.template_id,
            changed_fields=("content", "version"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RetireProtocolTemplateCommand(Command[ProtocolTemplate]):
    """The clinic administrator retires a template: it can no longer be cloned."""

    audit_action: ClassVar[str] = "PROTOCOL_TEMPLATE_RETIRED"
    audit_entity_type: ClassVar[str] = TEMPLATE_ENTITY

    template_id: UUID

    @override
    def audit_subject(self, result: ProtocolTemplate) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.template_id,
            changed_fields=("status",),
        )


def _owned(
    templates: ProtocolTemplateRepositoryPort, template_id: UUID, clinic_id: UUID | None
) -> ProtocolTemplate:
    """A template of the session clinic; a global seed is ``404`` for a clinic."""
    found = templates.get(template_id)
    if found is None or found.clinic_id is None or found.clinic_id != clinic_id:
        raise ResourceNotFoundError
    return found


@final
class CreateProtocolTemplateCommandHandler(
    CommandHandler[CreateProtocolTemplateCommand, ProtocolTemplate]
):
    """Stores version 1 of a new template; the code is unique in the clinic."""

    def __init__(
        self,
        *,
        templates: ProtocolTemplateRepositoryPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._templates = templates
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: CreateProtocolTemplateCommand) -> ProtocolTemplate:
        actor = command.actor
        actor.require(PermissionCode.PROTOCOL_TEMPLATES_MANAGE)
        clinic_id = actor.clinic_id
        if clinic_id is None:
            raise ResourceNotFoundError
        code = derive_template_code(
            command.name, max_length=FieldLimits.TEMPLATE_CODE_MAX_LENGTH
        )
        if self._templates.family(clinic_id, code):
            raise ConflictError(CODE_TAKEN)
        template = ProtocolTemplate(
            template_id=self._ids.new_id(),
            clinic_id=clinic_id,
            code=code,
            name=command.name,
            version=1,
            status=TemplateStatus.ACTIVE,
            content=command.content,
            created_by=actor.user_id,
            created_at=self._clock.now(),
        )
        self._templates.insert(template)
        return template


@final
class CreateProtocolTemplateVersionCommandHandler(
    CommandHandler[CreateProtocolTemplateVersionCommand, ProtocolTemplate]
):
    """Adds the next version of a template; the earlier versions stay as they are."""

    def __init__(
        self,
        *,
        templates: ProtocolTemplateRepositoryPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._templates = templates
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: CreateProtocolTemplateVersionCommand) -> ProtocolTemplate:
        actor = command.actor
        actor.require(PermissionCode.PROTOCOL_TEMPLATES_MANAGE)
        owned = _owned(self._templates, command.template_id, actor.clinic_id)
        latest = max(
            self._templates.family(owned.clinic_id, owned.code),
            key=lambda version: version.version,
        )
        version = latest.new_version(
            template_id=self._ids.new_id(),
            version=latest.version + 1,
            content=command.content,
            created_by=actor.user_id,
            at=self._clock.now(),
        )
        self._templates.insert(version)
        return version


@final
class RetireProtocolTemplateCommandHandler(
    CommandHandler[RetireProtocolTemplateCommand, ProtocolTemplate]
):
    """Retires every active version of the template: a retired one is never cloned."""

    def __init__(self, *, templates: ProtocolTemplateRepositoryPort) -> None:
        self._templates = templates

    @override
    def handle(self, command: RetireProtocolTemplateCommand) -> ProtocolTemplate:
        actor = command.actor
        actor.require(PermissionCode.PROTOCOL_TEMPLATES_MANAGE)
        owned = _owned(self._templates, command.template_id, actor.clinic_id)
        retired = owned.retired()
        for version in self._templates.family(owned.clinic_id, owned.code):
            if version.is_active:
                self._templates.retire(version.retired())
        return retired
