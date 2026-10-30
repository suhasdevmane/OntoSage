#!/usr/bin/env python3
"""Coding sheet for the qualitative analysis (plan 03 section 8.10; TODO 4.13).

    python make_qual_sheet.py

Units: every per-task reason (T*_R: "In a few words: why, and is there anything you would still check?", 180) and
every closing answer (CL1 most useful / most frustrating; CL2 'could not establish' useful or frustrating; CL3 an
answer that made you think something had been checked, 90). Writes, in G_Study_Data/labels/qual/:
  qual_coding_sheet.csv        one row per unit with its context (form, situation, decision kind, correct, answer
                               received, would act) and an empty 1/0 column per code of the Part C codebook
                               (D_Coding_and_Scoring/PartC_Reasons_Codebook.md: section A for reasons, B for closing
                               answers), inductive tags, note
  _reading/qual_<group>.md      the same units grouped for reading (by form; closing answers by question)
The second coder's seeded 20% is drawn with draw_double_coding_sample.py, once, after the author's sheet is complete
(codebook; command in 18_Human_Labelling_Guide.md). It is not drawn here.
The texts are participants' own words from the de-identified dataset (no names). Every participant ticked consent
statement C7 (anonymous verbatim quotes may be used; the app does not proceed without all nine statements).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import DEID, LABELS, RESULTS  # noqa: E402
from rq3_live_analysis import failure_kind  # noqa: E402
import analysis_rq3 as base  # noqa: E402

Q = LABELS / "qual"
from recode_qual_to_codebook import CLOSING, REASON  # noqa: E402  (the codebook's codes, one list each)

CODES = REASON + CLOSING
CL_TEXT = {"CL1": "What did you find most useful, and what most frustrating, about the answers?",
           "CL2": "When OntoSage said it could not establish something, was that useful or frustrating? Why?",
           "CL3": "Did any answer make you think something had been checked when you were not sure it had?"}


def main() -> int:
    Q.mkdir(parents=True, exist_ok=True)
    (Q / "_reading").mkdir(exist_ok=True)
    dec = pd.read_csv(DEID / "decisions.csv", dtype={"option": str})
    lab = RESULTS / "rq3" / "decisions_with_labels.csv"
    recv = pd.read_csv(lab, dtype=str).set_index(["code", "position"])["answer_received"] if lab.exists() else None
    roles = base.s3_option_roles()
    rows = []
    for r in dec.itertuples():
        kind = failure_kind(r.warranted, r.failure if isinstance(r.failure, str) else "")
        if r.situation == "S3" and roles.get(r.form, {}).get(str(r.option).strip().lower()) == "no_conclusion":
            kind = "warranted, no conclusion"
        ar = recv.get((r.code, str(r.position)), "") if recv is not None else ""
        rows.append({"unit_id": f"{r.code}-t{r.position}", "code": r.code, "unit": "task_reason", "form": r.form,
                     "situation": r.situation, "decision_kind": kind, "correct": int(r.warranted),
                     "answer_received": ar, "would_act": r.would_act, "confidence": r.confidence,
                     "text": str(r.reason or "").strip()})
    par = pd.read_csv(DEID / "participants.csv", dtype=str).fillna("")
    for r in par.itertuples():
        for k in CL_TEXT:
            t = str(getattr(r, k) or "").strip()
            rows.append({"unit_id": f"{r.code}-{k}", "code": r.code, "unit": k, "form": "", "situation": "",
                         "decision_kind": "", "correct": "", "answer_received": "", "would_act": "", "confidence": "",
                         "text": t})
    d = pd.DataFrame(rows)
    for c in CODES:
        d[c] = ""
    d["inductive"] = ""
    d["note"] = ""
    d.to_csv(Q / "qual_coding_sheet.csv", index=False, lineterminator="\n")
    (Q / "qual_second_coder_ids.csv").unlink(missing_ok=True)   # an earlier unstratified draw; see the docstring
    for g, sub in [(f, d[d.form == f]) for f in sorted(d.form.unique()) if f] + [(k, d[d.unit == k]) for k in CL_TEXT]:
        lines = [f"# {g}" + (f": {CL_TEXT[g]}" if g in CL_TEXT else ""), ""]
        for r in sub.itertuples():
            ctx = "" if r.unit in CL_TEXT else f" · {r.decision_kind} · correct={r.correct} · answer={r.answer_received or '-'}"
            lines.append(f"- **{r.unit_id}**{ctx}: {r.text}")
        (Q / "_reading" / f"qual_{g}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(d)} units ({(d.unit == 'task_reason').sum()} reasons, {(d.unit != 'task_reason').sum()} closing); "
          f"empty texts: {(d.text == '').sum()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
