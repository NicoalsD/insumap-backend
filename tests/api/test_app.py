from fastapi.testclient import TestClient

from insumap.main import app


def test_openapi_title_is_insumap_api() -> None:
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Insumap API"
