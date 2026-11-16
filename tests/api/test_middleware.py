import logging
import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

from insumap.api.errors import ApiExceptionHandlers, ErrorResponseFactory
from insumap.api.middleware import BodySizeLimitMiddleware, RequestIdMiddleware
from insumap.main import create_app
from insumap.shared.field_limits import FieldLimits
from insumap.shared.i18n import MessageCatalog
from insumap.shared.request_context import current_request_id
from tests.support.settings import make_settings

SPANISH = MessageCatalog.load_spanish()
TEST_LIMIT_BYTES = 16


class Note(BaseModel):
    text: str


def build_app() -> FastAPI:
    responses = ErrorResponseFactory(SPANISH)
    app = FastAPI()
    ApiExceptionHandlers(responses).install(app)
    app.add_middleware(
        BodySizeLimitMiddleware, responses=responses, max_body_bytes=TEST_LIMIT_BYTES
    )
    app.add_middleware(RequestIdMiddleware)

    @app.get("/request-id")
    def request_id() -> dict[str, str | None]:
        return {"request_id": current_request_id()}

    @app.post("/raw")
    async def raw(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    @app.post("/notes")
    def notes(note: Note) -> dict[str, int]:
        return {"size": len(note.text)}

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("unexpected")

    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(build_app(), raise_server_exceptions=False) as test_client:
        yield test_client


def is_uuid4(value: str) -> bool:
    return uuid.UUID(value).version == 4


def chunks(*parts: bytes) -> Iterator[bytes]:
    yield from parts


def test_accepts_a_safe_incoming_request_id(client: TestClient) -> None:
    response = client.get("/request-id", headers={"X-Request-ID": "front-42.a_b"})

    assert response.headers["X-Request-ID"] == "front-42.a_b"
    assert response.json() == {"request_id": "front-42.a_b"}


def test_generates_a_uuid4_when_the_header_is_missing(client: TestClient) -> None:
    response = client.get("/request-id")

    request_id = response.headers["X-Request-ID"]
    assert is_uuid4(request_id)
    assert response.json() == {"request_id": request_id}


@pytest.mark.parametrize(
    "unsafe",
    [
        "a" * (FieldLimits.REQUEST_ID_MAX_LENGTH + 1),
        "id with spaces",
        "<script>alert(1)</script>",
        "id;rm -rf",
        "",
    ],
)
def test_replaces_unsafe_request_ids(client: TestClient, unsafe: str) -> None:
    response = client.get("/request-id", headers={"X-Request-ID": unsafe})

    assert response.headers["X-Request-ID"] != unsafe
    assert is_uuid4(response.headers["X-Request-ID"])


def test_accepts_a_request_id_of_the_maximum_length() -> None:
    longest = "a" * FieldLimits.REQUEST_ID_MAX_LENGTH

    assert RequestIdMiddleware.accept_or_generate(longest) == longest


def test_error_responses_carry_the_request_id(client: TestClient) -> None:
    not_found = client.get("/missing", headers={"X-Request-ID": "req-404"})
    invalid = client.post("/notes", json={}, headers={"X-Request-ID": "req-422"})

    assert not_found.headers["X-Request-ID"] == "req-404"
    assert invalid.headers["X-Request-ID"] == "req-422"


def test_unexpected_errors_carry_and_log_the_request_id(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="insumap.api.errors"):
        response = client.get("/boom", headers={"X-Request-ID": "req-500"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "req-500"
    [record] = [r for r in caplog.records if r.name == "insumap.api.errors"]
    assert getattr(record, "request_id", None) == "req-500"


def test_small_bodies_pass(client: TestClient) -> None:
    response = client.post("/raw", content=b"x" * TEST_LIMIT_BYTES)

    assert response.status_code == 200
    assert response.json() == {"size": TEST_LIMIT_BYTES}


def test_declared_oversized_body_answers_413_with_request_id(
    client: TestClient,
) -> None:
    response = client.post(
        "/raw",
        content=b"x" * (TEST_LIMIT_BYTES + 1),
        headers={"X-Request-ID": "req-413"},
    )

    assert response.status_code == 413
    assert response.headers["X-Request-ID"] == "req-413"
    assert response.json() == {
        "error": {
            "code": "PAYLOAD_TOO_LARGE",
            "message": SPANISH.render("payload.too_large"),
            "detail": {"max_bytes": TEST_LIMIT_BYTES},
        }
    }


def test_chunked_oversized_body_read_by_hand_answers_413(client: TestClient) -> None:
    response = client.post("/raw", content=chunks(b"x" * 10, b"x" * 10))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_chunked_oversized_body_parsed_by_fastapi_answers_413(
    client: TestClient,
) -> None:
    response = client.post(
        "/notes",
        content=chunks(b'{"text": "', b"x" * 20, b'"}'),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_chunked_small_body_passes(client: TestClient) -> None:
    response = client.post("/raw", content=chunks(b"x" * 4, b"x" * 4))

    assert response.status_code == 200
    assert response.json() == {"size": 8}


def test_application_limits_bodies_with_field_limits() -> None:
    client = TestClient(create_app(make_settings()))

    response = client.post(
        "/anything", content=b"x" * (FieldLimits.MAX_REQUEST_BODY_BYTES + 1)
    )

    assert response.status_code == 413
    assert response.json()["error"]["detail"] == {
        "max_bytes": FieldLimits.MAX_REQUEST_BODY_BYTES
    }
    assert is_uuid4(response.headers["X-Request-ID"])
