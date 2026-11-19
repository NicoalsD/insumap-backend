"""FastAPI application entry point (``uvicorn insumap.main:app``)."""

from typing import Final

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from insumap.api.correlation import REQUEST_ID_HEADER
from insumap.api.middleware import (
    BodySizeLimitMiddleware,
    NoStoreCacheMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
    TrustedHostMiddleware,
)
from insumap.api.openapi import InsumapApi
from insumap.api.paths import API_V1_PREFIX
from insumap.container import Container
from insumap.shared.field_limits import FieldLimits

CORS_ALLOWED_METHODS: Final = ["GET", "POST", "PUT", "PATCH", "DELETE"]
REQUESTED_WITH_HEADER: Final = "X-Requested-With"
IDEMPOTENCY_KEY_HEADER: Final = "Idempotency-Key"
RETRY_AFTER_HEADER: Final = "Retry-After"
CORS_ALLOWED_HEADERS: Final = [
    "Authorization",
    "Content-Type",
    REQUESTED_WITH_HEADER,
    REQUEST_ID_HEADER,
    IDEMPOTENCY_KEY_HEADER,
]
CORS_EXPOSED_HEADERS: Final = [REQUEST_ID_HEADER, RETRY_AFTER_HEADER]
CORS_MAX_AGE_SECONDS: Final = 600


IMPORT_BODY_LIMITS: Final = {
    f"{API_V1_PREFIX}/imports/fhir": FieldLimits.FHIR_BUNDLE_MAX_BYTES,
    f"{API_V1_PREFIX}/imports/csv": FieldLimits.PATIENT_CSV_MAX_BYTES,
    f"{API_V1_PREFIX}/readings/batch": FieldLimits.READINGS_BATCH_MAX_BYTES,
    f"{API_V1_PREFIX}/readings/cgm-import": FieldLimits.CGM_CSV_MAX_BYTES,
}
"""Own body size of the routes that exceed the general limit (API.md 5)."""


def create_app(container: Container | None = None) -> FastAPI:
    """Build the FastAPI application from the parts of the composition root."""
    container = container or Container()
    settings = container.settings
    container.logging_configurator.configure()

    app = InsumapApi.create(docs_enabled=settings.api_docs_enabled)
    container.exception_handlers.install(app)
    # The last middleware added is the outermost. The request id wraps the size
    # limit, so a 413 carries X-Request-ID, CORS wraps both, so browsers can
    # read every error, the host check rejects a foreign Host before any work,
    # and the security headers wrap everything, errors included.
    app.add_middleware(NoStoreCacheMiddleware)
    app.add_middleware(
        BodySizeLimitMiddleware,
        responses=container.error_responses,
        max_body_bytes=FieldLimits.MAX_REQUEST_BODY_BYTES,
        path_limits=IMPORT_BODY_LIMITS,
    )
    app.add_middleware(RequestIdMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=CORS_ALLOWED_METHODS,
            allow_headers=CORS_ALLOWED_HEADERS,
            expose_headers=CORS_EXPOSED_HEADERS,
            max_age=CORS_MAX_AGE_SECONDS,
        )
    app.add_middleware(
        TrustedHostMiddleware,
        responses=container.error_responses,
        allowed_hosts=settings.allowed_hosts,
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.app_env == "production")
    app.include_router(container.health_router.router)
    app.include_router(container.meta_router.router)
    app.include_router(container.auth_router.router)
    app.include_router(container.care_team_router.router)
    app.include_router(container.consent_router.router)
    app.include_router(container.clinic_router.router)
    app.include_router(container.site_router.router)
    app.include_router(container.records_router.router)
    app.include_router(container.metrics_router.router)
    app.include_router(container.alerts_router.router)
    app.include_router(container.recommendation_router.router)
    app.include_router(container.ai_assessment_router.router)
    app.include_router(container.assistant_router.router)
    app.include_router(container.target_profile_router.router)
    app.include_router(container.reminder_router.router)
    app.include_router(container.user_router.router)
    app.include_router(container.import_router.router)
    app.include_router(container.treatment_router.router)
    app.include_router(container.reports_router.router)
    app.include_router(container.messaging_router.router)
    app.include_router(container.notification_router.router)
    app.include_router(container.patient_router.router)
    app.include_router(container.credential_router.router)
    app.include_router(container.dashboard_router.router)
    app.include_router(container.clinical_notes_router.router)
    app.include_router(container.overview_router.router)
    app.include_router(container.clinic_kpi_router.router)
    app.include_router(container.audit_router.router)
    return app


app = create_app()
