"""Physical and unit constants with a name (never clinical targets)."""

from decimal import Decimal
from typing import Final

MG_DL_PER_MMOL_L: Final = Decimal("18.0156")
"""mg/dL per mmol/L of glucose (Metricas-clinicas 2.1)."""

GMI_INTERCEPT: Final = Decimal("3.31")
GMI_SLOPE_PER_MG_DL: Final = Decimal("0.02392")
"""GMI (%) = intercept + slope x mean glucose in mg/dL (Bergenstal et al. 2018)."""

NGSP_PERCENT_PER_IFCC: Final = Decimal("0.09148")
NGSP_PERCENT_INTERCEPT: Final = Decimal("2.152")
"""IFCC-NGSP master equation: NGSP (%) = 0.09148 x IFCC (mmol/mol) + 2.152."""

SECONDS_PER_MINUTE: Final = 60
MINUTES_PER_HOUR: Final = 60
HOURS_PER_DAY: Final = 24
MINUTES_PER_DAY: Final = MINUTES_PER_HOUR * HOURS_PER_DAY
PERCENT: Final = Decimal(100)
