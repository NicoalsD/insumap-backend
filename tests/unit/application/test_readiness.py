import pytest

from insumap.application.readiness import (
    AlwaysReadyProbe,
    CheckReadinessUseCase,
    ReadinessProbe,
)


class StubProbe:
    def __init__(self, ready: bool) -> None:
        self.ready = ready
        self.calls = 0

    def is_ready(self) -> bool:
        self.calls += 1
        return self.ready


def test_always_ready_probe_is_ready() -> None:
    probe: ReadinessProbe = AlwaysReadyProbe()

    assert probe.is_ready() is True


@pytest.mark.parametrize("ready", [True, False])
def test_use_case_answers_what_the_probe_says(ready: bool) -> None:
    probe = StubProbe(ready)

    assert CheckReadinessUseCase(probe).execute() is ready
    assert probe.calls == 1
