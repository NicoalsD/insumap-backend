"""The AI schema against PostgreSQL: the ORM maps the migrated columns, and the
system audit row of an AI output is written as the ``insumap_app`` role.

Runs against ``INSUMAP_TEST_DATABASE_URL`` (``it_ia``) with the migrations of
``insumap-database`` at the tag of ``db-schema.lock``.
"""

from datetime import UTC, datetime

import psycopg

from insumap.application.common.unit_of_work import TransactionContext
from insumap.infrastructure.ai.output_store import SYSTEM_ACCESS_LOG
from insumap.infrastructure.identity_adapters import build_engine
from insumap.infrastructure.persistence.orm import (
    AiEvaluationOrm,
    AssistantMessageOrm,
    ClinicalSummaryOrm,
    GlucoseForecastOrm,
    KnowledgeDocumentOrm,
    PatternFindingOrm,
    PatternFindingReviewOrm,
    RecommendationDecisionOrm,
    RecommendationOrm,
    RiskAssessmentOrm,
)
from insumap.infrastructure.persistence.transactions import (
    CurrentSession,
    SqlTransactionFactory,
)
from tests.support.db_seed import DemoWorld
from tests.support.settings import make_settings

REQUEST_ID = "req-ai-audit-1"


def _columns(conn: psycopg.Connection, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = 'ai' AND table_name = %s",
        (table,),
    ).fetchall()
    return {row[0] for row in rows}


def _mapped(model: type) -> set[str]:
    return {column.name for column in model.__table__.columns}  # type: ignore[attr-defined]


def test_the_ai_orm_maps_every_column_of_the_migrated_tables(migrated_url: str) -> None:
    with psycopg.connect(migrated_url) as conn:
        for table, model in (
            ("glucose_forecasts", GlucoseForecastOrm),
            ("recommendations", RecommendationOrm),
            ("recommendation_decisions", RecommendationDecisionOrm),
            ("risk_assessments", RiskAssessmentOrm),
            ("pattern_findings", PatternFindingOrm),
            ("pattern_finding_reviews", PatternFindingReviewOrm),
            ("clinical_summaries", ClinicalSummaryOrm),
            ("assistant_messages", AssistantMessageOrm),
            ("knowledge_documents", KnowledgeDocumentOrm),
            ("ai_evaluations", AiEvaluationOrm),
        ):
            assert _mapped(model) == _columns(conn, table), table


def test_the_system_audit_row_of_an_ai_output_is_written(
    migrated_url: str, app_url: str, demo_world: DemoWorld
) -> None:
    with psycopg.connect(migrated_url) as conn:
        patient_id = conn.execute(
            "SELECT id FROM clinic.patients WHERE clinic_id = %s LIMIT 1",
            (demo_world.clinic_id,),
        ).fetchone()
    assert patient_id is not None
    engine = build_engine(make_settings(database_url=app_url))
    current = CurrentSession()
    factory = SqlTransactionFactory(engine, current)

    with factory.open() as transaction:
        transaction.apply_context(TransactionContext.for_system(demo_world.clinic_id))
        current.get().execute(
            SYSTEM_ACCESS_LOG,
            {
                "clinic_id": demo_world.clinic_id,
                "patient_id": patient_id[0],
                "request_id": REQUEST_ID,
                "occurred_at": datetime(2026, 11, 19, 12, 0, tzinfo=UTC),
            },
        )
        transaction.commit()

    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT actor_type, actor_user_id, actor_role, purpose, resource_type"
            " FROM audit.data_access_log WHERE request_id = %s",
            (REQUEST_ID,),
        ).fetchone()

    assert row == ("SYSTEM", None, None, "AI_PROCESSING", "AI_OUTPUTS")
