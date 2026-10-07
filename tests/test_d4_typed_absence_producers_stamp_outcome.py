"""D4 (trial readiness, 2026-10-07): every typed-absence producer stamps a typed outcome.

The tracker row asks that "a test derived from the source asserts every decline producer
stamps the field". This pins the part that CAN be stamped without guessing: a result whose
method is `typed_absence` is a turn that established a nothing, so it must carry a
`retrieval_outcome` whose value is one of the seven states.

It deliberately does NOT cover the generic decline producers (`_unanswered_response`, the
relevance gate's replacement). Their many failure reasons do not map onto one state, and
D4's own note says a guess there is the risk the module exists to prevent. This test fails
the moment a NEW typed-absence producer appears, so the author must decide its state.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from orchestrator.services.retrieval_outcome import RetrievalOutcome

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[1] / "orchestrator"
_TYPED = re.compile(r'"method":\s*"typed_absence"')
_STAMP = re.compile(r'"retrieval_outcome":\s*\{|"retrieval_outcome":\s*\(')

#: Producers known at 2026-10-07, each with the state it stamps. A new producer must be
#: added here WITH its state, which is the point of the test.
_KNOWN = {
    "orchestrator/agents/sparql_agent.py": 1,
    "orchestrator/services/sensor_binder.py": 1,
}


def _producer_sites() -> dict:
    found: dict = {}
    for path in _ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        hits = _TYPED.findall(text)
        if hits:
            rel = path.relative_to(_ROOT.parent).as_posix()
            found[rel] = len(hits)
    return found


def test_every_typed_absence_producer_is_known_and_stamps_an_outcome():
    sites = _producer_sites()
    assert sites == _KNOWN, (
        "A typed_absence producer was added or removed. Give it a retrieval_outcome at the "
        "point of production, then update _KNOWN. Found: " + repr(sites)
    )
    for rel in sites:
        text = (_ROOT.parent / rel).read_text(encoding="utf-8")
        for match in _TYPED.finditer(text):
            window = text[match.start() : match.start() + 1200]
            assert _STAMP.search(window), f"{rel}: typed_absence result without retrieval_outcome"


def test_the_sensor_binder_stamps_only_states_that_exist():
    stamped = {"reference_missing", "not_declared"}
    assert stamped <= {o.value for o in RetrievalOutcome}
    text = (_ROOT / "services" / "sensor_binder.py").read_text(encoding="utf-8")
    assert (
        '"reference_missing" if binding.reason == "reference_missing" else "not_declared"' in text
    )


def test_the_sparql_producer_stamps_the_classifier_output_not_a_literal():
    text = (_ROOT / "agents" / "sparql_agent.py").read_text(encoding="utf-8")
    assert '"outcome": outcome.outcome.value' in text
