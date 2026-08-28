# -*- coding: utf-8 -*-
"""One results table set, and the things it must never quietly do (V5-T45).

Three properties, in descending order of how much damage getting them wrong does:

* **A building that was never certified says so.** Omitting it leaves a table with four
  buildings and three columns, which reads as "the fourth scored nothing" to everyone
  who did not run it.
* **A run that declared itself INVALID is excluded AND named.** ``certify_building.py``
  stamps ``## Run validity`` into the scorecard; averaging a run whose stack died
  mid-way is exactly how CAVEAT-173 and BUG-177 produced numbers that had to be thrown
  away.
* **The field names match what the graders actually emit.** A first pass read
  ``ci95_coverage`` where ``grade_forecasts`` writes ``mean_ci95_raw``, and rendered an
  em dash for a pillar that HAD been measured. A missing number and an unmeasured one
  look identical in a table, and only one of them is true.
"""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]


def _mod():
    path = _REPO / "scripts" / "compile_v5_results.py"
    spec = importlib.util.spec_from_file_location("_compile_v5", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# -- the field names the graders really use ----------------------------------
def test_the_predict_cell_reads_the_field_grade_forecasts_writes():
    """grade_forecasts emits mean_ci95_raw. Reading ci95_coverage rendered an em dash
    for a measured pillar — the exact bug this test exists for."""
    cell = _mod()._predict_cell({"status": "ok", "mean_ci95_raw": 0.92, "cells": 18})
    assert "0.92" in cell
    assert "—" not in cell.split("<br>")[0]


def test_the_detect_cell_reads_the_field_grade_anomalies_writes():
    cell = _mod()._detect_cell({"status": "ok", "recall_pct": 96.9, "detected": 31, "injected": 32})
    assert "96.9%" in cell and "31/32" in cell


def test_the_coverage_cell_shows_the_quarantined_count():
    """Quarantined rows are the difference between a score and a valid score."""
    cell = _mod()._coverage_cell(
        {
            "status": "ok",
            "data_backed_pct": 26.2,
            "combined_pct": 80.6,
            "questions": 237,
            "quarantined_no_response": 3,
        }
    )
    assert "237" in cell and "3 quarantined" in cell


def test_an_unmeasured_pillar_is_not_rendered_as_a_number():
    for fn in ("_coverage_cell", "_privacy_cell", "_detect_cell", "_predict_cell"):
        out = getattr(_mod(), fn)({})
        assert "not measured" in out or "_" in out, f"{fn} invented a value for no data"


# -- what is absent is said out loud -----------------------------------------
def _write_card(tmp_path: Path, bid: str, validity: str) -> Path:
    body = f"""# V5 Scorecard — {bid}

## Run validity: {validity}

## Per-stratum detail

### coverage

```json
{{"status": "ok", "questions": 100, "data_backed_pct": 30.0, "combined_pct": 80.0}}
```
"""
    p = tmp_path / f"V5_SCORECARD_{bid}_20260828_000000.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_a_building_with_no_scorecard_is_reported_not_omitted(tmp_path, monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_OUT", tmp_path, raising=False)
    _write_card(tmp_path, "bldg1", "VALID")

    out = m.build(["bldg1", "bldg3"])
    assert "bldg1" in out
    assert "bldg3" in out, "an uncertified building vanished from the report"
    assert "not certified" in out


def test_an_invalid_run_is_excluded_and_named(tmp_path, monkeypatch):
    """Excluding it silently would be worse than including it: the reader would see
    three buildings and never learn a fourth run was thrown away."""
    m = _mod()
    monkeypatch.setattr(m, "_OUT", tmp_path, raising=False)
    _write_card(tmp_path, "bldg1", "VALID")
    _write_card(tmp_path, "bldg2", "INVALID")

    out = m.build(["bldg1", "bldg2"])
    assert "INVALID" in out
    assert "excluded from" in out
    header = out[out.index("| pillar |") : out.index("| pillar |") + 200]
    assert "bldg2" not in header, "an INVALID run was aggregated into the table"


def test_the_validity_stamp_is_read_from_the_scorecard():
    m = _mod()
    assert m._validity("## Run validity: VALID\n") == "VALID"
    assert m._validity("## Run validity: INVALID\n") == "INVALID"
    assert m._validity("no stamp here") == "UNKNOWN"


def test_an_older_scorecard_without_a_stamp_is_not_treated_as_invalid():
    """Scorecards predating certify_building carry no stamp. Dropping them would erase
    the only bldg2 certification this repo has."""
    m = _mod()
    assert m._validity("# V5 Scorecard — bldg2\n") == "UNKNOWN"


# -- every figure names its source -------------------------------------------
def test_each_building_row_names_the_artifact_it_came_from(tmp_path, monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_OUT", tmp_path, raising=False)
    card = _write_card(tmp_path, "bldg1", "VALID")
    out = m.build(["bldg1"])
    assert card.name in out, "a figure appears with no provenance"
