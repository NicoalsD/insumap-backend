import base64

import pytest

from insumap.shared.key_material import decode_key, key_fingerprint

KEY = bytes(range(32))


def test_decodes_standard_and_url_safe_base64() -> None:
    standard = base64.b64encode(KEY).decode()
    url_safe = base64.urlsafe_b64encode(KEY).decode().rstrip("=")

    assert decode_key(standard) == KEY
    assert decode_key(url_safe) == KEY


@pytest.mark.parametrize(
    "value", ["not base64!!", base64.b64encode(b"x" * 16).decode()]
)
def test_rejects_other_lengths_and_alphabets_without_echoing(value: str) -> None:
    with pytest.raises(ValueError) as caught:
        decode_key(value)

    assert value not in str(caught.value)


def test_fingerprint_identifies_the_key_without_revealing_it() -> None:
    fingerprint = key_fingerprint(KEY)

    assert len(fingerprint) == 16
    assert fingerprint == key_fingerprint(KEY)
    assert fingerprint != key_fingerprint(bytes(reversed(KEY)))
    assert KEY.hex() not in fingerprint
