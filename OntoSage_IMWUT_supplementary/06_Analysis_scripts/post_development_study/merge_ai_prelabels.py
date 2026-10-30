#!/usr/bin/env python3
"""Merge the pass-1 AI pre-labels (one CSV per form in G_Study_Data/labels/_ai_parts/) into one checked file (TODO 3.2).

    python merge_ai_prelabels.py

Writes G_Study_Data/labels/answer_labels_ai_prelabel.csv and answer_labels_ai_prelabel_summary.json.

PROVISIONAL. These labels were assigned by an AI model (Claude) reading every answer in full against the frozen key
and the rubric (D_Coding_and_Scoring/PartB_Answer_Scoring_Rubric.md), with claims checked against the stores where
that took under two minutes. They are NOT the pre-registered human labels and must never be reported as such. The
analysis switches to labels/answer_labels_agreed.csv (two human coders, adjudicated) as soon as that file exists.

Checks, each fatal: every answer in the labelling sheet is labelled exactly once; nothing is labelled that is not on
the sheet; labels and U sub-types are from the rubric's sets; every U has a sub-type; every FD says what was held.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import LABELS, write_manifest  # noqa: E402

LABEL_SET = {"W", "WL", "U", "FD", "OT", "PF"}
SUBTYPES = {"scope", "proxy", "temporal", "fabricated", "criterion_drop", "causal", "wrong_value", "wrong_source"}
LABELLER = "AI pre-label (Claude Opus 5.5), PROVISIONAL - not a human label"
ALT = {"S2-1-standard": "WL", "S2-2-decline": "WL"}


def main() -> int:
    sheet = {r["answer_id"]: r for r in csv.DictReader((LABELS / "labelling_sheet_pass1.csv").open(encoding="utf-8"))}
    parts = sorted((LABELS / "_ai_parts").glob("*.csv"))
    rows, seen, errors = [], Counter(), []
    for p in parts:
        for r in csv.DictReader(p.open(encoding="utf-8")):
            a = r["answer_id"].strip()
            seen[a] += 1
            if a not in sheet:
                errors.append(f"{p.name}: {a} is not on the labelling sheet")
                continue
            lab = r["label"].strip()
            subs = [s for s in r["u_subtypes"].replace(";", " ").split() if s]
            if lab not in LABEL_SET:
                errors.append(f"{a}: label {lab!r}")
            if lab == "U" and not subs:
                errors.append(f"{a}: U without a sub-type")
            if any(s not in SUBTYPES for s in subs):
                errors.append(f"{a}: sub-type {subs}")
            if lab == "FD" and not r["fd_what_was_held"].strip():
                errors.append(f"{a}: FD without what was held")
            m = re.search(r"\[contested:([^\]]+)\]", r["note"])
            contested = m.group(1) if m else ""
            alt = ALT.get(contested, "")
            if not alt:
                m2 = re.search(r"Alternative label (W|WL|U|FD|OT)\b", r["note"]) or re.search(r"[Aa]rguably (W|WL|U|FD|OT)\b", r["note"])
                alt = m2.group(1) if m2 else ""
            s = sheet[a]
            rows.append({"answer_id": a, "turn_id": a, "code": s["code"], "role": s["role"], "form": s["form"],
                         "situation": s["situation"], "labeller": LABELLER, "label": lab, "u_subtypes": " ".join(subs),
                         "fd_what_was_held": r["fd_what_was_held"], "ot_what_instead": r["ot_what_instead"],
                         "wl_limit_stated": r["wl_limit_stated"], "panel_present": s["panel_present"],
                         "panel_supports_text": "", "panel_wrong": "", "verified": r["verified"],
                         "confidence": r["confidence"], "evidence_quote": r["evidence_quote"], "note": r["note"],
                         "contested_class": contested, "alt_label": alt})
    missing = [a for a, s in sheet.items() if s["role"] != "own_question" and a not in seen]
    dup = [a for a, n in seen.items() if n > 1]
    errors += [f"not labelled: {a}" for a in missing] + [f"labelled twice: {a}" for a in dup]
    own_missing = [a for a, s in sheet.items() if s["role"] == "own_question" and a not in seen]
    if errors:
        print("\n".join(errors[:40]))
        print(f"{len(errors)} errors; nothing written")
        return 1
    cols = list(rows[0].keys())
    with (LABELS / "answer_labels_ai_prelabel.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["answer_id"]))
    summ = {"labeller": LABELLER, "n_labelled": len(rows), "own_question_answers_not_yet_labelled": len(own_missing),
            "by_role_label": {}, "by_form_label": {}, "contested": Counter(r["contested_class"] for r in rows if r["contested_class"]),
            "with_alt_label": sum(1 for r in rows if r["alt_label"]),
            "confidence": Counter(r["confidence"] for r in rows), "verified": Counter(r["verified"] for r in rows)}
    for r in rows:
        summ["by_role_label"].setdefault(r["role"], Counter())[r["label"]] += 1
        if r["form"]:
            summ["by_form_label"].setdefault(r["form"], Counter())[r["label"]] += 1
    (LABELS / "answer_labels_ai_prelabel_summary.json").write_text(json.dumps(summ, indent=1, default=dict), encoding="utf-8")
    write_manifest(LABELS, {p.name: p for p in parts}, note="pass-1 AI pre-labels, PROVISIONAL")
    print(json.dumps({k: v for k, v in summ.items() if k != "by_form_label"}, indent=1, default=dict))
    for f in sorted(summ["by_form_label"]):
        print(f, dict(summ["by_form_label"][f]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
