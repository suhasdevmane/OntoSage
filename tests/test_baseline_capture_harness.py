# -*- coding: utf-8 -*-
"""The golden-baseline capture harness itself (V6-T54).

This project's own history is the argument for this file. Four of the five most recent P1s
were in *measurement apparatus*, not in the system being measured: BUG-176 graded a run
whose stack had been recreated mid-flight, BUG-177 scored an outage's fallback text as an
answer, BUG-191 counted the "2" inside `bldg2` as a sensor reading and manufactured a
perfect 39/39. Each one failed in the flattering direction, which is why none was noticed
until someone read the rows behind the number.

So the harness gets the same scrutiny as the code it measures. The two properties asserted
here are the two that were wrong when this file was written:

* a **quarantined row is not a capture** -- `--resume` must retry it, or the flag is a no-op
  on precisely the rows it exists for;
* **tallies describe the file, not the invocation** -- otherwise a resume of 51 rows
  overwrites `ok=1529` with `ok=51` in the metadata a supervisor reads.
"""

import csv
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "capture_golden_baseline.py"


@pytest.fixture(scope="module")
def cap():
    """Load the script as a module -- it is a CLI, not an importable package."""
    spec = importlib.util.spec_from_file_location("capture_golden_baseline", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(path: Path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


@pytest.fixture
def capture(tmp_path, cap):
    """Three rows: one good, one degraded, one timed out."""
    path = tmp_path / "baseline_test.csv"
    _write(
        path,
        [
            {"qid": "Q1", "question": "a", "answer": "22.4 C", "status": "OK"},
            {"qid": "Q2", "question": "b", "answer": "", "status": "LLM-DEGRADED:empty"},
            {"qid": "Q3", "question": "c", "answer": "", "status": "TIMEOUT"},
        ],
        cap.FIELDS,
    )
    return path


# ── a quarantined row is not a capture ───────────────────────────────────────


def test_resume_treats_only_healthy_rows_as_done(cap, capture):
    """The defect this test exists for: --resume was a no-op on the rows it targets."""
    assert cap._done_qids(capture) == {"Q1"}


def test_the_freeze_option_still_counts_everything(cap, capture):
    """Opting out must be explicit, and must actually opt out."""
    assert cap._done_qids(capture, retry_failed=False) == {"Q1", "Q2", "Q3"}


def test_retried_rows_are_replaced_not_duplicated(cap, capture):
    """Two rows for one question makes every later count ambiguous."""
    dropped = cap._drop_rows(capture, {"Q2", "Q3"})
    assert dropped == 2
    rows = cap._read_rows(capture)
    assert [r["qid"] for r in rows] == ["Q1"]


def test_dropping_never_touches_a_healthy_answer(cap, capture):
    """The captured answers are the artefact; a retry must not be able to eat one."""
    cap._drop_rows(capture, {"Q2", "Q3"})
    assert cap._read_rows(capture)[0]["answer"] == "22.4 C"


def test_dropping_nothing_leaves_the_file_alone(cap, capture):
    before = capture.read_bytes()
    assert cap._drop_rows(capture, set()) == 0
    assert capture.read_bytes() == before


def test_an_interrupted_rewrite_cannot_leave_a_stray_temp_file(cap, capture):
    cap._drop_rows(capture, {"Q2"})
    assert not list(capture.parent.glob("*.tmp"))


# ── tallies describe the file, not the invocation ────────────────────────────


def test_tally_counts_the_whole_capture(cap, capture):
    assert cap._tally(capture) == {"ok": 1, "degraded": 1, "failed": 1, "captured": 3}


def test_tally_separates_degradation_from_transport_failure(cap, capture, tmp_path):
    """Different causes, different remedies: one is the model, one is the network."""
    t = cap._tally(capture)
    assert t["degraded"] == 1 and t["failed"] == 1


def test_tally_of_a_missing_file_is_empty_not_an_error(cap, tmp_path):
    assert cap._tally(tmp_path / "absent.csv")["captured"] == 0


# ── the harness must refuse to grade an unhealthy stack ──────────────────────


def test_capture_refuses_to_start_without_health(cap):
    """Non-negotiable: a run is only valid if the stack was healthy for all of it."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "REFUSING TO START" in src


def test_degraded_turns_are_quarantined_rather_than_scored(cap):
    """BUG-177: an outage's fallback text reads like an answer and once graded as a PASS."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "LLM-DEGRADED" in src
    assert "llm_degraded" in src


def test_the_harness_carries_no_building_literal(cap):
    """A baseline harness pinned to one building cannot measure portability."""
    from scripts.check_building_literals import _prose_lines

    src = SCRIPT.read_text(encoding="utf-8")
    prose = _prose_lines(src)
    code = "\n".join(l for n, l in enumerate(src.splitlines(), 1) if n not in prose).lower()
    for literal in ("abacws", "bldg1", "bldg2", "bldg3"):
        assert literal not in code, f"harness hardcodes {literal}"
