"""OpenAPI document and Swagger UI of the API."""

from __future__ import annotations

from importlib.metadata import version
from typing import Any, Final, Self

from fastapi import FastAPI

from insumap.api.security import BEARER_SCHEME_NAME, bearer_auth
from insumap.api.tags import ApiTag

API_TITLE: Final = "Insumap API"
DISTRIBUTION_NAME: Final = "insumap-backend"
DOCS_URL: Final = "/docs"
OPENAPI_URL: Final = "/openapi.json"
API_DESCRIPTION: Final = (
    "API REST de Insumap, plataforma académica de monitoreo de pacientes con "
    "diabetes para clínicas.\n\n"
    "**Aviso:** Insumap es un proyecto académico. No es un dispositivo médico, no "
    "reemplaza el criterio clínico y la IA solo apoya al médico, que toma todas "
    "las decisiones. Todos los pacientes son simulados.\n\n"
    'Los errores usan el formato `{"error": {"code", "message", "detail"}}`, con '
    "`message` en español, y cada respuesta trae el encabezado `X-Request-ID`."
)
OPENAPI_TAGS: Final[list[dict[str, Any]]] = [
    {
        "name": ApiTag.HEALTH,
        "description": "Estado de la API para monitores y orquestadores.",
    },
    {
        "name": ApiTag.META,
        "description": "Metadatos públicos de la API, como los límites de los campos.",
    },
    {
        "name": ApiTag.AUTH,
        "description": (
            "Inicio de sesión, segundo factor (TOTP), renovación y cierre de "
            "sesión, y activación de cuentas con código de un solo uso."
        ),
    },
]


class InsumapApi(FastAPI):
    """FastAPI application with the Insumap OpenAPI document.

    FastAPI lists a security scheme only once a route depends on it. ``openapi()``
    declares ``bearerAuth`` from the same ``HTTPBearer`` the protected routes use,
    so the contract shows it from the start. Swagger UI and the OpenAPI document
    are served only when the docs are enabled.
    """

    @classmethod
    def create(cls, *, docs_enabled: bool) -> Self:
        """Return the application with its title, description, version and tags."""
        return cls(
            title=API_TITLE,
            description=API_DESCRIPTION,
            version=version(DISTRIBUTION_NAME),
            openapi_tags=OPENAPI_TAGS,
            docs_url=DOCS_URL if docs_enabled else None,
            openapi_url=OPENAPI_URL if docs_enabled else None,
            redoc_url=None,
        )

    def openapi(self) -> dict[str, Any]:
        """Return the OpenAPI document with the ``bearerAuth`` scheme declared."""
        schema = super().openapi()
        components = schema.setdefault("components", {})
        schemes = components.setdefault("securitySchemes", {})
        schemes.setdefault(
            BEARER_SCHEME_NAME,
            bearer_auth.model.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
        return schema
