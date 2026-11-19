"""Security headers of Seguridad 13.1 on every response."""

import pytest
from fastapi.testclient import TestClient

from insumap.api.middleware import API_CONTENT_SECURITY_POLICY, HSTS_VALUE
from insumap.container import Container
from insumap.main import create_app
from tests.support.settings import make_settings

FRONTEND_ORIGIN = "http://localhost:5173"
FIXED = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    ),
    "Cross-Origin-Resource-Policy": "same-site",
    "Content-Security-Policy": API_CONTENT_SECURITY_POLICY,
}


def build_client(**overrides: object) -> TestClient:
    return TestClient(create_app(Container(make_settings(**overrides))))


@pytest.mark.parametrize(
    "path", ["/health", "/missing", "/api/v1/meta/field-limits", "/api/v1/me"]
)
def test_every_response_carries_the_fixed_headers(path: str) -> None:
    response = build_client().get(path)

    for name, value in FIXED.items():
        assert response.headers[name] == value
    assert "server" not in response.headers
    assert "x-powered-by" not in response.headers


def test_the_csp_forbids_framing_and_everything_else() -> None:
    csp = build_client().get("/health").headers["Content-Security-Policy"]

    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_hsts_is_sent_only_in_production() -> None:
    assert "Strict-Transport-Security" not in build_client().get("/health").headers
    production = build_client(app_env="production", allowed_hosts=["testserver"])

    response = production.get("/health")

    assert response.headers["Strict-Transport-Security"] == HSTS_VALUE
    assert HSTS_VALUE == "max-age=31536000; includeSubDomains"


def test_errors_and_oversized_bodies_carry_the_headers_too() -> None:
    client = build_client()

    too_big = client.post("/api/v1/auth/login", content=b"x" * (64 * 1024 + 1))

    assert too_big.status_code == 413
    assert too_big.headers["X-Content-Type-Options"] == "nosniff"
    assert too_big.headers["Content-Security-Policy"] == API_CONTENT_SECURITY_POLICY


def test_cors_preflight_carries_the_headers() -> None:
    client = build_client(cors_origins=[FRONTEND_ORIGIN])

    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_a_route_keeps_the_cache_policy_it_sets() -> None:
    response = build_client().get("/api/v1/meta/field-limits")

    assert response.headers["Cache-Control"] == "public, max-age=300"


def test_swagger_keeps_working_without_the_strict_csp() -> None:
    client = build_client(api_docs_enabled=True)

    docs = client.get("/docs")

    assert docs.status_code == 200
    assert "Content-Security-Policy" not in docs.headers
    assert docs.headers["X-Content-Type-Options"] == "nosniff"
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    assert "Content-Security-Policy" not in spec.headers
