# -*- coding: utf-8 -*-
"""The graders keep what the system actually said, not a 300-character preview.

Both harnesses stored the reply truncated: ``answer_preview`` in corpus_replay and
``response_snippet`` in leak_benchmark, each ``[:300]`` with the newlines flattened.
That is the right thing for a spreadsheet column and the wrong thing for the artifact a
claim rests on.

This project's recurring lesson is that a number only means something once somebody
reads the rows behind it. CAVEAT-039 was found that way; so were BUG-176, BUG-177 and
BUG-191 -- and BUG-177's fallback text was a 1000-row dump that would have graded as a
PASS. A table dump, a fabricated figure or a policy leak can all sit past character 300.

The privacy bank is the sharper case: grading reads the WHOLE reply, so a leak beyond
character 300 is graded correctly and is then invisible in the file anyone later audits.
The number would be right and unverifiable.

So each run now writes a JSONL transcript beside its CSV -- one object per graded row,
carrying the full text. JSONL rather than more CSV columns because answers are long and
multi-line, and a transcript that has to survive a spreadsheet round-trip is one that
will be mangled.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]


def _src(name: str) -> str:
    return (_REPO / "scripts" / name).read_text(encoding="utf-8")


def _write_block(src: str) -> str:
    """The lines around where the transcript is actually written.

    Located by the open() call rather than by a character offset from the filename, so
    the test asserts behaviour rather than how far apart two lines happen to sit.
    """
    marker = 'open(transcript_path, "a"'
    if marker not in src:
        marker = "def _append_transcript"
    start = src.index(marker)
    return src[max(0, start - 600) : start + 1800]


# -- coverage harness --------------------------------------------------------
def test_corpus_replay_writes_a_transcript():
    src = _src("corpus_replay.py")
    assert "_transcript.jsonl" in src, "no transcript path"
    assert "_append_transcript(" in src, "the transcript writer is never called"


def test_corpus_replay_stores_the_untruncated_answer():
    """The point of the file. If this becomes a slice, the transcript is a preview."""
    src = _src("corpus_replay.py")
    block = src[src.index("def _append_transcript") : src.index("def _append_transcript") + 2000]
    assert '"answer": answer' in block, "the transcript truncates the answer"


def test_corpus_replay_still_keeps_the_preview_column():
    """The CSV stays readable; the transcript is additional, not a replacement."""
    assert "answer_preview" in _src("corpus_replay.py")


# -- privacy harness ---------------------------------------------------------
def test_leak_benchmark_writes_a_transcript():
    src = _src("leak_benchmark.py")
    assert "_transcript.jsonl" in src
    assert '"response": resp,' in src, "the transcript truncates the reply"


def test_leak_benchmark_transcript_records_the_verdict_beside_the_text():
    """Reading a leak means seeing the reply AND what it was graded, together.

    Anchored on the WRITE, not on the path definition. A fixed window from the first
    mention of the filename measured how far apart two lines happened to sit -- the
    brittle-slice mistake twice made in this suite already.
    """
    src = _src("leak_benchmark.py")
    block = _write_block(src)
    for field in ('"verdict"', '"question"', '"expected"', '"role"'):
        assert field in block, f"transcript omits {field}"


# -- a transcript write must never cost a graded run -------------------------
@pytest.mark.parametrize("name", ["corpus_replay.py", "leak_benchmark.py"])
def test_a_failed_transcript_write_does_not_lose_the_run(name):
    """Hours of grading must not be lost to a full disk. The grade is the product;
    the transcript is evidence for it, and evidence must not endanger the product."""
    assert "except OSError" in _write_block(
        _src(name)
    ), f"{name}: a transcript write can kill the run"
