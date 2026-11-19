"""Injection sites of the patient: where the next dose goes (API.md 8.6)."""

from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any, Final, Self, final

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from insumap.api.paths import API_V1_PREFIX
from insumap.api.routers.common import ACCESS_EXTENSION, access, error_responses
from insumap.api.tags import ApiTag
from insumap.application.common.actor import Actor
from insumap.application.monitoring.injection import GetOwnInjectionSitesUseCase
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.monitoring.injection_rule import (
    InjectionSites,
    InjectionSiteStatus,
    InjectionSuggestion,
)
from insumap.domain.monitoring.injection_sites import (
    NeedleNote,
    ReasonCode,
    SiteCode,
    SiteState,
)
from insumap.domain.monitoring.records import InsulinKind
from insumap.shared.field_limits import FieldLimits

INJECTION_SITES_PATH: Final = f"{API_V1_PREFIX}/patients/own/injection-sites"
ERRORS: Final = error_responses(
    HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN, HTTPStatus.UNPROCESSABLE_ENTITY
)


class InjectionSuggestionResponse(BaseModel):
    """El sitio y el punto que el paciente debería usar ahora."""

    site: SiteCode
    spot: int = Field(
        ge=FieldLimits.INJECTION_SPOT_MIN, le=FieldLimits.INJECTION_SPOT_MAX
    )
    reason_codes: list[ReasonCode]
    needle_note: NeedleNote
    pinch_up: bool = Field(description="`true` si conviene pellizcar la piel.")

    @classmethod
    def of(cls, suggestion: InjectionSuggestion) -> Self:
        return cls(
            site=suggestion.site,
            spot=suggestion.spot,
            reason_codes=list(suggestion.reason_codes),
            needle_note=suggestion.needle_note,
            pinch_up=suggestion.pinch_up,
        )


class InjectionSiteStatusResponse(BaseModel):
    """El estado de uno de los ocho sitios y su último uso."""

    site: SiteCode
    state: SiteState
    reason_code: ReasonCode | None
    last_used_at: datetime | None
    last_spot: int | None

    @classmethod
    def of(cls, status: InjectionSiteStatus) -> Self:
        return cls(
            site=status.site,
            state=status.state,
            reason_code=status.reason_code,
            last_used_at=status.last_used_at,
            last_spot=status.last_spot,
        )


class InjectionSitesResponse(BaseModel):
    """La sugerencia y el estado de los sitios. Nunca contiene unidades de insulina."""

    kind: InsulinKind
    suggestion: InjectionSuggestionResponse | None = Field(
        description="Nulo solo cuando ningún sitio es seguro para este paciente."
    )
    sites: list[InjectionSiteStatusResponse]
    rules_version: str

    @classmethod
    def of(cls, answer: InjectionSites) -> Self:
        return cls(
            kind=answer.kind,
            suggestion=None
            if answer.suggestion is None
            else InjectionSuggestionResponse.of(answer.suggestion),
            sites=[InjectionSiteStatusResponse.of(row) for row in answer.sites],
            rules_version=answer.rules_version,
        )


@final
class InjectionSitesRouter:
    """Builds ``GET /patients/own/injection-sites`` over its use case."""

    def __init__(
        self, *, injection_sites: GetOwnInjectionSitesUseCase, session_actor: Any
    ) -> None:
        self._injection_sites = injection_sites
        self._session_actor = session_actor
        self.router = APIRouter(tags=[ApiTag.RECORDS])
        self._add_routes()

    def _add_routes(self) -> None:
        guard = Depends(self._session_actor)

        def get_own_injection_sites(
            actor: Annotated[Actor, guard],
            kind: Annotated[
                InsulinKind,
                Query(
                    description="Clase de insulina: `BASAL`, `BOLUS`, "
                    "`CORRECTION` o `MIXED`."
                ),
            ],
        ) -> InjectionSitesResponse:
            return InjectionSitesResponse.of(self._injection_sites.execute(actor, kind))

        self.router.add_api_route(
            INJECTION_SITES_PATH,
            get_own_injection_sites,
            methods=["GET"],
            operation_id="get_own_injection_sites",
            summary="Ver dónde inyectarme",
            description=(
                "Sugiere el sitio y el punto de la próxima inyección y muestra el "
                "estado de los ocho sitios. Es una regla determinista, no una IA: "
                "usa el plan, el sexo, la edad, el IMC, el embarazo, la "
                "lipohipertrofia reportada y las últimas dosis con sitio. **Nunca "
                "devuelve unidades de insulina.** `kind` es obligatorio."
            ),
            responses=ERRORS,
            openapi_extra={ACCESS_EXTENSION: access(PermissionCode.RECORDS_READ_OWN)},
        )
