"""Seeded Part A samples from the pre-development corpus (tracker G1; plan 03 §3.2).

Draws, in this order and from one seed:
  1. VALIDATION: n rows per stage (default 100; 75 if the second coder's time is short, decided
     BEFORE coding begins), without replacement within stage. Repeated wordings are kept: the
     target is submissions, not unique texts.
  2. Reserves every row whose normalised text equals a validation row's text, so the development
     set cannot contain a validation question under another row id.
  3. DEVELOPMENT: 25 rows per stage from what remains.
  4. FRESH COMPARISON: 90 corpus rows from what remains, proportional to stage size, to be shuffled
     with participants' own questions and coded blind to source (plan 03 §3.6).

Coders see ONLY row_id, stage, contributor code and question text. Usernames and personas never
leave this script: contributors become C001..C096 (sorted by username, so the code is stable and
reveals nothing), and the persona column is dropped (v8 §3.3).

Writes to --out-dir: partA_validation_rows.csv, partA_dev_rows.csv,
partA_corpus_for_fresh_comparison.csv, partA_sample_manifest.json (seed, counts, weights N_s/n_s,
distinct contributors and texts represented, SHA-256 of the source and of every output).

Usage:
    python make_partA_samples.py                       # defaults: seed 20261009, 100 per stage
    python make_partA_samples.py --per-stage 75        # the pre-declared reduction
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
SOURCE = REPO / "paper" / "Survey analysis and results" / "inputs" / "questions_by_user.csv"
FIELDS = ["row_id", "stage", "contributor", "question_text"]


def norm(text: str) -> str:
    """Text-equivalence key: lower case, collapsed whitespace, trailing punctuation removed."""
    return re.sub(r"\s+", " ", text.strip().lower()).rstrip(" ?.!")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, rows: List[Dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, quoting=csv.QUOTE_ALL, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in FIELDS})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", default=str(SOURCE))
    ap.add_argument("--seed", type=int, default=20261009)
    ap.add_argument("--per-stage", type=int, default=100)
    ap.add_argument("--dev-per-stage", type=int, default=25)
    ap.add_argument("--fresh-comparison", type=int, default=90)
    ap.add_argument("--out-dir", default=str(HERE / "outputs"))
    args = ap.parse_args()

    src = Path(args.source)
    with src.open(encoding="utf-8-sig", newline="") as fh:
        raw = list(csv.DictReader(fh))
    codes = {u: f"C{i + 1:03d}" for i, u in enumerate(sorted({r["Username"] for r in raw}))}
    rows = [
        {"row_id": f"R{i + 1:05d}", "stage": r["Stage"], "contributor": codes[r["Username"]],
         "question_text": r["Question"].strip(), "_norm": norm(r["Question"])}
        for i, r in enumerate(raw)
    ]
    by_stage: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for r in rows:
        by_stage[r["stage"]].append(r)
    stages = sorted(by_stage)
    rng = random.Random(args.seed)

    validation = []
    for s in stages:
        validation += rng.sample(by_stage[s], args.per_stage)
    reserved_text = {r["_norm"] for r in validation}
    remaining = {s: [r for r in by_stage[s] if r["_norm"] not in reserved_text] for s in stages}

    dev = []
    for s in stages:
        dev += rng.sample(remaining[s], args.dev_per_stage)
    taken = {r["row_id"] for r in dev}
    pool = [r for s in stages for r in remaining[s] if r["row_id"] not in taken]
    total = sum(len(by_stage[s]) for s in stages)
    quota = {s: round(args.fresh_comparison * len(by_stage[s]) / total) for s in stages}
    quota[stages[-1]] += args.fresh_comparison - sum(quota.values())
    fresh = []
    for s in stages:
        fresh += rng.sample([r for r in pool if r["stage"] == s], quota[s])

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "partA_validation_rows.csv": sorted(validation, key=lambda r: r["row_id"]),
        "partA_dev_rows.csv": sorted(dev, key=lambda r: r["row_id"]),
        "partA_corpus_for_fresh_comparison.csv": sorted(fresh, key=lambda r: r["row_id"]),
    }
    for name, rs in files.items():
        write(out / name, rs)

    manifest = {
        "seed": args.seed,
        "source": str(src.relative_to(REPO)) if src.is_relative_to(REPO) else str(src),
        "source_sha256": sha256(src),
        "source_rows": len(rows),
        "contributors": len(codes),
        "stage_sizes_N": {s: len(by_stage[s]) for s in stages},
        "validation_per_stage_n": args.per_stage,
        "weights_N_over_n": {s: round(len(by_stage[s]) / args.per_stage, 4) for s in stages},
        "validation_distinct_contributors": len({r["contributor"] for r in validation}),
        "validation_distinct_texts": len({r["_norm"] for r in validation}),
        "validation_repeated_wordings_kept": len(validation) - len({r["_norm"] for r in validation}),
        "rows_reserved_by_text_equivalence": sum(len(by_stage[s]) - len(remaining[s]) for s in stages),
        "dev_rows": len(dev),
        "fresh_comparison_rows": len(fresh),
        "fresh_comparison_quota": quota,
        "max_submissions_per_contributor_in_validation": max(Counter(r["contributor"] for r in validation).values()),
        "outputs_sha256": {name: sha256(out / name) for name in files},
    }
    (out / "partA_sample_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items() if k != "outputs_sha256"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
