# -*- coding: utf-8 -*-
"""I4 (QA-trial plan, 2026-10-04): the evidence-coverage script runs and reports a real
number against the stored answer corpus."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "measure_evidence_coverage.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("measure_evidence_coverage", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_it_runs_and_reports_figure_bearing_counts():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert "Figure-bearing" in result.stdout
    assert "NOT measured here" in result.stdout, "the honest scope-limit note must survive"


def test_answer_texts_deduplicates_across_files(tmp_path):
    mod = _load_module()
    f1 = tmp_path / "a.jsonl"
    f2 = tmp_path / "b.jsonl"
    f1.write_text(json.dumps({"answer": "The CO2 reading is 600 ppm."}) + "\n", encoding="utf-8")
    f2.write_text(json.dumps({"answer": "The CO2 reading is 600 ppm."}) + "\n", encoding="utf-8")
    texts = mod._answer_texts([str(f1), str(f2)])
    assert texts == ["The CO2 reading is 600 ppm."]


def test_a_text_answer_with_no_figure_is_excluded_from_the_figure_bearing_count(tmp_path):
    mod = _load_module()
    f = tmp_path / "a.jsonl"
    f.write_text(json.dumps({"answer": "I don't have that on record."}) + "\n", encoding="utf-8")
    texts = mod._answer_texts([str(f)])
    from orchestrator.services.publication_gate import has_quantitative_claim

    assert not has_quantitative_claim(texts[0])
