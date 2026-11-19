"""Glycemic metrics, AGP and forecast endpoints over the real app (API.md 8.8)."""

from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest

from insumap.domain.identity.consent import ConsentAction, ConsentRecord, ConsentScope
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from tests.api.identity_support import IdentityApi
from tests.support.identity_world import (
    CLINIC,
    NOTICE_ID,
    NOW,
    PASSWORD,
    PATIENT_ID,
    PATIENT_USER,
)
from tests.support.metrics_factories import series
from tests.support.monitoring_fakes import TEST_PROFILE

PATIENT_EMAIL = "paciente@example.test"
DOCTOR = UUID(int=920)
OTHER_PATIENT = UUID(int=999)
DAYS_OF_DATA = 15
READINGS_PER_DAY = 24 * 12
PATIENT_PERMISSIONS = frozenset(
    {PermissionCode.METRICS_READ_OWN, PermissionCode.AI_FORECASTS_READ_OWN}
)
DOCTOR_PERMISSIONS = frozenset(
    {
        PermissionCode.METRICS_READ_ASSIGNED,
        PermissionCode.AI_FORECASTS_READ_ASSIGNED,
    }
)
OWN_METRICS = "/api/v1/patients/own/metrics"
OWN_FORECAST = "/api/v1/patients/own/forecast"


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
    api.world.permissions.by_role[Role.PATIENT] = PATIENT_PERMISSIONS
    api.world.consents.add(
        [
            ConsentRecord(
                consent_id=UUID(int=921),
                clinic_id=CLINIC.clinic_id,
                patient_id=PATIENT_ID,
                privacy_notice_version_id=NOTICE_ID,
                scope=ConsentScope.SENSITIVE_DATA_PROCESSING,
                action=ConsentAction.ACCEPTED,
                occurred_at=NOW,
                recorded_by=PATIENT_USER,
            )
        ]
    )
    api.records.patients.assigned.add((DOCTOR, PATIENT_ID))
    api.records.series.points_by_patient[PATIENT_ID] = series(
        NOW - timedelta(days=DAYS_OF_DATA), [100] * (DAYS_OF_DATA * READINGS_PER_DAY)
    )
    return api


def patient(api: IdentityApi) -> dict[str, str]:
    login = api.client.post(
        "/api/v1/auth/login", json={"email": PATIENT_EMAIL, "password": PASSWORD}
    )
    return api.bearer(login.json()["access_token"])


def doctor(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(DOCTOR, Role.DOCTOR, DOCTOR_PERMISSIONS))


def test_patient_reads_the_metrics_of_the_last_14_days(api: IdentityApi) -> None:
    response = api.client.get(OWN_METRICS, headers=patient(api))

    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["window"] == "14d"
    assert body["is_sufficient"] is True
    assert body["confidence"] == "NORMAL"
    assert body["target_profile"]["code"] == TEST_PROFILE.code
    assert body["metrics"]["tir_pct"] == 100
    assert body["previous"] is not None


def test_without_data_the_metrics_say_they_are_insufficient(api: IdentityApi) -> None:
    api.records.series.points_by_patient.clear()

    response = api.client.get(OWN_METRICS, headers=patient(api))

    body = response.json()
    assert response.status_code == 200, response.text
    assert body["is_sufficient"] is False
    assert body["confidence"] == "LOW_CONFIDENCE"
    assert body["metrics"]["tir_pct"] is None


def test_comparison_with_the_previous_window_can_be_left_out(
    api: IdentityApi,
) -> None:
    response = api.client.get(
        f"/api/v1/patients/{PATIENT_ID}/metrics",
        headers=doctor(api),
        params={"window": "7d", "compare_previous": "false"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["window"] == "7d"
    assert response.json()["previous"] is None
    assert response.json()["tir_delta_pct"] is None


def test_doctor_reads_the_agp_of_an_assigned_patient(api: IdentityApi) -> None:
    response = api.client.get(
        f"/api/v1/patients/{PATIENT_ID}/metrics/agp", headers=doctor(api)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_sufficient"] is True
    assert body["target_range"] == {
        "low": float(TEST_PROFILE.range_low_mg_dl),
        "high": float(TEST_PROFILE.range_high_mg_dl),
    }
    assert len(body["bins"]) == 24
    assert body["bins"][0]["p50"] == 100


def test_forecast_without_the_model_is_a_fallback_not_an_error(
    api: IdentityApi,
) -> None:
    response = api.client.get(OWN_FORECAST, headers=patient(api))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_fallback"] is True
    assert body["points"] == []
    assert body["fallback_reason"] is not None


def test_doctor_reads_the_forecast_of_an_assigned_patient(api: IdentityApi) -> None:
    response = api.client.get(
        f"/api/v1/patients/{PATIENT_ID}/forecast",
        headers=doctor(api),
        params={"mode": "OVERNIGHT"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "OVERNIGHT"
    assert response.json()["is_fallback"] is True


def test_without_token_is_401(api: IdentityApi) -> None:
    assert api.client.get(OWN_METRICS).status_code == 401
    assert api.client.get(OWN_FORECAST).status_code == 401


def test_without_permission_is_403(api: IdentityApi) -> None:
    api.world.permissions.by_role[Role.PATIENT] = frozenset()

    response = api.client.get(OWN_METRICS, headers=patient(api))

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    "path",
    [
        "/metrics",
        "/metrics/agp",
        "/forecast",
    ],
)
def test_doctor_reading_a_patient_not_assigned_is_404_like_a_missing_one(
    api: IdentityApi, path: str
) -> None:
    not_assigned = api.client.get(
        f"/api/v1/patients/{OTHER_PATIENT}{path}", headers=doctor(api)
    )
    missing = api.client.get(
        f"/api/v1/patients/{UUID(int=12345)}{path}", headers=doctor(api)
    )

    assert not_assigned.status_code == missing.status_code == 404
    assert not_assigned.json() == missing.json()


def test_unknown_window_is_422(api: IdentityApi) -> None:
    response = api.client.get(
        OWN_METRICS, headers=patient(api), params={"window": "3d"}
    )

    assert response.status_code == 422, response.text
