#!/usr/bin/env python3
"""Stage 5 Trust and Success answers: how many of the 59 contributors named each requirement (tracker F4).

    python stage5_analysis.py

Codes (Stage5_Trust_Success_Codebook.md): labels/stage5/stage5_codes_agreed.csv if it ever exists, else the author's
review (labels/stage5/stage5_codes_author.csv, AUTHOR_CHECKED_SINGLE_CODER), else the AI pre-codes
(labels/stage5/_ai_parts/, PROVISIONAL_AI_PRECODE). The codebook plans one coder for this material and the second coder's
pack holds none of it, so the author's complete review is the final state (make_number_macros prints it as final) unless
a second coder is added.

Unit = one contributor's answer; every count is of people (out of 59), with a Wilson 95% interval. OTHER answers are
also counted by their inductive theme. Writes results/stage5/: stage5_codes.csv, stage5_themes.csv,
numbers_stage5.csv, stage5_results.json.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import LABELS, RESULTS, sha256  # noqa: E402

S5 = LABELS / "stage5"
OUT = RESULTS / "stage5"
CODES = ["PROVENANCE", "ACCURACY", "PRIVACY", "TIMELINESS", "ACTIONABILITY", "HONESTY_LIMITS", "EASE", "OTHER", "NONE"]


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def load() -> tuple:
    agreed, author = S5 / "stage5_codes_agreed.csv", S5 / "stage5_codes_author.csv"
    if agreed.exists():
        files, src = [agreed], "HUMAN_AGREED"
    elif author.exists():                           # written only once all 118 are reviewed at a reading pace
        files, src = [author], "AUTHOR_CHECKED_SINGLE_CODER"
    else:
        files, src = sorted((S5 / "_ai_parts").glob("stage5_*.csv")), "PROVISIONAL_AI_PRECODE"
    rows = []
    for p in files:
        with p.open(encoding="utf-8-sig", newline="") as fh:
            rows += list(csv.DictReader(fh))
    for r in rows:
        r["question"] = r.get("question") or r["unit_id"].split("-", 1)[0]
    ids = [r["unit_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise SystemExit("a unit is coded twice")
    return rows, src, files


OLD_SCRIPTS = Path(__file__).resolve().parents[4] / "Survey analysis and results" / "scripts"
OLD_THEMES = OLD_SCRIPTS.parent / "outputs" / "tables" / "Z_stage5_vision_themes.csv"
OLD_NAMES = {"Privacy and surveillance": "privacy", "Explanation and provenance": "provenance",
             "Accuracy and error": "accuracy", "Security and access control": "security", "Consent and opt-out": "consent"}


def near_duplicates() -> tuple:
    """The earlier Stage 5 analysis's cluster of near-identical answers, per prompt, as unit ids: its own rule
    (Z_stage5_vision_analysis.templated, character-sequence similarity >= SIMILARITY to another answer), so the
    sensitivity count sets aside exactly the answers the earlier keyword count set aside."""
    sys.path.insert(0, str(OLD_SCRIPTS))
    sys.path.insert(0, str(Path(__file__).resolve().parent / "author_check"))
    import Z_stage5_vision_analysis as Z  # noqa: E402
    from build_check_items import STAGE5_SRC, contributor_id  # noqa: E402
    with STAGE5_SRC.open(encoding="utf-8-sig", newline="") as fh:
        src = list(csv.DictReader(fh))
    return {q: {f"{q}-{contributor_id(u)}" for u in Z.templated(src, q)} for q in ("Trust", "Success")}, Z.SIMILARITY


def main() -> int:
    rows, src, files = load()
    OUT.mkdir(parents=True, exist_ok=True)
    table, themes, numbers = [], [], []
    cluster, similarity = near_duplicates()
    numbers.append({"key": "S5_cluster_similarity", "value": f"{similarity:.2f}",
                    "description": "Stage 5: similarity at or above which the earlier analysis set an answer aside as "
                                   "near-identical (Z_stage5_vision_analysis.SIMILARITY)"})
    for q in ("Trust", "Success"):
        sub = [r for r in rows if r["question"] == q]
        ids = cluster[q] & {r["unit_id"] for r in sub}
        rest = [r for r in sub if r["unit_id"] not in ids]
        numbers += [{"key": f"S5_{q}_cluster_n", "value": str(len(ids)),
                     "description": f"Stage 5 {q}: answers in the earlier analysis's near-identical cluster"},
                    {"key": f"S5_{q}_without_cluster_n", "value": str(len(rest)),
                     "description": f"Stage 5 {q}: contributors outside that cluster"}]
        for c in CODES:
            kc = sum((r.get(c) or "").strip() == "1" for r in sub if r["unit_id"] in ids)
            kr = sum((r.get(c) or "").strip() == "1" for r in rest)
            numbers += [{"key": f"S5_{q}_{c}_k_n_without_cluster", "value": f"{kr}/{len(rest)}",
                         "description": f"Stage 5 {q}: people coded {c}, near-identical cluster set aside"},
                        {"key": f"S5_{q}_cluster_{c}_k_n", "value": f"{kc}/{len(ids)}",
                         "description": f"Stage 5 {q}: answers in the near-identical cluster coded {c}"}]
        sub = [r for r in rows if r["question"] == q]
        n = len(sub)
        for c in CODES:
            k = sum((r.get(c) or "").strip() == "1" for r in sub)
            lo, hi = wilson(k, n)
            table.append({"question": q, "code": c, "people": k, "of": n, "pct": round(100 * k / n, 1),
                          "ci_lo": round(100 * lo, 1), "ci_hi": round(100 * hi, 1), "label_source": src})
            numbers += [
                {"key": f"S5_{q}_{c}_k_n", "value": f"{k}/{n}", "description": f"Stage 5 {q}: people coded {c}"},
                {"key": f"S5_{q}_{c}_pct", "value": f"{100 * k / n:.0f}", "description": f"Stage 5 {q}: % of people coded {c}"},
                {"key": f"S5_{q}_{c}_ci", "value": f"{100 * lo:.0f}-{100 * hi:.0f}",
                 "description": f"Stage 5 {q}: Wilson 95% CI for {c} (%)"}]
        tc = Counter(t.strip() for r in sub if (r.get("OTHER") or "").strip() == "1"
                     for t in (r.get("inductive") or "").split(";") if t.strip())
        for t, k in tc.most_common():
            themes.append({"question": q, "theme": t, "people": k, "of": n, "label_source": src})
            numbers.append({"key": f"S5_{q}_theme_{t}_k_n", "value": f"{k}/{n}",
                            "description": f"Stage 5 {q}: people whose OTHER code names the theme '{t}'"})
        numbers.append({"key": f"S5_{q}_n", "value": str(n), "description": f"Stage 5 {q}: contributors"})
    with OLD_THEMES.open(encoding="utf-8-sig", newline="") as fh:       # the earlier keyword count, as published
        for r in csv.DictReader(fh):
            if r["prompt"] == "Trust" and r["theme"] in OLD_NAMES:
                t = OLD_NAMES[r["theme"]]
                numbers += [{"key": f"S5_old_Trust_{t}_pct_all", "value": f"{float(r['pct_all']):.0f}",
                             "description": f"Earlier keyword count, Trust '{r['theme']}': % of all {r['n_base_all']}"},
                            {"key": f"S5_old_Trust_{t}_pct_without_cluster", "value": f"{float(r['pct_detemplated']):.0f}",
                             "description": f"Earlier keyword count, Trust '{r['theme']}': % of the "
                                            f"{r['n_base_detemplated']} outside the near-identical cluster"}]
    for name, data in (("stage5_codes.csv", table), ("stage5_themes.csv", themes)):
        with (OUT / name).open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(data[0].keys()), lineterminator="\n")
            w.writeheader()
            w.writerows(data)
    for r in numbers:
        r.update({"script": "stage5_analysis.py", "label_source": src})
    with (OUT / "numbers_stage5.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["key", "value", "description", "script", "label_source"], lineterminator="\n")
        w.writeheader()
        w.writerows(numbers)
    res = {"label_source": src, "inputs": {p.name: sha256(p)[:16] for p in [*files, OLD_THEMES]},
           "codes": table, "themes": themes}
    (OUT / "stage5_results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    for r in table:
        if r["people"]:
            print(f"{r['question']:8s} {r['code']:15s} {r['people']:3d}/{r['of']}  {r['pct']:5.1f}% [{r['ci_lo']}, {r['ci_hi']}]")
    print(f"label source: {src}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
