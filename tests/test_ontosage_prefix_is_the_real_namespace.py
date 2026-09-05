# -*- coding: utf-8 -*-
"""A SPARQL prefix that points at nothing fails silently, forever (BUG-428).

`orchestrator/services/evidence/spatial_facts.py` declared:

    PREFIX ontosage: <http://ontosage.org/schema#>

The ontology's term namespace is `<http://ontosage.org/capabilities#>` and always has been.
Measured on the live bldg1 graph: the declared IRI matches **0** triples; the real one
matches **37,207**.

Five queries in that module use the prefix — `environmentalBoundary`, `zoneValidated`,
`archivalIntervalS`, `calibratedOn`, `calibrationDueOn` — so every one of them had returned
nothing since it was written. Nothing errored, because an OPTIONAL that never binds and a
VALUES join that never matches are both perfectly valid SPARQL returning an empty result.

**The consequence was attributed to the wrong cause.** BUG-237 recorded the completeness and
calibration gates as unwirable "because each judges a field nothing populates". That was
true of the data — no sensor declared an archival interval. But the graph could have been
full of them and these queries would still have come back empty. Populating the data alone
would have fixed nothing and looked like the data was wrong: two independent causes for one
symptom, the same shape as BUG-403, where fixing the writer made freshness worse because two
errors had been cancelling.

Two scripts carried the same typo. `propose_archival_intervals.py` is the worse of them: it
WRITES the intervals the completeness gate reads, so its output would have loaded cleanly
and been invisible to the gate it exists to feed.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
REAL = "http://ontosage.org/capabilities#"
WRONG = "http://ontosage.org/schema#"

SEARCH_ROOTS = ("orchestrator", "shared", "scripts")


def _python_files():
    out = []
    for root in SEARCH_ROOTS:
        out.extend(sorted((REPO / root).rglob("*.py")))
    return [p for p in out if "test" not in p.name]


def test_the_schema_declares_the_namespace_this_test_asserts():
    """Guards the constant: if the ontology's namespace ever changes, fail here first."""
    schema = (REPO / "ontology" / "ontosage_schema.ttl").read_text(encoding="utf-8")
    assert REAL in schema, (
        f"the ontology no longer declares {REAL}; update this test before updating the code"
    )


def test_no_module_declares_the_namespace_that_matches_nothing():
    offenders = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            if WRONG not in line:
                continue
            # The explanatory comments in the fix itself name the wrong IRI on purpose.
            if line.lstrip().startswith("#"):
                continue
            offenders.append(f"{path.relative_to(REPO)}:{line_no}")
    assert not offenders, (
        f"these declare {WRONG}, which matches nothing: {offenders}. A prefix that resolves "
        f"to an unused namespace produces valid SPARQL and an empty result, so the failure "
        f"is invisible for as long as nobody checks the data by hand."
    )


def test_the_evidence_fetches_use_the_real_namespace():
    """Named explicitly because these five are what the gates depend on."""
    src = (REPO / "orchestrator" / "services" / "evidence" / "spatial_facts.py").read_text(
        encoding="utf-8"
    )
    m = re.search(r"PREFIX ontosage: <([^>]+)>", src)
    assert m, "spatial_facts no longer declares an ontosage prefix"
    assert m.group(1) == REAL, (
        f"spatial_facts declares {m.group(1)!r}; the completeness and calibration gates read "
        f"their inputs through it and would silently see nothing"
    )
    for term in (
        "archivalIntervalS",
        "calibratedOn",
        "calibrationDueOn",
        "zoneValidated",
        "environmentalBoundary",
    ):
        assert term in src, f"{term} is no longer queried; update this list deliberately"
