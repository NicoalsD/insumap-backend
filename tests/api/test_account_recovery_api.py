"""Password reset and email verification over HTTP (public endpoints)."""

from dataclasses import replace
from typing import Any

import pytest

from tests.api.identity_support import IdentityApi
from tests.support.identity_world import (
    ACTIVATION_CODE,
    NEW_PASSWORD,
    NOTICE_ID,
    PASSWORD,
    PATIENT_USER,
)

REQUEST = "/api/v1/auth/password-reset/request"
COMPLETE = "/api/v1/auth/password-reset/complete"
VERIFY = "/api/v1/auth/email-verification/confirm"
EMAIL = "paciente@example.test"


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def verified_api() -> IdentityApi:
    api = IdentityApi()
    account = api.world.users.accounts[PATIENT_USER]
    api.world.users.add(replace(account, email_verified=True))
    return api


def activate(api: IdentityApi) -> None:
    verified = api.client.post(
        "/api/v1/auth/activation/verify",
        json={"activation_code": ACTIVATION_CODE, "birth_date": "1980-05-17"},
    )
    done = api.client.post(
        "/api/v1/auth/activation/complete",
        json={
            "activation_token": verified.json()["activation_token"],
            "new_password": NEW_PASSWORD,
            "consent": {
                "privacy_notice_version_id": str(NOTICE_ID),
                "accepted": True,
                "ai_external_processing": False,
            },
        },
    )
    assert done.status_code == 200


# Request.


def test_the_answer_is_the_same_202_for_a_known_and_an_unknown_email() -> None:
    api = verified_api()

    known = api.client.post(REQUEST, json={"email": EMAIL})
    unknown = api.client.post(REQUEST, json={"email": "nadie@example.test"})

    assert known.status_code == unknown.status_code == 202
    assert known.content == unknown.content == b""
    assert known.headers["Cache-Control"] == unknown.headers["Cache-Control"]
    assert len(api.mail.delivered) == 1


def test_an_unverified_email_gets_no_link_but_the_same_answer() -> None:
    api = IdentityApi()

    response = api.client.post(REQUEST, json={"email": EMAIL})

    assert response.status_code == 202
    assert api.mail.delivered == []


@pytest.mark.parametrize("payload", [{}, {"email": ""}, {"email": "a@b.co", "x": 1}])
def test_the_request_validates_its_body(payload: dict[str, Any]) -> None:
    response = IdentityApi().client.post(REQUEST, json=payload)

    assert response.status_code == 422


# Completion.


def test_the_emailed_link_resets_the_password_and_ends_the_old_sessions() -> None:
    api = verified_api()
    old = api.client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
    ).json()["access_token"]
    api.client.post(REQUEST, json={"email": EMAIL})
    token = api.mail.delivered[0].token()

    done = api.client.post(
        COMPLETE, json={"token": token, "new_password": NEW_PASSWORD}
    )

    assert done.status_code == 204
    assert done.content == b""
    stale = api.client.get("/api/v1/auth/current-user", headers=api.bearer(old))
    assert error_code(stale) == "SESSION_REVOKED"
    new_login = api.client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": NEW_PASSWORD}
    )
    old_login = api.client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )
    assert new_login.status_code == 200
    assert error_code(old_login) == "INVALID_CREDENTIALS"
    assert "se restableció" in api.mail.delivered[-1].body


def test_a_used_or_unknown_link_is_410_and_a_weak_password_is_422() -> None:
    api = verified_api()
    api.client.post(REQUEST, json={"email": EMAIL})
    token = api.mail.delivered[0].token()

    weak = api.client.post(COMPLETE, json={"token": token, "new_password": "short"})
    first = api.client.post(
        COMPLETE, json={"token": token, "new_password": NEW_PASSWORD}
    )
    again = api.client.post(
        COMPLETE, json={"token": token, "new_password": NEW_PASSWORD}
    )
    unknown = api.client.post(
        COMPLETE, json={"token": "nothing", "new_password": NEW_PASSWORD}
    )

    assert weak.status_code == 422
    assert "PASSWORD_TOO_SHORT" in weak.text
    assert NEW_PASSWORD not in weak.text
    assert first.status_code == 204
    assert again.status_code == 410
    assert error_code(again) == error_code(unknown) == "INVITATION_INVALID"
    assert again.json() == unknown.json()


@pytest.mark.parametrize(
    "payload", [{}, {"token": "x"}, {"token": "", "new_password": "p"}]
)
def test_completion_validates_its_body(payload: dict[str, Any]) -> None:
    assert IdentityApi().client.post(COMPLETE, json=payload).status_code == 422


def test_completion_is_rate_limited() -> None:
    api = IdentityApi()
    api.world.limiter.blocked = True

    response = api.client.post(COMPLETE, json={"token": "x", "new_password": "y"})

    assert response.status_code == 429
    assert response.headers["Retry-After"]


# Email verification.


def test_activation_emails_a_verification_link_that_unlocks_the_reset() -> None:
    api = IdentityApi()
    activate(api)
    [verification] = api.mail.delivered
    assert "#token=" in verification.body
    assert "24 horas" in verification.body
    before = api.client.post(REQUEST, json={"email": "ana@example.test"})
    assert before.status_code == 202
    assert len(api.mail.delivered) == 1

    confirmed = api.client.post(VERIFY, json={"token": verification.token()})
    again = api.client.post(VERIFY, json={"token": verification.token()})
    after = api.client.post(REQUEST, json={"email": "ana@example.test"})

    assert confirmed.status_code == 204
    assert confirmed.content == b""
    assert again.status_code == 410
    assert after.status_code == 202
    assert len(api.mail.delivered) == 2
    assert "restablecer" in api.mail.delivered[1].body


def test_a_mail_outage_does_not_break_the_activation() -> None:
    api = IdentityApi()
    api.mail.fail = True

    activate(api)

    assert api.mail.delivered == []


@pytest.mark.parametrize("payload", [{}, {"token": ""}, {"token": "x", "y": 1}])
def test_verification_validates_its_body(payload: dict[str, Any]) -> None:
    assert IdentityApi().client.post(VERIFY, json=payload).status_code == 422


def test_an_unknown_verification_token_is_410() -> None:
    response = IdentityApi().client.post(VERIFY, json={"token": "nothing"})

    assert response.status_code == 410
    assert error_code(response) == "INVITATION_INVALID"
