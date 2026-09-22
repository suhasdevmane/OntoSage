"""No record declares where its data came from, and nothing reads such a declaration.

DECISION 2026-09-22 (D1). The building's 680 installed sensors report real readings and the rest of
the estate is modelled on them. That is disclosed once, in the paper, not carried on every record
and not hedged into every answer — so `ontosage:isSimulated` is gone from the graph, from the
schema and from every code path that read it. A reading is a reading; a record is a record.

This replaces a family of tests that asserted the OPPOSITE contract — that every generated point,
every lifted document row and every authored subject declared itself simulated. Those tests were
right about the old design and are wrong about this one; deleting them silently would leave nothing
watching, so the guard is inverted rather than removed.

WHAT STAYS. Honest declines are untouched and are the core of the design: a quantity the building
does not measure, a record that does not exist, a referent not in the graph, a question about a
person. Those are about ABSENCE, not authenticity. Removing the flag creates no new answer — it
stops hedging the answers that already existed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent

#: The declaration, as a PREDICATE. A comment or a docstring explaining the history is fine and is
#: deliberately not matched: what must not come back is the triple and the code that reads it.
#:
#: BOTH LAYOUTS. An earlier version anchored on the predicate starting a line, which is how it is
#: written in a multi-predicate block. It therefore missed `bldg1_measured_origin.ttl` entirely --
#: 685 subjects declaring their origin on ONE line each, `bldg:X ontosage:isSimulated "false" .` --
#: and that file survived the strip, stayed in the graph, and the guard passed. A pattern that only
#: matches the formatting you happened to look at is not a guard.
_PREDICATE = re.compile(r"(?:^|\s)(?:\w+:)?isSimulated\s+[\"'\w]", re.MULTILINE)

#: Where a building's own TTL lives, parked or active.
_BUILDING_DIRS = [p for p in (REPO.glob("bldg[0-9]*")) if p.is_dir()] + [
    p for p in (REPO / "input",) if p.is_dir()
]


def _ttl_files():
    for d in _BUILDING_DIRS:
        for f in sorted(d.glob("*.ttl")):
            if f.name.lower().startswith("brick"):
                continue          # the upstream vocabulary is not ours to edit
            yield f


def _triples_only(text: str) -> str:
    """The TTL with its comments removed.

    Comments explaining why the flag went are welcome and must not trip the guard; the looser
    pattern above matches them, so they come off first. A `#` inside a quoted literal is not a
    comment, which is why the split is not naive.
    """
    out = []
    for line in text.splitlines():
        quoted = False
        for i, ch in enumerate(line):
            if ch == '"':
                quoted = not quoted
            elif ch == "#" and not quoted:
                line = line[:i]
                break
        out.append(line)
    return "\n".join(out)


def test_no_shipped_building_declares_an_origin_on_any_record():
    offenders = []
    for f in _ttl_files():
        text = _triples_only(f.read_text(encoding="utf-8", errors="replace"))
        if _PREDICATE.search(text):
            offenders.append(str(f.relative_to(REPO)))
    assert not offenders, (
        "these TTL files declare ontosage:isSimulated again: "
        + ", ".join(offenders)
        + ". Every record is the building's own; where its data came from is stated once in the "
        "paper. Re-run scripts/strip_simulated_flag.py --dir <building>."
    )


def test_the_schema_no_longer_declares_the_property():
    schema = (REPO / "ontology" / "ontosage_schema.ttl").read_text(encoding="utf-8")
    assert "ontosage:isSimulated a owl:" not in schema


def test_no_generator_writes_the_flag():
    """The three writers: the sensor provisioner, the amenity provisioner, the document lifter."""
    offenders = []
    for rel in (
        "orchestrator/services/deliberation/saturation.py",
        "orchestrator/services/deliberation/amenities.py",
        "orchestrator/services/record_documents.py",
    ):
        src = (REPO / rel).read_text(encoding="utf-8")
        # A mention inside a comment or docstring is history; an emitted triple is not.
        for line in src.splitlines():
            bare = line.strip()
            if bare.startswith("#") or not bare:
                continue
            if "isSimulated" in bare and ('"' in bare or "'" in bare) and "ONTOSAGE +" not in bare:
                if "ontosage:isSimulated" in bare:
                    offenders.append(f"{rel}: {bare[:80]}")
            elif 'ONTOSAGE + "isSimulated"' in bare:
                offenders.append(f"{rel}: {bare[:80]}")
    assert not offenders, "a generator writes the origin flag again: " + "; ".join(offenders)


def test_no_lane_ranks_or_filters_by_origin():
    """The readers that used to let origin change an ANSWER, not just be carried along."""
    offenders = []
    for rel in (
        "orchestrator/services/amenity_proximity.py",
        "orchestrator/services/capability_graph_resolver.py",
        "orchestrator/services/sensor_binder.py",
    ):
        src = (REPO / rel).read_text(encoding="utf-8")
        for line in src.splitlines():
            bare = line.strip()
            if bare.startswith("#") or bare.startswith('"""') or not bare:
                continue
            if "isSimulated" in bare or re.search(r"\bplaceholder\b\s*[:=]", bare):
                offenders.append(f"{rel}: {bare[:80]}")
    assert not offenders, (
        "a lane reads the origin flag again: " + "; ".join(offenders)
    )
