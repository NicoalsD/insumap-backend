"""Hosts outside ``ALLOWED_HOSTS`` get the canonical error, not plain text."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from insumap.api.errors import ApiExceptionHandlers, ErrorResponseFactory
from insumap.api.middleware import TrustedHostMiddleware
from insumap.container import Container
from insumap.main import create_app
from insumap.shared.i18n import MessageCatalog
from tests.support.settings import make_settings

SPANISH = MessageCatalog.load_spanish()


def build_client(*allowed_hosts: str) -> TestClient:
    responses = ErrorResponseFactory(SPANISH)
    app = FastAPI()
    ApiExceptionHandlers(responses).install(app)
    app.add_middleware(
        TrustedHostMiddleware, responses=responses, allowed_hosts=allowed_hosts
    )

    @app.get("/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app, base_url="http://api.example.test")


def get_with_host(client: TestClient, host: str | None) -> int:
    headers = {"Host": host} if host is not None else None
    return client.get("/ping", headers=headers).status_code


@pytest.mark.parametrize(
    "host",
    ["api.example.test", "API.Example.Test", "api.example.test:8000"],
)
def test_an_allowed_host_passes(host: str) -> None:
    assert get_with_host(build_client("api.example.test"), host) == 200


@pytest.mark.parametrize(
    "host",
    [
        "evil.test",
        "api.example.test.evil.test",
        "xapi.example.test",
        "example.test",
        "",
    ],
)
def test_a_foreign_host_is_rejected_with_the_canonical_error(host: str) -> None:
    response = build_client("api.example.test").get("/ping", headers={"Host": host})

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": SPANISH.render("validation.invalid_host"),
            "detail": {},
        }
    }


def test_a_wildcard_entry_matches_subdomains_but_not_the_bare_domain() -> None:
    client = build_client("*.example.test")

    assert get_with_host(client, "api.example.test") == 200
    assert get_with_host(client, "a.b.example.test") == 200
    assert get_with_host(client, "example.test") == 400
    assert get_with_host(client, ".example.test") == 400


def test_an_ipv6_literal_is_compared_without_the_port() -> None:
    client = build_client("[::1]")

    assert get_with_host(client, "[::1]:8000") == 200
    assert get_with_host(client, "[::2]:8000") == 400


def test_the_application_accepts_the_development_hosts_by_default() -> None:
    client = TestClient(create_app(Container(make_settings())))

    assert client.get("/health").status_code == 200
    for host in ("localhost:8000", "127.0.0.1"):
        assert client.get("/health", headers={"Host": host}).status_code == 200


def test_the_application_rejects_a_foreign_host() -> None:
    client = TestClient(create_app(Container(make_settings())))

    response = client.get("/health", headers={"Host": "evil.test"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_the_application_uses_the_configured_hosts() -> None:
    settings = make_settings(allowed_hosts=["api.example.test"])
    client = TestClient(create_app(Container(settings)))

    assert client.get("/health").status_code == 400
    ok = client.get("/health", headers={"Host": "api.example.test"})
    assert ok.status_code == 200
