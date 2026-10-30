#!/usr/bin/env python3
"""Agreement between answer coders, and the adjudication list (TODO 3.4).

    python label_agreement.py coder1.csv coder2.csv [--out labels/agreement]
    python label_agreement.py coder1.csv coder2.csv --vs-ai     # also each human against the AI pre-labels

Each coder file is a filled copy of labels/answer_labels_human_template.csv (pass 1) or of
labels/rq2/blind_sheet_<set>.csv (pass 2): one row per answer, the id column ('answer_id' or 'blind_id') and 'label'.
Writes, in --out:
  agreement.json          percent agreement, Cohen's kappa with a 95% bootstrap CI (2,000 resamples over answers),
                          kappa per situation, and the same on the safety-relevant split (U vs not U)
  confusion.csv           coder 1 (rows) x coder 2 (columns)
  to_adjudicate.csv       every answer the coders labelled differently, with both labels and notes (to read)
  agreed_draft.csv        EVERY answer coder 1 labelled (coder 1 is the primary coder; coder 2 may have labelled only the
                          double-coding sample): 'agreed_label' and 'agreed_u_subtypes' are filled where the coders agree
                          or only coder 1 labelled, and left EMPTY where they disagree. Fill the empty ones, then run
                          finalise_agreed_labels.py, which writes the file the analysis picks up automatically
                          (labels/answer_labels_agreed.csv for pass 1; labels/rq2/_human/<set>_agreed.csv for pass 2).
The pre-registration asks for kappa on the full label set and on U vs not U; both are reported.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import LABELS, SEED  # noqa: E402

CATS = ["W", "WL", "FD", "U", "OT", "PF"]


def kappa(a: np.ndarray, b: np.ndarray) -> float:
    cats = sorted(set(a) | set(b))
    if len(a) == 0:
        return float("nan")
    po = float(np.mean(a == b))
    pe = sum(float(np.mean(a == c)) * float(np.mean(b == c)) for c in cats)
    return float("nan") if pe == 1 else (po - pe) / (1 - pe)


def boot_kappa(a: np.ndarray, b: np.ndarray, seed: int = SEED) -> tuple:
    rng = np.random.default_rng(seed)
    n = len(a)
    ks = []
    for _ in range(2000):
        i = rng.integers(0, n, n)
        ks.append(kappa(a[i], b[i]))
    ks = np.array([k for k in ks if k == k])
    return float(np.percentile(ks, 2.5)), float(np.percentile(ks, 97.5))


def load(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path, dtype=str).fillna("")
    idc = "answer_id" if "answer_id" in d.columns else "blind_id"
    d = d.rename(columns={idc: "id"})
    d["label"] = d["label"].str.strip().str.upper()
    bad = d[(d.label != "") & ~d.label.isin(CATS)]
    if len(bad):
        raise SystemExit(f"{path.name}: labels outside the rubric: {sorted(set(bad.label))}")
    return d


def compare(a: pd.DataFrame, b: pd.DataFrame, name_a: str, name_b: str, sit: pd.Series) -> dict:
    m = a[["id", "label"]].merge(b[["id", "label"]], on="id", suffixes=("_a", "_b"))
    m = m[(m.label_a != "") & (m.label_b != "")]
    x, y = m.label_a.values, m.label_b.values
    lo, hi = boot_kappa(x, y)
    ux, uy = (x == "U"), (y == "U")
    out = {"pair": f"{name_a} vs {name_b}", "n": int(len(m)), "percent_agreement": float(np.mean(x == y)),
           "kappa": kappa(x, y), "kappa_ci": [lo, hi], "kappa_U_vs_not_U": kappa(ux.astype(int), uy.astype(int)),
           "by_situation": {}}
    if sit is not None:
        m["situation"] = m.id.map(sit).fillna("")
        for s, g in m.groupby("situation"):
            out["by_situation"][s or "none"] = {"n": int(len(g)), "kappa": kappa(g.label_a.values, g.label_b.values),
                                                "agreement": float(np.mean(g.label_a.values == g.label_b.values))}
    return out, m


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("coder1")
    ap.add_argument("coder2")
    ap.add_argument("--out", default=str(LABELS / "agreement"))
    ap.add_argument("--vs-ai", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    c1, c2 = load(Path(args.coder1)), load(Path(args.coder2))
    sheet = LABELS / "labelling_sheet_pass1.csv"
    sit = pd.read_csv(sheet, dtype=str).fillna("").set_index("answer_id")["situation"] if sheet.exists() else None
    res, m = compare(c1, c2, "coder 1", "coder 2", sit)
    results = {"humans": res}
    pd.crosstab(m.label_a, m.label_b).to_csv(out / "confusion.csv")
    dis = m[m.label_a != m.label_b].copy()
    notes1 = c1.set_index("id").get("note", pd.Series(dtype=str))
    notes2 = c2.set_index("id").get("note", pd.Series(dtype=str))
    dis["note_coder1"] = dis.id.map(notes1).fillna("")
    dis["note_coder2"] = dis.id.map(notes2).fillna("")
    dis["agreed_label"] = ""
    dis.rename(columns={"label_a": "label_coder1", "label_b": "label_coder2"}).to_csv(out / "to_adjudicate.csv", index=False)
    idname = "answer_id" if "answer_id" in pd.read_csv(args.coder1, dtype=str, nrows=0).columns else "blind_id"
    one, two = c1.set_index("id"), c2.set_index("id")
    draft = one[one.label != ""][["label"]].rename(columns={"label": "label_coder1"})
    draft["label_coder2"] = two.label.reindex(draft.index).fillna("")
    for col in ("u_subtypes", "note", "confidence", "verified", "evidence_quote"):
        draft[f"{col}_coder1"] = one.get(col, pd.Series("", index=one.index)).reindex(draft.index).fillna("")
        draft[f"{col}_coder2"] = two.get(col, pd.Series("", index=two.index)).reindex(draft.index).fillna("")
    sub1 = draft.u_subtypes_coder1.str.split().map(lambda x: " ".join(sorted(x)))
    sub2 = draft.u_subtypes_coder2.str.split().map(lambda x: " ".join(sorted(x)))
    agree = (draft.label_coder2 == "") | (draft.label_coder1 == draft.label_coder2)
    draft["agreed_label"] = draft.label_coder1.where(agree, "")
    same_sub = (draft.label_coder2 == "") | (draft.label_coder1 != "U") | (sub1 == sub2)
    draft["agreed_u_subtypes"] = sub1.where(agree & same_sub, "")
    draft["to_settle"] = ["label" if not a else "sub-types" if not s else "" for a, s in zip(agree, same_sub)]
    draft["disputed"] = ""                 # settlement.py: 'yes' where the meeting could not agree (D7)
    draft.index.name = idname
    draft.to_csv(out / "agreed_draft.csv")
    print(f"agreed_draft.csv: {len(draft)} answers, {int((draft.agreed_label == '').sum())} labels and "
          f"{int(((draft.agreed_label == 'U') & (draft.agreed_u_subtypes == '')).sum())} U sub-types to adjudicate; "
          "where the meeting cannot agree, keep coder 1's label and write 'yes' under disputed")
    if args.vs_ai:
        # the AI file with the same ids: pass 1 answer_id, pass 2 blind_id (the blind sheet's AI parts)
        parts = ([LABELS / "answer_labels_ai_prelabel.csv"] if idname == "answer_id" else
                 sorted((LABELS / "rq2" / "_ai_parts").glob("comparison_*.csv")))
        if parts and all(p.exists() for p in parts):
            ai = pd.concat([load(p) for p in parts], ignore_index=True).drop_duplicates("id", keep="last")
            for name, c in (("coder 1", c1), ("coder 2", c2)):
                results[f"ai_vs_{name.replace(' ', '')}"] = compare(ai, c, "AI pre-label", name, sit)[0]
    (out / "agreement.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(json.dumps({k: {kk: v[kk] for kk in ("pair", "n", "percent_agreement", "kappa", "kappa_ci", "kappa_U_vs_not_U")}
                      for k, v in results.items()}, indent=1))
    print(f"{len(dis)} answers to adjudicate -> {out / 'to_adjudicate.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
