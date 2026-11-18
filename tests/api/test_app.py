from fastapi.testclient import TestClient

from insumap.api.openapi import InsumapApi
from insumap.container import Container
from insumap.main import app, create_app
from tests.support.settings import make_settings

FRONTEND_ORIGIN = "http://localhost:5173"


class NotReadyProbe:
    def is_ready(self) -> bool:
        return False


def test_module_level_app_is_ready_for_uvicorn() -> None:
    assert isinstance(app, InsumapApi)


def test_openapi_title_is_insumap_api() -> None:
    client = TestClient(create_app(Container(make_settings(api_docs_enabled=True))))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Insumap API"


def test_readiness_probe_comes_from_the_container() -> None:
    container = Container(make_settings(), readiness_probe=NotReadyProbe())
    client = TestClient(create_app(container))

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert response.headers["X-Request-ID"]


def test_cors_allows_configured_origins_and_exposes_the_request_id() -> None:
    settings = make_settings(cors_origins=FRONTEND_ORIGIN)
    client = TestClient(create_app(Container(settings)))

    preflight = client.options(
        "/health",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    response = client.get("/missing", headers={"Origin": FRONTEND_ORIGIN})

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert response.status_code == 404
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert "x-request-id" in response.headers["access-control-expose-headers"].lower()


def test_cors_ignores_unknown_origins() -> None:
    settings = make_settings(cors_origins=FRONTEND_ORIGIN)
    client = TestClient(create_app(Container(settings)))

    response = client.get("/health", headers={"Origin": "https://evil.example.test"})

    assert "access-control-allow-origin" not in response.headers


def test_no_cors_headers_without_configured_origins() -> None:
    client = TestClient(create_app(Container(make_settings(cors_origins=[]))))

    response = client.get("/health", headers={"Origin": FRONTEND_ORIGIN})

    assert "access-control-allow-origin" not in response.headers
