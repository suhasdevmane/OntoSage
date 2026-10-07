# -*- coding: utf-8 -*-
"""Pair two captures of the same frozen set into a BLINDED scoring sheet.

    python scripts/make_blinded_sheet.py --set eval/compound/T-REAL.jsonl --a v1 --b v2

For every item the two answers are shown as X and Y in an order drawn per item from a fixed
seed. The reader fills one label per answer (A-F, tasks/V2_COMPOUND_PLAN.md section 5) and, where
the item names criteria, how many each answer covered with evidence. Which system wrote X is in
a separate key file the reader must not open until scoring is finished.

Outputs, under eval/compound/scoring/:
  <set>_sheet.csv   the sheet the reader edits (UTF-8 with BOM, so Excel opens it cleanly)
  <set>_sheet.html  the same items, one per block, for comfortable reading
  <set>_key.json    X/Y -> version, per item (sealed)

Nothing here judges an answer. It only arranges two answers so a person can, without knowing
which system they came from.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import random
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parent.parent
LABELS = "A=full | B=honest partial | C=correct decline | D=false decline/silent partial | E=wrong | F=fabricated"


def _load(path: Path) -> List[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", required=True)
    ap.add_argument("--a", required=True, help="first version, e.g. v1")
    ap.add_argument("--b", required=True, help="second version, e.g. v2")
    ap.add_argument("--seed", type=int, default=20261007)
    args = ap.parse_args()

    set_path = (REPO / args.set).resolve()
    items = _load(set_path)
    res_dir = REPO / "eval" / "compound" / "results"
    a = {r["id"]: r for r in _load(res_dir / args.a / f"{set_path.stem}.jsonl")}
    b = {r["id"]: r for r in _load(res_dir / args.b / f"{set_path.stem}.jsonl")}

    out = REPO / "eval" / "compound" / "scoring"
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    key: Dict[str, Dict[str, str]] = {}
    rows = []
    for it in items:
        i = it["id"]
        pair = [(args.a, a.get(i, {})), (args.b, b.get(i, {}))]
        rng.shuffle(pair)
        key[i] = {"X": pair[0][0], "Y": pair[1][0]}
        rows.append(
            {
                "id": i,
                "shape": it.get("shape", ""),
                "answerability": it.get("answerability", ""),
                "question": it["question"],
                "criteria_needed": "; ".join(it.get("facets_needed", [])),
                "answer_X": pair[0][1].get("answer")
                or f"[no answer: {pair[0][1].get('error', 'missing')}]",
                "answer_Y": pair[1][1].get("answer")
                or f"[no answer: {pair[1][1].get('error', 'missing')}]",
                "label_X": "",
                "label_Y": "",
                "criteria_covered_X": "",
                "criteria_covered_Y": "",
                "notes": "",
            }
        )

    stem = set_path.stem
    with (out / f"{stem}_sheet.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    (out / f"{stem}_key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")

    blocks = [f"<h1>{html.escape(stem)} — blinded</h1><p><b>Labels:</b> {html.escape(LABELS)}</p>"]
    for r in rows:
        blocks.append(
            "<hr><h3>{id} · {shape} · {ans}</h3><p><b>Q:</b> {q}</p>"
            "<p><b>Criteria:</b> {c}</p>"
            "<h4>X</h4><pre style='white-space:pre-wrap'>{x}</pre>"
            "<h4>Y</h4><pre style='white-space:pre-wrap'>{y}</pre>".format(
                id=html.escape(r["id"]),
                shape=html.escape(r["shape"]),
                ans=html.escape(r["answerability"]),
                q=html.escape(r["question"]),
                c=html.escape(r["criteria_needed"]),
                x=html.escape(r["answer_X"]),
                y=html.escape(r["answer_Y"]),
            )
        )
    (out / f"{stem}_sheet.html").write_text(
        "<!doctype html><meta charset='utf-8'><body style='font-family:sans-serif;max-width:60rem'>"
        + "\n".join(blocks)
        + "</body>",
        encoding="utf-8",
    )
    print(f"{len(rows)} items -> {out / (stem + '_sheet.csv')} (key sealed in {stem}_key.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
