"""Authentication endpoints: login, second factor, session and activation."""

from http import HTTPStatus
from typing import Annotated, Any, Final, final

from fastapi import APIRouter, Cookie, Depends, Request, Response

from insumap.api.errors import ErrorResponse
from insumap.api.paths import AUTH_PREFIX
from insumap.api.routers.auth_schemas import (
    TOKEN_TYPE,
    AccessTokenResponse,
    AuthenticationResponse,
    ChangePasswordRequest,
    CompleteActivationRequest,
    ConfirmMfaEnrollmentRequest,
    CurrentUserResponse,
    LoginRequest,
    MfaEnrollmentResponse,
    RecoveryCodesAuthenticationResponse,
    RecoveryCodesResponse,
    RegenerateMfaRecoveryCodesRequest,
    VerifyActivationCodeRequest,
    VerifyActivationCodeResponse,
    VerifyMfaChallengeRequest,
)
from insumap.api.security import (
    REFRESH_COOKIE_NAME,
    RefreshCookie,
    client_ip,
)
from insumap.api.tags import ApiTag
from insumap.application.commands.base import CommandBus
from insumap.application.common.actor import Actor
from insumap.application.identity.activation import (
    CompleteActivationInput,
    CompleteActivationUseCase,
    ConsentInput,
    VerifyActivationCodeInput,
    VerifyActivationCodeUseCase,
)
from insumap.application.identity.change_password import ChangePasswordCommand
from insumap.application.identity.current_user import (
    GetCurrentUserInput,
    GetCurrentUserUseCase,
)
from insumap.application.identity.login import LoginInput, LoginUseCase
from insumap.application.identity.mfa import (
    ConfirmMfaEnrollmentInput,
    ConfirmMfaEnrollmentUseCase,
    StartMfaEnrollmentInput,
    StartMfaEnrollmentUseCase,
    VerifyMfaChallengeInput,
    VerifyMfaChallengeUseCase,
)
from insumap.application.identity.recovery_codes import (
    RegenerateMfaRecoveryCodesCommand,
)
from insumap.application.identity.session import AuthenticationResult, SessionTokens
from insumap.application.identity.sessions import (
    LogoutAllInput,
    LogoutAllUseCase,
    LogoutInput,
    LogoutUseCase,
    RefreshSessionInput,
    RefreshSessionUseCase,
)
from insumap.domain.identity.errors import UnauthenticatedError
from insumap.shared.time import Clock

ACCESS_EXTENSION: Final = "x-access"
PUBLIC: Final = "public"
SESSION_SELF: Final = "self:session"
ENROLLMENT_SELF: Final = "self:enrollment"
REFRESH_COOKIE_SELF: Final = "self:refresh-cookie"

type Responses = dict[int | str, dict[str, Any]]

ERROR_DESCRIPTIONS: Final[dict[int, str]] = {
    HTTPStatus.UNAUTHORIZED: (
        "`UNAUTHENTICATED`, `SESSION_REVOKED` o `INVALID_CREDENTIALS`."
    ),
    HTTPStatus.FORBIDDEN: (
        "`FORBIDDEN`, `ACCOUNT_NOT_ACTIVE`, `CLINIC_SUSPENDED`, `MFA_REQUIRED` o "
        "`CONSENT_REQUIRED`."
    ),
    HTTPStatus.CONFLICT: (
        "`EMAIL_UNAVAILABLE`, `CONSENT_VERSION_OUTDATED` o `INVALID_STATE_TRANSITION`."
    ),
    HTTPStatus.GONE: "`INVITATION_INVALID`: el código o el token no es válido.",
    HTTPStatus.UNPROCESSABLE_ENTITY: "`VALIDATION_ERROR`.",
    HTTPStatus.TOO_MANY_REQUESTS: "`RATE_LIMITED`, con el encabezado `Retry-After`.",
}


def error_responses(*statuses: HTTPStatus) -> Responses:
    """Document the canonical error body of each status in Swagger."""
    return {
        int(status): {"model": ErrorResponse, "description": ERROR_DESCRIPTIONS[status]}
        for status in (*statuses, HTTPStatus.TOO_MANY_REQUESTS)
    }


@final
class AuthRouter:
    """Builds the ``/api/v1/auth`` endpoints from their use cases.

    The router only maps HTTP to a use case input and back; the cookie, the CSRF
    check and the actor come from dependencies the container supplies.
    """

    def __init__(  # noqa: PLR0913 - one use case per endpoint
        self,
        *,
        commands: CommandBus,
        clock: Clock,
        cookie: RefreshCookie,
        login: LoginUseCase,
        verify_mfa: VerifyMfaChallengeUseCase,
        start_enrollment: StartMfaEnrollmentUseCase,
        confirm_enrollment: ConfirmMfaEnrollmentUseCase,
        current_user: GetCurrentUserUseCase,
        refresh: RefreshSessionUseCase,
        logout: LogoutUseCase,
        logout_all: LogoutAllUseCase,
        verify_activation: VerifyActivationCodeUseCase,
        complete_activation: CompleteActivationUseCase,
        session_actor: Any,
        enrollment_actor: Any,
        any_actor: Any,
        csrf_guard: Any,
    ) -> None:
        self._commands = commands
        self._clock = clock
        self._cookie = cookie
        self._login = login
        self._verify_mfa = verify_mfa
        self._start_enrollment = start_enrollment
        self._confirm_enrollment = confirm_enrollment
        self._current_user = current_user
        self._refresh = refresh
        self._logout = logout
        self._logout_all = logout_all
        self._verify_activation = verify_activation
        self._complete_activation = complete_activation
        self._session_actor = session_actor
        self._enrollment_actor = enrollment_actor
        self._any_actor = any_actor
        self._csrf_guard = csrf_guard
        self.router = APIRouter(prefix=AUTH_PREFIX, tags=[ApiTag.AUTH])
        self._add_routes()

    def _add_routes(self) -> None:
        add = self.router.add_api_route
        session_actor = Depends(self._session_actor)
        enrollment_actor = Depends(self._enrollment_actor)
        any_actor = Depends(self._any_actor)
        csrf = Depends(self._csrf_guard)

        def login(
            body: LoginRequest, request: Request, response: Response
        ) -> AuthenticationResponse:
            return self._login_endpoint(body, request, response)

        def verify_mfa(
            body: VerifyMfaChallengeRequest, request: Request, response: Response
        ) -> AuthenticationResponse:
            return self._verify_mfa_endpoint(body, request, response)

        def start_mfa_enrollment(
            actor: Annotated[Actor, enrollment_actor],
        ) -> MfaEnrollmentResponse:
            return self._start_enrollment_endpoint(actor)

        def confirm_mfa_enrollment(
            body: ConfirmMfaEnrollmentRequest,
            request: Request,
            response: Response,
            actor: Annotated[Actor, enrollment_actor],
        ) -> RecoveryCodesAuthenticationResponse:
            return self._confirm_enrollment_endpoint(body, request, response, actor)

        def regenerate_mfa_recovery_codes(
            body: RegenerateMfaRecoveryCodesRequest,
            actor: Annotated[Actor, session_actor],
        ) -> RecoveryCodesResponse:
            return self._regenerate_recovery_codes_endpoint(body, actor)

        def change_password(
            body: ChangePasswordRequest,
            response: Response,
            actor: Annotated[Actor, session_actor],
        ) -> AuthenticationResponse:
            return self._change_password_endpoint(body, response, actor)

        def get_current_user(actor: Annotated[Actor, any_actor]) -> CurrentUserResponse:
            return self._current_user_endpoint(actor)

        def refresh_session(
            response: Response,
            _csrf: Annotated[None, csrf],
            cookie: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
        ) -> AccessTokenResponse:
            return self._refresh_endpoint(response, cookie)

        def logout(
            response: Response,
            _csrf: Annotated[None, csrf],
            actor: Annotated[Actor, any_actor],
            cookie: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
        ) -> None:
            self._logout_endpoint(response, actor, cookie)

        def logout_all(
            response: Response,
            _csrf: Annotated[None, csrf],
            actor: Annotated[Actor, session_actor],
        ) -> None:
            self._logout_all_endpoint(response, actor)

        def verify_activation_code(
            body: VerifyActivationCodeRequest, request: Request
        ) -> VerifyActivationCodeResponse:
            return self._verify_activation_endpoint(body, request)

        def complete_activation(
            body: CompleteActivationRequest, request: Request, response: Response
        ) -> AuthenticationResponse:
            return self._complete_activation_endpoint(body, request, response)

        add(
            "/login",
            login,
            methods=["POST"],
            response_model=AuthenticationResponse,
            operation_id="login",
            summary="Iniciar sesión con correo y contraseña",
            description=(
                "Verifica la contraseña (siempre un Argon2id por intento, exista o no "
                "el correo). Responde `AUTHENTICATED` (pacientes, con la cookie de "
                "refresh), `MFA_CHALLENGE` (personal con MFA) o "
                "`MFA_ENROLLMENT_REQUIRED` (personal sin MFA, token de enrolamiento "
                "sin "
                "refresh). Cualquier fallo de credenciales responde el mismo "
                "`401 INVALID_CREDENTIALS`."
            ),
            responses=error_responses(
                HTTPStatus.UNAUTHORIZED,
                HTTPStatus.FORBIDDEN,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            ),
            openapi_extra={ACCESS_EXTENSION: PUBLIC},
        )
        add(
            "/mfa/verify",
            verify_mfa,
            methods=["POST"],
            response_model=AuthenticationResponse,
            operation_id="verify_mfa_challenge",
            summary="Verificar el segundo factor del inicio de sesión",
            description=(
                "Consume el `challenge_token` con un TOTP de 6 dígitos o un código de "
                'respaldo. Responde la sesión completa con `amr: ["pwd", "otp"]` y '
                "la cookie de refresh. Un código incorrecto, repetido o ya usado "
                "responde `401 INVALID_CREDENTIALS` y cuenta un intento; un reto "
                "vencido, usado o agotado responde `401 UNAUTHENTICATED`."
            ),
            responses=error_responses(
                HTTPStatus.UNAUTHORIZED, HTTPStatus.UNPROCESSABLE_ENTITY
            ),
            openapi_extra={ACCESS_EXTENSION: PUBLIC},
        )
        add(
            "/mfa/enrollment",
            start_mfa_enrollment,
            methods=["POST"],
            response_model=MfaEnrollmentResponse,
            operation_id="start_mfa_enrollment",
            summary="Iniciar el enrolamiento del segundo factor",
            description=(
                "Solo para personal con el token de enrolamiento. Devuelve el secreto "
                "TOTP y el `otpauth_uri` una sola vez; el QR se dibuja en el "
                "navegador. "
                "El factor no queda activo hasta confirmarlo."
            ),
            responses=error_responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN),
            openapi_extra={ACCESS_EXTENSION: ENROLLMENT_SELF},
        )
        add(
            "/mfa/enrollment/confirm",
            confirm_mfa_enrollment,
            methods=["POST"],
            response_model=RecoveryCodesAuthenticationResponse,
            operation_id="confirm_mfa_enrollment",
            summary="Confirmar el enrolamiento del segundo factor",
            description=(
                "Activa el factor con un TOTP vigente y abre la sesión completa con la "
                "cookie de refresh. Devuelve 10 códigos de respaldo de un solo uso, "
                "mostrados una sola vez."
            ),
            responses=error_responses(
                HTTPStatus.UNAUTHORIZED,
                HTTPStatus.FORBIDDEN,
                HTTPStatus.CONFLICT,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            ),
            openapi_extra={ACCESS_EXTENSION: ENROLLMENT_SELF},
        )
        add(
            "/mfa/recovery-codes",
            regenerate_mfa_recovery_codes,
            methods=["POST"],
            response_model=RecoveryCodesResponse,
            operation_id="regenerate_mfa_recovery_codes",
            summary="Regenerar los códigos de respaldo del segundo factor",
            description=(
                "Exige una sesión completa del personal y un TOTP vigente. Revoca los "
                "códigos anteriores y devuelve los nuevos una sola vez. Queda "
                "auditado en `audit.audit_log` (P09)."
            ),
            responses=error_responses(
                HTTPStatus.UNAUTHORIZED,
                HTTPStatus.FORBIDDEN,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            ),
            openapi_extra={ACCESS_EXTENSION: SESSION_SELF},
        )
        add(
            "/password/change",
            change_password,
            methods=["POST"],
            response_model=AuthenticationResponse,
            operation_id="change_password",
            summary="Cambiar la contraseña de la cuenta",
            description=(
                "Verifica la contraseña actual y aplica la política de contraseñas "
                "(longitud, contraseñas comunes, datos personales e historial). "
                "Sube la versión del token y revoca todas las sesiones; este "
                "dispositivo recibe una sesión nueva con su cookie de refresh. Queda "
                "auditado en `audit.audit_log` (P09)."
            ),
            responses=error_responses(
                HTTPStatus.UNAUTHORIZED,
                HTTPStatus.FORBIDDEN,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            ),
            openapi_extra={ACCESS_EXTENSION: SESSION_SELF},
        )
        add(
            "/current-user",
            get_current_user,
            methods=["GET"],
            response_model=CurrentUserResponse,
            operation_id="get_current_user",
            summary="Consultar la cuenta de la sesión",
            description=(
                "Devuelve la cuenta, el rol, la clínica, los permisos leídos de la "
                "base "
                "de datos, si el MFA está activo y si hay un consentimiento pendiente. "
                "Sirve con cualquier sesión válida, también la de enrolamiento y la de "
                "un paciente con consentimiento pendiente."
            ),
            responses=error_responses(HTTPStatus.UNAUTHORIZED),
            openapi_extra={ACCESS_EXTENSION: SESSION_SELF},
        )
        add(
            "/refresh",
            refresh_session,
            methods=["POST"],
            response_model=AccessTokenResponse,
            operation_id="refresh_session",
            summary="Renovar la sesión con la cookie de refresh",
            description=(
                "Rota el refresh token de la cookie `__Secure-insumap_rt` y devuelve "
                "un "
                "access token nuevo. Exige `X-Requested-With: insumap-web`; si "
                "`Origin` "
                "está presente debe estar en `CORS_ORIGINS` y `Sec-Fetch-Site` no "
                "puede "
                "ser `cross-site`. Reutilizar un refresh ya rotado revoca toda la "
                "familia y responde `401 SESSION_REVOKED`."
            ),
            responses=error_responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN),
            openapi_extra={ACCESS_EXTENSION: REFRESH_COOKIE_SELF},
        )
        add(
            "/logout",
            logout,
            methods=["POST"],
            status_code=HTTPStatus.NO_CONTENT,
            operation_id="logout",
            summary="Cerrar la sesión de este dispositivo",
            description=(
                "Revoca la familia de refresh de la cookie y borra la cookie. Exige "
                "`X-Requested-With: insumap-web` y un access token válido."
            ),
            responses=error_responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN),
            openapi_extra={ACCESS_EXTENSION: SESSION_SELF},
        )
        add(
            "/logout-all",
            logout_all,
            methods=["POST"],
            status_code=HTTPStatus.NO_CONTENT,
            operation_id="logout_all_sessions",
            summary="Cerrar la sesión en todos los dispositivos",
            description=(
                "Revoca todas las familias de refresh y sube la versión del token: los "
                "access tokens vigentes mueren en su siguiente petición. Exige "
                "`X-Requested-With: insumap-web` y un access token válido."
            ),
            responses=error_responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN),
            openapi_extra={ACCESS_EXTENSION: SESSION_SELF},
        )
        add(
            "/activation/verify",
            verify_activation_code,
            methods=["POST"],
            response_model=VerifyActivationCodeResponse,
            operation_id="verify_activation_code",
            summary="Verificar el código de activación",
            description=(
                "Paso 1 de la activación: código y fecha de nacimiento abren una "
                "sesión "
                "de activación de 15 minutos. No devuelve el nombre del paciente. Todo "
                "fallo responde el mismo `410 INVITATION_INVALID`; cinco fechas "
                "incorrectas con un código real bloquean la invitación."
            ),
            responses=error_responses(HTTPStatus.GONE, HTTPStatus.UNPROCESSABLE_ENTITY),
            openapi_extra={ACCESS_EXTENSION: PUBLIC},
        )
        add(
            "/activation/complete",
            complete_activation,
            methods=["POST"],
            response_model=AuthenticationResponse,
            operation_id="complete_activation",
            summary="Completar la activación de la cuenta",
            description=(
                "Paso 2: fija la contraseña y el correo, guarda el consentimiento y "
                "pasa "
                "la cuenta de `INVITED` a `ACTIVE` en una sola transacción. Responde "
                "la "
                "sesión completa con la cookie de refresh. El evento "
                "`PatientActivated` "
                "se publica después del commit."
            ),
            responses=error_responses(
                HTTPStatus.FORBIDDEN,
                HTTPStatus.CONFLICT,
                HTTPStatus.GONE,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            ),
            openapi_extra={ACCESS_EXTENSION: PUBLIC},
        )

    # Endpoint bodies. They only map HTTP to a use case input and back.

    def _login_endpoint(
        self, body: LoginRequest, request: Request, response: Response
    ) -> AuthenticationResponse:
        result = self._login.execute(
            LoginInput(
                email=body.email, password=body.password, client_ip=client_ip(request)
            )
        )
        return self._authentication(result, response)

    def _verify_mfa_endpoint(
        self, body: VerifyMfaChallengeRequest, request: Request, response: Response
    ) -> AuthenticationResponse:
        result = self._verify_mfa.execute(
            VerifyMfaChallengeInput(
                challenge_token=body.challenge_token,
                code=body.code,
                client_ip=client_ip(request),
            )
        )
        return self._authentication(result, response)

    def _start_enrollment_endpoint(self, actor: Actor) -> MfaEnrollmentResponse:
        return MfaEnrollmentResponse.from_result(
            self._start_enrollment.execute(StartMfaEnrollmentInput(actor=actor))
        )

    def _confirm_enrollment_endpoint(
        self,
        body: ConfirmMfaEnrollmentRequest,
        request: Request,
        response: Response,
        actor: Actor,
    ) -> RecoveryCodesAuthenticationResponse:
        result = self._confirm_enrollment.execute(
            ConfirmMfaEnrollmentInput(
                actor=actor, code=body.code, client_ip=client_ip(request)
            )
        )
        base = self._authentication(result.authentication, response)
        return RecoveryCodesAuthenticationResponse(
            **base.model_dump(), recovery_codes=list(result.recovery_codes)
        )

    def _regenerate_recovery_codes_endpoint(
        self, body: RegenerateMfaRecoveryCodesRequest, actor: Actor
    ) -> RecoveryCodesResponse:
        result = self._commands.dispatch(
            RegenerateMfaRecoveryCodesCommand(actor=actor, code=body.code)
        )
        return RecoveryCodesResponse(recovery_codes=list(result.recovery_codes))

    def _change_password_endpoint(
        self, body: ChangePasswordRequest, response: Response, actor: Actor
    ) -> AuthenticationResponse:
        result = self._commands.dispatch(
            ChangePasswordCommand(
                actor=actor,
                current_password=body.current_password,
                new_password=body.new_password,
            )
        )
        return self._authentication(result.authentication, response)

    def _current_user_endpoint(self, actor: Actor) -> CurrentUserResponse:
        return CurrentUserResponse.from_result(
            self._current_user.execute(GetCurrentUserInput(actor=actor))
        )

    def _refresh_endpoint(
        self, response: Response, cookie: str | None
    ) -> AccessTokenResponse:
        if not cookie:
            raise UnauthenticatedError
        tokens = self._refresh.execute(RefreshSessionInput(refresh_token=cookie))
        self._set_cookie(response, tokens)
        return AccessTokenResponse(
            access_token=tokens.access_token,
            token_type=TOKEN_TYPE,
            expires_in=self._expires_in(tokens),
        )

    def _logout_endpoint(
        self, response: Response, actor: Actor, cookie: str | None
    ) -> None:
        self._logout.execute(LogoutInput(actor=actor, refresh_token=cookie))
        self._cookie.clear(response)

    def _logout_all_endpoint(self, response: Response, actor: Actor) -> None:
        self._logout_all.execute(LogoutAllInput(actor=actor))
        self._cookie.clear(response)

    def _verify_activation_endpoint(
        self, body: VerifyActivationCodeRequest, request: Request
    ) -> VerifyActivationCodeResponse:
        return VerifyActivationCodeResponse.from_result(
            self._verify_activation.execute(
                VerifyActivationCodeInput(
                    activation_code=body.activation_code,
                    birth_date=body.birth_date,
                    client_ip=client_ip(request),
                )
            )
        )

    def _complete_activation_endpoint(
        self, body: CompleteActivationRequest, request: Request, response: Response
    ) -> AuthenticationResponse:
        result = self._complete_activation.execute(
            CompleteActivationInput(
                activation_token=body.activation_token,
                new_password=body.new_password,
                email=body.email,
                consent=ConsentInput(
                    privacy_notice_version_id=body.consent.privacy_notice_version_id,
                    accepted=body.consent.accepted,
                    ai_external_processing=body.consent.ai_external_processing,
                ),
                client_ip=client_ip(request),
            )
        )
        return self._authentication(result, response)

    def _authentication(
        self, result: AuthenticationResult, response: Response
    ) -> AuthenticationResponse:
        session = result.session
        if session is None:
            return AuthenticationResponse(
                status=result.status, challenge_token=result.challenge_token
            )
        self._set_cookie(response, session)
        return AuthenticationResponse(
            status=result.status,
            access_token=session.access_token,
            token_type=TOKEN_TYPE,
            expires_in=self._expires_in(session),
        )

    def _set_cookie(self, response: Response, tokens: SessionTokens) -> None:
        if tokens.refresh_token is None or tokens.refresh_expires_at is None:
            return
        self._cookie.set(
            response,
            token=tokens.refresh_token,
            expires_at=tokens.refresh_expires_at,
            now=self._clock.now(),
        )

    def _expires_in(self, tokens: SessionTokens) -> int:
        remaining = tokens.access_expires_at - self._clock.now()
        return max(int(remaining.total_seconds()), 0)
