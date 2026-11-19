"""Per route body limits: a route may allow more or less than the general limit."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from insumap.api.errors import ApiExceptionHandlers, ErrorResponseFactory
from insumap.api.middleware import BodySizeLimitMiddleware
from insumap.shared.i18n import MessageCatalog

GENERAL = 10
BIG = 40
SMALL = 4


def build_app() -> FastAPI:
    responses = ErrorResponseFactory(MessageCatalog.load_spanish())
    app = FastAPI()
    ApiExceptionHandlers(responses).install(app)
    app.add_middleware(
        BodySizeLimitMiddleware,
        responses=responses,
        max_body_bytes=GENERAL,
        path_limits={"/big": BIG, "/small": SMALL},
    )

    for path in ("/big", "/small", "/other"):

        async def endpoint(request: Request) -> dict[str, int]:
            return {"size": len(await request.body())}

        app.add_api_route(path, endpoint, methods=["POST"])
    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(build_app(), raise_server_exceptions=False) as test_client:
        yield test_client


def test_a_route_can_allow_more_than_the_general_limit(client: TestClient) -> None:
    assert client.post("/big", content=b"x" * BIG).status_code == 200
    rejected = client.post("/big", content=b"x" * (BIG + 1))

    assert rejected.status_code == 413
    assert rejected.json()["error"]["detail"] == {"max_bytes": BIG}


def test_a_route_can_allow_less_than_the_general_limit(client: TestClient) -> None:
    assert client.post("/small", content=b"x" * SMALL).status_code == 200
    rejected = client.post("/small", content=b"x" * (SMALL + 1))

    assert rejected.status_code == 413
    assert rejected.json()["error"]["detail"] == {"max_bytes": SMALL}


def test_the_other_routes_keep_the_general_limit(client: TestClient) -> None:
    assert client.post("/other", content=b"x" * GENERAL).status_code == 200
    assert client.post("/other", content=b"x" * (GENERAL + 1)).status_code == 413


def test_a_chunked_body_is_counted_against_the_route_limit(client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        yield b"x" * SMALL
        yield b"x"

    assert client.post("/small", content=chunks()).status_code == 413
