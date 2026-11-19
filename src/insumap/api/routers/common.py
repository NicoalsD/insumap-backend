"""Pieces every router shares: access labels, error docs, pages and the actor.

A module router (``*Router``) receives the use cases and the ``staff_actor`` /
``session_actor`` dependencies from ``container.py``, documents each route with
``openapi_extra={ACCESS_EXTENSION: access(...)}`` and ``error_responses(...)``,
and maps the result to a ``*Response``. It never calls a repository.
"""

from typing import Annotated, Final

from fastapi import Query
from pydantic import BaseModel, Field

from insumap.api.routers.auth import (
    ACCESS_EXTENSION,
    ERROR_DESCRIPTIONS,
    PUBLIC,
    SESSION_SELF,
    Responses,
    error_responses,
)
from insumap.api.routers.auth_schemas import StrictRequest
from insumap.application.common.pagination import PageRequest, decode_cursor
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.field_limits import FieldLimits

__all__ = [
    "ACCESS_EXTENSION",
    "ERROR_DESCRIPTIONS",
    "PUBLIC",
    "SESSION_SELF",
    "CursorQuery",
    "LimitQuery",
    "PageResponse",
    "Responses",
    "StrictRequest",
    "access",
    "error_responses",
    "page_request",
]

PERMISSION_PREFIX: Final = "permission:"


def access(permission: PermissionCode) -> str:
    """The ``x-access`` label of a route protected by ``permission``."""
    return f"{PERMISSION_PREFIX}{permission.value}"


type LimitQuery = Annotated[
    int,
    Query(
        ge=1,
        le=FieldLimits.PAGE_SIZE_MAX,
        description="Cantidad máxima de elementos de la página.",
    ),
]
type CursorQuery = Annotated[
    str | None,
    Query(
        max_length=FieldLimits.CURSOR_MAX_LENGTH,
        description="Cursor opaco de `next_cursor` de la página anterior.",
    ),
]


def page_request(limit: int, cursor: str | None) -> PageRequest:
    """The page asked for; an invalid cursor is a ``422`` from ``decode_cursor``."""
    return PageRequest(limit=limit, after=decode_cursor(cursor))


class PageResponse[T](BaseModel):
    """``{"items": [...], "next_cursor": ...}`` (API.md section 3)."""

    items: list[T]
    next_cursor: str | None = Field(
        description="Cursor de la página siguiente; `null` en la última."
    )
