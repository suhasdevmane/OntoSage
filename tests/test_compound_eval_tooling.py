# -*- coding: utf-8 -*-
"""The compound-question evaluation tooling arranges and counts correctly (v2 plan, section 5).

Synthetic data only -- no building, no held-out item. These pin the two properties the thesis
claim leans on: the sheet is BLINDED (the reader cannot tell which version wrote X), and the
unblinding counts exactly what the key says.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


@pytest.fixture
def workspace(tmp_path):
    items = [
        {
            "id": f"R{i:03d}",
            "question": f"q{i}",
            "shape": "C1",
            "answerability": "FULL",
            "facets_needed": ["a", "b"],
        }
        for i in range(1, 7)
    ]
    _write_jsonl(tmp_path / "eval/compound/T-TEST.jsonl", items)
    _write_jsonl(
        tmp_path / "eval/compound/results/v1/T-TEST.jsonl",
        [{"id": it["id"], "answer": f"v1 answer {it['id']}"} for it in items],
    )
    _write_jsonl(
        tmp_path / "eval/compound/results/v2/T-TEST.jsonl",
        [{"id": it["id"], "answer": f"v2 answer {it['id']}"} for it in items],
    )
    return tmp_path


def _run(mod, root: Path, argv):
    mod.REPO = root
    old = sys.argv
    sys.argv = ["x"] + argv
    try:
        return mod.main()
    finally:
        sys.argv = old


def test_the_sheet_hides_which_version_wrote_each_answer(workspace):
    mk = _load("make_blinded_sheet")
    assert (
        _run(mk, workspace, ["--set", "eval/compound/T-TEST.jsonl", "--a", "v1", "--b", "v2"]) == 0
    )
    sheet = (workspace / "eval/compound/scoring/T-TEST_sheet.csv").read_text(encoding="utf-8-sig")
    assert "v1" not in sheet.split("\n", 1)[0]  # no version name in the header
    key = json.loads((workspace / "eval/compound/scoring/T-TEST_key.json").read_text())
    # Both orders occur across six items with this seed: the order is not fixed per version.
    assert {k["X"] for k in key.values()} == {"v1", "v2"}
    with (workspace / "eval/compound/scoring/T-TEST_sheet.csv").open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            x_version = key[row["id"]]["X"]
            assert row["answer_X"].startswith(f"{x_version} answer")


def test_unblinding_counts_exactly_what_the_key_says(workspace):
    mk = _load("make_blinded_sheet")
    _run(mk, workspace, ["--set", "eval/compound/T-TEST.jsonl", "--a", "v1", "--b", "v2"])
    sdir = workspace / "eval/compound/scoring"
    key = json.loads((sdir / "T-TEST_key.json").read_text())
    with (sdir / "T-TEST_sheet.csv").open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    # Ground truth: v1 is acceptable on 2 of 6 (A), v2 on 5 of 6 (A), and one F for v1.
    truth_v1 = {"R001": "A", "R002": "A", "R003": "D", "R004": "D", "R005": "E", "R006": "F"}
    truth_v2 = {"R001": "A", "R002": "A", "R003": "A", "R004": "A", "R005": "A", "R006": "D"}
    for row in rows:
        for slot in ("X", "Y"):
            truth = truth_v1 if key[row["id"]][slot] == "v1" else truth_v2
            row[f"label_{slot}"] = truth[row["id"]]
            row[f"criteria_covered_{slot}"] = "2" if truth[row["id"]] == "A" else "0"
    with (sdir / "T-TEST_sheet.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    sc = _load("score_blinded")
    assert (
        _run(sc, workspace, ["--set", "eval/compound/T-TEST.jsonl", "--a", "v1", "--b", "v2"]) == 0
    )
    out = (sdir / "T-TEST_results.md").read_text(encoding="utf-8")
    assert "v1 33.3%; v2 83.3%" in out
    assert "only v1 acceptable = 0, only v2 acceptable = 3" in out
    assert "fabricated (F): v1 1, v2 0" in out


def test_an_unfinished_sheet_is_refused(workspace):
    mk = _load("make_blinded_sheet")
    _run(mk, workspace, ["--set", "eval/compound/T-TEST.jsonl", "--a", "v1", "--b", "v2"])
    sc = _load("score_blinded")
    assert (
        _run(sc, workspace, ["--set", "eval/compound/T-TEST.jsonl", "--a", "v1", "--b", "v2"]) == 2
    )


def _fill_all(sdir: Path, stem: str, label_v1: str, label_v2: str):
    key = json.loads((sdir / f"{stem}_key.json").read_text())
    with (sdir / f"{stem}_sheet.csv").open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        for slot in ("X", "Y"):
            row[f"label_{slot}"] = label_v1 if key[row["id"]][slot] == "v1" else label_v2
    with (sdir / f"{stem}_sheet.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def test_two_sets_pool_into_one_primary_analysis(workspace):
    """The pre-registered primary pools T-REAL and its supplement (plan section 5)."""
    items = [
        {"id": f"X{i:03d}", "question": f"s{i}", "shape": "C2", "answerability": "PARTIAL"}
        for i in range(1, 5)
    ]
    _write_jsonl(workspace / "eval/compound/T-SUPP.jsonl", items)
    for v in ("v1", "v2"):
        _write_jsonl(
            workspace / f"eval/compound/results/{v}/T-SUPP.jsonl",
            [{"id": it["id"], "answer": f"{v} answer {it['id']}"} for it in items],
        )
    mk = _load("make_blinded_sheet")
    for s in ("T-TEST", "T-SUPP"):
        _run(mk, workspace, ["--set", f"eval/compound/{s}.jsonl", "--a", "v1", "--b", "v2"])
        _fill_all(workspace / "eval/compound/scoring", s, "D", "A")
    sc = _load("score_blinded")
    argv = ["--set", "eval/compound/T-TEST.jsonl", "--set", "eval/compound/T-SUPP.jsonl"]
    assert _run(sc, workspace, argv + ["--a", "v1", "--b", "v2"]) == 0
    out = (workspace / "eval/compound/scoring/T-TEST+T-SUPP_results.md").read_text(encoding="utf-8")
    assert "n = 10;" in out  # 6 + 4 answerable items, pooled
    assert "only v1 acceptable = 0, only v2 acceptable = 10" in out


def test_pooling_refuses_sets_whose_ids_collide(workspace):
    mk = _load("make_blinded_sheet")
    _run(mk, workspace, ["--set", "eval/compound/T-TEST.jsonl", "--a", "v1", "--b", "v2"])
    sc = _load("score_blinded")
    argv = ["--set", "eval/compound/T-TEST.jsonl", "--set", "eval/compound/T-TEST.jsonl"]
    assert _run(sc, workspace, argv + ["--a", "v1", "--b", "v2"]) == 2
