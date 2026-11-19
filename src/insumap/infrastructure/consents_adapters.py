"""The adapters of the consent and privacy routes, built over the session holder.

``Container`` builds them with ``build_consents_adapters``. Tests pass their own
doubles through ``Container(consents_adapters=...)``.
"""

from __future__ import annotations

from dataclasses import dataclass

from insumap.application.access.ports import DataAccessLogPort
from insumap.application.common.unit_of_work import TransactionFactory
from insumap.application.consents.ports import (
    ConsentHistoryPort,
    PrivacyNoticeQueryPort,
    PrivacyRequestPort,
)
from insumap.infrastructure.access.sql_data_access_log import SqlDataAccessLog
from insumap.infrastructure.persistence.consent_repositories import (
    ConsentHistoryRepository,
    PrivacyNoticeQueryRepository,
    PrivacyRequestRepository,
)
from insumap.infrastructure.persistence.transactions import CurrentSession


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsentsAdapters:
    """Ports of the consent history, the public notice and privacy requests."""

    history: ConsentHistoryPort
    notices: PrivacyNoticeQueryPort
    requests: PrivacyRequestPort
    access_log: DataAccessLogPort


def build_consents_adapters(
    *, current: CurrentSession, transactions: TransactionFactory
) -> ConsentsAdapters:
    """Production adapters: PostgreSQL, scoped by the row level security context."""
    return ConsentsAdapters(
        history=ConsentHistoryRepository(current),
        notices=PrivacyNoticeQueryRepository(current),
        requests=PrivacyRequestRepository(current),
        access_log=SqlDataAccessLog(current, transactions),
    )
