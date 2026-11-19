"""FastAPI application entry point (``uvicorn insumap.main:app``)."""

from typing import Final

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from insumap.api.correlation import REQUEST_ID_HEADER
from insumap.api.middleware import (
    BodySizeLimitMiddleware,
    NoStoreCacheMiddleware,
    RequestIdMiddleware,
)
from insumap.api.openapi import InsumapApi
from insumap.api.paths import API_V1_PREFIX
from insumap.container import Container
from insumap.shared.field_limits import FieldLimits

CORS_ALLOWED_METHODS: Final = ["GET", "POST", "PUT", "PATCH", "DELETE"]
REQUESTED_WITH_HEADER: Final = "X-Requested-With"
RETRY_AFTER_HEADER: Final = "Retry-After"
CORS_ALLOWED_HEADERS: Final = [
    "Authorization",
    "Content-Type",
    REQUESTED_WITH_HEADER,
    REQUEST_ID_HEADER,
]
CORS_EXPOSED_HEADERS: Final = [REQUEST_ID_HEADER, RETRY_AFTER_HEADER]


IMPORT_BODY_LIMITS: Final = {
    f"{API_V1_PREFIX}/imports/fhir": FieldLimits.FHIR_BUNDLE_MAX_BYTES,
    f"{API_V1_PREFIX}/imports/csv": FieldLimits.PATIENT_CSV_MAX_BYTES,
}
"""Body size of the import routes, which read raw bodies (API.md 5)."""


def create_app(container: Container | None = None) -> FastAPI:
    """Build the FastAPI application from the parts of the composition root."""
    container = container or Container()
    settings = container.settings
    container.logging_configurator.configure()

    app = InsumapApi.create(docs_enabled=settings.api_docs_enabled)
    container.exception_handlers.install(app)
    # The last middleware added is the outermost. The request id wraps the size
    # limit, so a 413 carries X-Request-ID, and CORS wraps both, so browsers can
    # read every error.
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
        )
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
    app.include_router(container.target_profile_router.router)
    app.include_router(container.reminder_router.router)
    app.include_router(container.user_router.router)
    app.include_router(container.import_router.router)
    app.include_router(container.treatment_router.router)
    app.include_router(container.notification_router.router)
    app.include_router(container.patient_router.router)
    app.include_router(container.credential_router.router)
    return app


app = create_app()
