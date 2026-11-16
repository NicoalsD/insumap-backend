"""Readiness of the API to receive traffic."""

from typing import Protocol, final


class ReadinessProbe(Protocol):
    """Port that tells whether a dependency of the API can serve traffic.

    Infrastructure implements it for each dependency worth checking (for example,
    the database); the composition root picks the implementation.
    """

    def is_ready(self) -> bool:
        """Return ``True`` when the dependency can serve traffic."""
        ...


@final
class AlwaysReadyProbe:
    """Default probe while the API has no dependency to check: always ready."""

    def is_ready(self) -> bool:
        """Return ``True``."""
        return True


@final
class CheckReadinessUseCase:
    """Tells whether the API is ready to receive traffic, asking its probe."""

    def __init__(self, probe: ReadinessProbe) -> None:
        self._probe = probe

    def execute(self) -> bool:
        """Return ``True`` when the API can receive traffic."""
        return self._probe.is_ready()
