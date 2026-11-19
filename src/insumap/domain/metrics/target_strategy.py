"""How a patient is judged against the target profile (P19 Strategy).

The numbers always come from the ``TargetProfile`` row; a strategy only decides
which of them matter and in which order.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Final, final, override

from insumap.domain.metrics.glycemic_metrics import GlycemicMetrics, Signal
from insumap.domain.metrics.target_profile import TargetProfile
from insumap.shared.errors import ErrorCode, InsumapError


class GlycemicTargetStrategy(ABC):
    """Decides whether the metrics of a period meet the targets of a profile.

    ``None`` means it cannot say: not enough data or a family of metrics the
    profile has no percentage target for.

    Pattern: P19 Strategy
    """

    code: str

    @abstractmethod
    def is_on_target(
        self, metrics: GlycemicMetrics, profile: TargetProfile
    ) -> bool | None:
        """``True`` on target, ``False`` off target, ``None`` if it cannot say."""


def _tir_met(metrics: GlycemicMetrics, profile: TargetProfile) -> bool | None:
    if metrics.signal is not Signal.CGM or metrics.tir_pct is None:
        return None
    return metrics.tir_pct >= profile.tir_min_pct


@final
class AdultStandardTargetStrategy(GlycemicTargetStrategy):
    """Time in range first (consensus for adults with type 1 or type 2)."""

    code = "ADULT_STANDARD"

    @override
    def is_on_target(
        self, metrics: GlycemicMetrics, profile: TargetProfile
    ) -> bool | None:
        return _tir_met(metrics, profile)


@final
class OlderOrHighRiskTargetStrategy(GlycemicTargetStrategy):
    """Hypoglycemia first: time below range decides before time in range."""

    code = "OLDER_OR_HIGH_RISK"

    @override
    def is_on_target(
        self, metrics: GlycemicMetrics, profile: TargetProfile
    ) -> bool | None:
        if metrics.signal is not Signal.CGM or metrics.tbr_pct is None:
            return None
        if metrics.tbr_pct > profile.tbr_l1_max_pct:
            return False
        return _tir_met(metrics, profile)


@final
class PregnancyTargetStrategy(GlycemicTargetStrategy):
    """Tight range: time in range, time below range and time above range."""

    code = "PREGNANCY"

    @override
    def is_on_target(
        self, metrics: GlycemicMetrics, profile: TargetProfile
    ) -> bool | None:
        time_in_range = _tir_met(metrics, profile)
        if time_in_range is None or metrics.tbr_pct is None or metrics.tar_pct is None:
            return None
        return (
            time_in_range
            and metrics.tbr_pct <= profile.tbr_l1_max_pct
            and metrics.tar_pct <= profile.tar_l1_max_pct
        )


@final
class GlycemicTargetStrategyRegistry:
    """Finds the strategy of a profile by the population stored in the database."""

    STRATEGIES: Final[tuple[GlycemicTargetStrategy, ...]] = (
        AdultStandardTargetStrategy(),
        OlderOrHighRiskTargetStrategy(),
        PregnancyTargetStrategy(),
    )
    POPULATION_STRATEGY: Final = {
        "ADULT": AdultStandardTargetStrategy.code,
        "OLDER_OR_HIGH_RISK": OlderOrHighRiskTargetStrategy.code,
        "PREGNANCY_T1D": PregnancyTargetStrategy.code,
        "PREGNANCY_T2D_GDM": PregnancyTargetStrategy.code,
    }

    def for_profile(self, profile: TargetProfile) -> GlycemicTargetStrategy:
        """The strategy of ``profile.population``; an unknown one is an error."""
        code = self.POPULATION_STRATEGY.get(profile.population)
        for strategy in self.STRATEGIES:
            if strategy.code == code:
                return strategy
        raise InsumapError(ErrorCode.INTERNAL_ERROR)
