"""P05 Prototype: a new version is a copy of the active one, never a shared object."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from insumap.domain.metrics.target_profile_version import ACTIVE
from tests.unit.domain.metrics.test_target_profile_version import ACTOR, NOW, version

NEW_ID = UUID(int=50)


def test_copy_is_a_new_object_and_the_original_is_untouched() -> None:
    original = version()

    copy = original.copy_for_new_version(
        new_id=NEW_ID,
        changes={"cv_max_pct": Decimal("33.00")},
        by=ACTOR,
        change_reason="Ajuste de variabilidad aprobado",
        at=NOW,
    )

    assert copy is not original
    assert copy.values is not original.values
    assert original.values.cv_max_pct == Decimal("36.00")
    assert original.version == 1
    assert original.status == ACTIVE


def test_copy_without_changes_is_equal_except_identity_and_number() -> None:
    later = datetime(2026, 12, 1, tzinfo=UTC)
    original = version()

    copy = original.copy_for_new_version(
        new_id=NEW_ID,
        changes={},
        by=ACTOR,
        change_reason="Versión idéntica, solo para la prueba",
        at=later,
    )

    assert copy.values == original.values
    assert copy.id != original.id
    assert copy.version == original.version + 1
    assert copy.activated_at == later
