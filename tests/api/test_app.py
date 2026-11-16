from fastapi.testclient import TestClient

from insumap.api.openapi import InsumapApi
from insumap.main import app, create_app
from tests.support.settings import make_settings


def test_module_level_app_is_ready_for_uvicorn() -> None:
    assert isinstance(app, InsumapApi)


def test_openapi_title_is_insumap_api() -> None:
    client = TestClient(create_app(make_settings(api_docs_enabled=True)))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Insumap API"
