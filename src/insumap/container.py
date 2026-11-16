"""Composition root: the only place where the dependencies of the API are built."""

from __future__ import annotations

from typing import final

from insumap.api.errors import ApiExceptionHandlers, ErrorResponseFactory
from insumap.api.routers.health import HealthRouter
from insumap.application.readiness import (
    AlwaysReadyProbe,
    CheckReadinessUseCase,
    ReadinessProbe,
)
from insumap.infrastructure.logging import JsonLoggingConfigurator
from insumap.shared.config import Settings, get_settings
from insumap.shared.i18n import MessageCatalog
from insumap.shared.time import Clock, SystemClock


@final
class Container:
    """Builds every long-lived dependency of the API once and wires them together.

    Settings, clock, message catalog, logging setup, readiness probe, use cases
    and routers are created here and nowhere else; ``create_app`` only mounts
    them. Tests pass their own settings, clock or probe through the constructor.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        clock: Clock | None = None,
        readiness_probe: ReadinessProbe | None = None,
    ) -> None:
        self.settings: Settings = settings or get_settings()
        self.clock: Clock = clock or SystemClock.instance()
        self.message_catalog = MessageCatalog.load_spanish()
        self.logging_configurator = JsonLoggingConfigurator(self.settings.log_level)
        self.readiness_probe: ReadinessProbe = readiness_probe or AlwaysReadyProbe()

        self.check_readiness = CheckReadinessUseCase(self.readiness_probe)

        self.error_responses = ErrorResponseFactory(self.message_catalog)
        self.exception_handlers = ApiExceptionHandlers(self.error_responses)
        self.health_router = HealthRouter(self.check_readiness)
