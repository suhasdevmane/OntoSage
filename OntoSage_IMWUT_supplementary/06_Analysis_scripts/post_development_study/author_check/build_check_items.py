#!/usr/bin/env python3
"""Build the items for the author's check of the AI labels (plan 19, decision D1 = Option A).

    python author_check/build_check_items.py              # every material whose AI labels exist
    python author_check/build_check_items.py offline live  # only these

Materials, in the order plan 19 checks them:

    offline   300 offline comparison answers (RQ2)       AI labels: labels/rq2/_ai_parts/comparison_*.csv
    live      391 answers participants saw (RQ3)          AI labels: labels/answer_labels_ai_prelabel.csv
    reasons   270 reasons and closing answers             AI codes:  labels/qual/_ai_parts/codebook_*.csv
    mixed     175 own questions mixed with survey rows    AI codes:  labels/rq1/_ai_parts/rq1_*.csv
    partA     400 Part A survey rows (RQ1)                AI codes:  labels/partA/_ai_parts/partA_*.csv
    stage5    118 Stage 5 Trust and Success answers       AI codes:  labels/stage5/_ai_parts/stage5_*.csv
    stability 180 repeated offline answers (optional)     AI labels: labels/rq2/_ai_parts/stability_*.csv
    ttask      72 canonical task questions x 3 (optional) AI labels: labels/rq2/_ai_parts/ttask_*.csv

Each item shows the author what the second coder sees for the same material: the question, the answer with the
evidence-panel blocks removed, and the form's decision question, key and key facts. It also carries the AI's label
or codes and the AI's stated reason, which the author keeps or changes. An item never holds: which system wrote an
offline answer (nor the normalisation note, which differs by system), a participant's decision, correctness or
confidence, whether the item is in the second coder's sample, or whether a mixed question came from the survey.

Writes G_Study_Data/labels/author_check/items_<material>.json. Rebuilding never touches the author's decisions,
which live in journal_<material>.jsonl beside it.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from study_paths import BANK, LABELS, SEED, SM  # noqa: E402

OUT = LABELS / "author_check"
STAGE5_SRC = SM.parents[2] / "Survey analysis and results" / "inputs" / "recommendations.csv"
DETAILS_RE = re.compile(r"<details[^>]*>.*?</details>\s*", re.S)

ANSWER_LABELS = ["W", "WL", "FD", "U", "OT", "PF"]
SUBTYPES = ["scope", "proxy", "temporal", "fabricated", "criterion_drop", "causal", "wrong_value", "wrong_source"]
REASON_CODES = ["EVIDENCE_CITED", "LIMIT_RECOGNISED", "LIMIT_MATCH", "PROXY_ACCEPTED", "VERIFY_INTENDED", "FLUENCY_CUE",
                "DECLINE_FRUSTRATION", "DECLINE_ACCEPTED", "REPHRASED", "PRIOR_KNOWLEDGE", "GUESS", "OTHER"]
CLOSING_GROUPS = [
    ("Useful", ["USEFUL_SPECIFIC_VALUES", "USEFUL_EVIDENCE", "USEFUL_HONEST_LIMITS", "USEFUL_SPEED", "USEFUL_EASE"]),
    ("Frustrating", ["FRUST_DECLINES", "FRUST_SLOW", "FRUST_JARGON", "FRUST_WRONG", "FRUST_TOO_LONG",
                     "FRUST_NEEDED_REPHRASING"]),
    ("Refusals (CL2)", ["DECLINE_USEFUL", "DECLINE_FRUSTRATING", "DECLINE_DEPENDS"]),
    ("False impression of checking (CL3)", ["YES_FALSE_IMPRESSION", "NO", "UNSURE"]),
]
CLOSING_CODES = [c for _, g in CLOSING_GROUPS for c in g]
CLOSING_QUESTIONS = {
    "CL1": "What did you find most useful, and what most frustrating, about the answers?",
    "CL2": "When OntoSage said it could not establish something, was that useful or frustrating? Why?",
    "CL3": "Did any answer make you think something had been checked when you were not sure it had?",
}
PARTA_FIELDS = [
    ("F1_request_type", ["fact", "compare", "summarise", "rank", "explain", "capability", "action", "unclear"], True),
    ("F2_evidence_source", ["measurement", "description", "record", "document", "external", "none"], True),
    ("F3a_place", ["specified", "missing", "n/a"], False),
    ("F3b_time", ["specified", "missing", "n/a"], False),
    ("F3c_criterion", ["specified", "missing", "n/a"], False),
    ("F4_evidence_relation", ["direct", "proxy", "not_establishable", "unclear"], False),
    ("F5_answerable", ["yes", "partly", "no"], False),
    ("F6_purpose", ["yes", "no"], False),
    ("F7_certainty", ["clear", "uncertain", "discuss"], False),
]
STAGE5_CODES = ["PROVENANCE", "ACCURACY", "PRIVACY", "TIMELINESS", "ACTIONABILITY", "HONESTY_LIMITS", "EASE", "OTHER",
                "NONE"]
STAGE5_PROMPTS = {
    "Trust": "Trust, Privacy & Concerns: what would make you trust it, and what would stop you using it?",
    "Success": "Success Criteria & Impact: what would make it useful for your role, and how would you measure that?",
}

ANSWER_SPEC = {"kind": "answer", "labels": ANSWER_LABELS, "subtypes": SUBTYPES,
               "text_fields": ["fd_what_was_held", "ot_what_instead", "wl_limit_stated", "evidence_quote"],
               "rules": "PartB_Answer_Scoring_Rubric.md"}


def read(p: Path) -> list:
    with p.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def parts(cell: str) -> list:
    """Split a cell with several values on ; , | or spaces (the label files write U sub-types space-separated).
    'n/a' stays one value."""
    return [x.strip() for x in re.split(r"[;,|\s]+", cell or "") if x.strip()]


def bank() -> dict:
    return {r["form"]: r for r in read(BANK)}


def ai_files(folder: Path, prefix: str) -> dict:
    out = {}
    for p in sorted(folder.glob(f"{prefix}*.csv")):
        for r in read(p):
            out[r[next(iter(r))]] = r          # first column is the id
    return out


def answer_ai(r: dict) -> dict:
    return {"label": (r.get("label") or "").strip().upper(),
            "u_subtypes": [s.lower() for s in parts(r.get("u_subtypes", ""))],
            "fd_what_was_held": r.get("fd_what_was_held", "") or "",
            "ot_what_instead": r.get("ot_what_instead", "") or "",
            "wl_limit_stated": r.get("wl_limit_stated", "") or "",
            "evidence_quote": r.get("evidence_quote", "") or "",
            "verified": (r.get("verified") or "").strip().lower(),
            "confidence": (r.get("confidence") or "").strip().lower()}


def form_context(b: dict, form: str, key_answer: str, key_facts: str) -> dict:
    if not form or form == "own question":
        return {"title": "Participant's own question",
                "lines": [["Key", "none: judge from the answer and from what a building's records could hold; use "
                                  "'unverifiable' where you cannot check"]], "facts": ""}
    return {"title": f"Form {form}",
            "lines": [["Decision", b.get(form, {}).get("decision_question", "")], ["Key", key_answer]],
            "facts": key_facts or ""}


def build_offline(set_name: str) -> dict:
    b = bank()
    sheet = read(LABELS / "rq2" / f"blind_sheet_{set_name}.csv")
    ai = ai_files(LABELS / "rq2" / "_ai_parts", set_name + "_")
    merged = {r["blind_id"]: r for r in read(LABELS / "rq2" / f"rq2_labels_{set_name}.csv")}
    missing = [r["blind_id"] for r in sheet if r["blind_id"] not in ai]
    if missing:
        raise SystemExit(f"{set_name}: {len(missing)} answers have no AI label, e.g. {missing[:3]}")
    rng = random.Random(f"{SEED}:author:{set_name}")
    by_form = {}
    for r in sheet:
        by_form.setdefault(r["form"] or "own question", {}).setdefault(merged[r["blind_id"]]["qid"], []).append(r)
    items = []
    for form in sorted(by_form, key=lambda f: (f == "own question", f)):
        qids = sorted(by_form[form])
        rng.shuffle(qids)
        for q in qids:
            group = by_form[form][q][:]
            rng.shuffle(group)                 # the answers to one question sit together, in a seeded order
            for r in group:
                m = merged[r["blind_id"]]
                items.append({"id": r["blind_id"], "group": form,
                              "context": form_context(b, r["form"], r["key_answer"], r["key_facts"]),
                              "question": r["question"].strip(), "body": DETAILS_RE.sub("", r["answer"]).strip(),
                              "ai": answer_ai(ai[r["blind_id"]]),
                              "ai_reason": (ai[r["blind_id"]].get("note") or "").strip(),
                              "flag": (f"AI marked this as a contested class: {m['contested_class']}"
                                       + (f" (alternative label {m['alt_label']})" if m.get("alt_label") else ""))
                              if m.get("contested_class") else ""})
    titles = {"comparison": "Offline answers (RQ2): 100 participants' questions x 3 answers",
              "stability": "Repeated offline answers (stability; optional, if time allows)",
              "ttask": "Canonical task questions x 3 (T-TASK; optional, if time allows)"}
    return {"material": {"comparison": "offline"}.get(set_name, set_name), "title": titles[set_name],
            "id_col": "blind_id", **ANSWER_SPEC,
            "note_top": "Which system wrote each answer is hidden. The answers to one question are shown together.",
            "items": items}


def build_live() -> dict:
    b = bank()
    sheet = read(LABELS / "labelling_sheet_pass1.csv")
    ai = {r["answer_id"]: r for r in read(LABELS / "answer_labels_ai_prelabel.csv")}
    order = {"task": 0, "own_question": 1, "practice": 2, "other": 3}
    def gkey(r):
        return (order.get(r["role"], 9), r["form"] or "", r["answer_id"])
    items = []
    for r in sorted(sheet, key=gkey):
        a = ai[r["answer_id"]]
        group = r["form"] if r["role"] == "task" else {"own_question": "own question"}.get(r["role"], r["role"])
        ctx = form_context(b, r["form"] if r["role"] == "task" else "", r["key_answer"], r["key_facts"])
        if r["role"] in ("practice", "other"):
            ctx = {"title": r["role"].capitalize(), "lines": [["Key", "none"]], "facts": ""}
        items.append({"id": r["answer_id"], "group": group, "context": ctx, "question": r["question"].strip(),
                      "body": DETAILS_RE.sub("", r["answer_text"]).strip(), "ai": answer_ai(a),
                      "ai_reason": (a.get("note") or "").strip(),
                      "flag": (f"AI marked this as a contested class: {a['contested_class']}"
                               + (f" (alternative label {a['alt_label']})" if a.get("alt_label") else ""))
                      if a.get("contested_class") else ""})
    return {"material": "live", "title": "Answers participants saw during the study (RQ3)", "id_col": "answer_id",
            **ANSWER_SPEC, "note_top": "Evidence panels are removed, as in the second coder's material.",
            "items": items}


def build_reasons() -> dict:
    b = bank()
    sheet = read(LABELS / "qual" / "qual_coding_sheet.csv")
    ai = {**{r["unit_id"]: r for r in read(LABELS / "qual" / "_ai_parts" / "codebook_reasons.csv")},
          **{r["unit_id"]: r for r in read(LABELS / "qual" / "_ai_parts" / "codebook_closing.csv")}}
    items = []
    order = {"task_reason": 0, "CL1": 1, "CL2": 2, "CL3": 3}
    for r in sorted(sheet, key=lambda r: (order.get(r["unit"], 9), r["form"] or "", r["unit_id"])):
        a = ai[r["unit_id"]]
        if r["unit"] == "task_reason":
            codes, groups = REASON_CODES, [("Reason codes", REASON_CODES)]
            ctx = {"title": f"Form {r['form']}", "lines": [["Decision", b.get(r["form"], {}).get("decision_question", "")],
                                                           ["Key (what the data support)", b.get(r["form"], {}).get("key_answer", "")]],
                   "facts": ""}
            group = r["form"]
            question = "Why did you decide this, and is there anything you would still check?"
        else:
            codes, groups = CLOSING_CODES, CLOSING_GROUPS
            ctx = {"title": f"Closing question {r['unit']}", "lines": [], "facts": ""}
            group = r["unit"]
            question = CLOSING_QUESTIONS[r["unit"]]
        items.append({"id": r["unit_id"], "group": group, "context": ctx, "question": question, "body": r["text"].strip(),
                      "groups": groups,
                      "ai": {"codes": [c for c in codes if (a.get(c) or "").strip() == "1"],
                             "inductive": a.get("inductive", "") or ""},
                      "ai_reason": (a.get("note") or "").strip(), "flag": ""})
    return {"material": "reasons", "title": "Participants' reasons and closing answers", "id_col": "unit_id",
            "kind": "codes", "rules": "PartC_Reasons_Codebook.md",
            "note_top": "Tick every code that applies. LIMIT_MATCH only together with LIMIT_RECOGNISED, and only when "
                        "the limit named matches the key's limit. The participant's decision and correctness are hidden.",
            "items": items}


def partA_ai(a: dict) -> dict:
    out = {}
    for name, allowed, multi in PARTA_FIELDS:
        vals = [v.lower() for v in parts(a.get(name, ""))]
        out[name] = vals if multi else (vals[0] if vals else "")
    return out


def build_mixed() -> dict:
    sheet = read(LABELS / "rq1" / "fresh_vs_corpus_sheet.csv")
    ai = ai_files(LABELS / "rq1" / "_ai_parts", "rq1_")
    items = [{"id": r["item_id"], "group": "questions", "context": {"title": "", "lines": [], "facts": ""},
              "question": "", "body": r["question_text"].strip(), "ai": partA_ai(ai[r["item_id"]]),
              "ai_reason": (ai[r["item_id"]].get("note") or "").strip(), "flag": ""} for r in sheet]
    return {"material": "mixed", "title": "Participants' own questions mixed with survey questions (RQ1)",
            "id_col": "item_id", "kind": "partA", "fields": PARTA_FIELDS, "rules": "PartA_Codebook_v1.md",
            "note_top": "Where each question came from is hidden. Code only what the question's own words say.",
            "items": items}


def build_partA() -> dict:
    src = SM / "F_Analysis" / "outputs" / "partA_validation_rows.csv"
    folder = LABELS / "partA" / "_ai_parts"
    ai = ai_files(folder, "partA_") if folder.exists() else {}
    rows = read(src)
    missing = [r["row_id"] for r in rows if r["row_id"] not in ai]
    if missing:
        raise SystemExit(f"partA: {len(missing)} rows have no AI codes yet")
    rng = random.Random(f"{SEED}:author:partA")
    rng.shuffle(rows)
    items = [{"id": r["row_id"], "group": f"stage {r['stage']}", "context": {"title": f"Survey stage {r['stage']}",
                                                                            "lines": [], "facts": ""},
              "question": "", "body": r["question_text"].strip(), "ai": partA_ai(ai[r["row_id"]]),
              "ai_reason": (ai[r["row_id"]].get("note") or "").strip(), "flag": ""} for r in rows]
    return {"material": "partA", "title": "Part A: survey questions (RQ1)", "id_col": "row_id", "kind": "partA",
            "fields": PARTA_FIELDS, "rules": "PartA_Codebook_v1.md",
            "note_top": "Stages are mixed. Code only what the question's own words say.", "items": items}


def contributor_id(username: str) -> str:
    return "C" + hashlib.sha256(f"{SEED}:{username}".encode("utf-8")).hexdigest()[:6]


def build_stage5() -> dict:
    folder = LABELS / "stage5" / "_ai_parts"
    ai = ai_files(folder, "stage5_") if folder.exists() else {}
    items = []
    for field in ("Trust", "Success"):
        for r in read(STAGE5_SRC):
            uid = f"{field}-{contributor_id(r['Username'])}"
            if uid not in ai:
                raise SystemExit(f"stage5: {uid} has no AI codes yet")
            a = ai[uid]
            items.append({"id": uid, "group": field, "context": {"title": f"Stage 5: {field}", "lines": [], "facts": ""},
                          "question": STAGE5_PROMPTS[field], "body": (r[field] or "").strip(),
                          "groups": [("Codes", STAGE5_CODES)],
                          "ai": {"codes": [c for c in STAGE5_CODES if (a.get(c) or "").strip() == "1"],
                                 "inductive": (a.get("inductive") or "").strip()},
                          "ai_reason": (a.get("note") or "").strip(), "flag": ""})
    return {"material": "stage5", "title": "Stage 5 survey answers: Trust and Success", "id_col": "unit_id",
            "kind": "codes", "rules": "Stage5_Trust_Success_Codebook.md",
            "note_top": "Code what is stated, not what is implied. Trust and Success are coded separately.",
            "items": items}


BUILDERS = {"offline": lambda: build_offline("comparison"), "live": build_live, "reasons": build_reasons,
            "mixed": build_mixed, "partA": build_partA, "stage5": build_stage5,
            "stability": lambda: build_offline("stability"), "ttask": lambda: build_offline("ttask")}
ORDER = list(BUILDERS)


def main(argv: list) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = argv or ORDER
    for m in wanted:
        if m not in BUILDERS:
            print(f"unknown material {m}; choose from {', '.join(ORDER)}")
            return 2
        try:
            data = BUILDERS[m]()
        except SystemExit as e:
            print(f"{m}: skipped ({e})")
            continue
        data["order"] = ORDER.index(m)
        ids = [i["id"] for i in data["items"]]
        assert len(ids) == len(set(ids)), f"{m}: duplicate ids"
        (OUT / f"items_{m}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{m}: {len(ids)} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
