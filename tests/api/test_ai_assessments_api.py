"""AI assessment endpoints over the real app, the real proxy and in-memory doubles
(API.md 8.10)."""

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from insumap.application.access.ports import AccessPurpose
from insumap.application.ai.assessments import AiExplanation, SummarySection
from insumap.application.ai.ports import RemoteRisk, RemoteSummary
from insumap.application.ai.records import (
    AiEvaluationView,
    ClinicalSummaryView,
    DropoutRiskView,
    PatternFindingView,
)
from insumap.application.metrics.forecast import FallbackReason
from insumap.domain.ai.risk import RiskTier
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from tests.api.identity_support import IdentityApi
from tests.support.identity_world import NOW, PATIENT_ID
from tests.support.metrics_factories import series

DOCTOR = UUID(int=920)
OTHER_DOCTOR = UUID(int=921)
OTHER_PATIENT = UUID(int=999)
CLINIC_ADMIN = UUID(int=930)
PLATFORM = UUID(int=931)
BASE = "/api/v1"
RISK = f"{BASE}/patients/{PATIENT_ID}/risk"
FINDINGS = f"{BASE}/patients/{PATIENT_ID}/pattern-findings"
SUMMARIES = f"{BASE}/patients/{PATIENT_ID}/clinical-summaries"
DROPOUT = f"{BASE}/dropout-risks"
EVALUATIONS = f"{BASE}/ai-evaluations"
DOCTOR_PERMISSIONS = frozenset(
    {
        PermissionCode.AI_RISK_READ_ASSIGNED,
        PermissionCode.AI_DROPOUT_RISK_READ,
        PermissionCode.CLINICAL_SUMMARIES_GENERATE,
    }
)
ADMIN_PERMISSIONS = frozenset(
    {PermissionCode.AI_DROPOUT_RISK_READ, PermissionCode.AI_EVALUATIONS_READ}
)
LABEL_SUGGESTION = "Sugerencia de la IA: el médico decide si la usa."
LABEL_SUMMARY = "Generado con IA como apoyo; verifica con los datos."
LABEL_TEMPLATE = "Resumen generado con la plantilla fija; verifica con los datos."
EXPLANATION = AiExplanation(summary="Riesgo por tres metas incumplidas.")
WINDOW_DAYS = 15
FULL_WINDOW_READINGS = WINDOW_DAYS * 24 * 12
"""Five-minute readings of fifteen days: enough for a 14 day window."""


@pytest.fixture
def api() -> IdentityApi:
    harness = IdentityApi()
    harness.ai.profiles.codes[PATIENT_ID] = "T1D"
    harness.records.patients.assigned.add((DOCTOR, PATIENT_ID))
    harness.ai.dropout.assigned.add((DOCTOR, PATIENT_ID))
    half = FULL_WINDOW_READINGS // 2
    harness.records.series.points_by_patient[PATIENT_ID] = series(
        NOW - timedelta(days=WINDOW_DAYS),
        [60] * half + [200] * (FULL_WINDOW_READINGS - half),
    )
    return harness


def doctor(
    api: IdentityApi, permissions: frozenset[PermissionCode] = DOCTOR_PERMISSIONS
) -> dict[str, str]:
    return api.bearer(api.staff_token(DOCTOR, Role.DOCTOR, permissions))


def test_the_doctor_reads_the_risk_of_an_assigned_patient_from_the_rules(
    api: IdentityApi,
) -> None:
    response = api.client.get(RISK, headers=doctor(api))

    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["assessment_type"] == "DETERIORATION"
    assert body["window_days"] == 14
    assert body["is_fallback"] is True
    assert body["fallback_reason"] == "AI_ERROR"
    assert body["calibrated"] is False
    assert body["risk_tier"] in {"MEDIUM", "HIGH", "CRITICAL"}
    assert body["risk_probability"] > 0
    assert body["label"] == LABEL_SUGGESTION
    assert body["simulated"] is True
    assert body["explanation"]["factors"]
    (record,) = api.ai.store.risks
    assert record.patient_id == PATIENT_ID
    assert record.output.is_fallback is True


def test_the_service_answer_is_returned_and_stored_as_the_ai_output(
    api: IdentityApi,
) -> None:
    api.ai.service.risk = RemoteRisk(
        model_name="risk-gbm",
        model_version="0.3.0+sim1.0.0.seed42",
        input_hash="a" * 64,
        generated_at=NOW,
        is_fallback=False,
        fallback_reason=None,
        risk_probability=Decimal("0.64"),
        risk_tier=RiskTier.HIGH,
        calibrated=True,
        explanation=EXPLANATION,
    )

    response = api.client.get(RISK, headers=doctor(api))

    body = response.json()
    assert body["is_fallback"] is False
    assert body["fallback_reason"] is None
    assert body["risk_probability"] == 0.64
    assert body["model_version"] == "0.3.0+sim1.0.0.seed42"


def test_without_enough_data_the_risk_says_insufficient(api: IdentityApi) -> None:
    api.records.series.points_by_patient.clear()

    response = api.client.get(RISK, headers=doctor(api))

    body = response.json()
    assert response.status_code == 200
    assert body["fallback_reason"] == "INSUFFICIENT_DATA"
    assert body["risk_probability"] is None
    assert body["risk_tier"] is None


def test_the_window_must_be_within_the_limits(api: IdentityApi) -> None:
    response = api.client.get(f"{RISK}?window_days=6", headers=doctor(api))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_risk_without_token_is_401(api: IdentityApi) -> None:
    response = api.client.get(RISK)

    assert response.status_code == 401


def test_risk_without_the_permission_is_403(api: IdentityApi) -> None:
    response = api.client.get(RISK, headers=doctor(api, frozenset()))

    assert response.status_code == 403


def test_risk_of_a_patient_not_assigned_is_404_like_a_missing_one(
    api: IdentityApi,
) -> None:
    other = f"{BASE}/patients/{OTHER_PATIENT}/risk"
    missing = f"{BASE}/patients/{UUID(int=12345)}/risk"

    not_assigned = api.client.get(other, headers=doctor(api))
    absent = api.client.get(missing, headers=doctor(api))

    assert not_assigned.status_code == absent.status_code == 404
    assert not_assigned.json() == absent.json()


def test_findings_are_listed_with_their_suggestion_label(api: IdentityApi) -> None:
    api.ai.findings.items.append(
        PatternFindingView(
            finding_id=UUID(int=501),
            patient_id=PATIENT_ID,
            pattern_type="NOCTURNAL_HYPOGLYCEMIA",
            window_start=NOW - timedelta(days=7),
            window_end=NOW,
            confidence=Decimal("0.88"),
            evidence={"nights_affected": 4},
            explanation=EXPLANATION,
            model_version="0.2.0",
            is_fallback=False,
            fallback_reason=None,
            generated_at=NOW,
        )
    )

    response = api.client.get(FINDINGS, headers=doctor(api))

    assert response.status_code == 200, response.text
    (item,) = response.json()["items"]
    assert item["pattern_type"] == "NOCTURNAL_HYPOGLYCEMIA"
    assert item["label"] == LABEL_SUGGESTION
    assert response.json()["next_cursor"] is None


def test_findings_are_paginated_newest_first(api: IdentityApi) -> None:
    for number in (501, 502):
        api.ai.findings.items.append(
            PatternFindingView(
                finding_id=UUID(int=number),
                patient_id=PATIENT_ID,
                pattern_type="MISSED_DOSE",
                window_start=NOW - timedelta(days=1),
                window_end=NOW,
                confidence=None,
                evidence={},
                explanation=EXPLANATION,
                model_version="0.2.0",
                is_fallback=True,
                fallback_reason="AI_ERROR",
                generated_at=NOW,
            )
        )

    first = api.client.get(f"{FINDINGS}?limit=1", headers=doctor(api)).json()
    second = api.client.get(
        f"{FINDINGS}?limit=1&cursor={first['next_cursor']}", headers=doctor(api)
    ).json()

    assert first["items"][0]["id"] == str(UUID(int=502))
    assert second["items"][0]["id"] == str(UUID(int=501))
    assert second["next_cursor"] is None


def test_an_invalid_cursor_is_422(api: IdentityApi) -> None:
    response = api.client.get(f"{FINDINGS}?cursor=%%%", headers=doctor(api))

    assert response.status_code == 422


def test_the_doctor_generates_a_summary_and_gets_it_back(api: IdentityApi) -> None:
    created = api.client.post(SUMMARIES, json={"period_days": 14}, headers=doctor(api))

    assert created.status_code == 201, created.text
    body = created.json()
    summary_id = body["id"]
    assert created.headers["Location"].endswith(f"/clinical-summaries/{summary_id}")
    assert body["label"] == LABEL_TEMPLATE
    assert body["is_fallback"] is True
    assert body["fallback_reason"] == "AI_ERROR"
    assert body["sections"][0]["title"] == "Resumen del periodo"
    assert "TIR" in body["summary_text"]
    assert body["references"]
    (record,) = api.ai.store.summaries
    assert record.output.summary_id == UUID(summary_id)

    read = api.client.get(f"{SUMMARIES}/{summary_id}", headers=doctor(api))

    assert read.status_code == 200
    assert read.json()["id"] == summary_id


def test_a_summary_from_the_service_is_labelled_as_ai_output(api: IdentityApi) -> None:
    api.ai.service.summary = RemoteSummary(
        model_name="clinical-summary-llm",
        model_version="0.1.0+prompt-v3",
        input_hash="b" * 64,
        generated_at=NOW,
        is_fallback=False,
        fallback_reason=None,
        summary_text="Resumen de la IA.",
        sections=(
            SummarySection(title="Periodo", text="TIR.", refs=("metric:tir_pct",)),
        ),
        numeric_all_matched=True,
        explanation=EXPLANATION,
    )

    body = api.client.post(SUMMARIES, json={}, headers=doctor(api)).json()

    assert body["label"] == LABEL_SUMMARY
    assert body["summary_text"] == "Resumen de la IA."


def test_a_summary_read_through_another_patient_is_404(api: IdentityApi) -> None:
    summary_id = api.client.post(SUMMARIES, json={}, headers=doctor(api)).json()["id"]
    other = f"{BASE}/patients/{OTHER_PATIENT}/clinical-summaries/{summary_id}"

    response = api.client.get(other, headers=doctor(api))

    assert response.status_code == 404


def test_an_unknown_summary_is_404(api: IdentityApi) -> None:
    response = api.client.get(f"{SUMMARIES}/{UUID(int=4242)}", headers=doctor(api))

    assert response.status_code == 404


def test_the_summary_period_is_validated(api: IdentityApi) -> None:
    response = api.client.post(SUMMARIES, json={"period_days": 1}, headers=doctor(api))

    assert response.status_code == 422


def test_the_summaries_of_one_doctor_are_limited_per_hour(api: IdentityApi) -> None:
    headers = doctor(api)
    api.world.limiter.blocked = True

    response = api.client.post(SUMMARIES, json={}, headers=headers)

    assert response.status_code == 429
    assert response.headers["Retry-After"]
    assert api.ai.store.summaries == []


def test_the_doctor_lists_the_dropout_risk_of_assigned_patients_only(
    api: IdentityApi,
) -> None:
    api.ai.dropout.items.extend(
        [
            DropoutRiskView(
                patient_id=PATIENT_ID,
                patient_name="Paciente Simulado",
                risk_tier=RiskTier.HIGH,
                explanation=EXPLANATION,
                is_fallback=True,
                fallback_reason="AI_ERROR",
                generated_at=NOW,
            ),
            DropoutRiskView(
                patient_id=OTHER_PATIENT,
                patient_name="Otro Simulado",
                risk_tier=RiskTier.LOW,
                explanation=EXPLANATION,
                is_fallback=False,
                fallback_reason=None,
                generated_at=NOW,
            ),
        ]
    )

    mine = api.client.get(DROPOUT, headers=doctor(api)).json()
    high = api.client.get(f"{DROPOUT}?risk_tier=HIGH", headers=doctor(api)).json()
    other = api.staff_token(OTHER_DOCTOR, Role.DOCTOR, DOCTOR_PERMISSIONS)
    theirs = api.client.get(DROPOUT, headers=api.bearer(other)).json()

    assert [item["patient_id"] for item in mine["items"]] == [str(PATIENT_ID)]
    assert (DOCTOR, PATIENT_ID, AccessPurpose.CARE) in api.records.patients.reads
    assert mine["items"][0]["label"] == LABEL_SUGGESTION
    assert [item["patient_id"] for item in high["items"]] == [str(PATIENT_ID)]
    assert theirs["items"] == []


def test_the_clinic_admin_is_refused_the_dropout_list_until_its_function_exists(
    api: IdentityApi,
) -> None:
    token = api.staff_token(CLINIC_ADMIN, Role.CLINIC_ADMIN, ADMIN_PERMISSIONS)

    response = api.client.get(DROPOUT, headers=api.bearer(token))

    assert response.status_code == 403


def test_the_clinic_admin_reads_the_evaluations_of_its_clinic(api: IdentityApi) -> None:
    api.ai.evaluations.items.extend(
        [
            AiEvaluationView(
                evaluation_id=UUID(int=601),
                use_case="IA2",
                model_name="risk-gbm",
                model_version="0.3.0",
                baseline_name="risk-rules",
                cohort_ref="sim-seed42",
                sample_size=500,
                model_metrics={"auroc": 0.81},
                baseline_metrics={"auroc": 0.72},
                fallback_usage_pct=Decimal("12.50"),
                evaluated_at=NOW,
            ),
            AiEvaluationView(
                evaluation_id=UUID(int=602),
                use_case="IA1",
                model_name="chronos-bolt-small",
                model_version="2.3.2",
                baseline_name="linear",
                cohort_ref="sim-seed42",
                sample_size=300,
                model_metrics={"mae": 9.1},
                baseline_metrics={"mae": 11.0},
                fallback_usage_pct=None,
                evaluated_at=NOW,
            ),
        ]
    )
    token = api.staff_token(CLINIC_ADMIN, Role.CLINIC_ADMIN, ADMIN_PERMISSIONS)

    response = api.client.get(f"{EVALUATIONS}?use_case=IA2", headers=api.bearer(token))

    assert response.status_code == 200, response.text
    (item,) = response.json()["items"]
    assert item["use_case"] == "IA2"
    assert item["simulated"] is True
    assert item["fallback_usage_pct"] == 12.5


def test_the_platform_admin_is_refused_the_evaluations_until_its_function_exists(
    api: IdentityApi,
) -> None:
    token = api.staff_token(
        PLATFORM, Role.PLATFORM_ADMIN, frozenset({PermissionCode.AI_EVALUATIONS_READ})
    )

    response = api.client.get(EVALUATIONS, headers=api.bearer(token))

    assert response.status_code == 403


def test_an_unknown_use_case_is_422(api: IdentityApi) -> None:
    token = api.staff_token(CLINIC_ADMIN, Role.CLINIC_ADMIN, ADMIN_PERMISSIONS)

    response = api.client.get(f"{EVALUATIONS}?use_case=IA9", headers=api.bearer(token))

    assert response.status_code == 422


def test_the_fallback_reason_of_a_summary_is_a_known_code(api: IdentityApi) -> None:
    assert FallbackReason.AI_ERROR.value == "AI_ERROR"
    view = ClinicalSummaryView(
        summary_id=UUID(int=700),
        patient_id=PATIENT_ID,
        period_start=NOW - timedelta(days=14),
        period_end=NOW,
        summary_text="Texto.",
        sections=(),
        numeric_check_matched=True,
        model_version="0.1.0",
        is_fallback=True,
        fallback_reason="AI_ERROR",
        generated_at=NOW,
    )
    api.ai.summary_reads.items[view.summary_id] = view

    response = api.client.get(f"{SUMMARIES}/{view.summary_id}", headers=doctor(api))

    assert response.json()["fallback_reason"] == "AI_ERROR"
