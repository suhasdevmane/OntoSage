# -*- coding: utf-8 -*-
"""A teaching room may not be called ready on somebody's recollection.

The rule this enforces is conditional and a record-document mapping cannot express it:

    no component may be recorded `ready` without an evidence reference and a check date.

It was first written as two REQUIRED columns, and the register then refused to load. The
row that broke it is the most important one in the file — Room 1.06's hearing loop, installed
in April and never tested, which is why approval APR-032 is conditional. A component that has
never been checked has no check date and no reference by definition, so a schema strict
enough to demand them is a schema that cannot state the finding it exists to surface.

`unevidenced` is a state for exactly that. The conditional rule lives here instead.
"""

import csv
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
MAPPING = REPO / "ontology" / "record_documents" / "av_readiness.yaml"


def _register_rows():
    """Rows of the AV register, from whichever building folder is present."""
    candidates = list(REPO.glob("*/documents/av_readiness_register.md"))
    if not candidates:
        pytest.skip("no building holds an av_readiness register in this checkout")
    lines = [
        ln.strip()
        for ln in candidates[0].read_text(encoding="utf-8").splitlines()
        if ln.strip().startswith("|")
    ]
    header = None
    out = []
    for ln in lines:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if header is None:
            if "component" in cells and "state" in cells:
                header = cells
            continue
        if set(cells) <= {"", "---"}:
            continue
        if len(cells) == len(header):
            out.append(dict(zip(header, cells)))
    return out


def test_the_register_has_rows():
    assert _register_rows(), "the AV register parsed to nothing"


def test_nothing_is_ready_without_evidence():
    """The load-bearing rule. A room withheld or released on a claim is the failure."""
    bad = [
        r["component"]
        for r in _register_rows()
        if r["state"].lower() in ("ready", "in service", "working")
        and (not r.get("evidence_ref") or not r.get("last_checked"))
    ]
    assert not bad, (
        f"these are recorded ready with no evidence reference or no check date: {bad}. "
        f"'Checked' without a record is a claim."
    )


def test_an_untested_component_can_still_be_recorded():
    """The case that broke the first draft: it must be expressible, not excluded."""
    rows = _register_rows()
    untested = [r for r in rows if not r.get("evidence_ref")]
    assert untested, (
        "no untested component is recorded at all — either the building genuinely has none, "
        "or the schema has become too strict to state one again"
    )
    for r in untested:
        assert r["state"].lower() in ("unevidenced", "not checked", "evidence missing"), (
            f"{r['component']} has no evidence and is not marked unevidenced; it would read "
            f"as a component somebody checked"
        )


def test_the_mapping_does_not_require_the_evidence_columns():
    """Pinned so a future tightening fails here rather than by silently dropping the file.

    The lift is all-or-nothing, so marking these required again does not lose one row — it
    loses the whole register, with one warning line in a container log.
    """
    import yaml

    columns = (yaml.safe_load(MAPPING.read_text(encoding="utf-8")) or {}).get("columns") or {}
    for name in ("last_checked", "evidence_ref"):
        assert not (columns.get(name) or {}).get("required"), (
            f"{name} is required again; an untested component has neither, so the register "
            f"will refuse to load entirely"
        )


def test_a_broken_audio_link_is_visible_as_such():
    """The chain property the register exists for: a dead microphone is not 'mostly ready'."""
    rows = _register_rows()
    audio = [r for r in rows if r.get("audio_path", "").lower() == "true"]
    assert audio, "no component is marked as part of the audio path"
    by_room = {}
    for r in audio:
        by_room.setdefault(r["room"], []).append(r["state"].lower())
    broken = {room for room, states in by_room.items() if any(s != "ready" for s in states)}
    assert broken, (
        "no room has a broken audio link, so this register cannot demonstrate the case it "
        "was built for"
    )


def test_every_component_names_a_room():
    for r in _register_rows():
        assert r.get("room"), f"{r.get('component')} has no room"
        assert re.search(r"[A-Za-z]", r["room"])
