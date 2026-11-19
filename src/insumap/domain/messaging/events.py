"""Domain events of the messaging (P17 Observer).

They carry identifiers and the sender role only, never the text of a message:
a subscriber reads the row it needs under its own transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from insumap.domain.common.events import DomainEvent
from insumap.domain.messaging.message import SenderRole


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageSent(DomainEvent):
    """A message was appended to a thread (committed).

    Pattern: P17 Observer (event)
    """

    message_id: UUID
    thread_id: UUID
    clinic_id: UUID
    sender_role: SenderRole
