"""The AI assessment endpoints over PostgreSQL 18: RLS writes, CHECKs and audit rows.

The AI is not configured here, so each call answers with its fallback and stores it:
that is the path where the database constraints matter most.
"""

from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from insumap.infrastructure.security.password_hasher import (
    Argon2PasswordHasher,
    PasswordHashingConfig,
)
from tests.integration.test_sites_flow import _login, _staff_headers
from tests.support.db_seed import (
    ADMIN_EMAIL,
    DEMO_PASSWORD,
    DOCTOR_EMAIL,
    PATIENT_EMAIL,
    DemoWorld,
)
from tests.support.settings import make_settings

pytestmark = pytest.mark.integration

BASE = "/api/v1"
PROFILE_CODE = "IT_ADULT_DEFAULT"
PROFILE_ROW = (
    "INSERT INTO care.target_profiles (clinic_id, code, label, population, version,"
    " status, is_default, range_low_mg_dl, range_high_mg_dl, very_low_mg_dl,"
    " very_high_mg_dl, tir_min_pct, tbr_l1_max_pct, tbr_l2_max_pct, tar_l1_max_pct,"
    " tar_l2_max_pct, cv_max_pct, min_data_sufficiency_pct, min_days,"
    " max_gap_minutes, hypo_episode_min_minutes, min_readings_for_cv,"
    " min_readings_for_cv_smbg, night_start, night_end, source_reference)"
    # Dummy values: the goals are data; these tests only need a default profile.
    " SELECT NULL, %s, 'Perfil de prueba', 'ADULT', 1, 'ACTIVE', true,"
    " 10, 20, 5, 30, 50, 10, 5, 40, 10, 40, 60, 7, 15, 10, 50, 20,"
    " '00:00', '06:00', 'Fuente de prueba'"
    " WHERE NOT EXISTS (SELECT 1 FROM care.target_profiles"
    " WHERE clinic_id IS NULL AND code = %s)"
)
RISK = f"{BASE}/patients/{{patient}}/risk"
FINDINGS = f"{BASE}/patients/{{patient}}/pattern-findings"
SUMMARIES = f"{BASE}/patients/{{patient}}/clinical-summaries"
DROPOUT = f"{BASE}/dropout-risks"
EVALUATIONS = f"{BASE}/ai-evaluations"
ASSISTANT = f"{BASE}/assistant/messages"
DISMISS = f"{BASE}/patients/{{patient}}/pattern-findings/{{finding}}/dismiss"
PLATFORM_EMAIL = "plataforma.ia.demo@example.test"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _json(response: Any) -> Any:
    assert response.status_code < 300, response.text
    return response.json()


@pytest.fixture
def world(migrated_url: str, demo_world: DemoWorld) -> dict[str, Any]:
    """The seeded patient, assigned to the doctor, with both consents and a profile."""
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(PROFILE_ROW, (PROFILE_CODE, PROFILE_CODE))
        patient_id, profile_id = _ids(conn, demo_world)
        conn.execute(
            "INSERT INTO clinic.care_team_assignments (clinic_id, patient_id,"
            " doctor_user_id, is_primary, assigned_by, assigned_at)"
            " VALUES (%s, %s, %s, true, %s, now())",
            (
                demo_world.clinic_id,
                patient_id,
                demo_world.doctor_user_id,
                demo_world.admin_user_id,
            ),
        )
        for scope in ("SENSITIVE_DATA_PROCESSING", "AI_EXTERNAL_PROCESSING"):
            conn.execute(
                "INSERT INTO clinic.patient_consents (clinic_id, patient_id,"
                " privacy_notice_version_id, scope, action, recorded_by)"
                " VALUES (%s, %s, %s, %s, 'ACCEPTED', %s)",
                (
                    demo_world.clinic_id,
                    patient_id,
                    demo_world.notice_id,
                    scope,
                    demo_world.patient_user_id,
                ),
            )
    return {"patient": patient_id, "profile": profile_id}


def _ids(conn: psycopg.Connection, demo: DemoWorld) -> tuple[Any, Any]:
    patient = conn.execute(
        "SELECT id FROM clinic.patients WHERE user_id = %s", (demo.patient_user_id,)
    ).fetchone()
    profile = conn.execute(
        "SELECT id FROM care.target_profiles WHERE code = %s AND clinic_id IS NULL",
        (PROFILE_CODE,),
    ).fetchone()
    assert patient is not None and profile is not None
    return patient[0], profile[0]


def _rows(
    migrated_url: str, sql: str, params: tuple[Any, ...]
) -> list[tuple[Any, ...]]:
    with psycopg.connect(migrated_url) as conn:
        return list(conn.execute(sql, params).fetchall())


def test_a_doctor_risk_read_stores_the_assessment_and_audits_the_read(
    api: TestClient, migrated_url: str, world: dict[str, Any]
) -> None:
    doctor = _bearer(_staff_headers(api, DOCTOR_EMAIL)["Authorization"].split()[1])

    body = _json(api.get(RISK.format(patient=world["patient"]), headers=doctor))

    assert body["is_fallback"] is True
    assert body["fallback_reason"] == "INSUFFICIENT_DATA"
    assert body["calibrated"] is False
    stored = _rows(
        migrated_url,
        "SELECT assessment_type, calibrated, fallback_reason, window_days"
        " FROM ai.risk_assessments WHERE patient_id = %s",
        (world["patient"],),
    )
    assert stored == [("DETERIORATION", False, "INSUFFICIENT_DATA", 14)]
    audited = _rows(
        migrated_url,
        "SELECT purpose FROM audit.data_access_log WHERE patient_id = %s"
        " AND resource_type = 'AI_OUTPUTS'",
        (world["patient"],),
    )
    assert ("AI_PROCESSING",) in audited


def test_the_doctor_generates_and_reads_a_summary_through_the_database(
    api: TestClient, migrated_url: str, world: dict[str, Any]
) -> None:
    doctor = _staff_headers(api, DOCTOR_EMAIL)
    created = api.post(
        SUMMARIES.format(patient=world["patient"]),
        json={"period_days": 14},
        headers=doctor,
    )

    assert created.status_code == 201, created.text
    summary = created.json()
    assert summary["is_fallback"] is True
    read = _json(
        api.get(
            f"{SUMMARIES.format(patient=world['patient'])}/{summary['id']}",
            headers=doctor,
        )
    )
    assert read["id"] == summary["id"]
    stored = _rows(
        migrated_url,
        "SELECT jsonb_typeof(sections), numeric_check_matched FROM "
        "ai.clinical_summaries"
        " WHERE id = %s",
        (summary["id"],),
    )
    assert stored == [("object", True)]


def test_the_patient_question_and_the_reply_are_stored_under_their_own_rules(
    api: TestClient, migrated_url: str, world: dict[str, Any], demo_world: DemoWorld
) -> None:
    doc_id = uuid4()
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO ai.knowledge_documents (id, clinic_id, title, body, version,"
            " status, approved_by, approved_at)"
            " SELECT %s, clinic_id, 'Qué es la hipoglucemia',"
            " 'La hipoglucemia es una glucosa baja. Mide tu glucosa.', 1, 'APPROVED',"
            " %s, now() FROM clinic.patients WHERE id = %s",
            (doc_id, demo_world.admin_user_id, world["patient"]),
        )
    patient = _staff_patient(api)

    reply = _json(
        api.post(
            ASSISTANT,
            json={"message": "¿Qué es la hipoglucemia?"},
            headers=patient,
        )
    )

    assert reply["is_fallback"] is True
    assert reply["fallback_reason"] == "AI_ERROR"
    stored = _rows(
        migrated_url,
        "SELECT sender, is_fallback, context_doc_ids::text[] FROM ai.assistant_messages"
        " WHERE conversation_id = %s ORDER BY sent_at",
        (reply["conversation_id"],),
    )
    assert [row[0] for row in stored] == ["PATIENT", "ASSISTANT"]
    assert stored[1][1] is True
    assert stored[1][2] == [str(doc_id)]


def _staff_patient(api: TestClient) -> dict[str, str]:
    login = _login(api, PATIENT_EMAIL)
    assert login.status_code == 200, login.text
    return _bearer(str(login.json()["access_token"]))


def test_the_dropout_list_shows_the_assigned_patient_without_clinical_values(
    api: TestClient, migrated_url: str, world: dict[str, Any], demo_world: DemoWorld
) -> None:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO ai.risk_assessments (clinic_id, patient_id, assessment_type,"
            " risk_probability, risk_tier, calibrated, window_days, target_profile_id,"
            " model_name, model_version, input_hash, explanation, is_fallback,"
            " fallback_reason, is_shadow, generated_at, created_at)"
            " VALUES (%s, %s, 'DROPOUT', 0.7000, 'HIGH', false, 14, %s,"
            " 'risk-rules', 'risk-rules@1.0.0', %s, '{\"summary\": \"Sin "
            "registros.\"}',"
            " true, 'AI_ERROR', false, now(), now())",
            (demo_world.clinic_id, world["patient"], world["profile"], "f" * 64),
        )
    doctor = _staff_headers(api, DOCTOR_EMAIL)

    body = _json(api.get(DROPOUT, headers=doctor))

    (item,) = body["items"]
    assert item["patient_id"] == str(world["patient"])
    assert item["risk_tier"] == "HIGH"
    assert set(item) == {
        "patient_id",
        "patient_name",
        "account_status",
        "days_without_record",
        "risk_tier",
        "explanation",
        "is_fallback",
        "fallback_reason",
        "generated_at",
        "label",
        "simulated",
    }
    assert item["account_status"] is None
    assert item["days_without_record"] is None


def test_the_clinic_admin_reads_the_evaluations_of_its_clinic(
    api: TestClient, migrated_url: str, demo_world: DemoWorld
) -> None:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO ai.ai_evaluations (clinic_id, use_case, model_name, "
            "model_version,"
            " baseline_name, cohort_ref, sample_size, model_metrics, baseline_metrics,"
            " fallback_usage_pct, evaluated_at)"
            " VALUES (%s, 'IA2', 'risk-gbm', '0.3.0', 'risk-rules', 'sim-seed42', 120,"
            " '{\"auroc\": 0.81}', '{\"auroc\": 0.72}', 12.50, now())",
            (demo_world.clinic_id,),
        )
    admin = _staff_headers(api, ADMIN_EMAIL)

    body = _json(api.get(EVALUATIONS, headers=admin, params={"use_case": "IA2"}))

    assert [item["use_case"] for item in body["items"]] == ["IA2"]
    assert body["items"][0]["simulated"] is True


def test_the_findings_of_an_assigned_patient_are_listed_for_the_doctor(
    api: TestClient, migrated_url: str, world: dict[str, Any], demo_world: DemoWorld
) -> None:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO ai.pattern_findings (clinic_id, patient_id, pattern_type,"
            " window_start, window_end, confidence, evidence, model_name,"
            "model_version,"
            " input_hash, explanation, is_fallback, fallback_reason, is_shadow,"
            " generated_at, created_at)"
            " VALUES (%s, %s, 'NOCTURNAL_HYPOGLYCEMIA', now() - interval '7 days', "
            "now(),"
            " 0.8800, '{\"nights_affected\": 4}', 'pattern-detectors', '0.2.0', %s,"
            " '{\"summary\": \"Cuatro noches bajo meta.\"}', true, 'AI_ERROR', false,"
            " now(), now())",
            (demo_world.clinic_id, world["patient"], "e" * 64),
        )
    doctor = _staff_headers(api, DOCTOR_EMAIL)

    body = _json(api.get(FINDINGS.format(patient=world["patient"]), headers=doctor))

    (item,) = body["items"]
    assert item["pattern_type"] == "NOCTURNAL_HYPOGLYCEMIA"
    assert item["explanation"]["summary"] == "Cuatro noches bajo meta."


def _insert_finding(migrated_url: str, world: dict[str, Any], demo: DemoWorld) -> UUID:
    """A finding of IA3 written as the AI service does (the superuser skips RLS)."""
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        row = conn.execute(
            "INSERT INTO ai.pattern_findings (clinic_id, patient_id, pattern_type,"
            " window_start, window_end, confidence, evidence, model_name,"
            " model_version, input_hash, explanation, is_fallback, fallback_reason,"
            " is_shadow, generated_at, created_at)"
            " VALUES (%s, %s, 'NOCTURNAL_HYPOGLYCEMIA', now() - interval '7 days',"
            " now(), 0.8800, '{\"nights_affected\": 4}', 'pattern-detectors',"
            " '0.2.0', %s, '{\"summary\": \"Cuatro noches bajo meta.\"}',"
            " true, 'AI_ERROR', false, now(), now())"
            " RETURNING id",
            (demo.clinic_id, world["patient"], "d" * 64),
        ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def test_the_doctor_dismisses_a_finding_and_the_database_keeps_one_review(
    api: TestClient, migrated_url: str, world: dict[str, Any], demo_world: DemoWorld
) -> None:
    finding = _insert_finding(migrated_url, world, demo_world)
    doctor = _staff_headers(api, DOCTOR_EMAIL)

    body = _json(
        api.post(
            DISMISS.format(patient=world["patient"], finding=finding),
            json={"note": "  Ayuno explicado por la cena tardía.  "},
            headers=doctor,
        )
    )

    assert body["status"] == "DISMISSED"
    assert body["dismissed_by"] == str(demo_world.doctor_user_id)
    reviews = _rows(
        migrated_url,
        "SELECT clinic_id, patient_id, action, reason, reviewed_by"
        " FROM ai.pattern_finding_reviews WHERE finding_id = %s",
        (finding,),
    )
    assert reviews == [
        (
            demo_world.clinic_id,
            world["patient"],
            "DISMISSED",
            "Ayuno explicado por la cena tardía.",
            demo_world.doctor_user_id,
        )
    ]
    audited = _rows(
        migrated_url,
        "SELECT action, entity_type, entity_id FROM audit.audit_log"
        " WHERE entity_id = %s",
        (finding,),
    )
    assert audited == [("PATTERN_FINDING_DISMISSED", "PATTERN_FINDING", finding)]
    (item,) = _json(api.get(FINDINGS.format(patient=world["patient"]), headers=doctor))[
        "items"
    ]
    assert item["status"] == "DISMISSED"


def test_a_second_dismissal_is_409_and_leaves_one_row(
    api: TestClient, migrated_url: str, world: dict[str, Any], demo_world: DemoWorld
) -> None:
    finding = _insert_finding(migrated_url, world, demo_world)
    doctor = _staff_headers(api, DOCTOR_EMAIL)
    url = DISMISS.format(patient=world["patient"], finding=finding)
    _json(api.post(url, json={"note": "Primera respuesta."}, headers=doctor))

    response = api.post(url, json={"note": "Segunda respuesta."}, headers=doctor)

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    rows = _rows(
        migrated_url,
        "SELECT count(*) FROM ai.pattern_finding_reviews WHERE finding_id = %s",
        (finding,),
    )
    assert rows == [(1,)]


def test_the_database_refuses_a_review_signed_by_another_user_and_any_change(
    app_url: str, migrated_url: str, world: dict[str, Any], demo_world: DemoWorld
) -> None:
    """RLS as the API connects (``insumap_app``): the doctor writes only as herself."""
    finding = _insert_finding(migrated_url, world, demo_world)
    session = (
        "SELECT set_config('app.clinic_id', %s, false),"
        " set_config('app.user_id', %s, false), set_config('app.role', 'DOCTOR', false)"
    )
    settings = (str(demo_world.clinic_id), str(demo_world.doctor_user_id))
    insert = (
        "INSERT INTO ai.pattern_finding_reviews (clinic_id, patient_id, finding_id,"
        " action, reason, reviewed_by) VALUES (%s, %s, %s, 'DISMISSED', 'Motivo.', %s)"
    )
    with (
        psycopg.connect(app_url) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(session, settings)
        conn.execute(
            insert,
            (demo_world.clinic_id, world["patient"], finding, demo_world.admin_user_id),
        )
    with psycopg.connect(app_url) as conn:
        conn.execute(session, settings)
        conn.execute(
            insert,
            (
                demo_world.clinic_id,
                world["patient"],
                finding,
                demo_world.doctor_user_id,
            ),
        )
    with (
        psycopg.connect(app_url) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(session, settings)
        conn.execute(
            "UPDATE ai.pattern_finding_reviews SET reason = 'Otro.'"
            " WHERE finding_id = %s",
            (finding,),
        )
    with (
        psycopg.connect(app_url) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(session, settings)
        conn.execute(
            "DELETE FROM ai.pattern_finding_reviews WHERE finding_id = %s", (finding,)
        )


def test_the_clinic_admin_reads_the_dropout_list_through_the_definer_function(
    api: TestClient, migrated_url: str, world: dict[str, Any], demo_world: DemoWorld
) -> None:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO ai.risk_assessments (clinic_id, patient_id, assessment_type,"
            " risk_probability, risk_tier, calibrated, window_days, target_profile_id,"
            " model_name, model_version, input_hash, explanation, is_fallback,"
            " fallback_reason, is_shadow, generated_at, created_at)"
            " VALUES (%s, %s, 'DROPOUT', 0.7000, 'HIGH', false, 14, %s,"
            " 'risk-rules', 'risk-rules@1.0.0', %s,"
            ' \'{"summary": "Sin registros."}\','
            " true, 'AI_ERROR', false, now(), now())",
            (demo_world.clinic_id, world["patient"], world["profile"], "e" * 64),
        )
        status = conn.execute(
            "SELECT status FROM iam.users WHERE id = %s", (demo_world.patient_user_id,)
        ).fetchone()
    assert status is not None
    admin = _staff_headers(api, ADMIN_EMAIL)

    body = _json(api.get(DROPOUT, headers=admin))

    (item,) = body["items"]
    assert item["patient_id"] == str(world["patient"])
    assert item["account_status"] == status[0]
    assert item["days_without_record"] is None
    assert item["risk_tier"] == "HIGH"
    assert "glucose" not in str(item).lower()


def _platform_headers(api: TestClient, migrated_url: str) -> dict[str, str]:
    """A platform administrator: a membership with no clinic (API.md 8.3)."""
    settings = make_settings()
    hasher = Argon2PasswordHasher(
        PasswordHashingConfig(
            memory_kib=settings.argon2_memory_kib,
            time_cost=settings.argon2_time_cost,
            parallelism=settings.argon2_parallelism,
            max_concurrency=settings.password_hash_max_concurrency,
        )
    )
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        user = conn.execute(
            "INSERT INTO iam.users (email, email_normalized, password_hash, status)"
            " VALUES (%s, %s, %s, 'ACTIVE') RETURNING id",
            (PLATFORM_EMAIL, PLATFORM_EMAIL, hasher.hash(DEMO_PASSWORD)),
        ).fetchone()
        assert user is not None
        conn.execute(
            "INSERT INTO iam.memberships (user_id, clinic_id, role_id)"
            " SELECT %s, NULL, id FROM iam.roles WHERE code = 'PLATFORM_ADMIN'",
            (user[0],),
        )
    return _staff_headers(api, PLATFORM_EMAIL)


def test_the_platform_admin_reads_the_evaluations_of_every_clinic(
    api: TestClient, migrated_url: str, demo_world: DemoWorld
) -> None:
    version = "9.9.9-platform"
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO ai.ai_evaluations (clinic_id, use_case, model_name,"
            " model_version, baseline_name, cohort_ref, sample_size, model_metrics,"
            " baseline_metrics, fallback_usage_pct, evaluated_at)"
            " VALUES (%s, 'IA2', 'risk-gbm', %s, 'risk-rules', 'sim-a', 100,"
            " '{\"auroc\": 0.8}', '{\"auroc\": 0.7}', 5.00, now()),"
            " (NULL, 'IA1', 'chronos-bolt-small', %s, 'linear', 'sim-global', 80,"
            " '{\"mae\": 9.0}', '{\"mae\": 11.0}', NULL, now())",
            (demo_world.clinic_id, version, version),
        )
    platform = _platform_headers(api, migrated_url)

    body = _json(
        api.get(EVALUATIONS, headers=platform, params={"model_version": version})
    )

    assert sorted(item["use_case"] for item in body["items"]) == ["IA1", "IA2"]
    assert all(item["simulated"] is True for item in body["items"])
