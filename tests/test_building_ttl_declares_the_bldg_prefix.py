# -*- coding: utf-8 -*-
"""A per-building TTL without `@prefix bldg:` crash-loops the orchestrator.

`assert_ttl_validation_or_die` runs in the FastAPI lifespan and hard-fails startup when a
building TTL omits the prefix. That is the right behaviour — a file whose terms cannot be
resolved against the building namespace should not be loaded silently — but it fires at
BOOT, which means the first evidence of the mistake is a container that will not start.

Measured: `input/bldg1_sensor_metrology.ttl` was generated with full IRIs in angle brackets
and only `ontosage:` and `xsd:` declared. The orchestrator restarted eight times before the
cause was read out of the log, and the stack was down for roughly fifteen minutes.

The validator was not wrong and does not need changing. What was missing is a check that
runs BEFORE a deploy rather than during one — a generated file is committed long before it
is booted, and that is the moment to catch it.

A second check follows from the same incident: the namespace must be the one the building
actually uses. The generator's first attempt derived
"http://abacwsbuilding.cardiff.ac.uk/" from "http://abacwsbuilding.cardiff.ac.uk/abacws#..."
because it preferred the shorter of the '#' and '/' splits. That file parsed cleanly, passed
the prefix check, and would have attached every triple to subjects the graph does not have.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent

PREFIX_RE = re.compile(r"@prefix\s+bldg:\s*<([^>]+)>", re.I)


#: Mirrors `ttl_validator`'s own exclusions. A building-AGNOSTIC TBox (Brick, REC, s223,
#: *_schema.ttl) legitimately has no `@prefix bldg:` and must not be judged here — copying
#: the validator's rule rather than inventing a second one keeps the two from diverging.
_SCHEMA_TOKENS = ("brick", "rec", "s223", "schema")


def _building_folders():
    """Folders the validator would actually load: the active input/, and parked buildings.

    NOT `bldg*` by glob. That also matches staging directories like `bldg2_source/`, whose
    files are never loaded by anything — an early version of this test failed on four of
    them and would have sent someone to fix files that are not part of any building.
    """
    folders = [REPO / "input"]
    folders += [
        d for d in sorted(REPO.glob("bldg[0-9]"))
        if d.is_dir() and (d / "building.yaml").exists()
    ]
    return [d for d in folders if d.is_dir()]


def _ttls_in(folder: Path):
    return [
        p for p in sorted(folder.glob("bldg[0-9]_*.ttl"))
        if not any(t in p.name.lower() for t in _SCHEMA_TOKENS)
    ]


def _building_ttls():
    out = []
    for folder in _building_folders():
        out.extend(_ttls_in(folder))
    return out


def test_there_are_building_ttls_to_check():
    """Guards the discovery: an empty list would make the parametrised tests vacuous."""
    assert _building_ttls(), (
        "no per-building TTL files found — the layout or the naming convention has changed "
        "and these checks would silently pass on nothing"
    )


@pytest.mark.parametrize("ttl", _building_ttls(), ids=lambda p: p.name)
def test_every_building_ttl_declares_the_bldg_prefix(ttl):
    text = ttl.read_text(encoding="utf-8", errors="replace")
    assert PREFIX_RE.search(text), (
        f"{ttl.name} does not declare @prefix bldg:. assert_ttl_validation_or_die will "
        f"hard-fail the orchestrator on boot, so the first sign of this is a container "
        f"that will not start."
    )


@pytest.mark.parametrize("ttl", _building_ttls(), ids=lambda p: p.name)
def test_the_declared_namespace_ends_in_a_separator(ttl):
    """A namespace that does not end in '#' or '/' concatenates into nonsense."""
    m = PREFIX_RE.search(ttl.read_text(encoding="utf-8", errors="replace"))
    if not m:
        pytest.skip("covered by the previous test")
    assert m.group(1).endswith(("#", "/")), (
        f"{ttl.name} declares bldg: as {m.group(1)!r}, which does not end in a separator"
    )


@pytest.mark.parametrize("folder", _building_folders(), ids=lambda p: p.name)
def test_one_building_declares_one_namespace(folder):
    """The failure the prefix check alone would not catch.

    A generated file can declare a well-formed prefix that is simply the WRONG namespace —
    "http://abacwsbuilding.cardiff.ac.uk/" instead of ".../abacws#" — and it will parse,
    pass every syntactic check, and attach its triples to subjects the graph has never
    heard of. Agreement between one building's own files is what catches that.

    Per FOLDER, not globally: three buildings have three namespaces by design, and a test
    that compared across them would fail on the system working correctly.
    """
    declared = {}
    for ttl in _ttls_in(folder):
        m = PREFIX_RE.search(ttl.read_text(encoding="utf-8", errors="replace"))
        if m:
            declared.setdefault(m.group(1), []).append(ttl.name)
    if len(declared) <= 1:
        return
    detail = {ns: sorted(names)[:4] for ns, names in declared.items()}
    pytest.fail(
        f"{folder.name} declares {len(declared)} different bldg: namespaces: {detail}. "
        f"Triples written against the wrong one attach to subjects that do not exist, "
        f"and nothing errors."
    )
