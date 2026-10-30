#!/usr/bin/env python3
"""Task A6 (plan 20 E2): for every field below the 0.60 kappa rule, how many items each coder used each value for,
the raw % agreement, and every sentence in the live article that rests on it.

    python coder2_affected_sentences.py

Reads the same coder-1/coder-2 files the agreement scripts already compare (author's reviewed labels/codes vs the
second coder's final return), and `research paper v9.tex` for usage. Writes
G_Study_Data/labels/second_coder_return (no -- writes to) results/agreement/affected_fields.md, a one-page summary
meant for the first author and the AI to read before deciding E2, not for the article itself.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS = HERE.parent / "G_Study_Data" / "labels"
TEX = HERE.parent.parent.parent.parent / "research paper v9.tex"
OUT = HERE / "results" / "agreement" / "affected_fields.md"


def rows(p: Path) -> list:
    with p.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def dist(rs: list, field: str) -> Counter:
    return Counter((r.get(field) or "").strip() for r in rs)


def raw_agree(a: list, b: list, idc: str, field: str) -> tuple:
    bm = {r[idc]: r for r in b}
    same = sum(1 for r in a if r[idc] in bm and r[field] == bm[r[idc]][field])
    n = sum(1 for r in a if r[idc] in bm)
    return same, n


def tex_hits(pattern: str) -> list:
    if not TEX.exists():
        return ["(research paper v9.tex not found at expected path)"]
    text = TEX.read_text(encoding="utf-8")
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if re.search(pattern, line, re.IGNORECASE):
            hits.append(f"line {i}: {line.strip()[:160]}")
    return hits or ["(no match found by this pattern -- field not named directly in prose)"]


def section_f3(material: str, author_path: Path, coder2_path: Path, idc: str, kappas: dict) -> list:
    a_full, b = rows(author_path), rows(coder2_path)
    b_ids = {r[idc] for r in b}
    a = [r for r in a_full if r[idc] in b_ids]  # only the double-coded subset -- the full author file is much larger
    out = [f"\n## {material} (n={len(b)})\n"]
    for field in ("F3a_place", "F3b_time", "F3c_criterion"):
        kappa = kappas[field]
        same, n = raw_agree(a, b, idc, field)
        out.append(f"### {field} -- kappa {kappa:.2f} {'(BELOW 0.60)' if kappa < 0.60 else '(clears 0.60)'}")
        out.append(f"- raw agreement: {same}/{n} ({100*same/n:.0f}%)")
        out.append(f"- first author's values (on the {n} double-coded rows): {dict(dist(a, field))}")
        out.append(f"- second coder's values: {dict(dist(b, field))}")
        out.append("")
    return out


def section_reason(code: str, kappa, author_path: Path, coder2_path: Path, idc: str = "unit_id") -> list:
    a, b = rows(author_path), rows(coder2_path)
    bm = {r[idc]: r for r in b}
    both = [r for r in a if r[idc] in bm]
    a_ticked = sum(1 for r in both if (r.get(code) or "0").strip() == "1")
    b_ticked = sum(1 for r in both if (bm[r[idc]].get(code) or "0").strip() == "1")
    same = sum(1 for r in both if (r.get(code) or "0").strip() == (bm[r[idc]].get(code) or "0").strip())
    n = len(both)
    kstr = f"{kappa:.2f}" if kappa is not None else "undefined (no variance -- see counts)"
    out = [f"### {code} -- kappa {kstr}"]
    out.append(f"- raw agreement: {same}/{n} ({100*same/n:.0f}%)")
    out.append(f"- first author ticked it: {a_ticked}/{n}; second coder ticked it: {b_ticked}/{n}")
    out.append("")
    return out


def main() -> int:
    lines = ["# Fields below the 0.60 kappa rule, and where they are used in the article",
             "",
             "Task A6 (plan 20 section 2, decision E2). Generated, not hand-maintained -- re-run after any "
             "coder-return correction.",
             "",
             "## Live answer labels (RQ3)", ""]
    a = rows(LABELS / "answer_labels_author.csv")
    b = rows(LABELS / "second_coder_return" / "coder2_pass1.csv")
    bm = {r["answer_id"]: r for r in b}
    a_live = [r for r in a if r["answer_id"] in bm]
    same = sum(1 for r in a_live if r["label"] == bm[r["answer_id"]]["label"])
    lines.append(f"- n={len(a_live)}, kappa 0.48, raw agreement {same}/{len(a_live)} ({100*same/len(a_live):.0f}%)")
    lines.append(f"- first author's labels: {dict(dist(a_live, 'label'))}")
    lines.append(f"- second coder's labels: {dict(dist(b, 'label'))}")
    lines.append("- used in: the RQ3 answer-type comparison (full vs. partial-with-limits vs. refusal), the "
                 "wrong-refusal results, and the W/WL boundary discussion (plan 20 problem (d))")
    lines.append("")

    lines += section_f3("Mixed questions (RQ1)", LABELS / "rq1" / "fresh_vs_corpus_author.csv",
                         LABELS / "second_coder_return" / "coder2_rq1.csv", "item_id",
                         {"F3a_place": 0.24, "F3b_time": 0.76, "F3c_criterion": 0.45})
    lines += section_f3("Part A survey questions (RQ1)", LABELS / "partA" / "partA_codes_author.csv",
                         LABELS / "second_coder_return" / "coder2_partA.csv", "row_id",
                         {"F3a_place": 0.34, "F3b_time": 0.75, "F3c_criterion": 0.54})

    lines.append("## Reason codes (RQ3) below 0.60\n")
    reason_kappas = {"LIMIT_MATCH": 0.12, "DECLINE_ACCEPTED": 0.23, "PROXY_ACCEPTED": 0.00,
                      "FLUENCY_CUE": 0.00, "DECLINE_FRUSTRATION": 0.00, "PRIOR_KNOWLEDGE": None, "GUESS": None}
    for code, k in reason_kappas.items():
        lines += section_reason(code, k, LABELS / "qual" / "qual_codes_author.csv",
                                 LABELS / "second_coder_return" / "coder2_qual.csv")

    lines.append("## Where each field is used in `research paper v9.tex` (grep, line numbers)\n")
    patterns = {
        "Live answer labels / W-WL boundary": r"W/WL|wrong refusal|full answer.*partial|partial answer.*state",
        "F3a (place)": r"F3a|need a place they do not name",
        "F3c (criterion)": r"F3c|criterion they do not define",
        "LIMIT_MATCH": r"LIMIT_MATCH|named limit|limit.*real|none of the named limits",
        "DECLINE_ACCEPTED": r"DECLINE_ACCEPTED|refusal was taken as the answer",
    }
    for label, pat in patterns.items():
        lines.append(f"### {label}")
        lines += [f"- {h}" for h in tex_hits(pat)]
        lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"written -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
