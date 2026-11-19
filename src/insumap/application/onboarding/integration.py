"""Ports of one import family (P03 Abstract Factory) and of its rows.

A family is the trio parser, mapper and validator of one file format. A
pipeline asks its factory once per run and uses the three products together.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

from insumap.domain.onboarding.batch import RowOutcome
from insumap.domain.onboarding.patient import PatientCandidate, ValidationResult
from insumap.domain.onboarding.vocabulary import (
    DataOrigin,
    ImportIssue,
    RowVerdict,
    SourceFormat,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceRow:
    """One entry of the file: its position, its resource type and its raw content.

    ``data`` is whatever the parser read (a FHIR resource or the cells of a CSV
    line); only the mapper of the same family looks inside it.
    """

    row_number: int
    resource_type: str | None
    data: object


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedSource:
    """What the parser understood from a file: its declared origin and its rows."""

    origin: DataOrigin
    rows: tuple[SourceRow, ...]


class SourceRowError(Exception):
    """A row the mapper cannot read; it becomes one row outcome, not a failure."""

    def __init__(
        self, issue: ImportIssue, verdict: RowVerdict = RowVerdict.ERROR
    ) -> None:
        super().__init__(issue.value)
        self.issue = issue
        self.verdict = verdict

    def outcome(self, row: SourceRow) -> RowOutcome:
        """The row outcome this error stands for."""
        return RowOutcome(
            row_number=row.row_number,
            resource_type=row.resource_type,
            verdict=self.verdict,
            issues=(self.issue,),
        )


class PatientSourceParser(ABC):
    """Reads a file of one format; a file that cannot be read is a ``422``."""

    source_format: SourceFormat

    @abstractmethod
    def parse(self, content: bytes) -> ParsedSource:
        """The declared origin and the rows, in file order."""


class PatientRecordMapper(ABC):
    """Turns one raw row into the candidate fields (P06 Adapter for FHIR)."""

    source_format: SourceFormat

    @abstractmethod
    def to_candidate(self, row: SourceRow) -> PatientCandidate:
        """The candidate, or ``SourceRowError`` when the row has no patient shape."""


class ImportValidator(ABC):
    """Applies the rules of the import to one candidate."""

    source_format: SourceFormat

    @abstractmethod
    def validate(self, candidate: PatientCandidate, *, today: date) -> ValidationResult:
        """Errors stop the row; warnings keep it."""


class ClinicIntegrationFactory(ABC):
    """Abstract factory of one import family (P03).

    Pattern: P03 Abstract Factory
    """

    @property
    @abstractmethod
    def source_format(self) -> SourceFormat:
        """The format every product of this family reads."""

    @abstractmethod
    def create_parser(self) -> PatientSourceParser:
        """The parser of this family."""

    @abstractmethod
    def create_mapper(self) -> PatientRecordMapper:
        """The mapper of this family."""

    @abstractmethod
    def create_validator(self) -> ImportValidator:
        """The validator of this family."""
