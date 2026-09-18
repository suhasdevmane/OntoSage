"""A superlative is a lay term too (BUG-640).

"Which rooms in the building are the stuffiest right now?" reached the ranking lane and then
failed to compile — *"I couldn't map part of your request (stuffiest)"* — while the same
question with "stuffy" compiled cleanly to co2. People ask for the extreme far more often than
the plain adjective, and listing every inflection of every lay term in the hint table is a
losing game: the reduction belongs in code.
"""

import importlib.util
import sys

import pytest

pytestmark = pytest.mark.unit


def _compiler():
    spec = importlib.util.spec_from_file_location(
        "_cmp_mod", "orchestrator/services/deliberation/compiler.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_cmp_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    "word,modality",
    [
        ("stuffiest", "co2"),
        ("stuffier", "co2"),
        ("stuffy", "co2"),
        ("noisiest", "noise"),
        ("quietest", "noise"),
        ("warmest", "temperature"),
        ("coolest", "temperature"),
        ("busiest", "occupancy"),
        ("emptiest", "occupancy"),
        ("brightest", "illuminance"),
        ("darkest", "illuminance"),
        ("dampest", "humidity"),
        ("driest", "humidity"),
    ],
)
def test_an_inflected_lay_term_resolves_to_its_modality(word, modality):
    assert _compiler()._modality_from_lay_term(word) == modality


@pytest.mark.parametrize("word", ["printer", "corridor", "handover", "", "the"])
def test_a_word_that_is_not_a_lay_term_resolves_to_nothing(word):
    """The fallback must not invent a modality — that would answer about a quantity nobody
    asked for, which is worse than declining."""
    assert _compiler()._modality_from_lay_term(word) is None


def test_the_stem_must_survive_with_two_letters():
    """"driest" -> "dry" is a word; a bound of len(suffix)+2 dropped exactly that case."""
    mod = _compiler()
    assert mod._base_form("driest") == "dry"
    assert mod._base_form("est") == "est"


def test_the_fallback_only_accepts_a_modality_this_building_has():
    """Translating an unknown word is not a guess ONLY because the result is checked against
    the building's own modality set before it is used."""
    import inspect

    source = inspect.getsource(_compiler()._parse_compiled)
    assert "_modality_from_lay_term" in source
    assert "in known" in source
