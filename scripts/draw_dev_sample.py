# -*- coding: utf-8 -*-
"""Draw a reproducible development sample from eval/compound/DEV.jsonl.

    python scripts/draw_dev_sample.py --n 40 --seed 1 --out eval/compound/dev_samples/DEV-40-s1.jsonl

DEV is the ONLY set the v2 developer may look at (tasks/V2_COMPOUND_PLAN.md section 5). A sample
from it gives fast feedback while building; numbers from it are development signal, never the
thesis result. Stratified across personas so one role cannot dominate. Ids are D-prefixed so a
dev capture can never be pooled with a held-out set by accident.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = [
        json.loads(x)
        for x in (REPO / "eval/compound/DEV.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    by_persona = defaultdict(list)
    for r in rows:
        by_persona[r.get("persona", "")].append(r)
    rng = random.Random(args.seed)
    personas = sorted(by_persona)
    rng.shuffle(personas)
    picked = []
    while len(picked) < args.n and any(by_persona.values()):
        for p in personas:
            if by_persona[p] and len(picked) < args.n:
                pool = by_persona[p]
                picked.append(pool.pop(rng.randrange(len(pool))))
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for i, r in enumerate(picked, 1):
            fh.write(
                json.dumps(
                    {"id": f"D{i:03d}", "question": r["question"], "persona": r.get("persona", "")},
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"{len(picked)} DEV items from {len({r.get('persona') for r in picked})} personas -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
