"""Patient credential endpoints (API.md 8.4): issue, re-issue in batch and revoke.

The activation code is shown once, in the response that issues it, with
``Cache-Control: no-store`` (set for every ``/api/v1`` response). It is never
stored in clear and never repeated by a later read.
"""

from datetime import datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Any, Final, Self, final
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from insumap.api.paths import API_V1_PREFIX
from insumap.api.routers.common import (
    ACCESS_EXTENSION,
    StrictRequest,
    access,
    error_responses,
)
from insumap.api.tags import ApiTag
from insumap.application.commands.base import CommandBus
from insumap.application.common.actor import Actor
from insumap.application.credentials.commands import (
    IssuedCredential,
    RevokeCredentialInvitationCommand,
)
from insumap.application.credentials.issuance import (
    BatchItemResult,
    IssueCredentialInput,
    IssueCredentialsBatchInput,
    IssueCredentialsBatchUseCase,
    IssueCredentialUseCase,
)
from insumap.domain.identity.invitation import (
    InvitationChannel,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits

PURPOSE_PATIENT_ACTIVATION: Final = "PATIENT_ACTIVATION"
STATUS_PENDING: Final = "PENDING"
STATUS_ISSUED: Final = "ISSUED"
STATUS_FAILED: Final = "FAILED"


class CredentialChannelCode(StrEnum):
    """How the code reaches the patient: printed by the clinic or sent by email."""

    PRINT = "PRINT"
    EMAIL = "EMAIL"


class IssueCredentialRequest(StrictRequest):
    """The channel of the new code."""

    channel: CredentialChannelCode = Field(
        description=(
            "`PRINT` muestra el código una sola vez; `EMAIL` lo envía por correo."
        )
    )


class BatchIssueCredentialsRequest(StrictRequest):
    """Several patients of the caller's clinic and the channel for all of them."""

    patient_ids: list[UUID] = Field(
        min_length=1,
        max_length=FieldLimits.CREDENTIAL_BATCH_MAX_ITEMS,
        description="Pacientes de la clínica, sin repetir. Hasta 100 por petición.",
    )
    channel: CredentialChannelCode = Field(
        description=(
            "`PRINT` muestra cada código una sola vez; `EMAIL` lo envía por correo."
        )
    )

    @field_validator("patient_ids")
    @classmethod
    def unique_patients(cls, value: list[UUID]) -> list[UUID]:
        """A patient appears once: a repeated id is a validation error (``422``)."""
        if len(set(value)) != len(value):
            raise ValueError("los pacientes no pueden repetirse")
        return value


class CredentialInvitationResponse(BaseModel):
    """The invitation that was created; `activation_code` only for `PRINT`."""

    invitation_id: UUID
    patient_id: UUID
    purpose: str = PURPOSE_PATIENT_ACTIVATION
    status: str = STATUS_PENDING
    channel: CredentialChannelCode
    expires_at: datetime
    delivery_status: str = Field(
        description="`NOT_APPLICABLE` para `PRINT`; `PENDING` para `EMAIL`."
    )
    activation_code: str | None = Field(
        default=None,
        description="Código en claro, solo en esta respuesta y solo para `PRINT`.",
    )

    @classmethod
    def of(cls, issued: IssuedCredential) -> Self:
        return cls(
            invitation_id=issued.invitation_id,
            patient_id=issued.patient_id,
            channel=CredentialChannelCode(issued.channel.value),
            expires_at=issued.expires_at,
            delivery_status=issued.delivery_status.value,
            activation_code=issued.activation_code,
        )


class CredentialBatchItemResponse(BaseModel):
    """The outcome for one patient of a batch."""

    patient_id: UUID
    status: str = Field(description="`ISSUED` o `FAILED`.")
    error_code: str | None = Field(
        default=None,
        description="Código de error de esta fila cuando `status` es `FAILED`.",
    )
    invitation_id: UUID | None = None
    channel: CredentialChannelCode
    expires_at: datetime | None = None
    delivery_status: str | None = None
    activation_code: str | None = Field(
        default=None,
        description="Código en claro, solo en esta respuesta y solo para `PRINT`.",
    )

    @classmethod
    def of(cls, result: BatchItemResult, channel: InvitationChannel) -> Self:
        issued = result.issued
        if issued is None:
            return cls(
                patient_id=result.patient_id,
                status=STATUS_FAILED,
                error_code=None
                if result.error_code is None
                else result.error_code.value,
                channel=CredentialChannelCode(channel.value),
            )
        return cls(
            patient_id=result.patient_id,
            status=STATUS_ISSUED,
            invitation_id=issued.invitation_id,
            channel=CredentialChannelCode(issued.channel.value),
            expires_at=issued.expires_at,
            delivery_status=issued.delivery_status.value,
            activation_code=issued.activation_code,
        )


class CredentialBatchResponse(BaseModel):
    """One item per requested patient, in the order sent."""

    items: list[CredentialBatchItemResponse]


ISSUE_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.CONFLICT,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
BATCH_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)
REVOKE_ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.NOT_FOUND,
    HTTPStatus.CONFLICT,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)


@final
class CredentialRouter:
    """Builds the credential endpoints over the issue use cases and the revoke command.

    Issuing goes through a use case that checks the permission and the clinic's
    rate limit first; each code is then created by a command on the bus, so it
    runs in its transaction and leaves its audit row (P09). A patient of another
    clinic, or one not in an issuable state, is reported as its own error.
    """

    def __init__(
        self,
        *,
        commands: CommandBus,
        issue: IssueCredentialUseCase,
        issue_batch: IssueCredentialsBatchUseCase,
        staff_actor: Any,
    ) -> None:
        self._commands = commands
        self._issue = issue
        self._issue_batch = issue_batch
        self._staff_actor = staff_actor
        self.router = APIRouter(prefix=API_V1_PREFIX, tags=[ApiTag.IMPORTS])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        staff = Depends(self._staff_actor)

        def issue_patient_credentials(
            patient_id: UUID,
            body: IssueCredentialRequest,
            actor: Annotated[Actor, staff],
        ) -> CredentialInvitationResponse:
            issued = self._issue.execute(
                IssueCredentialInput(
                    actor=actor,
                    patient_id=patient_id,
                    channel=InvitationChannel(body.channel.value),
                )
            )
            return CredentialInvitationResponse.of(issued)

        def issue_credentials_batch(
            body: BatchIssueCredentialsRequest, actor: Annotated[Actor, staff]
        ) -> CredentialBatchResponse:
            channel = InvitationChannel(body.channel.value)
            results = self._issue_batch.execute(
                IssueCredentialsBatchInput(
                    actor=actor,
                    patient_ids=tuple(body.patient_ids),
                    channel=channel,
                )
            )
            return CredentialBatchResponse(
                items=[CredentialBatchItemResponse.of(r, channel) for r in results]
            )

        def revoke_credential_invitation(
            invitation_id: UUID, actor: Annotated[Actor, staff]
        ) -> None:
            self._commands.dispatch(
                RevokeCredentialInvitationCommand(
                    actor=actor, invitation_id=invitation_id
                )
            )

        issue_access = {ACCESS_EXTENSION: access(PermissionCode.CREDENTIALS_ISSUE)}
        revoke_access = {ACCESS_EXTENSION: access(PermissionCode.CREDENTIALS_REVOKE)}
        add(
            "/patients/{patient_id}/credential-invitations",
            issue_patient_credentials,
            methods=["POST"],
            status_code=HTTPStatus.CREATED,
            operation_id="issue_patient_credentials",
            summary="Emitir o reemitir el código de activación de un paciente",
            description=(
                "Pasa al paciente importado a `INVITED` y crea un código de un "
                "solo uso con vigencia de 7 días. Si ya tenía una invitación "
                "abierta, la revoca: el código anterior deja de funcionar. Con "
                "`PRINT` el código se muestra solo en esta respuesta, para "
                "imprimirlo. Con `EMAIL` se envía por correo y no aparece aquí. "
                "Un paciente activo, suspendido o dado de baja responde `409`."
            ),
            responses=ISSUE_ERRORS,
            openapi_extra=issue_access,
        )
        add(
            "/credential-invitations/batch",
            issue_credentials_batch,
            methods=["POST"],
            status_code=HTTPStatus.OK,
            operation_id="issue_credentials_batch",
            summary="Emitir códigos de activación para varios pacientes",
            description=(
                "Emite un código por paciente, hasta 100 por petición. La respuesta "
                "trae un elemento por paciente: `ISSUED` con su código (solo con "
                "`PRINT`) o `FAILED` con su `error_code`. Los pacientes que fallan no "
                "impiden emitir a los demás. Los límites de emisión se cuentan antes "
                "de crear el primer código."
            ),
            responses=BATCH_ERRORS,
            openapi_extra=issue_access,
        )
        add(
            "/credential-invitations/{invitation_id}/revoke",
            revoke_credential_invitation,
            methods=["POST"],
            status_code=HTTPStatus.NO_CONTENT,
            operation_id="revoke_credential_invitation",
            summary="Revocar una invitación pendiente",
            description=(
                "La invitación pasa a `REVOKED` y el paciente vuelve a `IMPORTED`. El "
                "código revocado responde `410 INVITATION_INVALID` al activar."
            ),
            responses=REVOKE_ERRORS,
            openapi_extra=revoke_access,
        )
