"""Audit endpoints (API.md 8.13, ``/api/v1/audit-log`` and ``/security-events``).

The router maps HTTP to queries and back. The scope (clinic or platform) and the
permissions are decided in the use cases from the token, never from the request.
The responses carry identifiers and field names only, never clinical values.
"""

from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any, Final, Self, final
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel, Field

from insumap.api.paths import API_V1_PREFIX
from insumap.api.routers.common import (
    ACCESS_EXTENSION,
    CursorQuery,
    LimitQuery,
    PageResponse,
    access,
    error_responses,
    page_request,
)
from insumap.api.tags import ApiTag
from insumap.application.access.ports import DataResource
from insumap.application.audit.ports import (
    AuditLogFilter,
    AuditLogRow,
    ChainVerification,
    DataAccessFilter,
    DataAccessRow,
    SecurityEventKind,
    SecurityEventRow,
)
from insumap.application.audit.queries import (
    ListAuditLogInput,
    ListAuditLogUseCase,
    ListDataAccessInput,
    ListDataAccessUseCase,
    ListSecurityEventsInput,
    ListSecurityEventsUseCase,
)
from insumap.application.audit.verification import (
    VerifyAuditChainInput,
    VerifyAuditChainUseCase,
)
from insumap.application.common.actor import Actor
from insumap.application.security.events import SecuritySeverity
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits

AUDIT_LOG_PREFIX: Final = f"{API_V1_PREFIX}/audit-log"
SECURITY_EVENTS_PREFIX: Final = f"{API_V1_PREFIX}/security-events"


class AuditLogResponse(BaseModel):
    """One action of the clinic: who, when, what and which fields changed."""

    id: UUID
    occurred_at: datetime
    actor_user_id: UUID | None
    actor_role: str | None
    action: str
    entity_type: str
    entity_id: UUID | None
    reason: str | None
    changed_fields: list[str] = Field(description="Nombres de los campos cambiados.")

    @classmethod
    def of(cls, row: AuditLogRow) -> Self:
        return cls(
            id=row.id,
            occurred_at=row.occurred_at,
            actor_user_id=row.actor_user_id,
            actor_role=row.actor_role,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            reason=row.reason,
            changed_fields=list(row.changed_fields),
        )


class DataAccessResponse(BaseModel):
    """One read of clinical data: who read which resource, with which outcome."""

    id: UUID
    occurred_at: datetime
    actor_user_id: UUID | None
    actor_role: str | None
    patient_id: UUID | None
    resource_type: DataResource
    action: str
    outcome: str
    purpose: str

    @classmethod
    def of(cls, row: DataAccessRow) -> Self:
        return cls(
            id=row.id,
            occurred_at=row.occurred_at,
            actor_user_id=row.actor_user_id,
            actor_role=row.actor_role,
            patient_id=row.patient_id,
            resource_type=row.resource_type,
            action=row.action,
            outcome=row.outcome.value,
            purpose=row.purpose.value,
        )


class SecurityEventResponse(BaseModel):
    """A security event: identifiers and a truncated address, never the address."""

    id: UUID
    type: SecurityEventKind
    severity: SecuritySeverity
    user_id: UUID | None
    clinic_id: UUID | None
    occurred_at: datetime
    ip_truncated: str | None = Field(
        description="IP truncada: /24 en IPv4 y /48 en IPv6."
    )

    @classmethod
    def of(cls, row: SecurityEventRow) -> Self:
        return cls(
            id=row.id,
            type=row.event_type,
            severity=row.severity,
            user_id=row.user_id,
            clinic_id=row.clinic_id,
            occurred_at=row.occurred_at,
            ip_truncated=row.ip_truncated,
        )


class ChainVerificationResponse(BaseModel):
    """The result of the chain check; the first broken row when it fails."""

    is_valid: bool
    first_inconsistent_row_id: UUID | None

    @classmethod
    def of(cls, result: ChainVerification) -> Self:
        return cls(
            is_valid=result.is_valid,
            first_inconsistent_row_id=result.first_inconsistent_row_id,
        )


AUDIT_READ_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
VERIFY_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
ACTION_PATTERN: Final = FieldLimits.AUDIT_ACTION_PATTERN


@final
class AuditRouter:
    """Builds the audit reads (API.md 8.13) over their use cases.

    Reads are not audited as clinical reads: they expose no clinical content. A
    caller without the permission gets ``403`` before any row is read.
    """

    def __init__(
        self,
        *,
        list_audit_log: ListAuditLogUseCase,
        list_data_access: ListDataAccessUseCase,
        list_security_events: ListSecurityEventsUseCase,
        verify_chain: VerifyAuditChainUseCase,
        session_actor: Any,
    ) -> None:
        self._list_audit_log = list_audit_log
        self._list_data_access = list_data_access
        self._list_security_events = list_security_events
        self._verify_chain = verify_chain
        self._session_actor = session_actor
        self.router = APIRouter(tags=[ApiTag.AUDIT])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        session = Depends(self._session_actor)
        read = {ACCESS_EXTENSION: access(PermissionCode.AUDIT_READ)}

        def list_audit_log(
            actor: Annotated[Actor, session],
            user_id: Annotated[UUID | None, Query()] = None,
            action: Annotated[
                str | None,
                Query(
                    max_length=FieldLimits.AUDIT_ACTION_MAX_LENGTH,
                    pattern=ACTION_PATTERN,
                ),
            ] = None,
            from_: Annotated[AwareDatetime | None, Query(alias="from")] = None,
            to: Annotated[AwareDatetime | None, Query()] = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[AuditLogResponse]:
            page = self._list_audit_log.execute(
                ListAuditLogInput(
                    actor=actor,
                    filters=AuditLogFilter(
                        user_id=user_id,
                        action=action,
                        occurred_from=from_,
                        occurred_to=to,
                    ),
                    page=page_request(limit, cursor),
                )
            )
            return PageResponse(
                items=[AuditLogResponse.of(row) for row in page.items],
                next_cursor=page.next_cursor,
            )

        def list_data_access(
            actor: Annotated[Actor, session],
            user_id: Annotated[UUID | None, Query()] = None,
            patient_id: Annotated[UUID | None, Query()] = None,
            resource_type: Annotated[DataResource | None, Query()] = None,
            from_: Annotated[AwareDatetime | None, Query(alias="from")] = None,
            to: Annotated[AwareDatetime | None, Query()] = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[DataAccessResponse]:
            page = self._list_data_access.execute(
                ListDataAccessInput(
                    actor=actor,
                    filters=DataAccessFilter(
                        user_id=user_id,
                        patient_id=patient_id,
                        resource_type=resource_type,
                        occurred_from=from_,
                        occurred_to=to,
                    ),
                    page=page_request(limit, cursor),
                )
            )
            return PageResponse(
                items=[DataAccessResponse.of(row) for row in page.items],
                next_cursor=page.next_cursor,
            )

        def verify_audit_chain(
            actor: Annotated[Actor, session],
        ) -> ChainVerificationResponse:
            return ChainVerificationResponse.of(
                self._verify_chain.execute(VerifyAuditChainInput(actor=actor))
            )

        def list_security_events(
            actor: Annotated[Actor, session],
            type: Annotated[SecurityEventKind | None, Query()] = None,
            severity: Annotated[SecuritySeverity | None, Query()] = None,
            from_: Annotated[AwareDatetime | None, Query(alias="from")] = None,
            to: Annotated[AwareDatetime | None, Query()] = None,
            limit: LimitQuery = FieldLimits.PAGE_SIZE_DEFAULT,
            cursor: CursorQuery = None,
        ) -> PageResponse[SecurityEventResponse]:
            page = self._list_security_events.execute(
                ListSecurityEventsInput(
                    actor=actor,
                    event_type=type,
                    severity=severity,
                    occurred_from=from_,
                    occurred_to=to,
                    page=page_request(limit, cursor),
                )
            )
            return PageResponse(
                items=[SecurityEventResponse.of(row) for row in page.items],
                next_cursor=page.next_cursor,
            )

        add(
            "/audit-log",
            list_audit_log,
            methods=["GET"],
            operation_id="list_audit_log",
            summary="Listar la auditoría de la clínica",
            description=(
                "Acciones de la clínica del token que cambian seguridad o decisiones "
                "clínicas: quién, cuándo, qué y los nombres de los campos cambiados. "
                "Nunca valores de glucosa ni textos de notas."
            ),
            responses=AUDIT_READ_ERRORS,
            openapi_extra=read,
        )
        add(
            "/audit-log/data-access",
            list_data_access,
            methods=["GET"],
            operation_id="list_data_access_log",
            summary="Listar los accesos a datos clínicos",
            description=(
                "Quién leyó datos clínicos de qué paciente, qué recurso, con qué "
                "resultado (`GRANTED` o `DENIED`) y propósito. Sin contenido clínico. "
                "La propia consulta no se audita como lectura clínica."
            ),
            responses=AUDIT_READ_ERRORS,
            openapi_extra=read,
        )
        add(
            "/audit-log/verifications",
            verify_audit_chain,
            methods=["POST"],
            operation_id="verify_audit_chain",
            summary="Verificar la cadena de hashes de la auditoría",
            description=(
                "Recalcula la cadena de hashes de la clínica del token. Si una fila no "
                "coincide, responde su identificador y registra un evento crítico "
                "`AUDIT_CHAIN_BROKEN`."
            ),
            responses=VERIFY_ERRORS,
            openapi_extra=read,
        )
        add(
            "/security-events",
            list_security_events,
            methods=["GET"],
            operation_id="list_security_events",
            summary="Listar eventos de seguridad",
            description=(
                "Con `audit.read` ve los eventos de su clínica. Con "
                "`audit.read_platform` (sin clínica) ve los de la plataforma. Nunca "
                "secretos ni la IP completa."
            ),
            responses=AUDIT_READ_ERRORS,
            openapi_extra=read,
        )
