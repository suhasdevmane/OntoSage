#!/usr/bin/env python3
"""RQ3 exploratory "Phrasing": the first question's place / time / criterion specification against the label of the
first answer (Analysis_Specification section 2).

    python phrasing_analysis.py

Deterministic, no coder: each study form's goal card names exactly which place, date and criterion its answer
needs, so a first question is checked for those specifics by pattern (FORM_NEEDS below; 'n/a' where the form needs
none). A dimension is 'specified' when the question states it, else 'missing'. Hours inside a window are not
checked, only the date. Also flagged: the first question is the form's bold decision question pasted as it stands
(several of those leave out the place or the date given in the goal card above them).

Reads deidentified_v1/decisions.csv + turns.csv, the task bank, and the pass-1 labels (agreed, else the AI
pre-labels). Writes results/rq3/: phrasing.csv (one row per decision with a question), phrasing_by_label.csv,
numbers_phrasing.csv, phrasing_results.json.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import BANK, DEID, RESULTS, SEED, pass1_labels, sha256  # noqa: E402

OUT = RESULTS / "rq3"
ROOM = lambda r: rf"(?<![\d.]){re.escape(r)}(?![\d])"  # noqa: E731  a room id, not part of a longer number
# per form: (place patterns, all needed), (time patterns, any), (criterion patterns, all needed); None = n/a
FORM_NEEDS = {
    "S1-1": ([ROOM("5.02")], [r"14(th)?\s*(of\s*)?jan", r"14/0?1/2025"], [r"\b20\b.{0,12}\b24\b"]),
    "S1-2": ([ROOM("5.04"), ROOM("5.12")], [r"21(st)?\s*(of\s*)?jan", r"21/0?1/2025"], [r"lower|average|mean|compar|better"]),
    "S1-3": ([r"boiler"], [r"2026"], None),
    "S2-1": ([r"whole|entire|all floors|across the|building|BUILDING_NAME|BUILDING_NAME_MISSPELT_1|BUILDING_NAME_MISSPELT_2"], [r"26(th)?\s*(of\s*)?feb",
             r"26/0?2/2025"], [r"1[,.]?000"]),
    "S2-2": ([ROOM("2.14")], [r"20(th)?\s*(of\s*)?jul", r"20/0?7/2026"], None),
    "S2-3": ([ROOM("3.68")], None, [r"\b12\b"]),
    "S3-1": ([ROOM("3.52")], [r"\b3(rd)?\s*(of\s*)?sep", r"\b0?3/0?9/2026"], None),
    "S3-2": ([ROOM("0.01")], None, None),
    "S3-3": ([ROOM("2.40")], [r"10(th)?\s*(of\s*)?aug", r"10/0?8/2026"], None),
    "S4-1": ([ROOM("5.18"), ROOM("5.14"), ROOM("5.21"), ROOM("5.07")], [r"21(st)?\s*(of\s*)?feb", r"21/0?2/2025"],
             [r"\b8\b", r"\b25\b"]),
    "S4-2": ([r"floors?\s*1\b.{0,20}\b3\b"], [r"14(th)?\s*(of\s*)?sep", r"20(th)?\s*(of\s*)?sep", r"september 2026"], None),
    "S4-3": ([ROOM("5.58")], [r"29(th)?\s*(of\s*)?jul", r"29/0?7/2026"], None),
}


GENERIC_PLACE = {"S2-1"}     # its place ('the building') is not distinctive enough to mark another task


def about_other_task(q: str, form: str) -> list:
    """Other forms whose distinctive place (a room id, the boiler, floors 1 and 3) the question names. Questions are
    linked to a task by the page on screen when they were sent, so a question about the previous task can land on
    the next task's page; such a question is not an under-specified one and is set apart."""
    return [f for f, (place, _, _) in FORM_NEEDS.items()
            if f != form and f not in GENERIC_PLACE and any(re.search(p, q, re.I) for p in place)]


def spec(q: str, pats, need_all: bool) -> str:
    if pats is None:
        return "n/a"
    hits = [bool(re.search(p, q, re.I)) for p in pats]
    return "specified" if (all(hits) if need_all else any(hits)) else "missing"


def norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower().replace("₂", "2")).split())


def boot_rate(g: pd.DataFrame, rng) -> tuple:
    """Share of 'first answer W or WL' with a participant-cluster bootstrap interval."""
    parts = {c: x.good.values for c, x in g.groupby("code")}
    keys = list(parts)
    obs = float(g.good.mean())
    draws = [np.concatenate([parts[keys[i]] for i in rng.integers(0, len(keys), len(keys))]).mean() for _ in range(2000)]
    return obs, float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    d = pd.read_csv(DEID / "decisions.csv", dtype=str, keep_default_na=False)
    t = pd.read_csv(DEID / "turns.csv", dtype=str, keep_default_na=False).set_index("turn_id")
    bank = {r["form"]: r for r in csv.DictReader(BANK.open(encoding="utf-8"))}
    lab_f, src = pass1_labels()
    lab = pd.read_csv(lab_f, dtype=str, keep_default_na=False).set_index("turn_id")["label"]
    rows = []
    for r in d[d.first_question_turn != ""].itertuples():
        q = t["question"].get(r.first_question_turn, "")
        place, time_, crit = FORM_NEEDS[r.form]
        row = {"code": r.code, "form": r.form, "situation": r.situation,
               "place": spec(q, place, True), "time": spec(q, time_, False), "criterion": spec(q, crit, True),
               "pasted_decision_question": int(norm(q) == norm(bank[r.form]["decision_question"])),
               "first_answer_label": lab.get(r.first_question_turn, ""), "warranted": r.warranted}
        needed = [row[k] for k in ("place", "time", "criterion") if row[k] != "n/a"]
        row["all_needed_specified"] = int(all(x == "specified" for x in needed))
        row["n_missing"] = sum(x == "missing" for x in needed)
        other = about_other_task(q, r.form)
        row["about_another_task"] = ";".join(other) if row["place"] == "missing" and other else ""
        rows.append(row)
    allp = pd.DataFrame(rows)
    allp.to_csv(OUT / "phrasing.csv", index=False)
    p = allp[allp.about_another_task == ""].copy()      # the comparison uses questions about their own task
    p["good"] = p.first_answer_label.isin(["W", "WL"]).astype(float)
    ct = pd.crosstab(p.all_needed_specified.map({1: "all needed specifics stated", 0: "something missing"}),
                     p.first_answer_label, margins=True)
    ct.to_csv(OUT / "phrasing_by_label.csv")
    rng = np.random.default_rng(SEED)
    rates = {}
    for k, g in p.groupby("all_needed_specified"):
        obs, lo, hi = boot_rate(g, rng)
        rates["complete" if k == 1 else "incomplete"] = {"n": int(len(g)), "first_answer_W_or_WL": obs, "lo": lo,
                                                         "hi": hi, "decisions_correct": float(g.warranted.astype(int).mean())}
    by_dim = {dim: p[dim].value_counts().to_dict() for dim in ("place", "time", "criterion")}
    pasted = p[p.pasted_decision_question == 1]
    other = allp[allp.about_another_task != ""]
    # a check on the linking E2 rests on: is the answer received (last before the decision) ever about another task?
    rec = d[d.received_turn != ""]
    rec_other = [r.received_turn for r in rec.itertuples()
                 if spec(t["question"].get(r.received_turn, ""), FORM_NEEDS[r.form][0], False) == "missing"
                 and about_other_task(t["question"].get(r.received_turn, ""), r.form)]
    res = {"label_source": src, "n_first_questions": int(len(allp)),
           "received_answers_about_another_task": [len(rec_other), int(len(rec))],
           "about_another_task": {"n": int(len(other)), "pairs": (other.form + " asked about " + other.about_another_task).tolist()},
           "n_compared": int(len(p)), "by_dimension": by_dim, "rates": rates,
           "pasted_decision_question": {"n": int(len(pasted)),
                                        "of_which_something_missing": int((pasted.all_needed_specified == 0).sum()),
                                        "by_form": pasted.form.value_counts().to_dict()},
           "missing_by_form": p[p.all_needed_specified == 0].form.value_counts().to_dict(),
           "note": "exploratory; specification checked deterministically against each form's goal card",
           "inputs": {"decisions.csv": sha256(DEID / "decisions.csv")[:16], "turns.csv": sha256(DEID / "turns.csv")[:16],
                      lab_f.name: sha256(lab_f)[:16]}}
    (OUT / "phrasing_results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    c, i = rates.get("complete", {}), rates.get("incomplete", {})
    nums = [("phrasing_complete_first_questions", f"{c.get('n', 0)} of {len(p)}",
             "first questions (about their own task) that state every place, date and criterion their form needs", ""),
            ("phrasing_about_another_task", f"{len(other)} of {len(allp)}",
             "first questions linked to a task (by the page on screen) that are about another task's room", ""),
            ("linking_received_about_another_task", f"{len(rec_other)} of {len(rec)}",
             "answers received before a decision (E2's input) whose question names another task's room or asset "
             "and not its own", ""),
            ("phrasing_pasted_decision_question", f"{len(pasted)} of {len(p)} ({res['pasted_decision_question']['of_which_something_missing']} of them missing a specific)",
             "first questions that are the bold decision question pasted as it stands", ""),
            ("phrasing_first_answer_good_complete", f"{100 * c.get('first_answer_W_or_WL', 0):.0f}% [{100 * c.get('lo', 0):.0f}, {100 * c.get('hi', 0):.0f}]",
             "first answer W or WL when the first question stated everything needed (participant bootstrap)", src),
            ("phrasing_first_answer_good_incomplete", f"{100 * i.get('first_answer_W_or_WL', 0):.0f}% [{100 * i.get('lo', 0):.0f}, {100 * i.get('hi', 0):.0f}]",
             "first answer W or WL when the first question left something out (participant bootstrap)", src)]
    pd.DataFrame([{"key": k, "value": v, "description": ds, "script": "phrasing_analysis.py", "label_source": ls}
                  for k, v, ds, ls in nums]).to_csv(OUT / "numbers_phrasing.csv", index=False)
    print(ct.to_string())
    print(json.dumps({k: v for k, v in res.items() if k != "inputs"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
