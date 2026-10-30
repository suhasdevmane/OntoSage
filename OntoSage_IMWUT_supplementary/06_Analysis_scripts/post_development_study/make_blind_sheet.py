#!/usr/bin/env python3
"""Blind scoring sheet for the RQ2 offline answers (plan 03 section 7.5, pass 2; TODO 2.6).

    python make_blind_sheet.py --set ttask   runs/e6_ttask_A_B_x3.jsonl
    python make_blind_sheet.py --set comparison runs/e6_comparison_A_B.jsonl [runs/e6_comparison_Aminus.jsonl]
    python make_blind_sheet.py --set stability runs/e6_stability_A_B_x3.jsonl

Writes G_Study_Data/labels/rq2/:
  blind_sheet_<set>.csv           blind_id, question, the answer NORMALISED (identity hidden), the form and its key
                                  where the question came from a task (T-LIVE, T-TASK), blank label columns
  _unblinding_key_<set>.csv       blind_id -> system (A / A-minus / B), qid, run, attempt, file, row  (keep closed
                                  until the labels are locked)
  _reading/<set>_NN.md            the same answers in reading order: grouped by form (the key once per group),
                                  shuffled inside the group, 25 to a file
Normalisation (rubric "Blinding in pass 2"): OntoSage's evidence panel and its pipeline-steps block removed; other
collapsible blocks unfolded to plain text; "Sources:" and "You might also ask" footers, horizontal rules and Markdown
heading marks removed; bold/italic marks removed. Nothing else is changed: limitation notes stay, because they are
part of what the answer claims. Shuffle seed: the project's 20261009, per set.
Which attempt is scored: a provider failure's re-run (attempt 2) replaces it; both stay in the run file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import BANK, INSTANCES, LABELS, SEED  # noqa: E402

RQ2 = LABELS / "rq2"


def normalise(text: str) -> tuple:
    applied = []
    t = text or ""
    if re.search(r'<details type="evidence"', t):
        t = re.sub(r'<details type="evidence".*?</details>', "", t, flags=re.S)
        applied.append("evidence panel removed")
    if "<summary>Pipeline steps</summary>" in t:
        t = re.sub(r"<details>\s*<summary>Pipeline steps</summary>.*?</details>", "", t, flags=re.S)
        applied.append("pipeline steps removed")
    if "<details" in t:
        t = re.sub(r"<summary>(.*?)</summary>", r"\1:", t, flags=re.S)
        t = re.sub(r"</?details[^>]*>", "", t)
        applied.append("collapsible blocks unfolded")
    t2 = re.sub(r"^\s*\*?Sources:.*$", "", t, flags=re.M)
    t2 = re.sub(r"^\s*\*\*You might also ask:\*\*.*$", "", t2, flags=re.M)
    t2 = re.sub(r"^\s*-{3,}\s*$", "", t2, flags=re.M)
    t2 = re.sub(r"^\s*#{1,6}\s*", "", t2, flags=re.M)
    t2 = re.sub(r"\*\*(.+?)\*\*", r"\1", t2)
    t2 = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", t2)
    t2 = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"\1", t2)
    if t2 != t:
        applied.append("footers, rules, headings and emphasis marks removed")
    t2 = re.sub(r"\n{3,}", "\n\n", t2).strip()
    return t2, applied


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--set", required=True)
    ap.add_argument("--hash-ids", action="store_true",
                    help="blind ids from a seeded hash of (question, system, run, attempt), so ids stay the same while a "
                         "run is still adding rows and labelling can start early")
    ap.add_argument("--only-unlabelled", action="store_true",
                    help="reading files hold only answers with no label yet in _ai_parts/<set>_*.csv")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()
    bank = {r["form"]: r for r in csv.DictReader(BANK.open(encoding="utf-8")) if r["use"] == "study"}
    inst = {f["form"]: f for f in json.loads(INSTANCES.read_text(encoding="utf-8"))["forms"]}
    rows = []
    for f in args.files:
        for i, line in enumerate(Path(f).read_text(encoding="utf-8").splitlines()):
            if line.strip():
                r = json.loads(line)
                r["_file"], r["_row"] = Path(f).name, i
                rows.append(r)
    # a provider failure's re-run replaces it for scoring
    rerun_of = {(r["qid"], r["run"], r["system"]) for r in rows if r.get("attempt") == 2}
    scored = [r for r in rows if not (r.get("attempt", 1) == 1 and (r["qid"], r["run"], r["system"]) in rerun_of)]
    def hid(r: dict) -> str:
        s = f"{SEED}:blind:{args.set}:{r['qid']}:{r['system']}:{r['run']}:{r.get('attempt', 1)}"
        return hashlib.sha256(s.encode()).hexdigest()[:6]

    if args.hash_ids:
        scored.sort(key=hid)
    else:
        rng = random.Random(f"{SEED}:blind:{args.set}")
        rng.shuffle(scored)
    RQ2.mkdir(parents=True, exist_ok=True)
    (RQ2 / "_reading").mkdir(exist_ok=True)
    sheet, key = [], []
    for n, r in enumerate(scored, 1):
        bid = f"{args.set[:2].upper()}{hid(r)}" if args.hash_ids else f"{args.set[:2].upper()}{n:03d}"
        text, applied = normalise(r.get("answer") or "")
        form = r.get("form", "")
        b = bank.get(form, {})
        sheet.append({"blind_id": bid, "question": r["question"], "answer": text, "form": form,
                      "key_answer": b.get("key_answer", ""), "key_facts": json.dumps(inst.get(form, {}).get("key", {}), ensure_ascii=False) if form else "",
                      "normalisation": "; ".join(applied), "label": "", "u_subtypes": "", "fd_what_was_held": "",
                      "ot_what_instead": "", "wl_limit_stated": "", "verified": "", "confidence": "", "evidence_quote": "",
                      "note": "", "identity_guess": ""})
        key.append({"blind_id": bid, "system": r["system"], "qid": r["qid"], "set": r.get("set", ""), "run": r["run"],
                    "attempt": r.get("attempt", 1), "file": r["_file"], "row": r["_row"],
                    "started_utc": r.get("started_utc", ""), "seconds": (r.get("result") or {}).get("seconds", ""),
                    "error": (r.get("result") or {}).get("error", "") or "",
                    "provider_failure": (r.get("result") or {}).get("provider_failure", "")})
    for name, data in ((f"blind_sheet_{args.set}.csv", sheet), (f"_unblinding_key_{args.set}.csv", key)):
        with (RQ2 / name).open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(data[0].keys()), lineterminator="\n")
            w.writeheader()
            w.writerows(data)
    order = sorted(sheet, key=lambda s: (s["form"] or "~", s["blind_id"]))
    if args.only_unlabelled:
        done = set()
        for p in (RQ2 / "_ai_parts").glob(f"{args.set}_*.csv"):
            done |= {r["blind_id"] for r in csv.DictReader(p.open(encoding="utf-8"))}
        order = [s for s in order if s["blind_id"] not in done]
        for old in (RQ2 / "_reading").glob(f"{args.set}_*.md"):
            old.unlink()
    for k in range(0, len(order), 25):
        chunk = order[k:k + 25]
        out, last = [f"# {args.set} reading file {k // 25 + 1} ({len(chunk)} answers)\n"], None
        for s in chunk:
            if s["form"] != last:
                last = s["form"]
                b = bank.get(s["form"], {})
                out.append(f"\n## FORM {s['form'] or '(own question: no key)'}\n" + (
                    f"**Decision:** {b['decision_question']}\n\n**Key:** {b['key_answer']}\n\n**Facts:** `{s['key_facts']}`\n" if b else ""))
            out.append(f"\n---\n### {s['blind_id']}\n**Q:** {s['question']}\n\n**A:**\n\n{s['answer']}\n")
        (RQ2 / "_reading" / f"{args.set}_{k // 25 + 1:02d}.md").write_text("".join(out), encoding="utf-8")
    print(f"{args.set}: {len(sheet)} answers scored ({len(rows) - len(scored)} provider failures replaced by their re-run); "
          f"{(len(order) + 24) // 25} reading files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
