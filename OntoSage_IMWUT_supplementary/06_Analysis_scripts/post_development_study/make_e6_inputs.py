#!/usr/bin/env python3
"""Question sets for the RQ2 offline runs (E6, plan 03 section 7.1), from the de-identified dataset (TODO 2.1).

    python make_e6_inputs.py

  T-LIVE   the first question each participant typed in each task (linked by the page on screen); tasks with no
           question have none
  T-FRESH  the participants' own questions, written before they used OntoSage
  T-TASK   the 12 canonical task questions (the researcher's phrasing, task bank)
  comparison_sample.jsonl   seeded random 60 T-LIVE + 40 T-FRESH (plan 7.5, pass 2)
  stability_sample.jsonl    seeded 30 of the 60 sampled T-LIVE (plan 7.4: re-run three times through both systems)
  t_task.jsonl              the 12, for three runs
Seed: the project's pre-declared 20261009 (random.Random(f"{seed}:{set}")). Writes G_Study_Data/e6_offline_runs/inputs/.
"""

from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import BANK, DEID, E6, SEED, write_manifest  # noqa: E402


def main() -> int:
    out = E6 / "inputs"
    out.mkdir(parents=True, exist_ok=True)
    turns = {r["turn_id"]: r for r in csv.DictReader((DEID / "turns.csv").open(encoding="utf-8"))}
    dec = list(csv.DictReader((DEID / "decisions.csv").open(encoding="utf-8")))
    own = list(csv.DictReader((DEID / "own_questions.csv").open(encoding="utf-8")))
    bank = [r for r in csv.DictReader(BANK.open(encoding="utf-8")) if r["use"] == "study"]
    tlive = [{"qid": f"TL-{d['code']}-{d['position']}", "set": "T-LIVE", "participant": d["code"], "form": d["form"],
              "situation": d["situation"], "question": turns[d["first_question_turn"]]["question"].strip(),
              "source_turn": d["first_question_turn"]}
             for d in dec if d["first_question_turn"] and turns[d["first_question_turn"]]["question"].strip()]
    tfresh = [{"qid": f"TF-{o['code']}-{o['slot']}", "set": "T-FRESH", "participant": o["code"], "form": "", "situation": "",
               "question": o["question"].strip()} for o in own if o["question"].strip()]
    ttask = [{"qid": f"TT-{r['form']}", "set": "T-TASK", "participant": "", "form": r["form"], "situation": r["situation"],
              "question": r["canonical_question"].strip()} for r in bank]
    s_live = random.Random(f"{SEED}:T-LIVE").sample(tlive, 60)
    s_fresh = random.Random(f"{SEED}:T-FRESH").sample(tfresh, 40)
    stab = random.Random(f"{SEED}:STABILITY").sample(s_live, 30)
    for name, rows in (("t_live_all.jsonl", tlive), ("t_fresh_all.jsonl", tfresh), ("t_task.jsonl", ttask),
                       ("comparison_sample.jsonl", s_live + s_fresh), ("stability_sample.jsonl", stab)):
        (out / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    info = {"seed": SEED, "t_live_pool": len(tlive), "t_fresh_pool": len(tfresh), "t_task": len(ttask),
            "comparison": {"T-LIVE": len(s_live), "T-FRESH": len(s_fresh)}, "stability": len(stab),
            "forms_in_sampled_t_live": sorted({r["form"] for r in s_live}),
            "participants_in_sample": len({r["participant"] for r in s_live + s_fresh})}
    (out / "sample_info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    write_manifest(out, {"turns.csv": DEID / "turns.csv", "decisions.csv": DEID / "decisions.csv",
                         "own_questions.csv": DEID / "own_questions.csv", "task_bank.csv": BANK}, note="E6 inputs")
    print(json.dumps(info, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
