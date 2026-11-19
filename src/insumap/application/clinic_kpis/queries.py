"""``GET /clinic-kpis``: aggregates for the clinic administrator, no clinical detail."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import final

from insumap.application.alerts.ports import AlertSummaryPort
from insumap.application.clinic_kpis.ports import ClinicKpiPort
from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.domain.common.rounding import round_half_up
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.permissions import PermissionCode

PERCENT_PLACES = 2
HUNDRED_PERCENT = Decimal(100)


@dataclass(frozen=True, slots=True, kw_only=True)
class ClinicKpis:
    """Counts below the clinic's minimum cell size are ``None`` (not shown)."""

    total_patients: int | None
    patients_by_status: dict[str, int | None]
    activation_rate_pct: Decimal | None
    open_alerts: int | None
    escalated_alerts: int | None


@final
class GetClinicKpisUseCase:
    """Patients per account status, activation rate and open alerts of the clinic.

    The status counts come from the patient roster under RLS; the alert counts
    come from ``alerts.clinic_alert_summary()``, a definer function, because the
    administrator cannot read ``alerts.alerts`` (V8). Adherence is not computed:
    the administrator cannot read the glucose readings (see the report).
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        kpis: ClinicKpiPort,
        alerts: AlertSummaryPort,
    ) -> None:
        self._uow = uow
        self._kpis = kpis
        self._alerts = alerts

    def execute(self, actor: Actor) -> ClinicKpis:
        actor.require(PermissionCode.CLINIC_KPIS_READ)
        with self._uow.begin(TransactionContext.for_actor(actor)):
            counts = dict(self._kpis.patient_status_counts())
            minimum = self._kpis.min_cell_size()
            summary = self._alerts.summary()

        def shown(value: int) -> int | None:
            # Zero discloses nothing about a cell, so it is always shown.
            return value if value == 0 or value >= minimum else None

        total = sum(counts.values())
        active = counts.get(AccountStatus.ACTIVE.value, 0)
        rate = (
            None
            if total == 0 or shown(active) is None
            else round_half_up(
                Decimal(active) * HUNDRED_PERCENT / Decimal(total), PERCENT_PLACES
            )
        )
        return ClinicKpis(
            total_patients=shown(total),
            patients_by_status={
                status.value: shown(counts.get(status.value, 0))
                for status in AccountStatus
            },
            activation_rate_pct=rate,
            open_alerts=shown(summary.open_count),
            escalated_alerts=shown(summary.escalated_count),
        )
