"""Security schemes of the API, as declared in OpenAPI."""

from typing import Final

from fastapi.security import HTTPBearer

BEARER_SCHEME_NAME: Final = "bearerAuth"
BEARER_FORMAT: Final = "JWT"

bearer_auth: Final = HTTPBearer(
    scheme_name=BEARER_SCHEME_NAME,
    bearerFormat=BEARER_FORMAT,
    auto_error=False,
    description=(
        "Access token JWT de corta duración. Se envía en el encabezado "
        "`Authorization: Bearer <token>`."
    ),
)
"""Bearer JWT scheme. ``auto_error=False`` leaves the 401 to the canonical
error format instead of FastAPI's default answer."""
