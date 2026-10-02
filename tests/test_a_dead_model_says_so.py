# -*- coding: utf-8 -*-
"""A model outage must not read as a gap in the building's records (CAVEAT-1409).

MEASURED 2026-10-01. The host killed the local model server mid-measurement and did not bring
it back. Everything behaved correctly: the breaker tripped, the lanes fell back, and 14 of 60
tail-O answers came back as honest non-answers —

    "I wasn't able to generate an answer just now. Please try asking again in a moment."
    "Here are the readings themselves. The readings could not be summarised."

Every one of those sentences is true. None says WHY. The orchestrator logged
`circuit breaker is OPEN - the ollama provider has been unresponsive` **134 times** while the
reader was told nothing, and from the answer alone "the model is down" is indistinguishable from
"the building cannot answer that". Only the first is worth retrying, and the reader is the one
who decides.

It also cost the measurement: the first pass read 45.0% acceptable and the second, after
restarting the provider and re-asking those 14, read 60.0% — with no change to the system.
"""

import pytest

from orchestrator.services.circuit_breaker import (
    CircuitState,
    circuit_breaker_for,
    model_is_unavailable,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_llm_breaker():
    """Leave the shared registry as it was: this breaker is a process-wide singleton."""
    breaker = circuit_breaker_for("llm")
    before = breaker._state, breaker._failure_count, breaker._last_failure_time
    yield breaker
    breaker._state, breaker._failure_count, breaker._last_failure_time = before


class TestTheCheckReadsTheBreaker:
    def test_closed_means_available(self, _reset_llm_breaker):
        _reset_llm_breaker._state = CircuitState.CLOSED
        assert model_is_unavailable() is False

    def test_open_means_unavailable(self, _reset_llm_breaker):
        import time

        _reset_llm_breaker._state = CircuitState.OPEN
        _reset_llm_breaker._last_failure_time = time.monotonic()
        assert model_is_unavailable() is True

    def test_half_open_still_counts_as_unavailable(self, _reset_llm_breaker):
        """A probing breaker is not a working model; a reader should still be told to retry."""
        _reset_llm_breaker._state = CircuitState.HALF_OPEN
        assert model_is_unavailable() is True

    def test_it_never_raises(self, monkeypatch):
        """A fallback path must not fail while explaining a failure."""
        import orchestrator.services.circuit_breaker as cb

        monkeypatch.setattr(cb, "_breakers", None)  # the worst case: registry unusable
        assert model_is_unavailable() is False


class TestTheReaderIsTold:
    def test_the_fallback_distinguishes_the_two_causes(self):
        import inspect

        from orchestrator.workflow import _orchestrator

        src = inspect.getsource(_orchestrator)
        assert "model_is_unavailable" in src, (
            "the general-knowledge fallback no longer asks whether the MODEL is the problem; a "
            "provider outage will read as a gap in the building's records again"
        )
        assert "is not responding at the moment" in src
        assert "not a gap in the building's records" in src, (
            "the outage wording must say explicitly that the records are not the problem — that "
            "is the whole point of the distinction"
        )

    def test_the_ordinary_wording_is_still_there_for_the_other_case(self):
        """A question that simply cannot be answered must NOT blame the model."""
        import inspect

        from orchestrator.workflow import _orchestrator

        src = inspect.getsource(_orchestrator)
        assert "I wasn't able to generate an answer just now" in src
