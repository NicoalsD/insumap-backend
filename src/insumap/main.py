"""FastAPI application entry point."""

from fastapi import FastAPI

from insumap.api.errors import ApiExceptionHandlers, ErrorResponseFactory
from insumap.api.middleware import BodySizeLimitMiddleware, RequestIdMiddleware
from insumap.api.openapi import InsumapApi
from insumap.api.routers.health import HealthRouter
from insumap.application.readiness import AlwaysReadyProbe, CheckReadinessUseCase
from insumap.infrastructure.logging import JsonLoggingConfigurator
from insumap.shared.config import Settings, get_settings
from insumap.shared.field_limits import FieldLimits
from insumap.shared.i18n import MessageCatalog


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application with all its parts wired."""
    settings = settings or get_settings()
    JsonLoggingConfigurator(settings.log_level).configure()
    app = InsumapApi.create(docs_enabled=settings.api_docs_enabled)
    responses = ErrorResponseFactory(MessageCatalog.load_spanish())
    ApiExceptionHandlers(responses).install(app)
    # The last middleware added is the outermost: the request id wraps the size
    # limit, so a 413 also carries X-Request-ID.
    app.add_middleware(
        BodySizeLimitMiddleware,
        responses=responses,
        max_body_bytes=FieldLimits.MAX_REQUEST_BODY_BYTES,
    )
    app.add_middleware(RequestIdMiddleware)
    check_readiness = CheckReadinessUseCase(AlwaysReadyProbe())
    app.include_router(HealthRouter(check_readiness).router)
    return app


app = create_app()
