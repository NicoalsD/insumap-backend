from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from insumap.api.errors import ApiExceptionHandlers, ErrorResponseFactory
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.i18n import MessageCatalog

SPANISH = MessageCatalog.load_spanish()
SENSITIVE_VALUE = "hunter2-not-a-real-password"


class SignUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=10)
    password: str = Field(min_length=64)


def build_app() -> FastAPI:
    catalog = MessageCatalog(
        {
            **{key: SPANISH.render(key) for key in SPANISH.message_keys()},
            "patient.duplicated": "El paciente {name} ya existe.",
        }
    )
    app = FastAPI()
    ApiExceptionHandlers(ErrorResponseFactory(catalog)).install(app)

    @app.get("/conflict")
    def conflict() -> None:
        raise InsumapError(
            ErrorCode.CONFLICT,
            message_key="patient.duplicated",
            params={"name": "Ana"},
            detail={"field": "document"},
        )

    @app.get("/rate-limited")
    def rate_limited() -> None:
        raise InsumapError(ErrorCode.RATE_LIMITED, headers={"Retry-After": "42"})

    @app.get("/unknown-key")
    def unknown_key() -> None:
        raise InsumapError(ErrorCode.FORBIDDEN, message_key="missing.text")

    @app.get("/missing-param")
    def missing_param() -> None:
        raise InsumapError(ErrorCode.CONFLICT, message_key="patient.duplicated")

    @app.post("/sign-up")
    def sign_up(body: SignUpRequest) -> None:
        del body

    @app.get("/http-unauthorized")
    def http_unauthorized() -> None:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError(f"database password is {SENSITIVE_VALUE}")

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(), raise_server_exceptions=False)


def error_of(body: dict[str, Any]) -> dict[str, Any]:
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "detail"}
    error: dict[str, Any] = body["error"]
    return error


def test_business_error_uses_its_code_message_and_detail(client: TestClient) -> None:
    response = client.get("/conflict")

    assert response.status_code == 409
    assert error_of(response.json()) == {
        "code": "CONFLICT",
        "message": "El paciente Ana ya existe.",
        "detail": {"field": "document"},
    }


def test_unknown_message_key_falls_back_to_the_code_message(
    client: TestClient,
) -> None:
    response = client.get("/unknown-key")

    assert response.status_code == 403
    assert error_of(response.json())["message"] == SPANISH.render("forbidden")


def test_missing_message_parameter_falls_back_to_the_code_message(
    client: TestClient,
) -> None:
    response = client.get("/missing-param")

    assert response.status_code == 409
    assert error_of(response.json())["message"] == SPANISH.render("conflict")


def test_validation_error_lists_fields_without_their_values(client: TestClient) -> None:
    response = client.post(
        "/sign-up",
        json={"email": "ana.perez@example.test", "password": SENSITIVE_VALUE, "x": 1},
    )

    error = error_of(response.json())
    assert response.status_code == 422
    assert error["code"] == "VALIDATION_ERROR"
    assert error["message"] == SPANISH.render("validation.error")
    assert error["detail"] == {
        "errors": [
            {"field": "body.email", "type": "string_too_long"},
            {"field": "body.password", "type": "string_too_short"},
            {"field": "body.x", "type": "extra_forbidden"},
        ]
    }
    assert SENSITIVE_VALUE not in response.text
    assert "example.test" not in response.text


def test_malformed_json_is_a_validation_error(client: TestClient) -> None:
    response = client.post(
        "/sign-up",
        content=b'{"password": "' + SENSITIVE_VALUE.encode(),
        headers={"Content-Type": "application/json"},
    )

    error = error_of(response.json())
    assert response.status_code == 422
    assert error["detail"]["errors"][0]["type"] == "json_invalid"
    assert SENSITIVE_VALUE not in response.text


def test_unknown_route_answers_not_found(client: TestClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert error_of(response.json())["code"] == "NOT_FOUND"


def test_unsupported_method_answers_not_found(client: TestClient) -> None:
    response = client.delete("/conflict")

    assert response.status_code == 404
    assert error_of(response.json())["code"] == "NOT_FOUND"
    assert "allow" not in response.headers


def test_framework_http_error_keeps_its_status_and_headers(client: TestClient) -> None:
    response = client.get("/http-unauthorized")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert error_of(response.json()) == {
        "code": "UNAUTHENTICATED",
        "message": SPANISH.render("unauthenticated"),
        "detail": {},
    }


def test_unexpected_error_answers_500_without_internals(client: TestClient) -> None:
    response = client.get("/boom")

    assert response.status_code == 500
    assert error_of(response.json()) == {
        "code": "INTERNAL_ERROR",
        "message": SPANISH.render("internal.error"),
        "detail": {},
    }
    assert SENSITIVE_VALUE not in response.text
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text


def test_business_error_headers_reach_the_response(client: TestClient) -> None:
    response = client.get("/rate-limited")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "42"
    assert response.json()["error"]["code"] == "RATE_LIMITED"
