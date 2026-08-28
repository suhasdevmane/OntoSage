# -*- coding: utf-8 -*-
"""Detect recall is scored against THIS building's own injections (BUG-359/360).

bldg1's certification reported 8% recall against bldg2's certified 96.9%, which reads as
a catastrophic regression in the detectors. It was arithmetic over another building's
ground truth, and it was wrong in two places that compounded:

* **The label filter** read ``round`` and ignored ``building``. Round 1 held 16 faults
  injected into bldg2 ten days earlier plus bldg1's own 8. Those bldg2 UUIDs do not
  exist in bldg1's data and can never be detected.
* **The summariser** globbed every building's scorecards and summed "the newest three by
  modification time" — which meant bldg2's August artifact plus BOTH of today's bldg1
  runs, including the superseded one the first fix had just replaced. It reported 41.7%
  where the scoped figure was 25.0%.

The corrected number is 25.0% (2 of 8), and it is NOT comparable to bldg2's 96.9%: bldg2
is wholly synthetic and its tables hold exactly what the injector wrote, while bldg1
carries a real snapshot plus a live generator (BUG-360 tracks the remaining gap).

What is pinned here is that neither mixing can come back.
"""

import csv
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]


def _graders():
    path = _REPO / "scripts" / "run_all_graders.py"
    spec = importlib.util.spec_from_file_location("_graders", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _card(dirpath: Path, building: str, rnd: int, stamp: str, injected: int, detected: int):
    p = dirpath / f"v5_t22_scorecard_{building}_r{rnd}_{stamp}.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["detector", "injected", "detected", "recall"])
        w.writeheader()
        w.writerow(
            {
                "detector": "spike",
                "injected": injected,
                "detected": detected,
                "recall": round(detected / injected, 3) if injected else 0,
            }
        )
    return p


# -- the summariser ----------------------------------------------------------
def test_another_buildings_scorecard_is_not_summed_in(tmp_path, monkeypatch):
    m = _graders()
    monkeypatch.setattr(m, "OUT", tmp_path, raising=False)
    _card(tmp_path, "bldg1", 1, "20260828_120000", injected=8, detected=2)
    _card(tmp_path, "bldg2", 1, "20260819_020000", injected=32, detected=31)

    out = m.summarise_detect("bldg1")
    assert out["injected"] == 8, "another building's injections were counted"
    assert out["detected"] == 2
    assert out["recall_pct"] == 25.0


def test_a_re_graded_round_replaces_its_predecessor(tmp_path, monkeypatch):
    """Both files are this building's and both are round 1. Summing them would average
    a corrected artifact with the one it corrected — which is how 41.7% appeared."""
    m = _graders()
    monkeypatch.setattr(m, "OUT", tmp_path, raising=False)
    old = _card(tmp_path, "bldg1", 1, "20260828_100000", injected=24, detected=2)
    new = _card(tmp_path, "bldg1", 1, "20260828_140000", injected=8, detected=2)
    import os
    import time

    os.utime(old, (time.time() - 600, time.time() - 600))
    os.utime(new, None)

    out = m.summarise_detect("bldg1")
    assert out["injected"] == 8, "a superseded re-grade of the same round was summed in"
    assert out["rounds"] == 1


def test_separate_rounds_are_still_added_together(tmp_path, monkeypatch):
    """Scoping must not cost the multi-round total the DETECT pillar reports."""
    m = _graders()
    monkeypatch.setattr(m, "OUT", tmp_path, raising=False)
    _card(tmp_path, "bldg1", 1, "20260828_100000", injected=8, detected=4)
    _card(tmp_path, "bldg1", 2, "20260828_110000", injected=8, detected=6)

    out = m.summarise_detect("bldg1")
    assert out["injected"] == 16 and out["detected"] == 10
    assert out["rounds"] == 2


def test_a_building_with_no_scorecard_says_so(tmp_path, monkeypatch):
    """Never zero, never another building's number."""
    m = _graders()
    monkeypatch.setattr(m, "OUT", tmp_path, raising=False)
    _card(tmp_path, "bldg2", 1, "20260819_020000", injected=32, detected=31)

    out = m.summarise_detect("bldg1")
    assert out["status"] == "no artifact"
    assert "bldg1" in out["detail"]


def test_the_artifacts_used_are_named_in_the_result(tmp_path, monkeypatch):
    """A recall figure whose provenance nobody can reconstruct is how this went wrong."""
    m = _graders()
    monkeypatch.setattr(m, "OUT", tmp_path, raising=False)
    card = _card(tmp_path, "bldg1", 1, "20260828_120000", injected=8, detected=2)
    out = m.summarise_detect("bldg1")
    assert card.name in out.get("artifacts", [])


# -- the label filter, a layer below -----------------------------------------
def test_the_label_filter_scopes_to_the_active_building():
    src = (_REPO / "scripts" / "grade_anomalies.py").read_text(encoding="utf-8")
    block = src[src.index("labels = [") : src.index("labels = [") + 700]
    assert 'lab.get("building")' in block, "labels are selected by round alone again"
    assert "BUILDING_ID" in src


def test_the_scorecard_filename_carries_the_building():
    """Without it the summariser cannot tell two buildings' artifacts apart."""
    src = (_REPO / "scripts" / "grade_anomalies.py").read_text(encoding="utf-8")
    assert "v5_t22_scorecard_{_bid" in src
