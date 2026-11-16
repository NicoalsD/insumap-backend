from importlib.metadata import version
from typing import Annotated, Any

import pytest
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from insumap.api.openapi import InsumapApi
from insumap.api.security import bearer_auth
from insumap.main import create_app
from tests.support.settings import make_settings

BEARER_JWT = {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    client = TestClient(create_app(make_settings(api_docs_enabled=True)))
    response = client.get("/openapi.json")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def test_info_has_title_package_version_and_disclaimer(
    document: dict[str, Any],
) -> None:
    info = document["info"]

    assert info["title"] == "Insumap API"
    assert info["version"] == version("insumap-backend")
    assert "No es un dispositivo médico" in info["description"]
    assert "simulados" in info["description"]


def test_declares_the_bearer_jwt_scheme(document: dict[str, Any]) -> None:
    scheme = document["components"]["securitySchemes"]["bearerAuth"]

    assert {key: scheme[key] for key in BEARER_JWT} == BEARER_JWT
    assert scheme["description"]


def test_tags_are_in_spanish_with_descriptions(document: dict[str, Any]) -> None:
    assert [tag["name"] for tag in document["tags"]] == ["Salud"]
    assert all(tag["description"] for tag in document["tags"])


def test_health_endpoints_are_tagged_and_public(document: dict[str, Any]) -> None:
    for path in ("/health", "/ready"):
        operation = document["paths"][path]["get"]

        assert operation["tags"] == ["Salud"]
        assert operation["summary"]
        assert operation["description"]
        assert "security" not in operation


def test_swagger_ui_is_served_when_docs_are_enabled() -> None:
    client = TestClient(create_app(make_settings(api_docs_enabled=True)))

    docs = client.get("/docs")
    redoc = client.get("/redoc")

    assert docs.status_code == 200
    assert "swagger-ui" in docs.text
    assert redoc.status_code == 404


def test_docs_and_document_are_hidden_when_disabled() -> None:
    client = TestClient(create_app(make_settings(api_docs_enabled=False)))

    docs = client.get("/docs")
    document = client.get("/openapi.json")

    assert docs.status_code == 404
    assert document.status_code == 404
    assert document.json()["error"]["code"] == "NOT_FOUND"


def test_declared_scheme_matches_the_one_protected_routes_produce() -> None:
    app = InsumapApi.create(docs_enabled=True)

    @app.get("/protected")
    def protected(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Depends(bearer_auth)
        ],
    ) -> None:
        del credentials

    document = TestClient(app).get("/openapi.json").json()

    assert set(document["components"]["securitySchemes"]) == {"bearerAuth"}
    assert document["paths"]["/protected"]["get"]["security"] == [{"bearerAuth": []}]
    assert (
        document["components"]["securitySchemes"]["bearerAuth"]
        == InsumapApi.create(docs_enabled=True).openapi()["components"][
            "securitySchemes"
        ]["bearerAuth"]
    )
