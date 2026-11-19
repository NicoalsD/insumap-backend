"""A Web Push endpoint is untrusted: https, an allowed push service, no IP literal."""

import hashlib

import pytest

from insumap.domain.notifications.errors import PushEndpointRejectedError
from insumap.domain.notifications.push import PushEndpoint
from insumap.shared.field_limits import FieldLimits

ALLOWED = ("fcm.googleapis.com", "*.notify.windows.com")
GOOGLE = "https://fcm.googleapis.com/fcm/send/abc123"


def test_an_https_endpoint_of_an_allowed_host_is_accepted() -> None:
    endpoint = PushEndpoint.parse(GOOGLE, allowed_hosts=ALLOWED)

    assert endpoint.host == "fcm.googleapis.com"
    assert endpoint.url == GOOGLE


def test_a_wildcard_matches_the_subdomains_and_not_the_bare_domain() -> None:
    sub = PushEndpoint.parse(
        "https://wns2-pn1.notify.windows.com/w/?token=x", allowed_hosts=ALLOWED
    )

    assert sub.host == "wns2-pn1.notify.windows.com"
    with pytest.raises(PushEndpointRejectedError):
        PushEndpoint.parse("https://notify.windows.com/w/", allowed_hosts=ALLOWED)


@pytest.mark.parametrize(
    "raw",
    [
        "http://fcm.googleapis.com/fcm/send/abc",
        "ftp://fcm.googleapis.com/abc",
        "https://evil.example.test/abc",
        "https://fcm.googleapis.com.evil.example.test/abc",
        "https://10.0.0.5/abc",
        "https://[::1]/abc",
        "https://user:pass@fcm.googleapis.com/abc",
        "https:///abc",
        "not a url",
    ],
)
def test_an_endpoint_outside_the_rules_is_rejected(raw: str) -> None:
    with pytest.raises(PushEndpointRejectedError) as error:
        PushEndpoint.parse(raw, allowed_hosts=ALLOWED)

    assert error.value.detail == {
        "errors": [{"field": "body.endpoint", "type": "endpoint_rejected"}]
    }


def test_an_endpoint_longer_than_the_limit_is_rejected() -> None:
    raw = "https://fcm.googleapis.com/" + "a" * FieldLimits.PUSH_ENDPOINT_MAX_LENGTH

    with pytest.raises(PushEndpointRejectedError):
        PushEndpoint.parse(raw, allowed_hosts=ALLOWED)


def test_the_hash_is_the_sha256_of_the_url() -> None:
    endpoint = PushEndpoint.parse(GOOGLE, allowed_hosts=ALLOWED)

    assert endpoint.endpoint_hash == hashlib.sha256(GOOGLE.encode()).hexdigest()
