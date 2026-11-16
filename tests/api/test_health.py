from fastapi import FastAPI
from fastapi.testclient import TestClient

from insumap.api.routers.health import HealthRouter
from insumap.application.readiness import CheckReadinessUseCase, ReadinessProbe
from insumap.main import create_app
from tests.support.settings import make_settings


class NotReadyProbe:
    def is_ready(self) -> bool:
        return False


def client_with(probe: ReadinessProbe) -> TestClient:
    app = FastAPI()
    app.include_router(HealthRouter(CheckReadinessUseCase(probe)).router)
    return TestClient(app)


def test_health_answers_ok_without_authentication() -> None:
    client = TestClient(create_app(make_settings()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_answers_ok_with_the_default_probe() -> None:
    client = TestClient(create_app(make_settings()))

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_answers_503_when_a_dependency_is_not_ready() -> None:
    response = client_with(NotReadyProbe()).get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_health_stays_ok_when_a_dependency_is_not_ready() -> None:
    response = client_with(NotReadyProbe()).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
