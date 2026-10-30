#!/usr/bin/env python3
"""Qualitative analysis of the per-task reasons and closing answers (plan 03 section 8.10; plan 04 section 3 themes),
coded with the Part C codebook (D_Coding_and_Scoring/PartC_Reasons_Codebook.md).

    python qual_analysis.py

Reads labels/qual/qual_coding_sheet.csv (make_qual_sheet.py) and the codes: labels/qual/qual_codes_agreed.csv if it
exists (the author's codes with the second coder's sample adjudicated), otherwise the AI pre-codes in
labels/qual/_ai_parts/codebook_{reasons,closing}.csv, marked PROVISIONAL_AI_PRECODE. Writes results/qual/:
  code_counts.csv        each code and inductive tag: units and participants (people), by material (reasons, CL1-CL3)
  limit_match.csv        reasons that name a limit: how often the limit matches the key, by situation and decision
  decline_accepted.csv   reasons that take a refusal as informative, by the answer received (FD vs WL) and decision
  codes_by_decision.csv  reason codes by decision kind, correct / not and answer received
  excerpts.md            verbatim excerpts per code and tag, with unit ids (all 30 ticked consent statement C7)
  qual_results.json, numbers_qual.csv
The codes are a first pass to speed up the first author's own coding; the themes and their wording are his.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recode_qual_to_codebook import CLOSING, REASON  # noqa: E402
from study_paths import LABELS, RESULTS  # noqa: E402

Q = LABELS / "qual"
OUT = RESULTS / "qual"
PLAIN = {"EVIDENCE_CITED": "said what the answer or data showed", "LIMIT_RECOGNISED": "named something the answer could not establish",
         "LIMIT_MATCH": "the limit named is the true one (key)", "PROXY_ACCEPTED": "took a related reading as the answer",
         "VERIFY_INTENDED": "would check elsewhere before acting", "FLUENCY_CUE": "trusted detail, confidence or an 'analysis report'",
         "DECLINE_FRUSTRATION": "frustrated by a refusal", "DECLINE_ACCEPTED": "took a refusal as the answer",
         "REPHRASED": "asked again in other words", "PRIOR_KNOWLEDGE": "used what they expected of the building",
         "GUESS": "guessed", "OTHER": "other",
         "USEFUL_SPECIFIC_VALUES": "useful: specific values", "USEFUL_EVIDENCE": "useful: the evidence and sources",
         "USEFUL_HONEST_LIMITS": "useful: honest limits", "USEFUL_SPEED": "useful: speed", "USEFUL_EASE": "useful: clear, well written",
         "FRUST_DECLINES": "frustrating: refusals and missing data", "FRUST_SLOW": "frustrating: slow", "FRUST_JARGON": "frustrating: jargon",
         "FRUST_WRONG": "frustrating: misunderstood or wrong", "FRUST_TOO_LONG": "frustrating: too long or complex",
         "FRUST_NEEDED_REPHRASING": "frustrating: had to rephrase", "DECLINE_USEFUL": "refusals were useful",
         "DECLINE_FRUSTRATING": "refusals were frustrating", "DECLINE_DEPENDS": "it depends",
         "YES_FALSE_IMPRESSION": "yes, an answer seemed checked when it was not", "NO": "no", "UNSURE": "unsure"}


def load() -> tuple:
    sheet = pd.read_csv(Q / "qual_coding_sheet.csv", dtype=str).fillna("")
    agreed, author = Q / "qual_codes_agreed.csv", Q / "qual_codes_author.csv"
    if agreed.exists():
        codes, src = pd.read_csv(agreed, dtype=str).fillna(""), "HUMAN_AGREED"
    elif author.exists():                  # author_check/export_checked.py (plan 19, Option A)
        codes, src = pd.read_csv(author, dtype=str).fillna(""), "AUTHOR_CHECKED"
    else:
        parts = [pd.read_csv(Q / "_ai_parts" / f, dtype=str).fillna("") for f in ("codebook_reasons.csv", "codebook_closing.csv")]
        codes, src = pd.concat(parts, ignore_index=True).fillna(""), "PROVISIONAL_AI_PRECODE"
    dup = codes.unit_id[codes.unit_id.duplicated()].tolist()
    missing = sorted(set(sheet.unit_id) - set(codes.unit_id))
    extra = sorted(set(codes.unit_id) - set(sheet.unit_id))
    if dup or missing or extra:
        raise SystemExit(f"codes do not match the sheet: duplicated {dup[:5]}, missing {missing[:5]}, unknown {extra[:5]}")
    keep = [c for c in sheet.columns if c not in REASON + CLOSING + ["inductive", "note"]]
    d = sheet[keep].merge(codes, on="unit_id")
    for c in REASON + CLOSING:
        if c not in d:
            d[c] = 0
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0).astype(int)
    d["tags"] = d.inductive.astype(str).str.split(";").map(lambda xs: [x.strip() for x in xs if x.strip()])
    return d, src


def counts(d: pd.DataFrame, src: str) -> pd.DataFrame:
    rows = []
    for material, codes in (("task reasons", REASON), ("CL1", CLOSING), ("CL2", CLOSING), ("CL3", CLOSING)):
        g = d[d.unit == ("task_reason" if material == "task reasons" else material)]
        for c in codes:
            hit = g[g[c] == 1]
            if material != "task reasons" and hit.empty:
                continue
            rows.append({"material": material, "code": c, "plain": PLAIN.get(c, c), "type": "codebook",
                         "units": len(hit), "of_units": len(g), "people": hit.code.nunique(), "label_source": src})
    tags = d.explode("tags").dropna(subset=["tags"])
    for t, g in tags.groupby("tags"):
        rows.append({"material": "all", "code": t, "plain": t.replace("_", " "), "type": "inductive", "units": len(g),
                     "of_units": len(d), "people": g.code.nunique(), "label_source": src})
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    d, src = load()
    cc = counts(d, src)
    cc.to_csv(OUT / "code_counts.csv", index=False)
    tr = d[d.unit == "task_reason"].copy()
    lim = tr[tr.LIMIT_RECOGNISED == 1]
    rows = [{"by": "all", "value": "all", "n_limit_named": len(lim), "matches_key": int(lim.LIMIT_MATCH.sum())}]
    for col in ("situation", "form", "correct"):
        for v, g in lim.groupby(col):
            rows.append({"by": col, "value": v, "n_limit_named": len(g), "matches_key": int(g.LIMIT_MATCH.sum())})
    pd.DataFrame(rows).to_csv(OUT / "limit_match.csv", index=False)
    rows = []
    for v, g in tr.groupby("answer_received"):
        rows.append({"answer_received": v or "none", "n": len(g), "decline_accepted": int(g.DECLINE_ACCEPTED.sum()),
                     "decline_accepted_and_correct": int(((g.DECLINE_ACCEPTED == 1) & (g.correct == "1")).sum())})
    pd.DataFrame(rows).to_csv(OUT / "decline_accepted.csv", index=False)
    out = []
    for col in ("decision_kind", "correct", "answer_received"):
        for v, g in tr.groupby(col):
            out.append({"by": col, "value": v, "n": len(g), **{c: int(g[c].sum()) for c in REASON}})
    pd.DataFrame(out).to_csv(OUT / "codes_by_decision.csv", index=False)
    lines = [f"# Verbatim excerpts by code ({src})", "",
             "Participants' own words, with unit ids (code-task position, or code-closing question). Every participant "
             "ticked consent statement C7 (anonymous verbatim quotes may be used). Quote with the participant code and "
             "form; never tidy a quotation; drop anything that could identify a person.", ""]
    for material, codes in (("task_reason", REASON), ("CL1", CLOSING), ("CL2", CLOSING), ("CL3", CLOSING)):
        for c in codes:
            hit = d[(d.unit == material) & (d[c] == 1) & (d.text.str.len() > 15)]
            if hit.empty:
                continue
            lines += [f"## {material} · {c}: {PLAIN.get(c, c)} ({len(hit)} units, {hit.code.nunique()} people)", ""]
            lines += [f"- {r.unit_id} ({r.form + ', ' if r.form else ''}{r.decision_kind or r.unit}): \"{r.text}\""
                      for r in hit.head(6).itertuples()] + [""]
    tags = d.explode("tags").dropna(subset=["tags"])
    for t, g in tags.groupby("tags"):
        g = g[g.text.str.len() > 15]
        if g.code.nunique() < 2:
            continue
        lines += [f"## tag: {t} ({g.code.nunique()} people)", ""]
        lines += [f"- {r.unit_id} ({r.form + ', ' if r.form else ''}{r.decision_kind or r.unit}): \"{r.text}\""
                  for r in g.head(6).itertuples()] + [""]
    (OUT / "excerpts.md").write_text("\n".join(lines), encoding="utf-8")
    s43 = tr[tr.form == "S4-3"]
    chose_b = s43[s43.decision_kind == "accepted an unsupported claim"]
    fd, wl = tr[tr.answer_received == "FD"], tr[tr.answer_received == "WL"]
    res = {"label_source": src, "units": len(d), "task_reasons": len(tr), "closing": int((d.unit != "task_reason").sum()),
           "reasons_limit_named": len(lim), "reasons_limit_matches_key": int(lim.LIMIT_MATCH.sum()),
           "people_limit_named": int(lim.code.nunique()),
           "after_FD_n": len(fd), "after_FD_decline_accepted": int(fd.DECLINE_ACCEPTED.sum()),
           "after_FD_limit_named_not_true": int(((fd.LIMIT_RECOGNISED == 1) & (fd.LIMIT_MATCH == 0)).sum()),
           "after_WL_n": len(wl), "after_WL_decline_accepted": int(wl.DECLINE_ACCEPTED.sum()),
           "people_decline_accepted": int(tr[tr.DECLINE_ACCEPTED == 1].code.nunique()),
           "people_verify_intended": int(tr[tr.VERIFY_INTENDED == 1].code.nunique()),
           "reasons_verify_intended": int(tr.VERIFY_INTENDED.sum()),
           "people_fluency_cue": int(tr[tr.FLUENCY_CUE == 1].code.nunique()),
           "people_prior_knowledge": int(tr[tr.PRIOR_KNOWLEDGE == 1].code.nunique()),
           "people_blamed_missing_data": int(tags[tags.tags == "blamed_missing_data"].code.nunique()),
           "people_useful_evidence": int(d[(d.unit != "task_reason") & (d.USEFUL_EVIDENCE == 1)].code.nunique()),
           "people_frust_declines": int(d[(d.unit != "task_reason") & (d.FRUST_DECLINES == 1)].code.nunique()),
           "people_frust_rephrasing": int(d[(d.unit != "task_reason") & (d.FRUST_NEEDED_REPHRASING == 1)].code.nunique()),
           "CL2_decline_useful": int(d[d.unit == "CL2"].DECLINE_USEFUL.sum()),
           "CL2_decline_frustrating": int(d[d.unit == "CL2"].DECLINE_FRUSTRATING.sum()),
           "CL3_no": int(d[d.unit == "CL3"].NO.sum()), "CL3_yes": int(d[d.unit == "CL3"].YES_FALSE_IMPRESSION.sum()),
           "CL3_unsure": int(d[d.unit == "CL3"].UNSURE.sum()),
           "S4_3_chose_b": len(chose_b),
           "S4_3_chose_b_naming_people_limit": int(chose_b.tags.map(lambda t: "chose_b_without_people_fact" in t).sum())}
    (OUT / "qual_results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    nums = [{"key": f"qual_{k}", "value": v, "description": k.replace("_", " "), "script": "qual_analysis.py",
             "label_source": src} for k, v in res.items() if k != "label_source"]
    pd.DataFrame(nums).to_csv(OUT / "numbers_qual.csv", index=False)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
