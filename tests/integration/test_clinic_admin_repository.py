"""The database errors of ``iam.create_first_clinic_admin`` map to business errors."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest

from insumap.application.clinic_admins.ports import NewClinicAdmin
from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import (
    TransactionalUnitOfWorkPort,
    TransactionContext,
)
from insumap.application.events.publisher import InProcessDomainEventPublisher
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.infrastructure.identity_adapters import build_engine
from insumap.infrastructure.persistence.clinic_admin_repository import (
    ClinicAdminProvisioningRepository,
)
from insumap.infrastructure.persistence.transactions import (
    CurrentSession,
    SqlTransactionFactory,
)
from tests.support.db_seed import DemoWorld
from tests.support.settings import make_settings

pytestmark = pytest.mark.integration

HASH = "a" * 64
KEY_ID = "k" * 16


def _admin(clinic_id: UUID) -> NewClinicAdmin:
    return NewClinicAdmin(
        clinic_id=clinic_id,
        email="probe@example.test",
        full_name="Sonda de prueba",
        code_hash=HASH,
        code_key_id=KEY_ID,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )


def _platform() -> Actor:
    return Actor(
        user_id=uuid4(),
        clinic_id=None,
        role=Role.PLATFORM_ADMIN,
        permissions=frozenset({PermissionCode.CLINIC_ADMINS_MANAGE}),
    )


def _session(app_url: str) -> tuple[TransactionalUnitOfWorkPort, CurrentSession]:
    current = CurrentSession()
    engine = build_engine(make_settings(database_url=app_url))
    uow = TransactionalUnitOfWorkPort(
        SqlTransactionFactory(engine, current), InProcessDomainEventPublisher()
    )
    return uow, current


def test_a_missing_clinic_is_not_found(app_url: str, demo_world: DemoWorld) -> None:
    uow, current = _session(app_url)
    repository = ClinicAdminProvisioningRepository(current)

    with (
        uow.begin(TransactionContext.for_actor(_platform())),
        pytest.raises(ResourceNotFoundError),
    ):
        repository.create_first_admin(_admin(uuid4()))


def test_a_clinic_that_is_not_active_is_an_invalid_state(
    app_url: str, migrated_url: str, demo_world: DemoWorld
) -> None:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE clinic.clinics SET status = 'SUSPENDED',"
            " suspended_at = now(), suspended_reason = 'Revisión de prueba'"
            " WHERE id = %s",
            (demo_world.clinic_id,),
        )
    uow, current = _session(app_url)
    repository = ClinicAdminProvisioningRepository(current)

    with (
        uow.begin(TransactionContext.for_actor(_platform())),
        pytest.raises(InvalidStateTransitionError),
    ):
        repository.create_first_admin(_admin(demo_world.clinic_id))
