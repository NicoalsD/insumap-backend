"""The alarm words of a message: normalization, whole words and phrases (RF-85)."""

import pytest

from insumap.domain.messaging.alarm_keywords import ALARM_KEYWORDS, AlarmKeywordDetector


@pytest.fixture
def detector() -> AlarmKeywordDetector:
    return AlarmKeywordDetector()


@pytest.mark.parametrize(
    "text",
    [
        "Tuve una convulsión esta noche",
        "TUVE UNA CONVULSIÓN ESTA NOCHE",
        "tuve una convulsion esta noche",
        "tuve una ｃｏｎｖｕｌｓｉóｎ",  # full width letters, NFKC folds them
        "Tuve una convulsión, y luego me dormí.",
        "Me dio dificultad   para\trespirar",
        "Perdí la pérdida de conocimiento",
    ],
)
def test_detects_a_keyword_whatever_the_case_accent_spacing_or_punctuation(
    detector: AlarmKeywordDetector, text: str
) -> None:
    assert detector.detect(text)


def test_accents_are_optional_on_both_sides(detector: AlarmKeywordDetector) -> None:
    assert detector.detect("tuve confusion al despertar") == ("confusión",)
    assert detector.detect("tuve confusión al despertar") == ("confusión",)


def test_a_phrase_must_appear_as_consecutive_words(
    detector: AlarmKeywordDetector,
) -> None:
    assert detector.detect("dificultad para respirar") == ("dificultad para respirar",)
    assert detector.detect("dificultad grande para respirar") == ()
    assert detector.detect("respirar con dificultad") == ()


@pytest.mark.parametrize(
    "text",
    [
        "Me dio confusionada la receta",  # "confusionada" is not "confusión"
        "Me pesa el desmayado del grupo",  # longer word, not "desmayo"
        "Comí precocinetas en la cena",  # "cetonas" inside a longer word
        "Un cetonasxx de prueba",  # letters glued to the keyword
    ],
)
def test_no_false_positives_inside_other_words(
    detector: AlarmKeywordDetector, text: str
) -> None:
    assert detector.detect(text) == ()


def test_each_keyword_is_reported_once_in_list_order(
    detector: AlarmKeywordDetector,
) -> None:
    detected = detector.detect(
        "convulsión, otra convulsión y luego cetonas y confusión"
    )

    assert detected == ("confusión", "convulsión", "cetonas")


def test_a_message_without_alarm_words_has_none(detector: AlarmKeywordDetector) -> None:
    assert detector.detect("Hoy me sentí bien y comí poco") == ()
    assert detector.detect("") == ()


def test_keywords_are_normalized_so_they_can_be_written_with_accents() -> None:
    detector = AlarmKeywordDetector(keywords=("Pérdida de Conocimiento",))

    assert detector.detect("hubo pérdida de conocimiento") == (
        "Pérdida de Conocimiento",
    )


def test_the_catalog_words_are_all_detectable_on_their_own() -> None:
    detector = AlarmKeywordDetector()

    for keyword in ALARM_KEYWORDS:
        assert detector.detect(f"Mi mensaje: {keyword}.") == (keyword,)


def test_an_empty_keyword_is_refused() -> None:
    with pytest.raises(ValueError):
        AlarmKeywordDetector(keywords=("  ",))
