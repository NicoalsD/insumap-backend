"""Import commands: permission first, and only a previewed batch can be confirmed."""

from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import UUID

import pytest

from insumap.application.commands.transactional import CurrentUnitOfWork
from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWork
from insumap.application.onboarding.commands import (
    ConfirmImportCommand,
    ConfirmImportCommandHandler,
    PreviewImportCommand,
    PreviewImportCommandHandler,
)
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.common.events import DomainEvent
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.onboarding.vocabulary import SourceFormat
from insumap.infrastructure.integration.csv.pipeline import CsvPatientImportPipeline
from insumap.shared.field_limits import FieldLimits
from tests.support.identity_world import CLINIC
from tests.support.onboarding_fakes import FixedClock, OnboardingWorld, SequentialIds

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
ADMIN = UUID(int=520)


class _Unit(UnitOfWork):
    def apply_context(self, context: TransactionContext) -> None:
        del context

    def collect(self, events: Sequence[DomainEvent]) -> None:
        del events

    def commit(self) -> None:
        return None


def actor(*permissions: PermissionCode, demo: bool = False) -> Actor:
    return Actor(
        user_id=ADMIN,
        clinic_id=CLINIC.clinic_id,
        role=Role.CLINIC_ADMIN,
        permissions=frozenset(permissions),
        clinic_is_demo=demo,
        requires_mfa=True,
        mfa_verified=True,
    )


@pytest.fixture
def world() -> OnboardingWorld:
    return OnboardingWorld()


def handlers(
    world: OnboardingWorld,
) -> tuple[PreviewImportCommandHandler, ConfirmImportCommandHandler, CurrentUnitOfWork]:
    current = CurrentUnitOfWork()
    adapters = world.adapters()
    pipeline = CsvPatientImportPipeline(
        batches=adapters.batches,
        vault=adapters.vault,
        ids=SequentialIds(),
        clock=FixedClock(),
    )
    preview = PreviewImportCommandHandler(
        pipelines={SourceFormat.CSV: pipeline},
        staged=adapters.staged,
        current=current,
    )
    confirm = ConfirmImportCommandHandler(
        batches=adapters.batches,
        accounts=adapters.accounts,
        staged=adapters.staged,
        current=current,
        ids=SequentialIds(),
        clock=FixedClock(),
    )
    return preview, confirm, current


def run_in_transaction[T](current: CurrentUnitOfWork, action: Callable[[], T]) -> T:
    """Run a handler in a bound unit, then its after-commit actions."""
    with current.bind(_Unit()):
        result = action()
        current.run_after_commit()
    return result


def test_preview_needs_the_import_permission(world: OnboardingWorld) -> None:
    preview, _, current = handlers(world)
    command = PreviewImportCommand(
        actor=actor(), source_format=SourceFormat.CSV, content=b"mrn\n"
    )

    with pytest.raises(PermissionDeniedError):
        run_in_transaction(current, lambda: preview.handle(command))


def test_preview_stages_and_confirm_is_only_once(world: OnboardingWorld) -> None:
    preview, confirm, current = handlers(world)
    content = (FIXTURES / "pacientes_validos.csv").read_bytes()
    batch = run_in_transaction(
        current,
        lambda: preview.handle(
            PreviewImportCommand(
                actor=actor(PermissionCode.PATIENTS_IMPORT),
                source_format=SourceFormat.CSV,
                content=content,
            )
        ),
    )
    assert world.staged.entries  # staged after the commit

    done = run_in_transaction(
        current,
        lambda: confirm.handle(
            ConfirmImportCommand(
                actor=actor(PermissionCode.PATIENTS_IMPORT),
                batch_id=batch.batch_id,
            )
        ),
    )
    assert done.totals.created == 3
    assert not world.staged.entries

    with pytest.raises(InvalidStateTransitionError):
        run_in_transaction(
            current,
            lambda: confirm.handle(
                ConfirmImportCommand(
                    actor=actor(PermissionCode.PATIENTS_IMPORT),
                    batch_id=batch.batch_id,
                )
            ),
        )


def test_confirm_of_an_unknown_batch_is_not_found(world: OnboardingWorld) -> None:
    _, confirm, current = handlers(world)

    with pytest.raises(ResourceNotFoundError):
        run_in_transaction(
            current,
            lambda: confirm.handle(
                ConfirmImportCommand(
                    actor=actor(PermissionCode.PATIENTS_IMPORT), batch_id=UUID(int=9)
                )
            ),
        )


def test_the_upload_size_limit_is_the_csv_limit() -> None:
    assert FieldLimits.PATIENT_CSV_MAX_BYTES == 2 * 1024 * 1024
