#!/usr/bin/env python3
"""Pass-1 labelling sheet: every OntoSage answer a participant saw, with its task's key (TODO 3.1, 3.4).

    python make_labelling_sheet.py

Writes G_Study_Data/labels/:
  labelling_sheet_pass1.csv        one row per answer (task, own-question, practice and other turns), the context a
                                   coder needs (question, answer text WITHOUT the evidence panel, the form's key and
                                   data facts), and the rubric's step-4 columns left blank
                                   (D_Coding_and_Scoring/PartB_Answer_Scoring_Rubric.md)
  answer_labels_human_template.csv the same rows, label columns only, for coder 1 and coder 2 (copy it twice)
  _reading/<group>.md              every answer in full, grouped by form (own questions in one file), for reading;
                                   nothing is cut, because cut text produced wrong labels in this project before
Reads only the de-identified dataset and the frozen task bank.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import BANK, DEID, INSTANCES, LABELS, write_manifest  # noqa: E402

RUBRIC_COLS = ["label", "u_subtypes", "fd_what_was_held", "ot_what_instead", "wl_limit_stated", "panel_present",
               "panel_supports_text", "panel_wrong", "verified", "confidence", "evidence_quote", "note"]


def main() -> int:
    LABELS.mkdir(parents=True, exist_ok=True)
    read_dir = LABELS / "_reading"
    read_dir.mkdir(exist_ok=True)
    turns = list(csv.DictReader((DEID / "turns.csv").open(encoding="utf-8")))
    bank = {r["form"]: r for r in csv.DictReader(BANK.open(encoding="utf-8")) if r["use"] == "study"}
    inst = {f["form"]: f for f in json.loads(INSTANCES.read_text(encoding="utf-8"))["forms"]}
    rows = []
    for t in turns:
        f = t["form"] if t["role"] == "task" else ""
        b, k = bank.get(f, {}), inst.get(f, {}).get("key", {})
        rows.append({"answer_id": t["turn_id"], "question_id": f or t["role"], "code": t["code"], "role": t["role"],
                     "form": f, "situation": t["situation"] if f else "", "task_position": t["task_position"],
                     "page_on_screen": t["page_on_screen"], "route_final": t["route_final"],
                     "question": t["question"], "answer_text": t["answer_text"],
                     "key_answer": b.get("key_answer", ""), "key_facts": json.dumps(k, ensure_ascii=False) if k else "",
                     "warranted_options": b.get("warranted_options", ""),
                     **{c: "" for c in RUBRIC_COLS},
                     "panel_present": "yes" if t["evidence_panel_present"] == "1" else "no"})
    cols = list(rows[0].keys())
    with (LABELS / "labelling_sheet_pass1.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    with (LABELS / "answer_labels_human_template.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["answer_id", "coder"] + RUBRIC_COLS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({"answer_id": r["answer_id"], "coder": "", **{c: "" for c in RUBRIC_COLS},
                        "panel_present": r["panel_present"]})
    groups: dict = {}
    for r in rows:
        groups.setdefault(r["form"] or r["role"], []).append(r)
    for g, rs in groups.items():
        b = bank.get(g, {})
        out = [f"# {g}: {len(rs)} answers\n"]
        if b:
            out.append(f"**Decision:** {b['decision_question']}\n\n**Key:** {b['key_answer']} (warranted options "
                       f"{b['warranted_options']})\n\n**Facts:** `{rs[0]['key_facts']}`\n\n**Failure per option:** "
                       f"{b['failure_per_option']}\n")
        for r in rs:
            out.append(f"\n---\n## {r['answer_id']} · {r['code']} · task {r['task_position']} · page {r['page_on_screen']}"
                       f" · route {r['route_final']} · panel {r['panel_present']}\n\n**Q:** {r['question']}\n\n"
                       f"**A:**\n\n{r['answer_text']}\n")
        (read_dir / f"{g}.md").write_text("".join(out), encoding="utf-8")
    write_manifest(LABELS, {"turns.csv": DEID / "turns.csv", "task_bank.csv": BANK, "task_bank_instances.json": INSTANCES},
                   note="pass-1 labelling sheet (no labels in it)")
    print({g: len(v) for g, v in sorted(groups.items())})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
