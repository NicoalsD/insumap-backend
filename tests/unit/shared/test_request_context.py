from insumap.shared.request_context import (
    bind_request_id,
    current_request_id,
    unbind_request_id,
)


def test_no_request_id_outside_a_request() -> None:
    assert current_request_id() is None


def test_bind_and_unbind_restore_the_previous_id() -> None:
    outer = bind_request_id("outer")
    inner = bind_request_id("inner")

    assert current_request_id() == "inner"
    unbind_request_id(inner)
    assert current_request_id() == "outer"
    unbind_request_id(outer)
    assert current_request_id() is None
