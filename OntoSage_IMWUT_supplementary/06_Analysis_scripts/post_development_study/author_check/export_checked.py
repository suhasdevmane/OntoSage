#!/usr/bin/env python3
"""Turn the author's checked labels into the files the analyses and the agreement scripts read (plan 19, Option A).

    python author_check/export_checked.py            # progress for every material; writes the file of each COMPLETE one
    python author_check/export_checked.py --status   # progress only, writes nothing

A material's file is written only when every item in it has been checked, so no analysis ever mixes the author's
labels with AI labels. Each analysis prefers the adjudicated two-coder file, then these files, then the AI pre-labels,
and reports AUTHOR_CHECKED as its label source while these are in use:

    live      labels/answer_labels_author.csv            (the columns of answer_labels_ai_prelabel.csv)
    offline   labels/rq2/_author/comparison_author.csv   (blind-sheet columns; read by merge_rq2_labels.py)
    stability labels/rq2/_author/stability_author.csv
    ttask     labels/rq2/_author/ttask_author.csv
    reasons   labels/qual/qual_codes_author.csv
    mixed     labels/rq1/fresh_vs_corpus_author.csv
    partA     labels/partA/partA_codes_author.csv
    stage5    labels/stage5/stage5_codes_author.csv

The same files are coder 1 for the agreement scripts once the second coder's sheets are back.

Also writes labels/author_check/check_summary.json: per material, items checked, kept and changed, and for answer
labels the AI -> author table. The paper reports it ("the first author changed N of the M labels the AI proposed").
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from study_paths import LABELS  # noqa: E402

DATA = LABELS / "author_check"
TAG_RE = re.compile(r"\[contested:[^\]]+\]|\[empty-answer\]|Alternative label (?:W|WL|U|FD|OT)\b")
ANSWER_FIELDS = ["label", "u_subtypes", "fd_what_was_held", "ot_what_instead", "wl_limit_stated", "verified",
                 "confidence", "evidence_quote"]


def read_csv(p: Path) -> list:
    with p.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(p: Path, head: list, rows: list) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=head, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(p)


def latest(m: str) -> dict:
    p = DATA / f"journal_{m}.jsonl"
    out = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                e = json.loads(line)
                out[e["id"]] = e
    return out


def items(m: str) -> dict:
    p = DATA / f"items_{m}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def answer_values(v: dict) -> dict:
    out = {k: v.get(k, "") for k in ANSWER_FIELDS}
    out["u_subtypes"] = " ".join(v.get("u_subtypes") or [])        # the label files keep sub-types space-separated
    return out


def tags(note: str) -> str:
    return " ".join(TAG_RE.findall(note or ""))


def export_live(mat: dict, dec: dict) -> Path:
    base = read_csv(LABELS / "answer_labels_ai_prelabel.csv")
    head = list(base[0].keys())
    rows = []
    for r in base:
        e = dec[r["answer_id"]]
        r = dict(r)
        r.update(answer_values(e["values"]))
        r["labeller"] = "AUTHOR_CHECKED"
        r["note"] = e["values"].get("note", "")
        rows.append(r)                         # contested_class and alt_label stay: they describe the answer, not the label
    out = LABELS / "answer_labels_author.csv"
    write_csv(out, head, rows)
    return out


def export_offline(set_name: str, dec: dict) -> Path:
    ai = {}
    for p in sorted((LABELS / "rq2" / "_ai_parts").glob(f"{set_name}_*.csv")):
        for r in read_csv(p):
            ai[r["blind_id"]] = r
    sheet = read_csv(LABELS / "rq2" / f"blind_sheet_{set_name}.csv")
    head = ["blind_id"] + ANSWER_FIELDS + ["note"]
    rows = []
    for s in sheet:
        b = s["blind_id"]
        e = dec[b]
        r = {"blind_id": b, **answer_values(e["values"])}
        own = e["values"].get("note", "")
        carried = tags(ai.get(b, {}).get("note", ""))             # merge_rq2_labels reads these from the note
        r["note"] = " ".join(x for x in (carried, own) if x)
        rows.append(r)
    out = LABELS / "rq2" / "_author" / f"{set_name}_author.csv"
    write_csv(out, head, rows)
    return out


def export_codes(mat: dict, dec: dict, out: Path, id_col: str, extra: dict = None) -> Path:
    codes = []
    for it in mat["items"]:
        for _, group in it.get("groups", []):
            for c in group:
                if c not in codes:
                    codes.append(c)
    head = [id_col] + (list(extra) if extra else []) + codes + ["inductive", "note"]
    rows = []
    for it in mat["items"]:
        v = dec[it["id"]]["values"]
        r = {id_col: it["id"], **{c: ("1" if c in v.get("codes", []) else "0") for c in codes},
             "inductive": v.get("inductive", ""), "note": v.get("note", "")}
        if extra:
            r.update({k: f(it) for k, f in extra.items()})
        rows.append(r)
    write_csv(out, head, rows)
    return out


def export_partA_kind(mat: dict, dec: dict, out: Path, id_col: str, extra: dict = None) -> Path:
    names = [n for n, _, _ in mat["fields"]]
    head = [id_col] + (list(extra) if extra else []) + names + ["note"]
    rows = []
    for it in mat["items"]:
        v = dec[it["id"]]["values"]
        r = {id_col: it["id"], "note": v.get("note", "")}
        for n, _, multi in mat["fields"]:
            r[n] = ";".join(v[n]) if multi else v[n]
        if extra:
            r.update({k: f(it) for k, f in extra.items()})
        rows.append(r)
    write_csv(out, head, rows)
    return out


def summarise(mat: dict, dec: dict) -> dict:
    done = [dec[i["id"]] for i in mat["items"] if i["id"] in dec]
    s = {"total": len(mat["items"]), "checked": len(done), "kept": sum(e["decision"] == "kept" for e in done),
         "changed": sum(e["decision"] == "changed" for e in done)}
    if mat["kind"] == "answer":
        s["ai_to_author"] = dict(Counter(f"{e['ai']['label']}->{e['values']['label']}" for e in done))
        s["label_changed"] = sum(e["ai"]["label"] != e["values"]["label"] for e in done)
        s["subtype_only_changed"] = sum(e["ai"]["label"] == e["values"]["label"] == "U"
                                        and sorted(e["ai"].get("u_subtypes", [])) != sorted(e["values"].get("u_subtypes", []))
                                        for e in done)
    elif mat["kind"] == "codes":
        c = Counter()
        for e in done:
            a, b = set(e["ai"].get("codes", [])), set(e["values"].get("codes", []))
            for x in a - b:
                c[f"removed {x}"] += 1
            for x in b - a:
                c[f"added {x}"] += 1
        s["code_changes"] = dict(c)
    else:
        s["field_changes"] = dict(Counter(f for e in done for f in e["changed_fields"]))
    return s


MIN_MEDIAN_SECONDS = {"answer": 8, "partA": 5, "codes": 4}   # reading one item takes longer than this; faster
                                                            # saves are not a review (answers are long; codes short)


def pace(m: str) -> dict:
    """How fast the saves came: the record the paper's description of the check has to match.

    The speed check reads the time before each item's LAST save, the save that becomes its label. Saves an item
    later replaced (a held-down Enter key runs through items at ~20 a second) do not count, so a burst followed by
    a one-by-one pass is judged on the pass; a pass that never reads is still judged on its own saves."""
    p = DATA / f"journal_{m}.jsonl"
    if not p.exists():
        return {}
    ents = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    ents = sorted(enumerate(ents), key=lambda x: (x[1]["ts"], x[0]))
    t = [dt.datetime.strptime(e["ts"], "%Y-%m-%dT%H:%M:%SZ") for _, e in ents]
    gaps = [(b - a).total_seconds() for a, b in zip(t, t[1:])]
    last = {e["id"]: k for k, (_, e) in enumerate(ents)}
    before_final = [(t[k] - t[k - 1]).total_seconds() for k in sorted(last.values()) if k > 0]
    return {"saves": len(t), "first_utc": t[0].strftime("%Y-%m-%dT%H:%M:%SZ"), "last_utc": t[-1].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "median_seconds_between_saves": statistics.median(gaps) if gaps else None,
            "median_seconds_before_final_saves": statistics.median(before_final) if before_final else None,
            "final_saves_under_2_s": sum(g < 2 for g in before_final),
            "active_minutes": round(sum(g for g in gaps if g < 300) / 60, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--accept-fast", action="store_true",
                    help="export a material even if its saves came faster than the minimum for its kind (answers 8 s, "
                         "Part A 5 s, codes 4 s apart); the paper must then report the time the review took")
    a = ap.parse_args()
    summary = {}
    for m in ("offline", "live", "reasons", "mixed", "partA", "stage5", "stability", "ttask"):
        mat = items(m)
        if not mat:
            continue
        dec = latest(m)
        s = summarise(mat, dec)
        s["pace"] = pace(m)
        summary[m] = s
        complete = s["checked"] == s["total"]
        line = f"{m:10s} {s['checked']:4d} of {s['total']:4d} checked, {s['changed']:3d} changed"
        med = s["pace"].get("median_seconds_before_final_saves")
        too_fast = complete and med is not None and med < MIN_MEDIAN_SECONDS[mat["kind"]] and not a.accept_fast
        if too_fast:
            s["exported"] = False
            line += (f"  NOT EXPORTED: a median of {med:.0f} s before each item's final save ({s['pace']['active_minutes']} "
                     f"min for {s['total']} items) cannot be described as reading each item; re-check, or use --accept-fast")
        elif complete and not a.status:
            if m == "live":
                out = export_live(mat, dec)
            elif m in ("offline", "stability", "ttask"):
                out = export_offline({"offline": "comparison"}.get(m, m), dec)
            elif m == "reasons":
                out = export_codes(mat, dec, LABELS / "qual" / "qual_codes_author.csv", "unit_id")
            elif m == "stage5":
                out = export_codes(mat, dec, LABELS / "stage5" / "stage5_codes_author.csv", "unit_id",
                                   {"question": lambda it: it["group"]})
            elif m == "mixed":
                out = export_partA_kind(mat, dec, LABELS / "rq1" / "fresh_vs_corpus_author.csv", "item_id")
            else:
                out = export_partA_kind(mat, dec, LABELS / "partA" / "partA_codes_author.csv", "row_id",
                                        {"stage": lambda it: it["group"].replace("stage ", "")})
            line += f"  -> {out.relative_to(LABELS)}"
        elif not complete:
            line += "  (file written when all are checked)"
        print(line)
    if not a.status:
        (DATA / "check_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
