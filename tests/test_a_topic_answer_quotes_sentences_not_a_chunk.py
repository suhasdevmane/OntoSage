"""A topic answer quotes the sentences of its document that answer, not the retrieval chunk.

2026-10-11: "Where is the fire assembly point?" appended the declared document's best chunk
verbatim -- the page title, a heading, the procedure and the first row of a register table run
together on one line. Text here is synthetic and names no building.
"""

import pytest

from orchestrator.agents.capability_agent import _relevant_sentences

pytestmark = pytest.mark.unit

CHUNK = (
    "# Safety Asset Register - Example House ## Evacuation procedure The procedure still "
    "applies: 1. On hearing the alarm, **leave the building immediately** via the nearest exit. "
    "2. **Do not use the lift** during an evacuation - use the stairs. 3. Assembly point: "
    "**Assembly Point A - North Road**, the open area outside the main entrance. Assembly Point B "
    "is the car park. 4. Report to your warden at the assembly point. **Emergency contacts:** "
    "Security 0000 - Emergency Services 999 ## Asset register | code | name | kind | location | "
    "| A-001 | Alarm panel | alarm | Room 0.10 |"
)


def test_the_sentences_about_the_question_are_quoted():
    out = _relevant_sentences("Where is the assembly point?", CHUNK)
    assert "North Road" in out
    assert "Report to your warden at the assembly point" in out


def test_no_table_row_title_or_heading_marker_is_quoted():
    out = _relevant_sentences("Where is the assembly point?", CHUNK)
    assert "|" not in out
    assert "#" not in out
    assert "Asset Register" not in out


def test_a_chunk_sharing_no_word_still_quotes_its_leading_sentences():
    """The topic declared the document, so relevance is settled; a synonym must not lose it."""
    out = _relevant_sentences(
        "how do I connect to the wifi?", "Full policy: eduroam covers all floors."
    )
    assert "eduroam covers all floors" in out


def test_a_chunk_of_table_rows_alone_quotes_nothing():
    rows = "| A-002 | Detector | detection | Level 1 | | A-003 | Exit | escape | Level 2 |"
    assert _relevant_sentences("Which detectors are on level 1?", rows) == ""
