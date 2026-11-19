"""Port of the CGM file readers: the adapter (P06) implements it."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

CGM_READING_NAMESPACE: Final = uuid.UUID("0b2d1c2e-6a3f-5c1e-9a57-6f0d3b8f7a10")
"""Namespace of the client ids derived from a CGM row (re-import is idempotent)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CgmCandidate:
    """One row of a sensor export, already in mg/dL."""

    measured_at: datetime
    value: Decimal

    def client_reading_id(self, patient_id: UUID) -> UUID:
        """The same patient and instant always give the same id."""
        return uuid.uuid5(
            CGM_READING_NAMESPACE, f"{patient_id}|{self.measured_at.isoformat()}"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedCgm:
    """What the adapter understood: the recognized format and its rows."""

    format: str
    rows: tuple[CgmCandidate, ...]
    invalid_rows: int = 0


class CgmReadingSource(ABC):
    """Reads a sensor export. An unknown format is ``422 VALIDATION_ERROR``."""

    @abstractmethod
    def read(self, content: bytes) -> ParsedCgm:
        """Parse the file or raise ``InsumapError`` with the supported formats."""
