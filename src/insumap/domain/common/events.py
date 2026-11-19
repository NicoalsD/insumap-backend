"""Base type of every domain event."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    """Something that happened in the domain, named in the past tense.

    Events are published by the unit of work after the transaction commits
    (P17), never inside it. They carry identifiers only, never personal or
    health data.
    """

    event_id: UUID
    occurred_at: datetime
