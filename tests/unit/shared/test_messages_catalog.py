import pytest

from insumap.shared.errors import ErrorCode
from insumap.shared.i18n import MessageCatalog, MessageRenderError, MissingMessageError


@pytest.fixture(scope="module")
def spanish() -> MessageCatalog:
    return MessageCatalog.load_spanish()


def test_spanish_catalog_loads_with_accents_intact(spanish: MessageCatalog) -> None:
    assert spanish.message_keys()
    assert "válidos" in spanish.render("validation.error")


def test_every_spanish_message_renders_with_its_placeholders(
    spanish: MessageCatalog,
) -> None:
    for key in spanish.message_keys():
        params = {name: "x" for name in spanish.placeholders(key)}

        assert spanish.render(key, **params).strip()


def test_render_fills_named_placeholders() -> None:
    catalog = MessageCatalog({"glucose.out_of_range": "El valor {value} mg/dL no."})

    assert catalog.render("glucose.out_of_range", value=612) == "El valor 612 mg/dL no."
    assert catalog.placeholders("glucose.out_of_range") == {"value"}


def test_render_ignores_parameters_the_text_does_not_use() -> None:
    catalog = MessageCatalog({"conflict": "Hay un conflicto."})

    assert catalog.render("conflict", extra="ignored") == "Hay un conflicto."


def test_missing_key_raises() -> None:
    catalog = MessageCatalog({"conflict": "Hay un conflicto."})

    assert "unknown.key" not in catalog
    with pytest.raises(MissingMessageError):
        catalog.render("unknown.key")


def test_missing_parameter_raises() -> None:
    catalog = MessageCatalog({"glucose.out_of_range": "El valor {value} no."})

    with pytest.raises(MessageRenderError, match="value"):
        catalog.render("glucose.out_of_range")


@pytest.mark.parametrize(
    "key", ["Glucose.out_of_range", "glucose out", "glucose..range", "", ".glucose"]
)
def test_rejects_malformed_keys(key: str) -> None:
    with pytest.raises(ValueError, match="Invalid message key"):
        MessageCatalog({key: "Texto."})


@pytest.mark.parametrize(
    "text", ["Hola {}.", "Hola {0}.", "Hola {user.name}.", "Hola {user[0]}."]
)
def test_rejects_positional_or_traversing_placeholders(text: str) -> None:
    with pytest.raises(ValueError, match="unsupported placeholder"):
        MessageCatalog({"greeting": text})


def test_rejects_non_string_texts() -> None:
    with pytest.raises(TypeError):
        MessageCatalog({"greeting": 42})  # type: ignore[dict-item]


def test_every_error_code_has_its_default_message(spanish: MessageCatalog) -> None:
    missing = [
        code.default_message_key
        for code in ErrorCode
        if code.default_message_key not in spanish
    ]

    assert missing == []


def test_default_error_messages_need_no_parameters(spanish: MessageCatalog) -> None:
    for code in ErrorCode:
        assert spanish.placeholders(code.default_message_key) == frozenset()
