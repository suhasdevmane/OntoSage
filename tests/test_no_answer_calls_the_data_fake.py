"""No answer describes the building's own data as fake (user decision, 2026-09-16).

Every reading in this deployment is PLACEHOLDER data standing in for the building's own feed,
and it is replaced wholesale when the real source is connected. Captions like "· simulated",
"declared synthetic" and "_**Synthetic demonstration record**_" therefore described the stage
of the deployment, not the source — and they appeared on answers about the building's own
registers, where a stakeholder reads them as a statement about the building.

WHAT THIS DOES NOT RELAX. The system still never invents a figure, still names the source of
every number, and still reports an absence as an absence. The `isSimulated` triples and the
`synthetic` flag on a provenance tag are untouched: the declaration stays where an auditor
reads it, and stops being printed as a caveat.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: The ACTIVE building's record documents. The canonical committed tree has NO active building
#: (`input/` does not exist), which is what a fresh clone and CI see, so both document tests below
#: are skipped there rather than passing vacuously — one of them asserted over an empty glob and
#: failed the parked suite on 2026-09-18, and its sibling "passed" by finding nothing to object to.
_DOCUMENTS = Path("input/documents")
_needs_documents = pytest.mark.skipif(
    not _DOCUMENTS.is_dir(), reason="no active building: input/documents is absent (parked tree)"
)

_FAKE_WORDS = re.compile(r"\b(simulated|synthetic|fictional|not\s+real|fake|dummy)\b", re.IGNORECASE)

#: The phrases that used to reach a user, named individually so re-adding one fails loudly.
_RETIRED_CAPTIONS = (
    "· simulated",
    "declared synthetic",
    "This is simulated data",
    "Source: simulated service feed",
    "Source: simulated estates feed",
    "Synthetic demonstration record",
)


def test_the_provenance_chip_names_the_source_only():
    from orchestrator.services.provenance import ProvenanceTag, render_chips

    chips = render_chips(
        [
            ProvenanceTag(
                source_id="occupancy_data",
                label="Occupancy Sensing System",
                color="#fff",
                synthetic=True,
            ),
            ProvenanceTag(
                source_id="ontology", label="Building Ontology", color="#fff", synthetic=False
            ),
        ]
    )
    assert "Occupancy Sensing System" in chips
    assert not _FAKE_WORDS.search(chips), chips


def test_the_flag_still_exists_for_an_audit():
    """The point is that the caption went, not the record. A tag still carries it."""
    from orchestrator.services.provenance import ProvenanceTag

    tag = ProvenanceTag(source_id="x", label="x", color="#fff", synthetic=True)
    assert tag.synthetic is True


def test_the_evidence_record_carries_no_such_caption():
    from orchestrator.services.answer_provenance import render

    text = render(
        {
            "claim_kind": "observed",
            "sources": [{"source_id": "uuid-1", "kind": "sensor", "simulated": True}],
        }
    )
    assert text and not _FAKE_WORDS.search(text), text


@pytest.mark.parametrize("caption", _RETIRED_CAPTIONS)
def test_a_retired_caption_is_gone_from_the_answer_path(caption):
    """Scanned across the modules that render user-visible text."""
    roots = [
        Path("orchestrator/services/provenance.py"),
        Path("orchestrator/services/answer_provenance.py"),
        Path("orchestrator/services/asset_state_service.py"),
        Path("orchestrator/services/deliberation/saturation.py"),
        Path("scripts/generate_record_documents.py"),
    ]
    for path in roots:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").split("\n"):
            code = line.split("#", 1)[0]  # a comment may describe what was removed
            assert caption not in code, f"{path}: {line.strip()}"


def test_no_point_label_carries_the_marker():
    """1,610 labels said "(simulated)", and a label is quoted verbatim in answers."""
    offenders = []
    for ttl in Path("input").glob("*.ttl"):
        for m in re.finditer(r'rdfs:label\s+"([^"]*)"', ttl.read_text(encoding="utf-8")):
            if _FAKE_WORDS.search(m.group(1)):
                offenders.append(f"{ttl.name}: {m.group(1)}")
    assert not offenders, offenders[:10]


@_needs_documents
def test_no_record_document_opens_with_a_disclaimer():
    """These registers are lifted into the graph and quoted in answers."""
    offenders = []
    for doc in _DOCUMENTS.glob("*.md"):
        for line in doc.read_text(encoding="utf-8").split("\n"):
            if line.strip().startswith("_**") and _FAKE_WORDS.search(line):
                offenders.append(f"{doc.name}: {line.strip()[:70]}")
    assert not offenders, offenders[:10]


@_needs_documents
def test_the_front_matter_declaration_is_untouched():
    """The lifter carries `simulated:` onto every triple; that is the audit trail and it
    must NOT have been stripped along with the prose."""
    declared = [
        doc.name
        for doc in _DOCUMENTS.glob("*.md")
        if re.search(r"^simulated:\s*true", doc.read_text(encoding="utf-8"), re.MULTILINE)
    ]
    assert declared, "no record document declares its provenance any more"
