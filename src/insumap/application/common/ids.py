"""Identifier generation port. The domain never creates identifiers."""

from abc import ABC, abstractmethod
from uuid import UUID


class IdGenerator(ABC):
    """Creates identifiers for new rows (UUIDv7 in production)."""

    @abstractmethod
    def new_id(self) -> UUID:
        """Return a new unique identifier."""
