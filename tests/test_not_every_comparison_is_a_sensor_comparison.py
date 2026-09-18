"""A comparison the building cannot measure is answered honestly (BUG-617).

"How do observed route lengths, waits and hand-offs compare with the design assumptions?" was
answered "comparing observed_route_lengths ... requires sensors with linked time-series data ...
give me zone IDs" — asking a stakeholder for a zone id about walking routes. The building has no
route-length sensor and never will; the honest answer names what it DOES measure and points at
the records, instead of demanding a sensor that cannot exist.
"""

import inspect
import re

import pytest

from orchestrator.workflow._orchestrator import WorkflowOrchestrator

pytestmark = pytest.mark.unit


def _compare_fallback_source() -> str:
    """The compare branch of the no-data fallback, as the file actually holds it."""
    source = inspect.getsource(WorkflowOrchestrator)
    start = source.index('elif _original_intent == "compare":')
    rest = source[start:]
    # The branch ends where the next sibling branch begins.
    end = rest.index("\n                else:")
    return rest[:end]


def test_the_fallback_no_longer_asks_for_zone_ids():
    body = _compare_fallback_source()
    # Only the comment recording the defect may still say it.
    code = "\n".join(l for l in body.split("\n") if not l.strip().startswith("#"))
    assert "zone IDs" not in code
    assert "zone ids" not in code.lower()


def test_it_says_there_is_no_measured_series():
    body = _compare_fallback_source()
    assert "no measured series" in body


def test_it_offers_what_the_building_does_measure():
    body = _compare_fallback_source()
    assert "What this building measures" in body
    # Derived from what the building MEASURES, never a written-in list — and never from the
    # DECLARED modality config either. This assertion used to require `load_modalities`, which
    # is the defect BUG-680/BUG-663 describe: a declared modality with zero points was offered
    # as measured. The branch now reads live point counts.
    assert "_measured_modality_counts" in body
    assert "load_modalities" not in body


def test_it_points_at_records_for_a_recorded_quantity():
    """A route time, a design duty and a booking are RECORDED, not measured. The fallback has
    to offer that door or the stakeholder is left believing the building knows nothing."""
    body = _compare_fallback_source()
    assert "RECORDED rather than measured" in body


def test_naming_the_modalities_cannot_break_the_answer():
    """The modality list is a nicety; a failure to load it must not cost the user the reply.

    The guarantee used to be a try/except written in this branch. It now lives in the helper the
    branch calls (BUG-680): `_measured_modality_counts` returns None rather than raising when the
    graph cannot be read, and `_measured_names(None)` is an empty list, so the sentence is simply
    omitted. Pinned as BEHAVIOUR, because a syntax check would pass on a helper that raises.
    """
    import asyncio

    from orchestrator.workflow import _orchestrator as orch

    body = _compare_fallback_source()
    assert "_measured_names(" in body and "if _measured" in body

    async def _graph_down(*_a, **_k):
        raise ConnectionError("graph unreachable")

    counts = asyncio.run(
        orch._measured_modality_counts(
            timeout_s=1.0,
            building_id="bldgX",
            namespace="http://example.org/unreachable#",
            sparql_exec=_graph_down,
            specs=[type("Spec", (), {"name": "co2", "brick_classes": ["CO2_Sensor"]})()],
        )
    )
    assert counts is None or all(v is None for v in counts.values())
    assert orch._measured_names(counts) == []
    assert orch._measured_names(None) == []


def test_the_building_is_not_named_in_the_message():
    """Building-agnostic: no building id, namespace or room literal in the text."""
    body = _compare_fallback_source()
    assert not re.search(r"bldg\d", body)
    assert "Abacws" not in body
