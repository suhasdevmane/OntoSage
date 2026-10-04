#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Draw the week's hand-read sample from the trial export (Phase 2 of the QA-trial plan).

Tails C–Q were drawn from the 2024 survey corpus; this draws from what testers ACTUALLY typed,
exported by `scripts/export_trial_turns.py`. The sample is the file the weekly hand read works
from, and the questions in it become the week's regression set.

    python scripts/draw_weekly_tail.py --turns docs/phase0/trial/turns_2026-10-09.jsonl \
        --name W1 --n 20 --seed 20261009

Rules, so the number it produces can be defended:
  * EVERY turn with a thumbs-down is included, before any sampling (they are the complaints).
  * The remaining N are drawn at random (seeded) from turns whose question has NOT appeared in
    any earlier tail or weekly sample under docs/phase0/ -- the same exclusion `draw_tail.py`
    applies, so a week never re-measures what a previous week tuned on.
  * Duplicates of the same question text are collapsed to the first occurrence.
  * The answer is kept IN FULL beside the question; the reader labels from the stored answer,
    never from a terminal window (CAVEAT-1293).

Writes `docs/phase0/weekly_<name>_sample.jsonl` (question + answer + user + feedback) and
`docs/phase0/weekly_<name>_questions.txt` (questions only, one per line) and prints the sha256
of the questions file, which goes into the read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PHASE0 = REPO / "docs" / "phase0"


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def _already_asked() -> set:
    seen = set()
    for f in list(PHASE0.glob("tail_*_questions.txt")) + list(
        PHASE0.glob("weekly_*_questions.txt")
    ):
        seen |= {_norm(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()}
    return seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, required=True)
    args = ap.parse_args()

    rows = [
        json.loads(l)
        for l in Path(args.turns).read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    seen_q = set()
    unique = []
    for r in rows:
        k = _norm(r.get("q"))
        if not k or k in seen_q:
            continue
        seen_q.add(k)
        unique.append(r)
    negative = [r for r in unique if (r.get("feedback") or {}).get("rating") in (-1, 0, "-1")]
    exclude = _already_asked() | {_norm(r["q"]) for r in negative}
    pool = [r for r in unique if _norm(r["q"]) not in exclude]
    rng = random.Random(args.seed)
    drawn = rng.sample(pool, min(args.n, len(pool)))
    sample = negative + drawn

    out_jsonl = PHASE0 / f"weekly_{args.name}_sample.jsonl"
    out_txt = PHASE0 / f"weekly_{args.name}_questions.txt"
    out_jsonl.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in sample), encoding="utf-8"
    )
    out_txt.write_text("".join(r["q"].strip() + "\n" for r in sample), encoding="utf-8")
    sha = hashlib.sha256(out_txt.read_bytes()).hexdigest()
    print(
        f"{len(sample)} turns ({len(negative)} thumbs-down + {len(drawn)} random of {len(pool)} "
        f"eligible; {len(unique)} unique questions in the export) -> {out_jsonl.name}\n"
        f"questions sha256 {sha}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
