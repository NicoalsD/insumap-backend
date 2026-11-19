"""UUIDv7 identifiers, time ordered, from the injected ``Clock``."""

from __future__ import annotations

import secrets
import uuid
from typing import Final, final, override

from insumap.application.common.ids import IdGenerator
from insumap.shared.time import Clock

MILLISECONDS: Final = 1000
VERSION_7: Final = 0x7
RANDOM_A_BITS: Final = 12
RANDOM_B_BITS: Final = 62
TIMESTAMP_SHIFT: Final = 80
VERSION_SHIFT: Final = 76
VARIANT_SHIFT: Final = 62
RANDOM_A_SHIFT: Final = 64
VARIANT_RFC_4122: Final = 0b10


@final
class Uuid7Generator(IdGenerator):
    """RFC 9562 UUIDv7: 48 bit millisecond timestamp plus 74 random bits."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    @override
    def new_id(self) -> uuid.UUID:
        millis = int(self._clock.now().timestamp() * MILLISECONDS)
        random_a = secrets.randbits(RANDOM_A_BITS)
        random_b = secrets.randbits(RANDOM_B_BITS)
        value = (
            (millis << TIMESTAMP_SHIFT)
            | (VERSION_7 << VERSION_SHIFT)
            | (random_a << RANDOM_A_SHIFT)
            | (VARIANT_RFC_4122 << VARIANT_SHIFT)
            | random_b
        )
        return uuid.UUID(int=value)
