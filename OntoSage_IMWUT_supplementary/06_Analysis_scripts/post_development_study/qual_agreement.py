#!/usr/bin/env python3
"""Agreement on the multi-label Part C codes, and the agreed file (Agreement_and_Adjudication_Procedure.md).

    python qual_agreement.py coder1_qual.csv coder2_qual.csv [--out labels/qual/agreement]
    python qual_agreement.py --finalise labels/qual/agreement/agreed_draft.csv

Each coder file: unit_id plus one 1/0 column per codebook code (qual_coding_sheet.csv's columns), and optionally
'inductive' and 'note'. Coder 1 is the author (all units); coder 2 the seeded sample. Writes, in --out:
  agreement.json      per-code Cohen's kappa and raw agreement over the units both coded, and overall raw agreement
  disagreements.csv   unit, code, coder 1, coder 2, the text
  agreed_draft.csv    coder 1's codes, with every code the coders disagree on left EMPTY to adjudicate
--finalise checks that no code is empty and that a unit marked disputed keeps coder 1's codes (plan 19 D7), writes
labels/qual/qual_codes_agreed.csv, which qual_analysis.py then uses automatically (label_source HUMAN_AGREED), and
settlement.json beside the draft (settlement.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settlement  # noqa: E402
from recode_qual_to_codebook import CLOSING, REASON  # noqa: E402
from study_paths import LABELS  # noqa: E402

CODES = REASON + CLOSING


def kappa(a: np.ndarray, b: np.ndarray) -> float:
    po = float(np.mean(a == b))
    pe = sum(float(np.mean(a == c)) * float(np.mean(b == c)) for c in (0, 1))
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--out", default=str(LABELS / "qual" / "agreement"))
    ap.add_argument("--finalise", default="")
    ap.add_argument("--to", default="", help="with --finalise: write here instead of labels/qual/ (for tests)")
    args = ap.parse_args()
    sheet = pd.read_csv(LABELS / "qual" / "qual_coding_sheet.csv", dtype=str).fillna("").set_index("unit_id")
    if args.finalise:
        d = pd.read_csv(args.finalise, dtype=str).fillna("")
        kind = sheet["unit"].to_dict()
        empty = [(r.unit_id, c) for r in d.itertuples()
                 for c in (REASON if kind.get(r.unit_id) == "task_reason" else CLOSING) if c in d and getattr(r, c) == ""]
        missing = sorted(set(sheet.index) - set(d.unit_id))
        if empty or missing:
            print(f"not finished: {len(empty)} empty codes (first {empty[:5]}), {len(missing)} units missing")
            return 1
        draft = Path(args.finalise)
        dis_p = draft.parent / "disagreements.csv"
        dis = pd.read_csv(dis_p, dtype=str).fillna("") if dis_p.exists() and dis_p.stat().st_size > 1 else pd.DataFrame(
            columns=["unit_id", "code", "coder1"])
        rows = d.to_dict("records")
        errs = settlement.kept_first_author(rows, "unit_id", {(r.unit_id, r.code): r.coder1 for r in dis.itertuples()})
        if errs:
            print("not written:\n  " + "\n  ".join(errs[:30]))
            return 1
        out = Path(args.to) if args.to else LABELS / "qual" / "qual_codes_agreed.csv"
        d.drop(columns=[c for c in ("to_settle", "disputed") if c in d]).to_csv(out, index=False, lineterminator="\n")
        print(f"{len(d)} units -> {out}")
        both = json.loads((draft.parent / "agreement.json").read_text(encoding="utf-8")).get("units_both_coded", 0) \
            if (draft.parent / "agreement.json").exists() else 0
        settlement.write(draft, "reasons", both, dis.unit_id, settlement.disputed_ids(rows, "unit_id"))
        return 0
    c1, c2 = (pd.read_csv(f, dtype=str).fillna("").set_index("unit_id") for f in args.files)
    both = sorted(set(c1.index) & set(c2.index))
    res, dis = {"units_both_coded": len(both), "per_code": {}}, []
    agree_cells = total_cells = 0
    for c in CODES:
        if c not in c1 or c not in c2:
            continue
        rel = [u for u in both if (sheet.loc[u, "unit"] == "task_reason") == (c in REASON)]
        if not rel:
            continue
        a = pd.to_numeric(c1.loc[rel, c], errors="coerce").fillna(0).astype(int).values
        b = pd.to_numeric(c2.loc[rel, c], errors="coerce").fillna(0).astype(int).values
        k = kappa(a, b)
        res["per_code"][c] = {"n": len(rel), "kappa": None if k != k else k, "agreement": float(np.mean(a == b)),
                              "coder1_yes": int(a.sum()), "coder2_yes": int(b.sum()),
                              **({"note": "kappa undefined: neither coder varied on this code"} if k != k else {})}
        agree_cells += int((a == b).sum())
        total_cells += len(rel)
        dis += [{"unit_id": u, "code": c, "coder1": int(x), "coder2": int(y), "text": sheet.loc[u, "text"]}
                for u, x, y in zip(rel, a, b) if x != y]
    res["overall_raw_agreement"] = agree_cells / total_cells if total_cells else float("nan")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "agreement.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    pd.DataFrame(dis).to_csv(out / "disagreements.csv", index=False)
    draft = c1.copy()
    draft["to_settle"], draft["disputed"] = "", ""        # settlement.py: 'yes' where the meeting cannot agree (D7)
    for row in dis:
        draft.loc[row["unit_id"], row["code"]] = ""
        draft.loc[row["unit_id"], "to_settle"] = " ".join(x for x in (draft.loc[row["unit_id"], "to_settle"], row["code"]) if x)
    draft.reset_index().to_csv(out / "agreed_draft.csv", index=False, lineterminator="\n")
    print(json.dumps({"units_both_coded": len(both), "overall_raw_agreement": res["overall_raw_agreement"],
                      "kappa": {k: (round(v["kappa"], 2) if v["kappa"] is not None else None)
                                for k, v in res["per_code"].items()}}, indent=1))
    print(f"{len(dis)} code disagreements -> {out / 'disagreements.csv'}; fill them in agreed_draft.csv, then --finalise")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
