#!/usr/bin/env python3
"""Turn an adjudicated agreed_draft.csv (label_agreement.py) into the label file the analyses read (TODO 3.4).

    python finalise_agreed_labels.py pass1 labels/agreement/agreed_draft.csv
    python finalise_agreed_labels.py pass2 comparison labels/agreement_comparison/agreed_draft.csv

pass1 -> labels/answer_labels_agreed.csv. rq3_live_analysis.py prefers it to the AI pre-labels and marks every
         label-based output HUMAN_AGREED.
pass2 -> labels/rq2/_human/<set>_agreed.csv, in the blind-sheet format. merge_rq2_labels.py prefers it to the AI
         pre-labels in _ai_parts/ and writes labeller = HUMAN_AGREED; rq2_live_analysis.py then reports HUMAN_AGREED.
Refuses to write anything while an agreed_label is empty, a label is outside the rubric, a U has no sub-type, or a
disputed row's final label does not match either (a) a sibling resolution_log.csv's logged resolution for that id,
or (b) coder 1's label where no such discussion was logged (plan 19 D7 fallback). Writes settlement.json beside the
draft (settlement.py): items both coded, items the coders disagreed on, items resolved by discussion per coder,
items still defaulted by the fallback.
The [contested] flags and alternative labels belong to the AI pre-labels and are not carried over.

Coder 1 is the first author's review of every AI proposal (plan 19, Option A) and coder 2 labelled a seeded sample,
so the agreed file is the reviewed labels with the sample's disagreements settled; HUMAN says exactly that.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settlement  # noqa: E402
from study_paths import LABELS  # noqa: E402

LABEL_SET = {"W", "WL", "FD", "U", "OT", "PF"}
SUBTYPES = {"scope", "proxy", "temporal", "fabricated", "criterion_drop", "causal", "wrong_value", "wrong_source"}
HUMAN = "HUMAN_AGREED (AI proposals reviewed by the first author; the second coder's sampled disagreements settled)"


def check(d: pd.DataFrame, idc: str) -> list:
    errs = []
    for r in d.itertuples():
        i, lab, subs = getattr(r, idc), r.agreed_label.strip().upper(), r.agreed_u_subtypes.split()
        if not lab:
            errs.append(f"{i}: agreed_label empty")
        elif lab not in LABEL_SET:
            errs.append(f"{i}: label {lab!r}")
        if lab == "U" and not subs:
            errs.append(f"{i}: U without sub-type")
        if any(s not in SUBTYPES for s in subs):
            errs.append(f"{i}: sub-type {subs}")
    return errs


def main() -> int:
    argv = sys.argv[1:]
    out_override = None
    if "--out" in argv:                      # for testing only: write somewhere other than the labels folder
        i = argv.index("--out")
        out_override = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if len(argv) < 2 or argv[0] not in ("pass1", "pass2") or (argv[0] == "pass2" and len(argv) < 3):
        print(__doc__)
        return 2
    mode = argv[0]
    draft = Path(argv[-1])
    d = pd.read_csv(draft, dtype=str).fillna("")
    idc = "answer_id" if mode == "pass1" else "blind_id"
    if idc not in d.columns:
        print(f"{draft.name} has no {idc} column")
        return 2
    errs = check(d, idc)
    rows = d.to_dict("records")
    resolved = settlement.load_resolution_log(draft)
    if "label_coder1" in d:                  # a disputed row keeps coder 1's label and sub-types, unless a
        first = {}                           # discussion resolved it otherwise (resolution_log.csv) -- D7 fallback
        for r in rows:
            first[(r[idc], "agreed_label")] = r["label_coder1"].strip().upper()
            if r["label_coder1"].strip().upper() == "U":
                first[(r[idc], "agreed_u_subtypes")] = " ".join(sorted(r.get("u_subtypes_coder1", "").split()))
        errs += settlement.kept_first_author(rows, idc, first, resolved=resolved,
                                             norm=lambda s: " ".join(sorted(s.strip().upper().split())))
    if errs:
        print(f"{len(errs)} problems, nothing written:\n  " + "\n  ".join(errs[:40]))
        return 1
    d["label"] = d.agreed_label.str.strip().str.upper()
    d["u_subtypes"] = d.agreed_u_subtypes.str.strip()
    d["note"] = (d.get("note_coder1", "") + " | " + d.get("note_coder2", "")).str.strip(" |")
    # confidence/verified/evidence_quote are never a disagreement -- only label and u_subtypes are settled by D7 --
    # so the first author's own value is the right one to carry through, not a blank (28 Oct, found while A5's
    # blinding check needed a real confidence column and found every row empty)
    for c in ("confidence", "verified", "evidence_quote"):
        d[c] = d.get(f"{c}_coder1", pd.Series("", index=d.index)).fillna("")
    if mode == "pass1":
        sheet = pd.read_csv(LABELS / "labelling_sheet_pass1.csv", dtype=str).fillna("").set_index("answer_id")
        missing = sorted(set(sheet.index) - set(d.answer_id))
        if missing:
            print(f"{len(missing)} answers on the labelling sheet have no agreed label (first: {missing[:5]}); nothing written")
            return 1
        out = pd.DataFrame({"answer_id": d.answer_id, "turn_id": d.answer_id})
        for c in ("code", "role", "form", "situation"):
            out[c] = d.answer_id.map(sheet[c])
        out["labeller"] = HUMAN
        out["label"], out["u_subtypes"] = d.label.values, d.u_subtypes.values
        out["confidence"], out["note"], out["contested_class"], out["alt_label"] = d.confidence.values, d.note.values, "", ""
        path = LABELS / "answer_labels_agreed.csv"
    else:
        name = argv[1]
        sheet = pd.read_csv(LABELS / "rq2" / f"blind_sheet_{name}.csv", dtype=str).fillna("")
        missing = sorted(set(sheet.blind_id) - set(d.blind_id))
        if missing:
            print(f"{len(missing)} answers on blind_sheet_{name}.csv have no agreed label; nothing written")
            return 1
        out = pd.DataFrame({"blind_id": d.blind_id, "label": d.label, "u_subtypes": d.u_subtypes})
        for c in ("fd_what_was_held", "ot_what_instead", "wl_limit_stated"):
            out[c] = ""
        out["verified"], out["confidence"], out["evidence_quote"] = d.verified.values, d.confidence.values, d.evidence_quote.values
        out["note"] = d.note.values
        path = LABELS / "rq2" / "_human" / f"{name}_agreed.csv"
    path = out_override or path
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, lineterminator="\n")
    print(f"{len(out)} agreed labels -> {path}")
    print(out.label.value_counts().to_string())
    both = d[d.get("label_coder2", pd.Series("", index=d.index)).str.strip() != ""] if "label_coder2" in d else d.iloc[0:0]
    settle = d[d.get("to_settle", pd.Series("", index=d.index)).str.strip() != ""] if "to_settle" in d else d.iloc[0:0]
    settlement.write(draft, "answers_live" if mode == "pass1" else f"answers_offline_{argv[1]}", len(both),
                     settle[idc], settlement.disputed_ids(rows, idc), resolved=resolved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
