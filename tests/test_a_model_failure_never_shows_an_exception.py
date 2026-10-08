"""A failed model call is never answered with the exception's own text (DEV S045, 2026-10-08).

"I found relevant ontology data but had trouble interpreting it: ReadTimeout:" reached a reader.
The reply now says what happened in words, and why when the model is known to be down.
"""

from pathlib import Path

import pytest

from orchestrator.services import circuit_breaker as cb
from orchestrator.services.reader_text import MODEL_DOWN, model_failure_sentence

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
#: The provider-failure wordings the compound evaluation pre-registered against v1's code.
PRE_REGISTERED = (
    "couldn't summarise them against your question just now",
    "able to generate an answer just now",
    "The readings could not be summarised.",
    "language model this assistant uses is not responding",
    "language model that writes the summary is not responding",
)


@pytest.fixture(autouse=True)
def _reachable():
    cb.note_model_reachable()
    yield
    cb.note_model_reachable()


def test_the_reason_is_added_only_when_the_model_is_known_to_be_down():
    assert model_failure_sentence("Lead.") == "Lead."
    cb.note_model_unreachable(30)
    assert model_failure_sentence("Lead.") == "Lead." + MODEL_DOWN


def test_the_new_wording_is_not_one_the_evaluation_already_counts():
    text = model_failure_sentence("x") + MODEL_DOWN
    assert not any(marker in text for marker in PRE_REGISTERED)


@pytest.mark.parametrize(
    "path", ["orchestrator/agents/sparql_agent.py", "orchestrator/agents/semantic_ontology_agent.py"]
)
def test_no_reply_interpolates_the_exception(path):
    source = (REPO / path).read_text(encoding="utf-8")
    assert "had trouble interpreting it: {" not in source
