"""FastAPI application entry point."""

from fastapi import FastAPI

from insumap.api.errors import ApiExceptionHandlers, ErrorResponseFactory
from insumap.infrastructure.logging import JsonLoggingConfigurator
from insumap.shared.config import Settings, get_settings
from insumap.shared.i18n import MessageCatalog


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application with all its parts wired."""
    settings = settings or get_settings()
    JsonLoggingConfigurator(settings.log_level).configure()
    app = FastAPI(
        title="Insumap API",
        description=(
            "API REST de Insumap, plataforma de monitoreo de pacientes con diabetes "
            "para clínicas. Proyecto académico: no es un dispositivo médico."
        ),
        version="0.1.0",
    )
    responses = ErrorResponseFactory(MessageCatalog.load_spanish())
    ApiExceptionHandlers(responses).install(app)
    return app


app = create_app()
