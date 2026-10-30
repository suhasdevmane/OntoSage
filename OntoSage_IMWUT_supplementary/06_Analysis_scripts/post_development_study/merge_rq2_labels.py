#!/usr/bin/env python3
"""Merge the blind RQ2 pre-labels and unblind them (TODO 5.1).

    python merge_rq2_labels.py ttask [comparison stability ...]

For each set: reads labels/rq2/_ai_parts/<set>_NN.csv (labels made on the blind sheet), checks every blind_id on
blind_sheet_<set>.csv is labelled exactly once with a rubric label, then joins the unblinding key and writes
labels/rq2/rq2_labels_<set>.csv (system, qid, run, attempt, label, sub-types, confidence, the [empty-answer] and
[contested] flags). PROVISIONAL: AI pre-labels made on the blind sheet, not the pre-registered human labels.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import LABELS  # noqa: E402

RQ2 = LABELS / "rq2"
LABEL_SET = {"W", "WL", "U", "FD", "OT", "PF"}
SUBTYPES = {"scope", "proxy", "temporal", "fabricated", "criterion_drop", "causal", "wrong_value", "wrong_source"}
ALT = {"S2-1-standard": "WL", "S2-2-decline": "WL"}


def merge(name: str) -> int:
    sheet = {r["blind_id"]: r for r in csv.DictReader((RQ2 / f"blind_sheet_{name}.csv").open(encoding="utf-8"))}
    key = {r["blind_id"]: r for r in csv.DictReader((RQ2 / f"_unblinding_key_{name}.csv").open(encoding="utf-8"))}
    got, errors = {}, []
    human = RQ2 / "_human" / f"{name}_agreed.csv"      # finalise_agreed_labels.py pass2; preferred when present
    author = RQ2 / "_author" / f"{name}_author.csv"    # author_check/export_checked.py (plan 19, Option A)
    if human.exists():
        parts, labeller = [human], ("HUMAN_AGREED (AI proposals reviewed by the first author; the second coder's "
                                    "sampled disagreements settled)")
    elif author.exists():
        parts, labeller = [author], "AUTHOR_CHECKED (the first author checked every AI pre-label; second coder pending)"
    else:
        parts = sorted((RQ2 / "_ai_parts").glob(f"{name}_*.csv"))
        labeller = "AI pre-label (Claude Opus 5.5) on the blind sheet, PROVISIONAL"
    for p in parts:
        for r in csv.DictReader(p.open(encoding="utf-8")):
            b = r["blind_id"].strip()
            if b in got:
                errors.append(f"{b} labelled twice")
            if b not in sheet:
                errors.append(f"{b} not on the sheet")
            lab = r["label"].strip()
            subs = r["u_subtypes"].split()
            if lab not in LABEL_SET:
                errors.append(f"{b}: label {lab!r}")
            if lab == "U" and not subs:
                errors.append(f"{b}: U without sub-type")
            if any(s not in SUBTYPES for s in subs):
                errors.append(f"{b}: sub-type {subs}")
            got[b] = r
    missing = sorted(set(sheet) - set(got))
    errors += [f"not labelled: {b}" for b in missing]
    if errors:
        print(f"{name}: " + "; ".join(errors[:30]))
        return 1
    rows = []
    for b, r in got.items():
        k, s = key[b], sheet[b]
        m = re.search(r"\[contested:([^\]]+)\]", r["note"])
        contested = m.group(1) if m else ""
        m2 = re.search(r"Alternative label (W|WL|U|FD|OT)\b", r["note"])
        alt = ALT.get(contested) or (m2.group(1) if m2 else "")
        rows.append({"blind_id": b, "set_name": name, "system": k["system"], "qid": k["qid"], "question_set": k["set"],
                     "run": k["run"], "attempt": k["attempt"], "form": s["form"], "situation": s["form"][:2] if s["form"] else "",
                     "label": r["label"], "u_subtypes": r["u_subtypes"], "confidence": r["confidence"],
                     "verified": r["verified"], "empty_answer": int("[empty-answer]" in r["note"]),
                     "contested_class": contested, "alt_label": alt, "seconds": k["seconds"], "error": k["error"],
                     "provider_failure": k["provider_failure"], "evidence_quote": r["evidence_quote"], "note": r["note"],
                     "labeller": labeller})
    rows.sort(key=lambda r: (r["qid"], int(r["run"]), r["system"]))
    with (RQ2 / f"rq2_labels_{name}.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    by = {}
    for r in rows:
        by.setdefault(r["system"], {}).setdefault(r["label"], 0)
        by[r["system"]][r["label"]] += 1
    print(f"{name}: {len(rows)} labels merged ({labeller.split(' ')[0]}); by system: {by}")
    return 0


if __name__ == "__main__":
    raise SystemExit(max(merge(n) for n in sys.argv[1:]))
