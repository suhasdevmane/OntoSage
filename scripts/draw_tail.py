#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Draw a fresh held-out tail of real survey questions, excluding everything ever asked.

WHY THIS EXISTS
---------------
Every quality number this project can defend comes from a HAND READ of specific answers
(CAVEAT-1346: no automatic grader bucket supports a claim about answers it was not calibrated
on). A hand read is only worth paying for on questions the system has not been developed
against, and tails C through N are spent -- each was read, and whoever reads a question while
fixing the system fixes towards it.

So this draws the next tail from the real survey corpus and EXCLUDES, by normalised text, every
question that appears in any stored answer file. It prints the questions, because unlike the
sealed Gate A set this tail is meant to be read and labelled immediately.

THE DRAW
--------
Source: ``paper/Survey analysis and results/corpus/classified_corpus.csv`` -- 96 participants,
the questions real people asked before the system was designed.

Excluded: every question in ``docs/phase0/*.jsonl`` and ``scripts/outputs/*.jsonl``, matched on
lowercased text with punctuation and whitespace collapsed, so a re-ask with a different trailing
question mark is still excluded.

Mix: stratified to the corpus's own complexity distribution, so the tail is representative of
what users ask rather than of what is hard. Deterministic given --seed, so a draw can be
reproduced and a reviewer can check that nothing was cherry-picked.

    python scripts/draw_tail.py --name O --n 60 --seed 20261001
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Set

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "paper" / "Survey analysis and results" / "corpus" / "classified_corpus.csv"
_PUNCT = re.compile(r"[^a-z0-9 ]+")


def _norm(text: str) -> str:
    """Lowercased, punctuation-stripped, whitespace-collapsed — so near-duplicates collide."""
    return " ".join(_PUNCT.sub(" ", (text or "").lower()).split())


def _already_asked() -> Set[str]:
    seen: Set[str] = set()
    for pattern in ("docs/phase0/*.jsonl", "scripts/outputs/*.jsonl"):
        for path in sorted(REPO.glob(pattern)):
            try:
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    if not isinstance(rec, dict):
                        continue
                    for key in ("question", "query", "prompt"):
                        q = rec.get(key)
                        if isinstance(q, str) and q.strip():
                            seen.add(_norm(q))
            except Exception:  # noqa: BLE001
                continue
    return seen


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="O", help="tail letter, for the output filename")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", default="20261001")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)

    if not CORPUS.exists():
        print("corpus not found: %s" % CORPUS)
        return 2

    asked = _already_asked()
    print("questions already asked in stored answer files: %d" % len(asked))

    rows: List[Dict[str, str]] = []
    with CORPUS.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rows.append(row)
    print("corpus rows: %d" % len(rows))
    qcol = next(
        (c for c in (rows[0].keys() if rows else []) if "question" in c.lower()),
        None,
    )
    ccol = next(
        (
            c
            for c in (rows[0].keys() if rows else [])
            if "complex" in c.lower() or c.lower() in ("type", "class", "category")
        ),
        None,
    )
    if not qcol:
        print("no question column found; columns are %s" % list(rows[0].keys()))
        return 2
    print("question column: %r   stratify column: %r" % (qcol, ccol))

    fresh = []
    for r in rows:
        q = (r.get(qcol) or "").strip()
        if not q or len(q) < 12:
            continue
        if _norm(q) in asked:
            continue
        fresh.append((q, (r.get(ccol) or "UNSPECIFIED").strip() if ccol else "UNSPECIFIED"))
    # de-duplicate within the corpus itself
    byn: Dict[str, tuple] = {}
    for q, c in fresh:
        byn.setdefault(_norm(q), (q, c))
    fresh = list(byn.values())
    print("corpus questions never asked: %d" % len(fresh))

    mix = Counter(c for _, c in fresh)
    total = sum(mix.values())
    print("\nunseen mix: %s" % dict(mix.most_common()))

    buckets: Dict[str, List[tuple]] = defaultdict(list)
    for q, c in fresh:
        buckets[c].append((q, c))
    for c in buckets:
        buckets[c].sort(key=lambda t: hashlib.sha256((args.seed + t[0]).encode()).hexdigest())

    want = {c: max(1, round(args.n * n / total)) for c, n in mix.items()}
    drawn: List[tuple] = []
    for c in sorted(want, key=lambda k: -mix[k]):
        drawn.extend(buckets[c][: want[c]])
    drawn = drawn[: args.n]
    # top up deterministically if rounding left us short
    if len(drawn) < args.n:
        pool = [t for c in sorted(buckets) for t in buckets[c] if t not in drawn]
        pool.sort(key=lambda t: hashlib.sha256((args.seed + t[0]).encode()).hexdigest())
        drawn.extend(pool[: args.n - len(drawn)])

    out = (
        Path(args.out)
        if args.out
        else REPO / "docs" / "phase0" / ("tail_%s_questions.txt" % args.name)
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(q for q, _ in drawn) + "\n", encoding="utf-8")
    sha = hashlib.sha256(out.read_bytes()).hexdigest()

    print("\ndrawn %d questions -> %s" % (len(drawn), out))
    print("sha256 %s" % sha)
    print("drawn mix: %s\n" % dict(Counter(c for _, c in drawn).most_common()))
    for i, (q, c) in enumerate(drawn, 1):
        print("%2d. [%s] %s" % (i, c[:18], q[:104]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
