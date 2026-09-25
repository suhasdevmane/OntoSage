#!/usr/bin/env python3
"""
K_master_table_analysis.py
==========================

Deep analysis of the complexity master table produced by
``J_complexity_master_table.py``.  Reads
``outputs/tables/complexity_master_table.csv`` and writes every artifact
(charts, ranked tables, data-quality report, stats JSON) into
``outputs/master table analysis/``.

Artifacts produced
------------------
  00_data_quality_report.md        invariant validation of the LLM labels
  01_summary_statistics.json       every headline number used in the report
  T1_top60_hardest_questions.csv   composite-difficulty ranking
  T2_iceberg_questions.csv         cognitively simple but architecturally hard
  T3_level6_meta_questions.csv     all surface-L6 strategic questions
  T4_latent6_orchestration.csv     all latent-L6 cross-domain/actuation questions
  T5_new_capability_gaps.csv       canonicalised [NEW] gap frequencies
  T6_difficulty_by_role.csv        per-role difficulty profile
  T7_hardest_per_role.csv          the single hardest question per role
  F1_level_distributions.png       cognitive vs latent level histograms
  F2_level_vs_latent_heatmap.png   the "iceberg" cross-tab heatmap
  F3_answerability_stack.png       answerability share per latent level
  F4_new_gaps.png                  top capability gaps bar chart
  F5_role_difficulty.png           mean latent level by role
  F6_answer_basis.png              answer-basis split + basis x latent

Usage (from repo root or anywhere):
    python "paper/Survey analysis and results/scripts/K_master_table_analysis.py"
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SURVEY_ROOT = HERE.parent
INPUT = SURVEY_ROOT / "outputs" / "tables" / "complexity_master_table.csv"
OUTDIR = SURVEY_ROOT / "outputs" / "master table analysis"

LEVEL_NAMES = {
    1: "Factual Recall",
    2: "Comparative Analysis",
    3: "Inferential Reasoning",
    4: "Causal Diagnosis",
    5: "Systemic Synthesis",
    6: "Meta / Strategic Reasoning",
}

# Canonicalisation of free-text [NEW] items into a stable gap taxonomy.
# Order matters: first match wins.
GAP_RULES = [
    ("Occupancy sensing", r"occupan|footfall|people.?count|headcount|motion|\bpir\b|presence|door (event|sensor|usage)|contact sensor"),
    ("Energy metering", r"energy|submeter|power|electricit|kwh"),
    ("Weather feed", r"weather|outdoor temp|forecast feed|meteo"),
    ("Live streams floors 0-4", r"floors? ?0[-–]4|floor0|live stream|live temp|live co2|live humidit"),
    ("Calendar / room-booking API", r"calendar|booking|timetable|schedul|event feed"),
    ("BMS actuation / write-back", r"bms|write.?back|actuat|control (api|command|loop|point)|setpoint|valve|damper"),
    ("Noise / acoustic sensing", r"noise|acoustic|sound|decibel"),
    ("Water metering", r"water"),
    ("Occupant surveys / feedback", r"satisfaction|survey|wellbeing|productivity data|comfort feedback"),
    ("Lighting sensing/control", r"light|lux|illumina|daylight"),
    ("Extended IAQ (PM/VOC/NO2 etc.)", r"air quality|pm2|pm10|voc|particulate|pollutant|radon|ozone|\bno2\b|\biaq\b"),
    ("Tariff / cost data", r"tariff|price|cost data|billing"),
    ("Maintenance / CMMS records", r"maintenance|inspection|cmms|work.?order|asset (register|history)|service record|fault log"),
    ("Access / security systems", r"access|security|cctv|camera|badge|intrusion"),
    ("Equipment condition monitoring", r"vibration|accelerometer|voltage|current sensor|lift telemetry|equipment (health|condition|telemetry)|runtime"),
    ("Ontology metadata enrichment", r"capacity|tenant|quiet.?zone|appliance inventory|facade|window metadata|room metadata|material|asset metadata|unit mapping"),
    ("Parking / EV", r"parking|\bev\b|charger"),
    ("Waste / recycling", r"waste|recycl"),
    ("Solar / renewables", r"solar|photovolta|\bpv\b|renewable"),
    ("Carbon / ESG data", r"carbon|co2e|emission|esg|sustainab"),
    ("User profiles / preferences", r"user (preference|profile)|personalis"),
    ("Policy / document KB", r"policy|regulation|standards doc|document ingestion|manual ingestion"),
]

# Fragments that are pipeline-stage verbs, not capabilities — don't count as gaps
_GENERIC_FRAG = re.compile(
    r"^(data |telemetry |stream |generic )?(retrieval|ingestion|lookup|query|fetch|api)$"
)


def canonical_gap(text: str) -> "str | None":
    t = text.lower().strip()
    if _GENERIC_FRAG.match(t):
        return None
    for name, pat in GAP_RULES:
        if re.search(pat, t):
            return name
    return "Other / niche"


def extract_new_items(row: pd.Series) -> list:
    """Pull every distinct [NEW] item across architecture/data_sources/pipeline."""
    items = set()
    blob = " ; ".join(
        str(row[c]) for c in ("architecture", "data_sources", "pipeline_stages")
    )
    for m in re.finditer(r"\[NEW\]\s*([^;>]+?)(?=$|;|->|\[NEW\])", blob, re.IGNORECASE):
        frag = m.group(1).strip().rstrip(".,)")
        if frag:
            gap = canonical_gap(frag)
            if gap is not None:
                items.add(gap)
    return sorted(items)


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(INPUT, dtype=str).fillna("")
    df["level"] = pd.to_numeric(df["level"], errors="coerce")
    df["latent_level"] = pd.to_numeric(df["latent_level"], errors="coerce")
    n_total = len(df)

    # ------------------------------------------------------------------ #
    # 0. Data-quality / invariant validation
    # ------------------------------------------------------------------ #
    issues = {}
    issues["rows_total"] = n_total
    issues["duplicate_qids"] = int(df.duplicated("qid").sum())
    issues["level_out_of_range"] = int((~df["level"].between(1, 6)).sum())
    issues["latent_out_of_range"] = int((~df["latent_level"].between(1, 6)).sum())

    name_mismatch = (
        df["level_name"].str.strip().str.lower()
        != df["level"].map(LEVEL_NAMES).fillna("").str.lower()
    )
    issues["level_name_mismatch"] = int(name_mismatch.sum())
    lat_name_mismatch = (
        df["latent_level_name"].str.strip().str.lower()
        != df["latent_level"].map(LEVEL_NAMES).fillna("").str.lower()
    )
    issues["latent_name_mismatch"] = int(lat_name_mismatch.sum())

    gk = df[df["answer_basis"] == "general-knowledge"]
    issues["gk_rows"] = len(gk)
    issues["gk_latent_not_1"] = int((gk["latent_level"] != 1).sum())
    issues["gk_with_NEW"] = int(
        gk[["architecture", "data_sources", "pipeline_stages"]]
        .apply(lambda r: "[NEW]" in " ".join(r).upper().replace("[new]", "[NEW]"), axis=1)
        .sum()
    )
    issues["gk_not_full"] = int((gk["answerability"] != "full").sum())

    has_new = df[["architecture", "data_sources", "pipeline_stages"]].apply(
        lambda r: bool(re.search(r"\[NEW\]", " ".join(r), re.IGNORECASE)), axis=1
    )
    req_ext = df["answerability"] == "requires_extension"
    issues["requires_ext_without_NEW"] = int((req_ext & ~has_new).sum())
    issues["full_with_NEW"] = int(((df["answerability"] == "full") & has_new).sum())

    empty_fields = {
        c: int((df[c].str.strip() == "").sum())
        for c in ("architecture", "pipeline_stages", "data_sources", "answerability")
    }
    issues["empty_required_fields"] = empty_fields

    n_checked = 8
    n_violations = sum(
        v
        for k, v in issues.items()
        if k
        in (
            "duplicate_qids",
            "level_out_of_range",
            "latent_out_of_range",
            "level_name_mismatch",
            "latent_name_mismatch",
            "gk_latent_not_1",
            "requires_ext_without_NEW",
            "full_with_NEW",
        )
    )
    with (OUTDIR / "00_data_quality_report.md").open("w", encoding="utf-8") as f:
        f.write("# Data-Quality Report — complexity_master_table.csv\n\n")
        f.write(f"Rows: **{n_total}**  |  Invariants checked: {n_checked}  |  ")
        f.write(f"Total violating rows: **{n_violations}** ({n_violations/n_total:.2%})\n\n")
        f.write("| Invariant | Violations |\n|---|---|\n")
        f.write(f"| Duplicate qid (same question twice) | {issues['duplicate_qids']} |\n")
        f.write(f"| `level` outside 1-6 | {issues['level_out_of_range']} |\n")
        f.write(f"| `latent_level` outside 1-6 | {issues['latent_out_of_range']} |\n")
        f.write(f"| `level_name` does not match `level` | {issues['level_name_mismatch']} |\n")
        f.write(f"| `latent_level_name` mismatch | {issues['latent_name_mismatch']} |\n")
        f.write(
            f"| general-knowledge but latent_level != 1 | {issues['gk_latent_not_1']} "
            f"(of {issues['gk_rows']} GK rows) |\n"
        )
        f.write(f"| general-knowledge but contains [NEW] | {issues['gk_with_NEW']} |\n")
        f.write(f"| general-knowledge but answerability != full | {issues['gk_not_full']} |\n")
        f.write(f"| requires_extension but NO [NEW] item | {issues['requires_ext_without_NEW']} |\n")
        f.write(f"| answerability=full but HAS [NEW] item | {issues['full_with_NEW']} |\n")
        f.write(f"| Empty required fields | {empty_fields} |\n")

    # ------------------------------------------------------------------ #
    # 1. Derived columns
    # ------------------------------------------------------------------ #
    df["new_items"] = df.apply(extract_new_items, axis=1)
    df["n_new"] = df["new_items"].str.len()
    df["gap_score"] = df["latent_level"] - df["level"]  # iceberg metric
    # composite difficulty: system effort dominates, cognitive adds, each gap adds
    df["difficulty"] = df["latent_level"] * 2 + df["level"] + df["n_new"]

    # ------------------------------------------------------------------ #
    # 2. Summary statistics JSON
    # ------------------------------------------------------------------ #
    stats = {
        "rows": n_total,
        "model": df["model"].iloc[0],
        "level_dist": df["level"].value_counts().sort_index().to_dict(),
        "latent_dist": df["latent_level"].value_counts().sort_index().to_dict(),
        "answer_basis": df["answer_basis"].value_counts().to_dict(),
        "answerability": df["answerability"].value_counts().to_dict(),
        "mean_level": round(df["level"].mean(), 2),
        "mean_latent": round(df["latent_level"].mean(), 2),
        "pct_latent_gt_level": round((df["gap_score"] > 0).mean() * 100, 1),
        "pct_iceberg_ge2": round((df["gap_score"] >= 2).mean() * 100, 1),
        "pct_iceberg_ge3": round((df["gap_score"] >= 3).mean() * 100, 1),
        "answerable_today_pct": round((df["answerability"] == "full").mean() * 100, 1),
        "requires_extension_pct": round(
            (df["answerability"] == "requires_extension").mean() * 100, 1
        ),
        "stage_counts": df["stage"].value_counts().sort_index().to_dict(),
        "n_roles": int(df["roles"].nunique()),
        "data_quality_violations": n_violations,
    }

    # gap frequencies
    gap_counts = Counter()
    for items in df["new_items"]:
        for it in items:
            gap_counts[it] += 1
    stats["gap_counts"] = dict(gap_counts.most_common())
    # % of requires_extension rows resolved by top-N gaps
    ext = df[req_ext]
    for topn in (3, 5, 8):
        top = {g for g, _ in gap_counts.most_common(topn)}
        resolved = ext["new_items"].apply(lambda its: bool(its) and all(i in top for i in its))
        stats[f"ext_rows_fully_covered_by_top{topn}_gaps_pct"] = round(
            resolved.mean() * 100, 1
        )

    with (OUTDIR / "01_summary_statistics.json").open("w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, default=str)

    # ------------------------------------------------------------------ #
    # 3. Ranked tables
    # ------------------------------------------------------------------ #
    cols = [
        "qid", "roles", "stage", "question", "level", "level_name", "latent_level",
        "latent_level_name", "gap_score", "n_new", "difficulty", "answer_basis",
        "answerability", "why", "latent_why", "architecture", "pipeline_stages",
        "data_sources",
    ]
    df["new_items_str"] = df["new_items"].apply("; ".join)

    top60 = df.sort_values(
        ["difficulty", "latent_level", "level"], ascending=False
    ).head(60)
    top60[cols + ["new_items_str"]].to_csv(
        OUTDIR / "T1_top60_hardest_questions.csv", index=False
    )

    iceberg = df[(df["gap_score"] >= 3) & (df["level"] <= 2)].sort_values(
        ["gap_score", "latent_level"], ascending=False
    )
    iceberg[cols + ["new_items_str"]].to_csv(
        OUTDIR / "T2_iceberg_questions.csv", index=False
    )

    df[df["level"] == 6][cols].to_csv(OUTDIR / "T3_level6_meta_questions.csv", index=False)
    df[df["latent_level"] == 6][cols].to_csv(
        OUTDIR / "T4_latent6_orchestration.csv", index=False
    )

    pd.DataFrame(
        [(g, c, round(100 * c / n_total, 1)) for g, c in gap_counts.most_common()],
        columns=["capability_gap", "questions_needing_it", "pct_of_corpus"],
    ).to_csv(OUTDIR / "T5_new_capability_gaps.csv", index=False)

    role_grp = (
        df.groupby("roles")
        .agg(
            n=("qid", "size"),
            mean_level=("level", "mean"),
            mean_latent=("latent_level", "mean"),
            pct_requires_ext=("answerability", lambda s: 100 * (s == "requires_extension").mean()),
            pct_general_knowledge=("answer_basis", lambda s: 100 * (s == "general-knowledge").mean()),
        )
        .round(2)
        .sort_values("n", ascending=False)
    )
    role_grp.to_csv(OUTDIR / "T6_difficulty_by_role.csv")

    hardest_per_role = (
        df.sort_values("difficulty", ascending=False).groupby("roles").head(1)
    )[["roles", "question", "level", "latent_level", "difficulty", "answerability", "new_items_str"]]
    hardest_per_role.sort_values("difficulty", ascending=False).to_csv(
        OUTDIR / "T7_hardest_per_role.csv", index=False
    )

    # ------------------------------------------------------------------ #
    # 4. Charts
    # ------------------------------------------------------------------ #
    plt.rcParams.update({"figure.dpi": 150, "font.size": 9, "axes.grid": True,
                         "grid.alpha": 0.3, "axes.axisbelow": True})

    # F1 — distributions
    fig, ax = plt.subplots(figsize=(8, 4))
    levels = np.arange(1, 7)
    lv = df["level"].value_counts().reindex(levels, fill_value=0)
    lat = df["latent_level"].value_counts().reindex(levels, fill_value=0)
    w = 0.38
    ax.bar(levels - w / 2, lv.values, w, label="Surface / cognitive (level)", color="#4C72B0")
    ax.bar(levels + w / 2, lat.values, w, label="Latent / architectural", color="#DD8452")
    for x, v in zip(levels - w / 2, lv.values):
        ax.text(x, v + 30, str(v), ha="center", fontsize=7)
    for x, v in zip(levels + w / 2, lat.values):
        ax.text(x, v + 30, str(v), ha="center", fontsize=7)
    ax.set_xticks(levels)
    ax.set_xticklabels([f"L{i}\n{LEVEL_NAMES[i].split(' /')[0]}" for i in levels], fontsize=7)
    ax.set_ylabel("questions")
    ax.set_title(f"Cognitive vs architectural complexity of {n_total} real user questions")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUTDIR / "F1_level_distributions.png")
    plt.close(fig)

    # F2 — heatmap
    ct = pd.crosstab(df["latent_level"], df["level"]).reindex(
        index=levels, columns=levels, fill_value=0
    )
    fig, ax = plt.subplots(figsize=(7, 5.5))
    im = ax.imshow(ct.values, cmap="YlOrRd", origin="lower", aspect="auto")
    for i in range(6):
        for j in range(6):
            v = ct.values[i, j]
            if v:
                ax.text(j, i, str(v), ha="center", va="center",
                        color="white" if v > ct.values.max() * 0.5 else "black", fontsize=8)
    ax.set_xticks(range(6)); ax.set_xticklabels([f"L{i}" for i in levels])
    ax.set_yticks(range(6)); ax.set_yticklabels([f"L{i}" for i in levels])
    ax.set_xlabel("SURFACE cognitive level (how hard for a human)")
    ax.set_ylabel("LATENT architectural level (how hard for the system)")
    ax.plot([-0.5, 5.5], [-0.5, 5.5], "k--", lw=1, alpha=0.6)
    ax.set_title("The complexity iceberg: questions above the diagonal look easy\n"
                 "to humans but are architecturally hard for the system")
    fig.colorbar(im, label="questions")
    fig.tight_layout()
    fig.savefig(OUTDIR / "F2_level_vs_latent_heatmap.png")
    plt.close(fig)

    # F3 — answerability per latent level
    ab = pd.crosstab(df["latent_level"], df["answerability"], normalize="index") * 100
    order = [c for c in ("full", "partial", "requires_extension") if c in ab.columns]
    ab = ab.reindex(columns=order).reindex(index=levels, fill_value=0)
    fig, ax = plt.subplots(figsize=(8, 4))
    bottom = np.zeros(6)
    colors = {"full": "#55A868", "partial": "#CCB974", "requires_extension": "#C44E52"}
    for c in order:
        ax.bar(levels, ab[c].values, bottom=bottom, label=c, color=colors[c])
        bottom += ab[c].values
    counts = df["latent_level"].value_counts().reindex(levels, fill_value=0)
    for x, n in zip(levels, counts.values):
        ax.text(x, 101, f"n={n}", ha="center", fontsize=7)
    ax.set_xticks(levels); ax.set_xlabel("latent (architectural) level")
    ax.set_ylabel("% of questions"); ax.set_ylim(0, 108)
    ax.set_title("Answerability by architectural complexity (current bldg1 deployment)")
    ax.legend(loc="lower left")
    fig.tight_layout()
    fig.savefig(OUTDIR / "F3_answerability_stack.png")
    plt.close(fig)

    # F4 — capability gaps
    top_gaps = gap_counts.most_common(14)
    fig, ax = plt.subplots(figsize=(8, 5))
    names = [g for g, _ in top_gaps][::-1]
    vals = [c for _, c in top_gaps][::-1]
    ax.barh(names, vals, color="#C44E52")
    for y, v in enumerate(vals):
        ax.text(v + 5, y, f"{v}  ({100*v/n_total:.1f}%)", va="center", fontsize=7)
    ax.set_xlabel("questions needing this missing capability")
    ax.set_title("What real users ask for that bldg1 cannot yet measure\n"
                 "(canonicalised [NEW] items across 5,604 questions)")
    fig.tight_layout()
    fig.savefig(OUTDIR / "F4_new_gaps.png")
    plt.close(fig)

    # F5 — role difficulty (roles with >= 80 questions)
    def short_role(r: str) -> str:
        parts = [p.strip() for p in r.split(";")]
        first = parts[0].split("/")[0].strip()
        if len(parts) > 1:
            return f"{first} +{len(parts) - 1} roles"
        return parts[0][:38]

    big = role_grp[role_grp["n"] >= 80].sort_values("mean_latent")
    fig, ax = plt.subplots(figsize=(8.5, 0.45 * len(big) + 1.5))
    y = np.arange(len(big))
    ax.barh(y - 0.18, big["mean_level"], 0.36, label="mean cognitive level", color="#4C72B0")
    ax.barh(y + 0.18, big["mean_latent"], 0.36, label="mean architectural level", color="#DD8452")
    ax.set_yticks(y)
    ax.set_yticklabels(
        [f"{short_role(r)}  (n={int(n)})" for r, n in zip(big.index, big["n"])], fontsize=8
    )
    ax.set_xlabel("mean level (1-6)")
    ax.set_title("Question difficulty by asker role — lay users implicitly demand\n"
                 "more system architecture than professionals")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(OUTDIR / "F5_role_difficulty.png", bbox_inches="tight")
    plt.close(fig)

    # F6 — answer basis
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    basis = df["answer_basis"].value_counts()
    axes[0].pie(basis.values, labels=[f"{k}\n{v} ({100*v/n_total:.0f}%)" for k, v in basis.items()],
                colors=["#4C72B0", "#DD8452", "#55A868"], startangle=90)
    axes[0].set_title("How answers are sourced")
    bb = pd.crosstab(df["answer_basis"], df["latent_level"]).reindex(columns=levels, fill_value=0)
    bb_pct = bb.div(bb.sum(axis=1), axis=0) * 100
    bottom = np.zeros(len(bb_pct))
    cmap = plt.cm.YlOrRd(np.linspace(0.25, 0.95, 6))
    for i, lvl in enumerate(levels):
        axes[1].bar(bb_pct.index, bb_pct[lvl].values, bottom=bottom,
                    label=f"latent L{lvl}", color=cmap[i])
        bottom += bb_pct[lvl].values
    axes[1].set_ylabel("% of questions"); axes[1].set_title("Architectural effort by answer basis")
    axes[1].legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(OUTDIR / "F6_answer_basis.png")
    plt.close(fig)

    # ------------------------------------------------------------------ #
    print(f"Wrote artifacts to: {OUTDIR}")
    print(json.dumps(stats, indent=2, default=str)[:3000])


if __name__ == "__main__":
    main()
