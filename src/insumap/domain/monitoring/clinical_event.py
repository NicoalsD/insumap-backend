"""Timeline events and the visitor that walks them (P21)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from insumap.domain.monitoring.glucose import GlucoseReading
from insumap.domain.monitoring.records import (
    InsulinDose,
    Meal,
    PhysicalActivity,
    Symptom,
)

type ClinicalEvent = GlucoseReading | InsulinDose | Meal | PhysicalActivity | Symptom


class ClinicalEventVisitor[R](ABC):
    """One method per kind of clinical event; adding a kind updates every visitor.

    Pattern: P21 Visitor
    """

    @abstractmethod
    def visit_glucose_reading(self, event: GlucoseReading) -> R:
        """Handle a glucose reading."""

    @abstractmethod
    def visit_insulin_dose(self, event: InsulinDose) -> R:
        """Handle an insulin dose."""

    @abstractmethod
    def visit_meal(self, event: Meal) -> R:
        """Handle a meal."""

    @abstractmethod
    def visit_physical_activity(self, event: PhysicalActivity) -> R:
        """Handle a physical activity."""

    @abstractmethod
    def visit_symptom(self, event: Symptom) -> R:
        """Handle a symptom."""
