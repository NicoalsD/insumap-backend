from fastapi.testclient import TestClient

from insumap.container import Container
from insumap.main import create_app
from insumap.shared.field_limits import FieldLimits
from tests.support.settings import make_settings

FIELD_LIMITS_PATH = "/api/v1/meta/field-limits"


def client() -> TestClient:
    return TestClient(create_app(Container(make_settings())))


def test_field_limits_are_public_and_cacheable() -> None:
    response = client().get(FIELD_LIMITS_PATH)

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=300"


def test_field_limits_publish_every_constant_in_snake_case() -> None:
    limits = client().get(FIELD_LIMITS_PATH).json()["limits"]

    expected = {
        name.lower(): value
        for name, value in vars(FieldLimits).items()
        if name.isupper()
    }
    assert limits == expected
    assert limits["password_min_length"] == FieldLimits.PASSWORD_MIN_LENGTH
    assert limits["activation_code_length"] == FieldLimits.ACTIVATION_CODE_LENGTH


def test_other_api_v1_responses_are_not_stored() -> None:
    response = client().get("/api/v1/missing")

    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"


def test_health_keeps_no_cache_policy_of_its_own() -> None:
    response = client().get("/health")

    assert "Cache-Control" not in response.headers


def test_field_limits_operation_is_documented_in_spanish() -> None:
    document = client().get("/openapi.json").json()
    operation = document["paths"][FIELD_LIMITS_PATH]["get"]

    assert operation["operationId"] == "get_field_limits"
    assert operation["tags"] == ["Metadatos"]
    assert "security" not in operation
