"""Observer of domain events: subscribers registered by event type."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import cast, final, override

from insumap.domain.common.events import DomainEvent

logger = logging.getLogger(__name__)


class EventSubscriber[E: DomainEvent](ABC):
    """Reacts to one type of domain event."""

    @abstractmethod
    def handle(self, event: E) -> None:
        """Handle ``event``; it already happened and was committed."""


class DomainEventPublisher(ABC):
    """Delivers committed domain events to their subscribers.

    Pattern: P17 Observer
    """

    @abstractmethod
    def publish_all(self, events: Sequence[DomainEvent]) -> None:
        """Deliver every event, in order."""


@final
class InProcessDomainEventPublisher(DomainEventPublisher):
    """Calls the subscribers of each event type in order, in-process.

    A failing subscriber is logged (event type only, never its content) and
    does not stop the others.
    """

    def __init__(self) -> None:
        self._subscribers: dict[
            type[DomainEvent], list[EventSubscriber[DomainEvent]]
        ] = {}

    def subscribe[E: DomainEvent](
        self, event_type: type[E], subscriber: EventSubscriber[E]
    ) -> None:
        """Register ``subscriber`` for events of exactly ``event_type``."""
        registry = self._subscribers.setdefault(event_type, [])
        registry.append(cast("EventSubscriber[DomainEvent]", subscriber))

    @override
    def publish_all(self, events: Sequence[DomainEvent]) -> None:
        for event in events:
            for subscriber in self._subscribers.get(type(event), []):
                try:
                    subscriber.handle(event)
                except Exception:
                    logger.exception(
                        "Event subscriber failed",
                        extra={"event_type": type(event).__name__},
                    )
