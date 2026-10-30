#!/usr/bin/env python3
"""Re-run every analysis on the labels as they stand, in the order of 17_Study_Results_Notes_24Oct.md section 9.

    python run_pipeline.py              # analyses, figures, article assets
    python run_pipeline.py --no-figures

Data preparation is NOT repeated (build_study_dataset.py, make_blind_sheet.py, drop_superseded_labels.py,
build_check_records.py, make_qual_sheet.py): their outputs are fixed inputs here. Each analysis picks its labels by
itself: the adjudicated two-coder file, else the author's checked labels, else the AI pre-labels, and says which in
its label_source. Stops at the first step that fails.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

F = Path(__file__).resolve().parent
ANALYSES = [
    ["author_check/export_checked.py"],          # first: a material the author has fully checked becomes the labels used
    ["merge_rq2_labels.py", "ttask", "comparison", "stability"],
    ["rq3_live_analysis.py"],
    ["rq2_live_analysis.py"],
    ["rq1_fresh_vs_corpus.py", "analyse"],
    ["panel_analysis.py"],
    ["phrasing_analysis.py"],
    ["check_firing_analysis.py"],
    ["qual_analysis.py"],
    ["coder2_sensitivity.py"],
    ["partA_results.py"],
    ["stage5_analysis.py"],
    ["text_numbers.py"],
]
FIGURES = [["figures/fig_rq1.py"], ["figures/fig_rq3_decisions.py"], ["figures/fig_rq3_answers.py"],
           ["figures/fig_rq3_calibration_reliance.py"], ["figures/fig_rq3_measures.py"], ["figures/fig_rq2.py"],
           ["figures/fig_qual.py"]]
# The authors' copy ends with pii_audit_outputs.py, a check of the outputs against the identifiable
# data. It is not in this release, because it reads that data.
ASSETS = [["build_article_assets.py"], ["make_number_macros.py"]]


def run(step: list) -> bool:
    t = time.time()
    p = subprocess.run([sys.executable] + step, cwd=F, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    ok = p.returncode == 0
    tail = (p.stdout.strip().splitlines() or [""])[-1][:150]
    print(f"{'ok  ' if ok else 'FAIL'} {' '.join(step):55s} {time.time() - t:5.1f}s  {tail}")
    if not ok:
        print(p.stdout[-3000:])
        print(p.stderr[-3000:])
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-figures", action="store_true")
    a = ap.parse_args()
    steps = ANALYSES + ([] if a.no_figures else FIGURES) + ASSETS
    for s in steps:
        if not run(s):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
