#!/usr/bin/env python3
"""Part A: what the 400 coded survey questions ask for and need (RQ1; tracker F2, G8).

    python partA_results.py

Codes (PartA_Codebook_v1.md): labels/partA/partA_codes_agreed.csv (two coders, disagreements settled) if it exists,
else the author's check (labels/partA/partA_codes_author.csv, AUTHOR_CHECKED), else the AI pre-codes
(labels/partA/_ai_parts/, PROVISIONAL_AI_PRECODE). Stage and contributor come from outputs/partA_validation_rows.csv.

Estimates use analysis_partA.py: stage-weighted share of each value (W_s = N_s / N from the sample manifest), a
contributor-clustered bootstrap interval (2,000 resamples), the equal-contributor share, and the unique-text and
top-decile-excluded sensitivities. Never a chi-square that treats questions as independent people.
Writes results/partA/partA_results.json and numbers_partA.csv.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analysis_partA as A  # noqa: E402
from study_paths import F, LABELS, RESULTS, sha256  # noqa: E402

PA = LABELS / "partA"
OUT = RESULTS / "partA"
FIELDS = ["F1_request_type", "F2_evidence_source", "F3a_place", "F3b_time", "F3c_criterion", "F4_evidence_relation",
          "F5_answerable", "F6_purpose"]


def load() -> tuple:
    agreed, author = PA / "partA_codes_agreed.csv", PA / "partA_codes_author.csv"
    if agreed.exists():
        files, src = [agreed], "HUMAN_AGREED"
    elif author.exists():
        files, src = [author], "AUTHOR_CHECKED"
    else:
        files, src = sorted((PA / "_ai_parts").glob("partA_*.csv")), "PROVISIONAL_AI_PRECODE"
    codes = {}
    for p in files:
        with p.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if r["row_id"] in codes:
                    raise SystemExit(f"{r['row_id']} coded twice")
                codes[r["row_id"]] = r
    with (F / "outputs" / "partA_validation_rows.csv").open(encoding="utf-8-sig", newline="") as fh:
        base = list(csv.DictReader(fh))
    missing = [b["row_id"] for b in base if b["row_id"] not in codes]
    if missing:
        raise SystemExit(f"{len(missing)} of {len(base)} rows have no codes, e.g. {missing[:3]}")
    rows = [{**b, **{f: codes[b["row_id"]][f] for f in FIELDS}} for b in base]
    return rows, src, files


def main() -> int:
    rows, src, files = load()
    N = {k: int(v) for k, v in json.loads((F / "outputs" / "partA_sample_manifest.json").read_text(encoding="utf-8"))
         ["stage_sizes_N"].items()}
    counts = A.corpus_counts()
    res = {"label_source": src, "n_rows": len(rows), "stage_N": N, "inputs": {p.name: sha256(p)[:16] for p in files}}
    numbers = [{"key": "PA_n_rows", "value": str(len(rows)), "description": "Part A: coded survey rows"}]
    for f in FIELDS:
        est = A.estimates(rows, f, N, counts)
        res[f] = est
        short = f.split("_", 1)[0]
        for v, e in est.items():
            vk = v.replace("/", "")
            numbers += [
                {"key": f"PA_{short}_{vk}_pct", "value": f"{100 * e['p']:.1f}",
                 "description": f"Part A {f} = {v}: stage-weighted % of questions"},
                {"key": f"PA_{short}_{vk}_ci", "value": f"{100 * e['cluster_boot_95'][0]:.1f}-{100 * e['cluster_boot_95'][1]:.1f}",
                 "description": f"Part A {f} = {v}: contributor-clustered bootstrap 95% CI (%)"},
                {"key": f"PA_{short}_{vk}_n", "value": str(e["n_rows_with_label"]),
                 "description": f"Part A {f} = {v}: coded rows with the value"},
                {"key": f"PA_{short}_{vk}_eq", "value": f"{100 * e['equal_contributor']:.1f}",
                 "description": f"Part A {f} = {v}: equal-contributor % (each person counts once)"}]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "partA_results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    for r in numbers:
        r.update({"script": "partA_results.py", "label_source": src})
    with (OUT / "numbers_partA.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["key", "value", "description", "script", "label_source"], lineterminator="\n")
        w.writeheader()
        w.writerows(numbers)
    for f in ("F2_evidence_source", "F4_evidence_relation", "F5_answerable"):
        for v, e in res[f].items():
            print(f"{f:22s} {v:18s} {100 * e['p']:5.1f}%  boot [{100 * e['cluster_boot_95'][0]:.1f}, "
                  f"{100 * e['cluster_boot_95'][1]:.1f}]  equal-contributor {100 * e['equal_contributor']:.1f}%")
    print(f"label source: {src}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
