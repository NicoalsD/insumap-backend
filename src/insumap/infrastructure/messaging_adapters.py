"""Adapters behind the messaging and follow-up ports, over the session holder."""

from __future__ import annotations

from dataclasses import dataclass

from insumap.application.access.ports import PatientDirectoryPort
from insumap.application.care_team.ports import CareTeamRepositoryPort
from insumap.application.follow_ups.ports import FollowUpRepositoryPort
from insumap.application.messaging.ports import (
    MessageThreadRepositoryPort,
    ThreadMessageRepositoryPort,
    ThreadReadRepositoryPort,
)
from insumap.infrastructure.persistence.care_team_repository import (
    CareTeamRepository,
    PatientDirectoryRepository,
)
from insumap.infrastructure.persistence.follow_up_repository import FollowUpRepository
from insumap.infrastructure.persistence.messaging_repositories import (
    MessageThreadRepository,
    ThreadMessageRepository,
    ThreadReadRepository,
)
from insumap.infrastructure.persistence.transactions import CurrentSession


@dataclass(frozen=True, slots=True, kw_only=True)
class MessagingAdapters:
    """Ports of the messaging and follow-up slice, wired by ``Container``.

    ``patients`` and ``care_teams`` only resolve who is on the other side of a
    notification; they run in the SYSTEM context after the commit. Tests pass
    their own doubles; production gets ``build_messaging_adapters``.
    """

    threads: MessageThreadRepositoryPort
    messages: ThreadMessageRepositoryPort
    read_marks: ThreadReadRepositoryPort
    follow_ups: FollowUpRepositoryPort
    patients: PatientDirectoryPort
    care_teams: CareTeamRepositoryPort


def build_messaging_adapters(*, current: CurrentSession) -> MessagingAdapters:
    """Build the production adapters over the session holder of the process."""
    return MessagingAdapters(
        threads=MessageThreadRepository(current),
        messages=ThreadMessageRepository(current),
        read_marks=ThreadReadRepository(current),
        follow_ups=FollowUpRepository(current),
        patients=PatientDirectoryRepository(current),
        care_teams=CareTeamRepository(current),
    )
