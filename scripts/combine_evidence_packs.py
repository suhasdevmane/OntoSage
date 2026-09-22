# -*- coding: utf-8 -*-
"""Combine several evidence packs into one, de-duplicated by question.

Each pack is a directory written by ``capture_evidence_screenshots.py`` plus the hand-written
``review.json`` of verdicts. This merges them into a single pack a reader can open once:

  * a question asked in more than one pack appears ONCE -- the LAST pack listed wins, because the
    later capture ran on the later build;
  * every surviving screenshot is copied under a fresh number, so no file is overwritten and no
    two files share a name;
  * verdicts follow their question, and a question with no verdict is reported rather than assumed.

    python scripts/combine_evidence_packs.py --packs docs/a docs/b --out docs/combined

Nothing here names a building or a question: the packs are the input.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
_SLUG = re.compile(r"[^a-z0-9]+")


def slug(text: str, n: int = 48) -> str:
    return _SLUG.sub("-", text.lower()).strip("-")[:n] or "question"


def norm(question: str) -> str:
    """Two questions are the same when they read the same, ignoring case and punctuation."""
    return _SLUG.sub(" ", str(question or "").lower()).strip()


def load(pack: Path) -> Tuple[List[Dict], Dict[str, List[str]]]:
    rows = [json.loads(x) for x in (pack / "answers.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    review = pack / "review.json"
    verdicts = json.loads(review.read_text(encoding="utf-8")).get("verdicts", {}) if review.exists() else {}
    for r in rows:
        r["_pack"] = pack
        r["_verdict"] = verdicts.get(str(r["n"]), ["UNREVIEWED", ""])
    return rows, verdicts


#: The order families appear in the combined pack. A question whose shape matches none of these
#: keeps its place after the ones that do, so a new family is never silently dropped.
FAMILY_ORDER = (
    "Prediction", "Chart", "Deliberation", "A room or floor", "A comparison", "Comparison",
    "Diagnosis", "Anomaly", "Data quality", "Method", "A register", "Register", "Which ...",
    "Operations", "Is a room", "Asset state", "Spatial", "Where something is", "What the building",
    "A fault report", "A suggestion", "Refusal", "Decline", "Something the building",
)


def family_rank(shape: str) -> int:
    for i, fam in enumerate(FAMILY_ORDER):
        if str(shape or "").lower().startswith(fam.lower()):
            return i
    return len(FAMILY_ORDER)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", nargs="+", required=True, help="pack directories, earliest first")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    packs = [Path(p) for p in args.packs]
    out = Path(args.out)
    (out / "screenshots").mkdir(parents=True, exist_ok=True)

    # LAST pack wins for a repeated question: it ran on the later build.
    chosen: Dict[str, Dict] = {}
    dropped: List[Tuple[str, str]] = []
    for pack in packs:
        rows, _ = load(pack)
        for r in rows:
            key = norm(r["question"])
            if key in chosen:
                dropped.append((chosen[key]["_pack"].name, r["question"]))
            chosen[key] = r

    rows = sorted(chosen.values(), key=lambda r: (family_rank(r.get("shape", "")), r["question"]))

    merged, verdicts = [], {}
    for i, r in enumerate(rows, 1):
        name = f"{i:02d}_{slug(r['question'])}.png"
        src = r["_pack"] / r["screenshot"]
        if not src.exists():
            print(f"  MISSING screenshot for #{i}: {src}")
            continue
        shutil.copyfile(src, out / "screenshots" / name)
        merged.append({
            "n": i,
            "shape": r.get("shape", ""),
            "question": r["question"],
            "seconds": r.get("seconds", 0),
            "complete": r.get("complete", True),
            "answer": r.get("answer", ""),
            "screenshot": f"screenshots/{name}",
            "from_pack": r["_pack"].name,
        })
        verdicts[str(i)] = r["_verdict"]

    (out / "answers.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in merged) + "\n", encoding="utf-8")
    (out / "review.json").write_text(json.dumps(
        {"_comment": "Verdicts carried over from the source packs, keyed by the combined numbering.",
         "verdicts": verdicts}, ensure_ascii=False, indent=2), encoding="utf-8")

    names = [Path(m["screenshot"]).name for m in merged]
    print(f"packs merged: {[p.name for p in packs]}")
    print(f"questions kept: {len(merged)}   duplicates dropped: {len(dropped)}")
    for pack_name, q in dropped:
        print(f"   dropped the {pack_name} copy of: {q[:70]}")
    print(f"unique screenshot names: {len(set(names)) == len(names)}")
    unreviewed = [n for n, v in verdicts.items() if v[0] == "UNREVIEWED"]
    if unreviewed:
        print(f"NOTE: {len(unreviewed)} question(s) carry no verdict: {unreviewed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
