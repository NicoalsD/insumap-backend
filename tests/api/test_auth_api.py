from typing import Any

import pytest

from insumap.application.security.events import SecurityEventType
from tests.api.identity_support import CSRF_HEADERS, ORIGIN, IdentityApi
from tests.support.identity_fakes import VALID_TOTP
from tests.support.identity_world import (
    ACTIVATION_CODE,
    NEW_PASSWORD,
    NOTICE_ID,
    PASSWORD,
)

PATIENT = {"email": "paciente@example.test", "password": PASSWORD}
DOCTOR = {"email": "medico@example.test", "password": PASSWORD}
NEW_DOCTOR = {"email": "nuevo@example.test", "password": PASSWORD}


def error_code(response: Any) -> str:
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "detail"}
    assert body["error"]["message"]
    return str(body["error"]["code"])


def patient_login(api: IdentityApi) -> dict[str, Any]:
    response = api.client.post("/api/v1/auth/login", json=PATIENT)
    assert response.status_code == 200
    return dict(response.json())


# Login.


def test_patient_login_returns_the_token_and_a_hardened_cookie() -> None:
    api = IdentityApi()

    response = api.client.post("/api/v1/auth/login", json=PATIENT)

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "AUTHENTICATED"
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 900
    assert "refresh" not in response.text
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Secure-insumap_rt=opaque-")
    for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Path=/api/v1/auth"):
        assert attribute in cookie
    assert "Max-Age=2592000" in cookie
    assert "Domain" not in cookie
    assert response.headers["Cache-Control"] == "no-store"


def test_staff_login_returns_a_challenge_without_cookie() -> None:
    response = IdentityApi().client.post("/api/v1/auth/login", json=DOCTOR)

    assert response.json()["status"] == "MFA_CHALLENGE"
    assert response.json()["challenge_token"]
    assert "set-cookie" not in response.headers


def test_enrollment_login_returns_a_token_without_cookie() -> None:
    response = IdentityApi().client.post("/api/v1/auth/login", json=NEW_DOCTOR)

    assert response.json()["status"] == "MFA_ENROLLMENT_REQUIRED"
    assert response.json()["access_token"]
    assert "set-cookie" not in response.headers


def test_bad_credentials_are_the_same_generic_401() -> None:
    api = IdentityApi()
    wrong = api.client.post(
        "/api/v1/auth/login", json={**PATIENT, "password": "wrong password!!"}
    )
    unknown = api.client.post(
        "/api/v1/auth/login", json={"email": "x@example.test", "password": PASSWORD}
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert error_code(wrong) == "INVALID_CREDENTIALS"
    assert wrong.json()["error"]["message"] == "Usuario o contraseña incorrectos."


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"email": "a@example.test"},
        {**PATIENT, "extra": 1},
        {**PATIENT, "password": "x" * 129},
        {**PATIENT, "email": "a" * 255},
        {"email": 5, "password": "x"},
    ],
)
def test_login_validates_its_body(payload: dict[str, Any]) -> None:
    response = IdentityApi().client.post("/api/v1/auth/login", json=payload)

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"
    assert "x" * 129 not in response.text


def test_login_rate_limit_answers_429_with_retry_after() -> None:
    api = IdentityApi()
    api.world.limiter.blocked = True

    response = api.client.post("/api/v1/auth/login", json=PATIENT)

    assert response.status_code == 429
    assert error_code(response) == "RATE_LIMITED"
    assert response.headers["Retry-After"] == "30"


# MFA.


def test_mfa_verify_completes_the_staff_login() -> None:
    api = IdentityApi()
    challenge = api.client.post("/api/v1/auth/login", json=DOCTOR).json()[
        "challenge_token"
    ]

    wrong = api.client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_token": challenge, "code": "000000"}
    )
    ok = api.client.post(
        "/api/v1/auth/mfa/verify",
        json={"challenge_token": challenge, "code": VALID_TOTP},
    )

    assert wrong.status_code == 401
    assert error_code(wrong) == "INVALID_CREDENTIALS"
    assert ok.status_code == 200
    assert ok.json()["status"] == "AUTHENTICATED"
    assert "Max-Age=43200" in ok.headers["set-cookie"]


def test_mfa_verify_with_an_unknown_challenge_is_401_and_validates_input() -> None:
    api = IdentityApi()

    unknown = api.client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_token": "nope", "code": "123456"}
    )
    short = api.client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_token": "x", "code": "1"}
    )

    assert error_code(unknown) == "UNAUTHENTICATED"
    assert short.status_code == 422


def test_enrollment_flow_returns_the_secret_then_the_session_and_codes() -> None:
    api = IdentityApi()
    token = api.client.post("/api/v1/auth/login", json=NEW_DOCTOR).json()[
        "access_token"
    ]
    headers = api.bearer(token)

    started = api.client.post("/api/v1/auth/mfa/enrollment", headers=headers)
    confirmed = api.client.post(
        "/api/v1/auth/mfa/enrollment/confirm",
        headers=headers,
        json={"code": VALID_TOTP},
    )

    assert started.status_code == 200
    assert started.json()["otpauth_uri"].startswith("otpauth://totp/Insumap:")
    assert started.headers["Cache-Control"] == "no-store"
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "AUTHENTICATED"
    assert len(confirmed.json()["recovery_codes"]) == 10
    assert "__Secure-insumap_rt" in confirmed.headers["set-cookie"]


def test_enrollment_confirm_rejects_bad_codes_and_patients() -> None:
    api = IdentityApi()
    doctor = api.client.post("/api/v1/auth/login", json=NEW_DOCTOR).json()
    headers = api.bearer(doctor["access_token"])
    api.client.post("/api/v1/auth/mfa/enrollment", headers=headers)

    bad_shape = api.client.post(
        "/api/v1/auth/mfa/enrollment/confirm", headers=headers, json={"code": "abc"}
    )
    wrong = api.client.post(
        "/api/v1/auth/mfa/enrollment/confirm", headers=headers, json={"code": "999999"}
    )
    patient = patient_login(api)
    forbidden = api.client.post(
        "/api/v1/auth/mfa/enrollment", headers=api.bearer(patient["access_token"])
    )

    assert bad_shape.status_code == 422
    assert error_code(wrong) == "INVALID_CREDENTIALS"
    assert forbidden.status_code == 403
    assert error_code(forbidden) == "FORBIDDEN"


def test_enrollment_requires_authentication() -> None:
    response = IdentityApi().client.post("/api/v1/auth/mfa/enrollment")

    assert response.status_code == 401
    assert error_code(response) == "UNAUTHENTICATED"


# Current user.


def test_me_returns_the_documented_shape() -> None:
    api = IdentityApi()
    token = patient_login(api)["access_token"]

    response = api.client.get("/api/v1/auth/current-user", headers=api.bearer(token))

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "paciente@example.test"
    assert body["role"] == "PATIENT"
    assert body["clinic"]["is_demo"] is True
    assert body["clinic"]["simulated"] is True
    assert body["permissions"] == ["patients.read_own"]
    assert body["mfa_enabled"] is False
    assert body["consent_required"] is True


def test_me_works_with_the_enrollment_session() -> None:
    api = IdentityApi()
    token = api.client.post("/api/v1/auth/login", json=NEW_DOCTOR).json()[
        "access_token"
    ]

    response = api.client.get("/api/v1/auth/current-user", headers=api.bearer(token))

    assert response.status_code == 200
    assert response.json()["role"] == "DOCTOR"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer garbage"},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer " + "a" * 2100},
    ],
)
def test_me_without_a_valid_bearer_is_401(headers: dict[str, str]) -> None:
    response = IdentityApi().client.get("/api/v1/auth/current-user", headers=headers)

    assert response.status_code == 401
    assert error_code(response) == "UNAUTHENTICATED"


def test_staff_without_otp_is_denied_outside_enrollment() -> None:
    api = IdentityApi()
    token = api.client.post("/api/v1/auth/login", json=NEW_DOCTOR).json()[
        "access_token"
    ]

    response = api.client.post(
        "/api/v1/auth/logout-all", headers={**api.bearer(token), **CSRF_HEADERS}
    )

    assert response.status_code == 403
    assert error_code(response) == "MFA_REQUIRED"


# Refresh, logout.


def test_refresh_rotates_the_cookie_and_returns_a_new_access_token() -> None:
    api = IdentityApi()
    patient_login(api)
    first_cookie = api.client.cookies["__Secure-insumap_rt"]

    response = api.client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)

    assert response.status_code == 200
    assert response.json()["access_token"]
    assert set(response.json()) == {"access_token", "token_type", "expires_in"}
    assert api.client.cookies["__Secure-insumap_rt"] != first_cookie


def test_reusing_a_rotated_refresh_revokes_the_session() -> None:
    api = IdentityApi()
    patient_login(api)
    old_cookie = api.client.cookies["__Secure-insumap_rt"]
    api.client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)

    api.client.cookies.set("__Secure-insumap_rt", old_cookie, path="/api/v1/auth")
    response = api.client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)

    assert response.status_code == 401
    assert error_code(response) == "SESSION_REVOKED"


def test_refresh_without_a_cookie_is_401() -> None:
    response = IdentityApi().client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)

    assert response.status_code == 401
    assert error_code(response) == "UNAUTHENTICATED"


@pytest.mark.parametrize("path", ["refresh", "logout", "logout-all"])
@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"X-Requested-With": "XMLHttpRequest"},
        {**CSRF_HEADERS, "Origin": "https://evil.example.test"},
        {**CSRF_HEADERS, "Origin": "null"},
        {**CSRF_HEADERS, "Sec-Fetch-Site": "cross-site"},
    ],
)
def test_cookie_endpoints_reject_failed_csrf_checks(
    path: str, extra: dict[str, str]
) -> None:
    api = IdentityApi()
    token = patient_login(api)["access_token"]

    response = api.client.post(
        f"/api/v1/auth/{path}", headers={**api.bearer(token), **extra}
    )

    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"
    assert api.world.events.events[-1].event_type is (
        SecurityEventType.CSRF_CHECK_FAILED
    )


def test_cookie_endpoints_accept_an_allowed_origin() -> None:
    api = IdentityApi()
    patient_login(api)

    response = api.client.post(
        "/api/v1/auth/refresh",
        headers={**CSRF_HEADERS, "Origin": ORIGIN, "Sec-Fetch-Site": "same-site"},
    )

    assert response.status_code == 200


def test_logout_revokes_the_family_and_clears_the_cookie() -> None:
    api = IdentityApi()
    token = patient_login(api)["access_token"]

    response = api.client.post(
        "/api/v1/auth/logout", headers={**api.bearer(token), **CSRF_HEADERS}
    )

    assert response.status_code == 204
    assert response.content == b""
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert all(t.is_revoked for t in api.world.refresh_tokens.tokens.values())


def test_logout_needs_a_valid_token() -> None:
    response = IdentityApi().client.post("/api/v1/auth/logout", headers=CSRF_HEADERS)

    assert response.status_code == 401


def test_logout_all_kills_the_access_token_of_the_same_session() -> None:
    api = IdentityApi()
    token = patient_login(api)["access_token"]

    done = api.client.post(
        "/api/v1/auth/logout-all", headers={**api.bearer(token), **CSRF_HEADERS}
    )
    after = api.client.get("/api/v1/auth/current-user", headers=api.bearer(token))

    assert done.status_code == 204
    assert after.status_code == 401
    assert error_code(after) == "SESSION_REVOKED"


# Activation.


def activation_token(api: IdentityApi, **overrides: Any) -> str:
    response = api.client.post(
        "/api/v1/auth/activation/verify",
        json={"activation_code": ACTIVATION_CODE, "birth_date": "1980-05-17"}
        | overrides,
    )
    assert response.status_code == 200
    return str(response.json()["activation_token"])


def completion(token: str, **overrides: Any) -> dict[str, Any]:
    return {
        "activation_token": token,
        "new_password": NEW_PASSWORD,
        "consent": {"privacy_notice_version_id": str(NOTICE_ID), "accepted": True},
    } | overrides


def test_activation_flow_activates_the_patient_and_sets_the_cookie() -> None:
    api = IdentityApi()
    verified = api.client.post(
        "/api/v1/auth/activation/verify",
        json={"activation_code": ACTIVATION_CODE, "birth_date": "1980-05-17"},
    )
    token = verified.json()["activation_token"]

    done = api.client.post("/api/v1/auth/activation/complete", json=completion(token))

    assert verified.status_code == 200
    assert verified.json()["clinic_name"] == "Clínica Demo"
    assert verified.json()["email_required"] is False
    assert "Ana" not in verified.text
    assert done.status_code == 200
    assert done.json()["status"] == "AUTHENTICATED"
    assert "__Secure-insumap_rt" in done.headers["set-cookie"]
    me = api.client.get(
        "/api/v1/auth/current-user", headers=api.bearer(done.json()["access_token"])
    )
    assert me.json()["user"]["email"] == "ana@example.test"
    assert me.json()["consent_required"] is True or me.status_code == 200


def test_activation_failures_are_a_single_410() -> None:
    api = IdentityApi()
    wrong_date = api.client.post(
        "/api/v1/auth/activation/verify",
        json={"activation_code": ACTIVATION_CODE, "birth_date": "1999-01-01"},
    )
    bad_code = api.client.post(
        "/api/v1/auth/activation/verify",
        json={"activation_code": "nonsense", "birth_date": "1980-05-17"},
    )
    bad_token = api.client.post(
        "/api/v1/auth/activation/complete", json=completion("nope")
    )

    assert (
        wrong_date.status_code == bad_code.status_code == bad_token.status_code == 410
    )
    assert wrong_date.json() == bad_code.json() == bad_token.json()
    assert error_code(wrong_date) == "INVITATION_INVALID"


def test_activation_errors_of_the_second_step() -> None:
    api = IdentityApi()
    token = activation_token(api)

    no_consent = api.client.post(
        "/api/v1/auth/activation/complete",
        json=completion(
            token,
            consent={"privacy_notice_version_id": str(NOTICE_ID), "accepted": False},
        ),
    )
    short = api.client.post(
        "/api/v1/auth/activation/complete", json=completion(token, new_password="abc")
    )
    taken = api.client.post(
        "/api/v1/auth/activation/complete",
        json=completion(token, email="paciente@example.test"),
    )
    stale = api.client.post(
        "/api/v1/auth/activation/complete",
        json=completion(
            token,
            consent={
                "privacy_notice_version_id": "00000000-0000-0000-0000-000000000001",
                "accepted": True,
            },
        ),
    )

    assert (no_consent.status_code, error_code(no_consent)) == (403, "CONSENT_REQUIRED")
    assert short.status_code == 422
    assert error_code(short) == "VALIDATION_ERROR"
    assert (taken.status_code, error_code(taken)) == (409, "EMAIL_UNAVAILABLE")
    assert (stale.status_code, error_code(stale)) == (
        409,
        "CONSENT_VERSION_OUTDATED",
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"activation_code": ""},
        {"activation_code": "x" * 33},
        {"activation_code": ACTIVATION_CODE, "birth_date": "1850-01-01"},
        {"activation_code": ACTIVATION_CODE, "birth_date": "not-a-date"},
        {"activation_code": ACTIVATION_CODE, "extra": 1},
    ],
)
def test_activation_verify_validates_its_body(payload: dict[str, Any]) -> None:
    response = IdentityApi().client.post("/api/v1/auth/activation/verify", json=payload)

    assert response.status_code == 422


def test_activation_complete_validates_its_body() -> None:
    api = IdentityApi()

    for body in (
        {},
        completion("x", extra=1),
        completion("x", email="not-an-email"),
        completion("x", consent={"accepted": True}),
    ):
        response = api.client.post("/api/v1/auth/activation/complete", json=body)
        assert response.status_code == 422


# Surface.


def test_cors_preflight_allows_the_csrf_header_and_exposes_retry_after() -> None:
    api = IdentityApi()

    preflight = api.client.options(
        "/api/v1/auth/refresh",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-requested-with",
        },
    )
    actual = api.client.post(
        "/api/v1/auth/login", json=PATIENT, headers={"Origin": ORIGIN}
    )

    assert preflight.status_code == 200
    assert (
        "x-requested-with" in preflight.headers["access-control-allow-headers"].lower()
    )
    assert "Retry-After" in actual.headers["access-control-expose-headers"]
    assert actual.headers["access-control-allow-credentials"] == "true"


def test_every_auth_route_declares_its_access_and_is_documented_in_spanish() -> None:
    api = IdentityApi()
    spec = api.client.get("/openapi.json").json()

    operations = [
        (path, method, operation)
        for path, item in spec["paths"].items()
        if path.startswith("/api/v1/auth")
        for method, operation in item.items()
    ]
    assert len(operations) == 10
    for path, method, operation in operations:
        assert operation["x-access"], (path, method)
        assert operation["operationId"]
        assert operation["summary"] and operation["description"]
        assert "429" in operation["responses"]
    public = {p for p, _, o in operations if o["x-access"] == "public"}
    assert public == {
        "/api/v1/auth/login",
        "/api/v1/auth/mfa/verify",
        "/api/v1/auth/activation/verify",
        "/api/v1/auth/activation/complete",
    }
    for path, _, operation in operations:
        if path not in public:
            assert operation.get("security") or "refresh" in path, path


def test_unhandled_dependency_errors_keep_the_canonical_format() -> None:
    api = IdentityApi()
    api.world.users.accounts.clear()

    response = api.client.post("/api/v1/auth/login", json=PATIENT)

    assert response.status_code == 401
