#!/usr/bin/env python3
"""Move the first-pass AI codes onto the Part C codebook's own codes (D_Coding_and_Scoring/PartC_Reasons_Codebook.md).

    python recode_qual_to_codebook.py

The first pass (labels/qual/_ai_parts/qual_0*.csv) used the plan's short list of deductive codes. The codebook names
them differently and adds LIMIT_MATCH, DECLINE_ACCEPTED, PRIOR_KNOWLEDGE, GUESS and OTHER for the reasons, and a
separate set for the closing answers (USEFUL_*, FRUST_*, DECLINE_*, YES_FALSE_IMPRESSION / NO / UNSURE). This script
maps the first pass onto those codes by written rules (below) plus a short list of per-unit decisions, and writes
labels/qual/_ai_parts/codebook_reasons.csv and codebook_closing.csv. The first pass moves to _ai_parts_v0_plan_names/.
Still PROVISIONAL AI pre-codes; the author codes everything and the second coder a seeded 20%.

LIMIT_MATCH follows the key: S1 (all held), S1-3, S4-1 and S4-3 have no true limit, so any stated absence there is a
mismatch; S2-1 (only Floor 5 measured), S2-2 (booking status not held), S2-3 (capacity not recorded), S3 (not held)
and S4-2 (readings missing) have one, and a stated limit of that kind matches.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import LABELS  # noqa: E402

Q = LABELS / "qual"
PARTS = Q / "_ai_parts"
OLD = Q / "_ai_parts_v0_plan_names"
REASON = ["EVIDENCE_CITED", "LIMIT_RECOGNISED", "LIMIT_MATCH", "PROXY_ACCEPTED", "VERIFY_INTENDED", "FLUENCY_CUE",
          "DECLINE_FRUSTRATION", "DECLINE_ACCEPTED", "REPHRASED", "PRIOR_KNOWLEDGE", "GUESS", "OTHER"]
CLOSING = ["USEFUL_SPECIFIC_VALUES", "USEFUL_EVIDENCE", "USEFUL_HONEST_LIMITS", "USEFUL_SPEED", "USEFUL_EASE",
           "FRUST_DECLINES", "FRUST_SLOW", "FRUST_JARGON", "FRUST_WRONG", "FRUST_TOO_LONG", "FRUST_NEEDED_REPHRASING",
           "DECLINE_USEFUL", "DECLINE_FRUSTRATING", "DECLINE_DEPENDS", "YES_FALSE_IMPRESSION", "NO", "UNSURE"]
ABSENCE = re.compile(r"\bno (records?|data|co2|people|occupancy|measurements?|pressure|history|ventilation|information|"
                     r"such|sensor|seat)|not (recorded|available|present|measured|added|stored|included)|"
                     r"does ?n[o']?t (have|record|store|know|kept|keep)|doesnt|missing|absent|half (of )?the data|"
                     r"unava|can'?t (tell|give)|cannot|could not|couldn'?t|refused|not enough|lack", re.I)
TRUE_LIMIT = {"S2-1", "S2-2", "S2-3", "S3-1", "S3-2", "S3-3", "S4-2"}
# per-unit decisions where a rule would misread the reason (unit: {code: value}), each with its reason in NOTES
OVERRIDE = {
    "P04-t6": {"LIMIT_MATCH": 0}, "P05-t6": {"LIMIT_MATCH": 0},          # vague 'not enough data', not the capacity
    "P03-t6": {"LIMIT_MATCH": 1}, "P17-t6": {"LIMIT_MATCH": 1},          # S3-3: room not present / not in the system
    "P21-t1": {"LIMIT_RECOGNISED": 1, "LIMIT_MATCH": 1},                 # 'there was no room'
    "P23-t6": {"LIMIT_RECOGNISED": 1, "LIMIT_MATCH": 1, "DECLINE_ACCEPTED": 1},
    "P06-t6": {"LIMIT_RECOGNISED": 0, "LIMIT_MATCH": 0},                 # complains about the date, no limit named
    "P06-t4": {"PRIOR_KNOWLEDGE": 1}, "P21-t6": {"PRIOR_KNOWLEDGE": 1}, "P26-t1": {"PRIOR_KNOWLEDGE": 1},
    "P08-t3": {"LIMIT_RECOGNISED": 0, "LIMIT_MATCH": 0},                 # says the data exist but were not linked
    "P14-t2": {"LIMIT_MATCH": 0},                                         # 'reading but not recommendation'
}
CL_RULES = {
    "USEFUL_SPECIFIC_VALUES": r"accura|nice results|good replies|gives good|when all data is present",
    "USEFUL_EVIDENCE": r"evidence|evidance|proof|how i know|reference|sources|chart",
    "USEFUL_HONEST_LIMITS": r"do not include things that are not supported",
    "USEFUL_EASE": r"clear|well written|well explained|description|summary|details in answer",
    "FRUST_DECLINES": r"unavail|unavaiab|not added|missin[gd] data|no results|less answers|could not get|can not be answered|disappoint|that's the problem",
    "FRUST_SLOW": r"more time|slow",
    "FRUST_JARGON": r"technical details",
    "FRUST_TOO_LONG": r"overly complex",
    "FRUST_WRONG": r"inability to understand|wasn'?t properly checking|partially supported|got confused|unrelated answer",
    "FRUST_NEEDED_REPHRASING": r"paraphras|paraphas|different words|rephrased|needs input|asking in different|asked in different",
    "DECLINE_USEFUL": r"somehow useful|^useful\.?$",
    "DECLINE_FRUSTRATING": r"frustrat|disappoint",
}


def main() -> int:
    sheet = pd.read_csv(Q / "qual_coding_sheet.csv", dtype=str).fillna("")
    if not OLD.exists():
        OLD.mkdir(parents=True)
        for p in sorted(PARTS.glob("qual_0*.csv")):
            shutil.move(str(p), OLD / p.name)
    old = pd.concat([pd.read_csv(p, dtype=str).fillna("") for p in sorted(OLD.glob("qual_0*.csv"))]).set_index("unit_id")
    rows_r, rows_c = [], []
    for s in sheet.itertuples():
        o = old.loc[s.unit_id]
        tags = [t for t in o.inductive.split(";") if t]
        text = s.text
        if s.unit == "task_reason":
            r = {c: 0 for c in REASON}
            r["EVIDENCE_CITED"] = int(o.evidence_cited or 0)
            r["LIMIT_RECOGNISED"] = int(int(o.limit_recognised or 0) or "believed_the_absence" in tags or bool(ABSENCE.search(text)))
            r["PROXY_ACCEPTED"] = int(o.proxy_accepted or 0)
            r["VERIFY_INTENDED"] = int(o.verification_intended or 0)
            r["FLUENCY_CUE"] = int(o.fluency_detail_cue or 0)
            r["DECLINE_FRUSTRATION"] = int(o.decline_frustration or 0)
            r["REPHRASED"] = int(o.rephrasing_strategy or 0)
            # the participant guessed (not 'it can't tell or guess', which is about the answer)
            r["GUESS"] = int(bool(re.search(r"\bi (just )?guess|guessed|at random|randomly|just picked", text, re.I)))
            r.update(OVERRIDE.get(s.unit_id, {}))
            if "LIMIT_MATCH" not in OVERRIDE.get(s.unit_id, {}):
                r["LIMIT_MATCH"] = int(bool(r["LIMIT_RECOGNISED"]) and s.form in TRUE_LIMIT)
            if "DECLINE_ACCEPTED" not in OVERRIDE.get(s.unit_id, {}):
                r["DECLINE_ACCEPTED"] = int(bool(r["LIMIT_RECOGNISED"]) and "doubted_the_absence" not in tags
                                            and (s.answer_received in ("FD", "WL") or "believed_the_absence" in tags
                                                 or "read_refusal_as_honesty" in tags))
            if not any(r[c] for c in REASON if c != "OTHER") and text and "no_reason" not in tags:
                r["OTHER"] = 1
            rows_r.append({"unit_id": s.unit_id, **r, "inductive": o.inductive, "note": o.note})
        else:
            c = {k: 0 for k in CLOSING}
            for k, pat in CL_RULES.items():
                c[k] = int(bool(re.search(pat, text, re.I)))
            if s.unit != "CL2":              # the DECLINE_* codes belong to CL2 only (codebook section B)
                for k in ("DECLINE_USEFUL", "DECLINE_FRUSTRATING", "DECLINE_DEPENDS"):
                    c[k] = 0
            if s.unit == "CL3":
                c = {k: 0 for k in CLOSING}
                low = text.strip().lower()
                if low in ("no", "noh", "na"):
                    c["NO"] = 1
                elif low == "yes":
                    c["YES_FALSE_IMPRESSION"] = 1
                elif "unsure" in low:
                    c["UNSURE"] = 1
                elif low:
                    c["NO"] = 1           # 'it is checking all data present, looks like' (tag: assumed_checked)
            rows_c.append({"unit_id": s.unit_id, **c, "inductive": o.inductive, "note": o.note})
    pd.DataFrame(rows_r).to_csv(PARTS / "codebook_reasons.csv", index=False, lineterminator="\n")
    pd.DataFrame(rows_c).to_csv(PARTS / "codebook_closing.csv", index=False, lineterminator="\n")
    r, c = pd.DataFrame(rows_r), pd.DataFrame(rows_c)
    print("reasons:", {k: int(r[k].sum()) for k in REASON})
    print("closing:", {k: int(c[k].sum()) for k in CLOSING})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
