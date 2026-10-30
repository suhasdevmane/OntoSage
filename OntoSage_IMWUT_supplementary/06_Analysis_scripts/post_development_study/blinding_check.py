#!/usr/bin/env python3
"""Blinding check for the pass-2 (offline) labels (plan 03 section 7.5; rubric "Blinding in pass 2").

    python blinding_check.py SHEET [SHEET ...] [--set comparison]

Each SHEET is a coder's filled blind sheet (the blind_sheet_<set>.csv columns, with identity_guess filled after
labelling each answer: A, B or can't tell). Run it only AFTER the labels are locked: it opens the unblinding key.

A guess is correct when it names the right family: OntoSage for OntoSage and for OntoSage with two checks off
(A-minus), Assistant B for B. The plan's rule: if coders identify the system most of the time, the paper says the
scoring was not effectively blind and reports the high-confidence-only sensitivity beside the main result.

Writes results/rq2/blinding_check.csv (per coder and system) and results/rq2/numbers_blinding.csv.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import LABELS, RESULTS  # noqa: E402


def norm_guess(g: str) -> str:
    g = re.sub(r"[^a-z]", "", str(g).lower())
    if g in ("a", "ontosage", "aminus"):
        return "A"
    if g in ("b", "assistantb", "baseline"):
        return "B"
    if g in ("cant", "canttell", "cannottell", "unsure", "dontknow", "ct", "x", "notsure"):
        return "can't tell"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sheets", nargs="+")
    ap.add_argument("--set", default="comparison")
    a = ap.parse_args()
    key = pd.read_csv(LABELS / "rq2" / f"_unblinding_key_{a.set}.csv", dtype=str).fillna("")
    key = key.sort_values("attempt").drop_duplicates("blind_id", keep="last").set_index("blind_id")
    rows, nums = [], []
    for sheet in a.sheets:
        d = pd.read_csv(sheet, dtype=str).fillna("")
        if "identity_guess" not in d:
            print(f"{sheet}: no identity_guess column")
            return 1
        d["guess"] = d.identity_guess.map(norm_guess)
        d = d[d.blind_id.isin(key.index) & (d.guess != "")]
        d["system"] = d.blind_id.map(key["system"])
        d["family"] = d.system.map(lambda s: "B" if s == "B" else "A")
        d["correct"] = d.guess == d.family
        coder = Path(sheet).stem
        for s, g in [("all", d)] + list(d.groupby("system")):
            rows.append({"coder": coder, "system": s, "guessed": int(len(g)),
                         "correct": int(g.correct.sum()), "cant_tell": int((g.guess == "can't tell").sum()),
                         "correct_share": round(float(g.correct.mean()), 3) if len(g) else None,
                         "correct_share_of_those_who_guessed": round(float(g[g.guess != "can't tell"].correct.mean()), 3)
                         if (g.guess != "can't tell").any() else None})
        allr = rows[-(1 + d.system.nunique())]
        nums.append({"key": f"blinding_{coder}_correct", "value": f"{allr['correct']} of {allr['guessed']} "
                     f"({100 * (allr['correct_share'] or 0):.0f}%); can't tell {allr['cant_tell']}",
                     "description": f"blinding check, {a.set} set, coder {coder}: identity guesses naming the right "
                                    "system family (OntoSage+ incl. two-checks-off, or Assistant B)",
                     "script": "blinding_check.py", "label_source": "SECOND_CODER"})
    out = RESULTS / "rq2"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "blinding_check.csv", index=False)
    pd.DataFrame(nums).to_csv(out / "numbers_blinding.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))
    print("If coders name the system most of the time, say the scoring was not effectively blind and report the "
          "high-confidence-only sensitivity (rq2 results: sens_high_confidence_pairs).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
