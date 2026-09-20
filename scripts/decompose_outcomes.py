# -*- coding: utf-8 -*-
"""W03 — decompose the hand-read outcome and test each part separately, offline.

WHY THIS EXISTS. Six waves were judged on one collapsed number, the "weird share". Refusing
more lowers it, so it rewarded declining. Split into its two halves on the same labels:

    correct ANSWERS   run1 -> run6   gained 9  / lost 11   p = 0.82   (no change)
    correct DECLINES  run1 -> run6   gained 21 / lost 8    p = 0.024  (a real change)
    either            run1 -> run6   gained 28 / lost 17   p = 0.135  (what was reported)

A wave may no longer claim progress on the collapsed number; this module is what a wave is
judged by. It reads only the committed ``docs/phase0/*_read.jsonl`` files, uses only the standard
library, and makes no network call (``tests/test_decompose_outcomes.py`` asserts that).

Also here: ``flip_rate`` with a seeded bootstrap CI, the instrument W02 (the control arm) needs.
"""

from __future__ import annotations

import argparse
import json
import random
from math import comb
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parent.parent
PHASE0 = REPO / "docs" / "phase0"

ANSWER = "GOOD_ANSWER"
DECLINE = "GOOD_DECLINE"
WEIRD = "WEIRD"

#: The six committed hand reads, in the order they were made.
DEFAULT_RUNS: Tuple[str, ...] = (
    "phase0_read",
    "phase0_rerun_read",
    "phase0_run3_read",
    "phase0_run4_read",
    "phase0_run5_read",
    "phase0_run6_read",
)

#: An outcome is a predicate over a verdict. ``either`` is the collapsed metric, kept only so a
#: reader can see what it hides.
OUTCOMES: Dict[str, Tuple[str, ...]] = {
    "answer": (ANSWER,),
    "decline": (DECLINE,),
    "either": (ANSWER, DECLINE),
}


def load_verdicts(path: Path) -> Dict[str, str]:
    """question id -> verdict for one hand-read file."""
    out: Dict[str, str] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                row = json.loads(line)
                out[str(row["id"])] = str(row["verdict"])
    return out


def load_runs(names: Sequence[str] = DEFAULT_RUNS, base: Path = PHASE0) -> List[Dict[str, str]]:
    return [load_verdicts(base / f"{n}.jsonl") for n in names]


def mcnemar_exact(gained: int, lost: int) -> float:
    """Two-sided exact McNemar p for ``gained`` vs ``lost`` discordant pairs.

    Exact binomial rather than the chi-square approximation: with 17 and 28 discordant pairs the
    approximation is not safe, and the exact form needs nothing outside ``math``.
    """
    n = gained + lost
    if n == 0:
        return 1.0
    k = min(gained, lost)
    tail = sum(comb(n, i) for i in range(k + 1)) / float(2**n)
    return min(1.0, 2.0 * tail)


def _has(verdict: Optional[str], accepted: Iterable[str]) -> bool:
    return verdict in set(accepted)


def paired_change(
    before: Dict[str, str], after: Dict[str, str], outcome: str
) -> Dict[str, float]:
    """Discordant-pair counts and exact p for one outcome between two reads of the same bank."""
    accepted = OUTCOMES[outcome]
    ids = sorted(set(before) & set(after))
    gained = sum(1 for i in ids if not _has(before[i], accepted) and _has(after[i], accepted))
    lost = sum(1 for i in ids if _has(before[i], accepted) and not _has(after[i], accepted))
    return {
        "n": len(ids),
        "before": sum(1 for i in ids if _has(before[i], accepted)),
        "after": sum(1 for i in ids if _has(after[i], accepted)),
        "gained": gained,
        "lost": lost,
        "p": mcnemar_exact(gained, lost),
    }


def flip_rate(
    a: Dict[str, str], b: Dict[str, str], iterations: int = 5000, seed: int = 20260918
) -> Dict[str, float]:
    """Share of questions whose verdict differs between two reads, with a bootstrap 95% CI.

    Two reads of the SAME frozen build put a floor under every wave delta in this project: a
    change smaller than this is indistinguishable from the system disagreeing with itself.
    Resamples questions with replacement; the RNG is seeded so the interval is reproducible.
    """
    ids = sorted(set(a) & set(b))
    flags = [1 if a[i] != b[i] else 0 for i in ids]
    n = len(flags)
    if n == 0:
        return {"n": 0, "rate": 0.0, "lo": 0.0, "hi": 0.0}
    rng = random.Random(seed)
    stats = sorted(sum(flags[rng.randrange(n)] for _ in range(n)) / n for _ in range(iterations))
    return {
        "n": n,
        "flips": sum(flags),
        "rate": sum(flags) / n,
        "lo": stats[int(0.025 * iterations)],
        "hi": stats[int(0.975 * iterations) - 1],
    }


def per_run_table(runs: Sequence[Dict[str, str]]) -> List[Dict[str, int]]:
    rows = []
    for verdicts in runs:
        vals = list(verdicts.values())
        rows.append(
            {"answer": vals.count(ANSWER), "decline": vals.count(DECLINE), "weird": vals.count(WEIRD)}
        )
    return rows


def decompose(
    names: Sequence[str] = DEFAULT_RUNS,
    base: Path = PHASE0,
    first: int = 0,
    last: int = -1,
) -> Dict[str, object]:
    runs = load_runs(names, base)
    return {
        "runs": list(names),
        "per_run": per_run_table(runs),
        "first_to_last": {
            o: paired_change(runs[first], runs[last], o) for o in OUTCOMES
        },
    }


def render(result: Dict[str, object]) -> str:
    per_run = result["per_run"]
    lines = ["Per run (of n):", "  run | answer | decline | weird"]
    for i, r in enumerate(per_run, 1):
        lines.append(f"  {i:>3} | {r['answer']:>6} | {r['decline']:>7} | {r['weird']:>5}")
    lines.append("")
    lines.append("First -> last, paired exact McNemar:")
    for name, r in result["first_to_last"].items():
        lines.append(
            f"  {name:<8} {r['before']:>3} -> {r['after']:>3}   gained {r['gained']:>2} / "
            f"lost {r['lost']:>2}   p = {r['p']:.3f}"
        )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", nargs="+", default=list(DEFAULT_RUNS), help="read-file stems")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    result = decompose(args.runs)
    print(json.dumps(result, indent=2) if args.json else render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
