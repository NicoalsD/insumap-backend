"""Requests and responses of the authentication endpoints."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from insumap.application.identity.activation import VerifyActivationCodeResult
from insumap.application.identity.current_user import CurrentUserResult
from insumap.application.identity.mfa import StartMfaEnrollmentResult
from insumap.domain.identity.roles import Role
from insumap.domain.identity.session import LoginStatus
from insumap.shared.field_limits import FieldLimits

TOKEN_TYPE = "Bearer"  # noqa: S105 - the HTTP scheme name, not a secret

EmailInput = Annotated[
    str,
    Field(
        min_length=3,
        max_length=FieldLimits.EMAIL_MAX_LENGTH,
        description="Correo electrónico. Se normaliza (NFKC, recorte y minúsculas).",
        examples=["medico@example.test"],
    ),
]
PasswordInput = Annotated[
    str,
    Field(
        min_length=1,
        max_length=FieldLimits.PASSWORD_MAX_LENGTH,
        description="Contraseña. Nunca se registra ni se devuelve.",
    ),
]
OpaqueTokenInput = Annotated[
    str,
    Field(min_length=1, max_length=FieldLimits.OPAQUE_TOKEN_MAX_LENGTH),
]


class StrictRequest(BaseModel):
    """Base of every request body: unknown fields answer ``422``."""

    model_config = ConfigDict(extra="forbid")


class LoginRequest(StrictRequest):
    """Credenciales de inicio de sesión."""

    email: EmailInput
    password: PasswordInput


class VerifyMfaChallengeRequest(StrictRequest):
    """Segundo factor del personal con el reto del inicio de sesión."""

    challenge_token: OpaqueTokenInput = Field(
        description="Reto opaco recibido en `MFA_CHALLENGE` (5 minutos, 5 intentos)."
    )
    code: str = Field(
        min_length=FieldLimits.TOTP_CODE_LENGTH,
        max_length=FieldLimits.MFA_CODE_INPUT_MAX_LENGTH,
        description="TOTP de 6 dígitos o código de respaldo `XXXXX-XXXXX`.",
        examples=["123456"],
    )


class ConfirmMfaEnrollmentRequest(StrictRequest):
    """Primer TOTP del factor recién creado."""

    code: str = Field(
        pattern=rf"^\d{{{FieldLimits.TOTP_CODE_LENGTH}}}$",
        description="TOTP vigente de 6 dígitos.",
        examples=["123456"],
    )


class RegenerateMfaRecoveryCodesRequest(StrictRequest):
    """TOTP vigente que prueba que quien pide los códigos es el titular."""

    code: str = Field(
        pattern=rf"^\d{{{FieldLimits.TOTP_CODE_LENGTH}}}$",
        description="TOTP vigente de 6 dígitos.",
        examples=["123456"],
    )


class ChangePasswordRequest(StrictRequest):
    """Contraseña actual y contraseña nueva de la cuenta de la sesión."""

    current_password: PasswordInput
    new_password: PasswordInput


class RequestPasswordResetRequest(StrictRequest):
    """Correo de la cuenta que olvidó su contraseña."""

    email: EmailInput


class CompletePasswordResetRequest(StrictRequest):
    """Token del enlace recibido por correo y contraseña nueva."""

    token: OpaqueTokenInput = Field(
        description="Token de un solo uso del fragmento `#token=` del enlace."
    )
    new_password: PasswordInput


class ConfirmEmailVerificationRequest(StrictRequest):
    """Token del enlace de verificación de correo."""

    token: OpaqueTokenInput = Field(
        description="Token de un solo uso del fragmento `#token=` del enlace."
    )


class VerifyActivationCodeRequest(StrictRequest):
    """Código de activación y fecha de nacimiento del paciente."""

    activation_code: str = Field(
        min_length=1,
        max_length=FieldLimits.ACTIVATION_CODE_INPUT_MAX_LENGTH,
        description=(
            "Código `XXXX-XXXX-XXXX-XXXX`. Se normaliza a mayúsculas sin guiones; "
            "`O` pasa a `0`, `I` y `L` pasan a `1`."
        ),
        examples=["ABCD-EFGH-JKMN-PQRS"],
    )
    birth_date: date | None = Field(
        default=None,
        description="Fecha de nacimiento `YYYY-MM-DD`. Obligatoria para pacientes.",
        examples=["1980-05-17"],
    )

    @field_validator("birth_date")
    @classmethod
    def not_before_the_minimum_year(cls, value: date | None) -> date | None:
        """Reject absurd years before they reach the comparison."""
        if value is not None and value.year < FieldLimits.BIRTH_DATE_MIN_YEAR:
            raise ValueError("birth date is too old")
        return value


class ConsentRequest(StrictRequest):
    """Consentimiento dado al activar la cuenta."""

    privacy_notice_version_id: UUID = Field(
        description="Versión vigente del aviso de privacidad."
    )
    accepted: bool = Field(description="Debe ser `true` para activar la cuenta.")
    ai_external_processing: bool = Field(
        default=False,
        description=(
            "Consentimiento aparte y opcional para el asistente con LLM externo."
        ),
    )


class CompleteActivationRequest(StrictRequest):
    """Contraseña, correo y consentimiento del paciente."""

    activation_token: OpaqueTokenInput = Field(
        description="Token de la sesión de activación (15 minutos, un solo uso)."
    )
    new_password: PasswordInput
    email: str | None = Field(
        default=None,
        max_length=FieldLimits.EMAIL_MAX_LENGTH,
        pattern=FieldLimits.EMAIL_PATTERN,
        description="Obligatorio si la importación no traía correo.",
    )
    consent: ConsentRequest


class AuthenticationResponse(BaseModel):
    """Estado del inicio de sesión (API.md, sección 2.3)."""

    model_config = ConfigDict(extra="forbid")

    status: LoginStatus = Field(
        description=(
            "`AUTHENTICATED`: sesión completa. `MFA_CHALLENGE`: falta el segundo "
            "factor. `MFA_ENROLLMENT_REQUIRED`: el personal debe activar el MFA."
        )
    )
    access_token: str | None = Field(
        default=None,
        description="JWT de 15 minutos. Solo en memoria del frontend.",
    )
    token_type: str | None = Field(default=None, examples=[TOKEN_TYPE])
    expires_in: int | None = Field(
        default=None, description="Segundos de vida del access token."
    )
    challenge_token: str | None = Field(
        default=None, description="Reto del segundo factor (5 minutos, 5 intentos)."
    )


class RecoveryCodesAuthenticationResponse(AuthenticationResponse):
    """Sesión completa más los códigos de respaldo, mostrados una sola vez."""

    recovery_codes: list[str] = Field(
        description="10 códigos `XXXXX-XXXXX` de un solo uso. No se vuelven a mostrar."
    )


class RecoveryCodesResponse(BaseModel):
    """Códigos de respaldo nuevos, mostrados una sola vez."""

    model_config = ConfigDict(extra="forbid")

    recovery_codes: list[str] = Field(
        description="Códigos `XXXXX-XXXXX` de un solo uso. Los anteriores quedan "
        "invalidados y estos no se vuelven a mostrar."
    )


class AccessTokenResponse(BaseModel):
    """Access token nuevo; el refresh rotado viaja solo en la cookie."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: str = Field(examples=[TOKEN_TYPE])
    expires_in: int = Field(description="Segundos de vida del access token.")


class MfaEnrollmentResponse(BaseModel):
    """Secreto TOTP, mostrado una sola vez."""

    model_config = ConfigDict(extra="forbid")

    secret: str = Field(description="Secreto base32 de 32 caracteres.")
    otpauth_uri: str = Field(
        description="`otpauth://totp/Insumap:<correo>?secret=...&issuer=Insumap`."
    )

    @classmethod
    def from_result(cls, result: StartMfaEnrollmentResult) -> MfaEnrollmentResponse:
        """Map the use case result."""
        return cls(secret=result.secret, otpauth_uri=result.otpauth_uri)


class UserSummary(BaseModel):
    """Identidad de la cuenta de la sesión."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str | None
    full_name: str | None


class ClinicResponse(BaseModel):
    """Clínica de la sesión."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    is_demo: bool
    simulated: bool = Field(description="`true` si es la clínica de datos simulados.")


class CurrentUserResponse(BaseModel):
    """Qué necesita el frontend para dibujar la sesión."""

    model_config = ConfigDict(extra="forbid")

    user: UserSummary
    role: Role
    clinic: ClinicResponse | None = Field(
        description="`null` solo para `PLATFORM_ADMIN`."
    )
    permissions: list[str] = Field(description="Códigos leídos de la base de datos.")
    mfa_enabled: bool
    consent_required: bool

    @classmethod
    def from_result(cls, result: CurrentUserResult) -> CurrentUserResponse:
        """Map the use case result."""
        clinic = result.clinic
        return cls(
            user=UserSummary(
                id=result.user_id, email=result.email, full_name=result.full_name
            ),
            role=result.role,
            clinic=None
            if clinic is None
            else ClinicResponse(
                id=clinic.clinic_id,
                name=clinic.name,
                is_demo=clinic.is_demo,
                simulated=clinic.is_demo,
            ),
            permissions=list(result.permissions),
            mfa_enabled=result.mfa_enabled,
            consent_required=result.consent_required,
        )


class VerifyActivationCodeResponse(BaseModel):
    """Sesión de activación. Nunca incluye el nombre ni otros datos del paciente."""

    model_config = ConfigDict(extra="forbid")

    activation_token: str = Field(description="Opaco, 15 minutos, un solo uso.")
    clinic_name: str
    privacy_notice_version_id: UUID
    email_required: bool = Field(
        description="`true` si hay que pedir el correo en el paso siguiente."
    )

    @classmethod
    def from_result(
        cls, result: VerifyActivationCodeResult
    ) -> VerifyActivationCodeResponse:
        """Map the use case result."""
        return cls(
            activation_token=result.activation_token,
            clinic_name=result.clinic_name,
            privacy_notice_version_id=result.privacy_notice_version_id,
            email_required=result.email_required,
        )
