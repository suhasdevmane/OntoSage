"""Turn the judge panel's output into filled scoring sheets, without opening any key.

    python scripts/llm_panel_apply.py eval/compound/scoring/llm_panel

Input: <dir>/panel_result.json (the workflow's return value: byAnswer, adjudications) and
<dir>/answer_map.json (or <dir>/private/answer_map.json, where llm_panel_build.py writes it).
- Final label per answer: the majority of three judges; where all three differ, the adjudicator's.
- criteria_covered: the median of the judges (the adjudicator's on a split).
- Fills label_X/label_Y/criteria_covered_X/Y/notes in eval/compound/scoring/<set>_sheet.csv.
- Writes the ablation arm's labels to eval/compound/scoring/<set>_ablation_labels.json.
- Writes eval/compound/scoring/llm_panel_record.json (every judgment, every rationale).
- Reports Fleiss' kappa over the three independent judges (six labels, and acceptable vs not).
Prints counts only.
"""
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
J = Path(sys.argv[1])
SC = REPO / "eval" / "compound" / "scoring"
LABELS = "ABCDEF"

res = json.loads((J / "panel_result.json").read_text(encoding="utf-8"))
_map = J / "answer_map.json" if (J / "answer_map.json").exists() else J / "private" / "answer_map.json"
amap = json.loads(_map.read_text(encoding="utf-8"))
by = res["byAnswer"]
adj = {a["answer_id"]: a for a in res.get("adjudications", [])}

missing = [a for a in amap if len(by.get(a, [])) < 3]
final = {}
for aid in amap:
    js = by.get(aid, [])
    c = Counter(j["label"] for j in js)
    top, n = (c.most_common(1)[0] if c else (None, 0))
    if n >= 2:
        cov = [j["criteria_covered"] for j in js if j["label"] == top]
        final[aid] = {"label": top, "cov": int(statistics.median(cov)), "how": f"{n}/{len(js)} judges"}
    elif aid in adj:
        final[aid] = {"label": adj[aid]["label"], "cov": adj[aid]["criteria_covered"],
                      "how": f"adjudicated ({'/'.join(j['label'] for j in js)})"}
    else:
        final[aid] = None

unresolved = [a for a, v in final.items() if v is None]
if unresolved:
    print(f"UNRESOLVED {len(unresolved)} answers (no majority, no adjudication): {unresolved[:10]}")
    sys.exit(2)

# --- sheets
by_set_item = defaultdict(dict)
for aid, m in amap.items():
    by_set_item[(m["set"], m["item"])][m["slot"]] = aid
for s in ("T-REAL", "T-REAL-SUPPLEMENT", "T-CAT"):
    p = SC / f"{s}_sheet.csv"
    rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
    fields = list(rows[0].keys())
    for r in rows:
        slots = by_set_item[(s, r["id"])]
        notes = []
        for slot in ("X", "Y"):
            f = final[slots[slot]]
            r[f"label_{slot}"] = f["label"]
            r[f"criteria_covered_{slot}"] = str(f["cov"])
            notes.append(f"{slot}: {f['how']}")
        r["notes"] = "LLM panel; " + "; ".join(notes)
    with open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    abl = {item: {"label": final[sl["Z"]]["label"], "cov": final[sl["Z"]]["cov"], "how": final[sl["Z"]]["how"]}
           for (ss, item), sl in by_set_item.items() if ss == s and "Z" in sl}
    if abl:
        (SC / f"{s}_ablation_labels.json").write_text(json.dumps(abl, indent=1), encoding="utf-8")

# --- full record (rationales), keyed by opaque id plus set/item (slot left out: the key unblinds)
record = {aid: {"set": amap[aid]["set"], "item": amap[aid]["item"],
                "is_ablation_arm": amap[aid]["slot"] == "Z",
                "final": final[aid], "judgments": by.get(aid, []), "adjudication": adj.get(aid)}
          for aid in amap}
(SC / "llm_panel_record.json").write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")


# --- Fleiss' kappa over answers with exactly three judgments
def fleiss(matrix):
    N = len(matrix)
    n = sum(matrix[0])
    k = len(matrix[0])
    p_j = [sum(row[j] for row in matrix) / (N * n) for j in range(k)]
    P_i = [(sum(c * c for c in row) - n) / (n * (n - 1)) for row in matrix]
    Pbar = sum(P_i) / N
    Pe = sum(p * p for p in p_j)
    return (Pbar - Pe) / (1 - Pe) if Pe < 1 else 1.0


three = [by[a] for a in amap if len(by.get(a, [])) == 3]
m6 = [[sum(j["label"] == L for j in js) for L in LABELS] for js in three]
m2 = [[sum(j["label"] in "ABC" for j in js), sum(j["label"] not in "ABC" for j in js)] for js in three]
unanimous = sum(1 for row in m6 if max(row) == 3)
majority = sum(1 for row in m6 if max(row) == 2)
split = sum(1 for row in m6 if max(row) == 1)
acc_unan = sum(1 for row in m2 if max(row) == 3)
out = {
    "answers": len(amap), "with_three_judgments": len(three), "missing_judgments": len(missing),
    "unanimous": unanimous, "two_of_three": majority, "three_way_split": split,
    "fleiss_kappa_six_labels": round(fleiss(m6), 3),
    "fleiss_kappa_acceptable_vs_not": round(fleiss(m2), 3),
    "unanimous_on_acceptability": acc_unan,
    "final_label_counts": dict(Counter(f["label"] for f in final.values())),
    "any_F_vote": sum(1 for a in amap if any(j["label"] == "F" for j in by.get(a, []))),
    "final_F": sum(1 for f in final.values() if f["label"] == "F"),
}
(SC / "llm_panel_agreement.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(json.dumps(out, indent=1))
