#!/usr/bin/env python3
"""RQ1 external validation: participants' own questions against corpus questions, coded blind to source with the
Part A codebook (codebook procedure step 3; Analysis_Specification section 4 "Corpus vs fresh"; tracker F5, G8).

    python rq1_fresh_vs_corpus.py make        # the blind mixed sheet, its closed source key, reading files
    python rq1_fresh_vs_corpus.py analyse     # distributions by source + contributor-clustered bootstrap differences
    python rq1_fresh_vs_corpus.py agree CODER1.csv CODER2.csv    # kappa / Jaccard per field + agreed_draft.csv
    python rq1_fresh_vs_corpus.py finalise labels/rq1/agreement/agreed_draft.csv   # -> fresh_vs_corpus_agreed.csv

make: the participants' own questions (written before they used OntoSage; deidentified_v1/own_questions.csv) mixed
with the 90 corpus rows drawn for this on 9 Oct (outputs/partA_corpus_for_fresh_comparison.csv), shuffled with the
project seed, item ids hashed, source hidden. Writes G_Study_Data/labels/rq1/:
  fresh_vs_corpus_sheet.csv        item_id, question_text, the Part A code columns (empty), note
  _source_key_KEEP_CLOSED.csv      item_id -> source (fresh / corpus), contributor, original id
  _reading/rq1_NN.md               the items in sheet order, 45 to a file
Refuses to overwrite an existing sheet.

analyse: reads labels/rq1/fresh_vs_corpus_agreed.csv when it exists (human, adjudicated), else the AI pre-codes in
labels/rq1/_ai_parts/rq1_*.csv (PROVISIONAL). For F2 (multi-label) each value's share of items, for F4 and F5 each
value's share; by source, and fresh minus corpus with a 95% bootstrap interval that resamples contributors within
each source (2,000 resamples, seed 20261009). Never a chi-square treating questions as independent. Writes
results/rq1/: fresh_vs_corpus.csv, fresh_vs_corpus_all_fields.csv, numbers_rq1.csv, rq1_results.json.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import DEID, F, LABELS, RESULTS, SEED, sha256  # noqa: E402

RQ1 = LABELS / "rq1"
CORPUS = F / "outputs" / "partA_corpus_for_fresh_comparison.csv"
CODE_COLS = ["F1_request_type", "F2_evidence_source", "F3a_place", "F3b_time", "F3c_criterion",
             "F4_evidence_relation", "F5_answerable", "F6_purpose", "F7_certainty"]
VALUES = {
    "F1_request_type": ["fact", "compare", "summarise", "rank", "explain", "capability", "action", "unclear"],
    "F2_evidence_source": ["measurement", "description", "record", "document", "external", "none"],
    "F3a_place": ["specified", "missing", "n/a"], "F3b_time": ["specified", "missing", "n/a"],
    "F3c_criterion": ["specified", "missing", "n/a"],
    "F4_evidence_relation": ["direct", "proxy", "not_establishable", "unclear"],
    "F5_answerable": ["yes", "partly", "no"], "F6_purpose": ["yes", "no"],
    "F7_certainty": ["clear", "uncertain", "discuss"],
}
MULTI = {"F1_request_type", "F2_evidence_source"}
PRIMARY = ["F2_evidence_source", "F4_evidence_relation", "F5_answerable"]   # the specification's comparison
B = 2000


def make() -> int:
    RQ1.mkdir(parents=True, exist_ok=True)
    sheet = RQ1 / "fresh_vs_corpus_sheet.csv"
    if sheet.exists():
        print(f"{sheet} exists; not overwritten (the sheet is drawn once)")
        return 1
    items = []
    for r in csv.DictReader((DEID / "own_questions.csv").open(encoding="utf-8")):
        q = (r.get("question") or "").strip()
        if q:
            items.append({"source": "fresh", "contributor": r["code"], "original_id": f"{r['code']}-{r['slot']}",
                          "question_text": q})
    for r in csv.DictReader(CORPUS.open(encoding="utf-8")):
        items.append({"source": "corpus", "contributor": r["contributor"], "original_id": r["row_id"],
                      "question_text": r["question_text"].strip()})
    for it in items:
        it["item_id"] = "Q" + hashlib.sha256(f"{SEED}|{it['source']}|{it['original_id']}".encode()).hexdigest()[:6]
    random.Random(SEED).shuffle(items)
    with sheet.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["item_id", "question_text"] + CODE_COLS + ["note"], lineterminator="\n")
        w.writeheader()
        for it in items:
            w.writerow({"item_id": it["item_id"], "question_text": it["question_text"], **{c: "" for c in CODE_COLS},
                        "note": ""})
    with (RQ1 / "_source_key_KEEP_CLOSED.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["item_id", "source", "contributor", "original_id"], lineterminator="\n")
        w.writeheader()
        for it in items:
            w.writerow({k: it[k] for k in ("item_id", "source", "contributor", "original_id")})
    rd = RQ1 / "_reading"
    rd.mkdir(exist_ok=True)
    for i in range(0, len(items), 45):
        part = items[i:i + 45]
        lines = [f"# RQ1 coding, items {i + 1}-{i + len(part)} of {len(items)} (source hidden)", ""]
        lines += [f"- **{it['item_id']}**: {it['question_text']}" for it in part]
        (rd / f"rq1_{i // 45 + 1:02d}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    n_f = sum(it["source"] == "fresh" for it in items)
    print(f"{len(items)} items ({n_f} fresh, {len(items) - n_f} corpus) -> {sheet}")
    return 0


def split(cell: str) -> list:
    return [x.strip() for x in str(cell).replace(",", ";").split(";") if x.strip()]


def load_codes() -> tuple:
    # keep_default_na=False: the codebook value "n/a" is a code, and pandas would otherwise read it as missing
    agreed, author = RQ1 / "fresh_vs_corpus_agreed.csv", RQ1 / "fresh_vs_corpus_author.csv"
    if agreed.exists():
        return pd.read_csv(agreed, dtype=str, keep_default_na=False), "HUMAN_AGREED", [agreed]
    if author.exists():                    # author_check/export_checked.py (plan 19, Option A)
        return pd.read_csv(author, dtype=str, keep_default_na=False), "AUTHOR_CHECKED", [author]
    parts = sorted((RQ1 / "_ai_parts").glob("rq1_*.csv"))
    if not parts:
        raise SystemExit("no codes yet: labels/rq1/_ai_parts/rq1_*.csv or fresh_vs_corpus_agreed.csv")
    d = pd.concat([pd.read_csv(p, dtype=str, keep_default_na=False) for p in parts], ignore_index=True)
    return d.drop_duplicates("item_id", keep="last"), "PROVISIONAL_AI_PRECODE", parts


def check(d: pd.DataFrame) -> list:
    errs = []
    for r in d.itertuples():
        for c in CODE_COLS:
            vals = split(getattr(r, c))
            if not vals:
                errs.append(f"{r.item_id}: {c} empty")
            elif c not in MULTI and len(vals) > 1:
                errs.append(f"{r.item_id}: {c} takes one value")
            elif any(v not in VALUES[c] for v in vals):
                errs.append(f"{r.item_id}: {c} = {getattr(r, c)}")
    return errs


def shares_by_source(d: pd.DataFrame, field: str) -> pd.DataFrame:
    rows = []
    for v in VALUES[field]:
        hit = d[field].map(lambda c: v in split(c))
        for s in ("fresh", "corpus"):
            m = d.source == s
            rows.append({"field": field, "value": v, "source": s, "n_items": int(m.sum()),
                         "n_with_value": int(hit[m].sum()), "share": float(hit[m].mean()) if m.any() else np.nan})
    return pd.DataFrame(rows)


def boot_diff(d: pd.DataFrame, field: str, value: str, rng: np.random.Generator) -> tuple:
    """Fresh minus corpus share, resampling contributors within each source (items stay with their contributor)."""
    hit = d[field].map(lambda c: value in split(c)).astype(float)
    groups = {s: [hit[(d.source == s) & (d.contributor == c)].values for c in d[d.source == s].contributor.unique()]
              for s in ("fresh", "corpus")}
    obs = hit[d.source == "fresh"].mean() - hit[d.source == "corpus"].mean()
    draws = []
    for _ in range(B):
        m = {}
        for s, gs in groups.items():
            pick = rng.integers(0, len(gs), len(gs))
            m[s] = np.concatenate([gs[i] for i in pick]).mean()
        draws.append(m["fresh"] - m["corpus"])
    return float(obs), float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def analyse() -> int:
    codes, source, inputs = load_codes()
    key = pd.read_csv(RQ1 / "_source_key_KEEP_CLOSED.csv", dtype=str, keep_default_na=False)
    errs = check(codes)
    if errs:
        print("not analysed, codes outside the codebook:\n  " + "\n  ".join(errs[:30]))
        return 1
    d = codes.drop(columns=[c for c in ("question_text",) if c in codes]).merge(key, on="item_id", how="inner")
    texts = pd.read_csv(RQ1 / "fresh_vs_corpus_sheet.csv", dtype=str, keep_default_na=False)
    d = d.merge(texts[["item_id", "question_text"]], on="item_id", how="left")
    missing = set(key.item_id) - set(codes.item_id)
    out = RESULTS / "rq1"
    out.mkdir(parents=True, exist_ok=True)
    allf = pd.concat([shares_by_source(d, f) for f in CODE_COLS], ignore_index=True)
    allf.to_csv(out / "fresh_vs_corpus_all_fields.csv", index=False)
    rng = np.random.default_rng(SEED)
    rows, nums = [], []
    for f in PRIMARY:
        for v in VALUES[f]:
            obs, lo, hi = boot_diff(d, f, v, rng)
            fr = allf[(allf.field == f) & (allf.value == v) & (allf.source == "fresh")].iloc[0]
            co = allf[(allf.field == f) & (allf.value == v) & (allf.source == "corpus")].iloc[0]
            rows.append({"field": f, "value": v, "fresh_n": int(fr.n_with_value), "fresh_items": int(fr.n_items),
                         "fresh_share": round(fr.share, 4), "corpus_n": int(co.n_with_value),
                         "corpus_items": int(co.n_items), "corpus_share": round(co.share, 4),
                         "diff_fresh_minus_corpus": round(obs, 4), "ci_lo": round(lo, 4), "ci_hi": round(hi, 4)})
            nums.append({"key": f"rq1_{f.split('_')[0]}_{v}_fresh_vs_corpus",
                         "value": f"{100 * fr.share:.0f}% vs {100 * co.share:.0f}%; {100 * obs:+.0f} "
                                  f"[{100 * lo:+.0f}, {100 * hi:+.0f}]",
                         "description": f"RQ1 {f} = {v}: share of participants' own questions vs corpus questions, "
                                        "fresh minus corpus (pp, contributor-clustered bootstrap 95% CI)",
                         "script": "rq1_fresh_vs_corpus.py", "label_source": source})
    tab = pd.DataFrame(rows)
    tab.to_csv(out / "fresh_vs_corpus.csv", index=False)
    # sensitivity (specification section 4): unique texts only, within each source
    norm = d.question_text.str.lower().str.replace(r"[^a-z0-9 ]", "", regex=True).str.split().str.join(" ")
    dup = d[norm.duplicated(keep=False)]
    du = d[~(norm.duplicated() & True)]
    uniq = {}
    for f in PRIMARY:
        for v in VALUES[f]:
            h = du[f].map(lambda c: v in split(c))
            uniq[f"{f}={v}"] = round(float(h[du.source == "fresh"].mean() - h[du.source == "corpus"].mean()), 4)
    nums.append({"key": "rq1_items", "value": f"{int((d.source == 'fresh').sum())} own questions from "
                 f"{d[d.source == 'fresh'].contributor.nunique()} participants; {int((d.source == 'corpus').sum())} corpus "
                 f"questions from {d[d.source == 'corpus'].contributor.nunique()} contributors",
                 "description": "RQ1 external validation: items coded", "script": "rq1_fresh_vs_corpus.py",
                 "label_source": source})
    pd.DataFrame(nums).to_csv(out / "numbers_rq1.csv", index=False)
    res = {"label_source": source, "inputs": {p.name: sha256(p)[:16] for p in inputs + [RQ1 / "_source_key_KEEP_CLOSED.csv"]},
           "items_coded": int(len(d)), "items_not_coded": len(missing), "primary": rows,
           "duplicate_texts": {"items": int(len(dup)), "by_source": dup.source.value_counts().to_dict(),
                               "across_sources": int(dup.groupby(norm[dup.index]).source.nunique().gt(1).sum())},
           "sensitivity_unique_texts_diff": uniq,
           "note": "Codebook v1 is a DRAFT until the first author's development session; AI pre-codes are provisional."}
    (out / "rq1_results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"{source}: {len(d)} items coded ({len(missing)} not coded)")
    print(tab.to_string(index=False))
    return 0


def agree(c1_path: str, c2_path: str, out: Path = None, id_col: str = "item_id") -> int:
    """Two coders' sheets: agreement per field (analysis_partA.agreement: kappa, mean Jaccard for multi-label
    fields), the disagreements, and agreed_draft.csv (coder 1's sheet with every disagreeing cell left empty, and the
    empty 'to_settle' and 'disputed' columns settlement.py reads). Part A reuses it with id_col='row_id'."""
    from analysis_partA import agreement
    c1 = pd.read_csv(c1_path, dtype=str, keep_default_na=False).rename(columns={id_col: "item_id"})
    c2 = pd.read_csv(c2_path, dtype=str, keep_default_na=False).rename(columns={id_col: "item_id"})
    for name, c in (("coder 1", c1), ("coder 2", c2)):
        errs = check(c[c.item_id.isin(set(c1.item_id) & set(c2.item_id))])
        if errs:
            print(f"{name}: codes outside the codebook:\n  " + "\n  ".join(errs[:20]))
            return 1
    rec = lambda c: [{**r, "row_id": r["item_id"]} for r in c.to_dict("records")]  # noqa: E731
    out = Path(out) if out else RQ1 / "agreement"
    out.mkdir(parents=True, exist_ok=True)
    res = agreement(rec(c1), rec(c2))
    (out / "agreement.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    both = c1.merge(c2[["item_id"] + CODE_COLS], on="item_id", suffixes=("_1", "_2"))
    dis = []
    draft = c1.copy().set_index("item_id")
    draft["to_settle"], draft["disputed"] = "", ""      # settlement.py: 'yes' where the meeting cannot agree (D7)
    for r in both.to_dict("records"):
        for c in CODE_COLS:
            if c == "F7_certainty":        # the coder's own certainty, not a code: coder 1's stays, nothing to settle
                continue
            a, b = sorted(split(r[f"{c}_1"])), sorted(split(r[f"{c}_2"]))
            if a != b:
                dis.append({id_col: r["item_id"], "field": c, "coder1": ";".join(a), "coder2": ";".join(b)})
                draft.loc[r["item_id"], c] = ""
                draft.loc[r["item_id"], "to_settle"] = " ".join(x for x in (draft.loc[r["item_id"], "to_settle"], c) if x)
    pd.DataFrame(dis, columns=[id_col, "field", "coder1", "coder2"]).to_csv(out / "disagreements.csv", index=False)
    draft.index.name = id_col
    draft.reset_index().to_csv(out / "agreed_draft.csv", index=False)
    print(json.dumps(res, indent=1, default=str)[:2000])
    print(f"{len(dis)} disagreeing cells over {len(both)} double-coded items -> {out}; fill each empty cell in "
          "agreed_draft.csv; where the meeting cannot agree, keep coder 1's value and write 'yes' under disputed")
    return 0


def finalise(draft_path: str, to: Path = None, id_col: str = "item_id", material: str = "mixed") -> int:
    """Check a filled agreed_draft.csv and write the agreed file the analysis reads (or `to`, for tests), and
    settlement.json beside it (settlement.py)."""
    import settlement
    draft = Path(draft_path)
    d = pd.read_csv(draft, dtype=str, keep_default_na=False)
    rows = d.to_dict("records")
    errs = check(d.rename(columns={id_col: "item_id"}))
    dis_p = draft.parent / "disagreements.csv"
    dis = pd.read_csv(dis_p, dtype=str, keep_default_na=False) if dis_p.exists() else pd.DataFrame(
        columns=[id_col, "field", "coder1"])
    errs += settlement.kept_first_author(rows, id_col, {(r[id_col], r["field"]): r["coder1"] for r in dis.to_dict("records")},
                                         norm=lambda s: ";".join(sorted(split(s))))
    if errs:
        print("not written; fill or correct first:\n  " + "\n  ".join(errs[:30]))
        return 1
    target = Path(to) if to else RQ1 / "fresh_vs_corpus_agreed.csv"
    d.drop(columns=[c for c in ("to_settle", "disputed") if c in d]).to_csv(target, index=False)
    print(f"{len(d)} items -> {target}" + ("" if to else " (the analysis now reads it)"))
    agr = draft.parent / "agreement.json"
    both = json.loads(agr.read_text(encoding="utf-8")).get("n_pairs", 0) if agr.exists() else 0
    settlement.write(draft, material, both, dis[id_col], settlement.disputed_ids(rows, id_col))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["make", "analyse", "agree", "finalise"])
    ap.add_argument("files", nargs="*", help="agree: CODER1 CODER2; finalise: DRAFT")
    ap.add_argument("--out", default="", help="agree: write here instead of labels/rq1/agreement/ (for tests)")
    ap.add_argument("--to", default="", help="finalise: write here instead of labels/rq1/ (for tests)")
    a = ap.parse_args()
    if a.mode == "agree":
        return agree(*a.files[:2], out=a.out or None) if len(a.files) >= 2 else ap.error("agree needs two coder sheets")
    if a.mode == "finalise":
        return finalise(a.files[0], to=a.to or None) if a.files else ap.error("finalise needs the draft")
    return make() if a.mode == "make" else analyse()


if __name__ == "__main__":
    raise SystemExit(main())
