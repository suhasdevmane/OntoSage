# -*- coding: utf-8 -*-
"""A register that names a room the building lacks fabricates through the data.

The referent-existence gate stops the MODEL inventing a place. It cannot stop a REGISTER
from doing it: a lifted record is graph data, so a workspace profile for "Room 6.02" would
be an authoritative-looking triple about a room that does not exist, and an answer built on
it would pass every honesty check the pipeline has. BUG-189 is the same failure arriving
from the other direction — there, a room's reading was attributed to a corridor the building
does not have.

This checks the room-naming columns of every register against the labels the building's own
TTL declares.

Deliberately offline. The live graph would be a stronger check but would make this an
integration test, and the failure it guards is committed in a markdown file — the moment to
catch it is before the register is ever lifted.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent

#: Columns that are supposed to name a physical space. Other free-text columns may mention
#: rooms in prose and are not checked — a note saying "see also the plant room" is not a
#: referent claim.
ROOM_COLUMNS = {"room", "location", "space"}


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", text.lower())


def _declared_labels() -> set:
    """Every rdfs:label in the active building's TTL, normalised."""
    labels = set()
    for ttl in REPO.glob("*/*.ttl"):
        try:
            text = ttl.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r'rdfs:label\s+"([^"]+)"', text):
            labels.add(_normalise(m.group(1)))
    return labels


def _tables(doc: Path):
    """(header, rows) for each markdown table in the document."""
    lines = [ln.strip() for ln in doc.read_text(encoding="utf-8").splitlines()
             if ln.strip().startswith("|")]
    out, header = [], None
    rows = []
    for i, ln in enumerate(lines):
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if set(ln.replace("|", "").replace(" ", "")) <= set("-:") and "-" in ln:
            if i and header is None:
                header = [c.strip() for c in lines[i - 1].strip("|").split("|")]
                rows = []
            continue
        if header is None:
            continue
        if cells == header:
            continue
        if len(cells) == len(header):
            rows.append(dict(zip(header, cells)))
    if header:
        out.append((header, rows))
    return out


def _registers():
    return [d for d in sorted(REPO.glob("*/documents/*.md"))
            if d.read_text(encoding="utf-8", errors="replace").startswith("---")]


def test_the_building_declares_labels_at_all():
    """Guards the harness: an empty label set would make every test below vacuous."""
    labels = _declared_labels()
    assert len(labels) > 50, (
        f"only {len(labels)} rdfs:label values found in the building TTL; the parser or the "
        f"layout has changed and these checks would pass on nothing"
    )


@pytest.mark.parametrize("doc", _registers(), ids=lambda p: p.name)
def test_every_room_named_by_a_register_exists(doc):
    labels = _declared_labels()
    unknown = []
    for header, rows in _tables(doc):
        cols = [c for c in header if c.lower() in ROOM_COLUMNS]
        if not cols:
            continue
        for row in rows:
            for col in cols:
                value = row.get(col, "").strip()
                # Only values that look like a room reference are claims about a room.
                if not value or not re.search(r"\broom\s+\d", value, re.I):
                    continue
                if _normalise(value) not in labels:
                    unknown.append(f"{col}={value!r}")
    assert not unknown, (
        f"{doc.name} names rooms the building's TTL does not declare: {sorted(set(unknown))}. "
        f"A lifted record is graph data, so this would read as an authoritative fact about a "
        f"room that does not exist."
    )
