"""
H_evaluation_analysis.py
========================
Phase H: OntoSage System Evaluation Against Pre-Development Survey Corpus

Joins survey_evaluation_results.csv (5,916 OntoSage responses) with the
classified_corpus.csv (Phase B classifications) to produce IMWUT-ready
evaluation metrics, figures, and tables.

Output structure:
  outputs/tables/H*.csv     — LaTeX-ready tables
  outputs/figures/H*.{png,pdf} — publication figures (300 dpi)
  outputs/tables/H_evaluation_summary.md — narrative summary

Usage:
  cd "paper/Survey analysis and results"
  python scripts/H_evaluation_analysis.py
"""

import csv
import json
import math
import os
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from scipy import stats
from scipy.stats import chi2_contingency, kruskal

warnings.filterwarnings("ignore", category=UserWarning)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE = Path(__file__).parent.parent
EVAL_CSV = BASE / "outputs" / "survey_evaluation_results.csv"
CORPUS_CSV = BASE / "corpus" / "classified_corpus.csv"
OUT_TABLES = BASE / "outputs" / "tables"
OUT_FIGS = BASE / "outputs" / "figures"
OUT_TABLES.mkdir(parents=True, exist_ok=True)
OUT_FIGS.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Publication style constants (IMWUT / ACM)
# ---------------------------------------------------------------------------
SINGLE_COL_W = 3.33   # inches — ACM single column
DOUBLE_COL_W = 7.00   # inches — ACM double column
DPI = 300

# Colorblind-friendly palette (Wong 2011, 8-colour)
PALETTE = {
    "GROUNDED":      "#0072B2",   # blue
    "INFORMATIONAL": "#56B4E9",   # sky blue
    "DISAMBIGUATION":"#009E73",   # green
    "BOUNDARY":      "#E69F00",   # orange
    "FAILED":        "#D55E00",   # vermillion
}
OUTCOME_ORDER = ["GROUNDED", "INFORMATIONAL", "DISAMBIGUATION", "BOUNDARY", "FAILED"]

DOMAIN_LABELS = {
    "OTHER":       "Other / Cross-domain",
    "ENERGY":      "Energy & Power",
    "AIR_QUALITY": "Air Quality & IAQ",
    "THERMAL":     "Thermal Comfort",
    "LIGHTING":    "Lighting",
    "SAFETY":      "Safety & Compliance",
    "SECURITY":    "Security & Access",
    "OCCUPANCY":   "Occupancy & Space",
}

QUERY_LABELS = {
    "STATUS":         "Status / Current",
    "CAPABILITY":     "Capability / Can-It",
    "COMPARISON":     "Comparison",
    "ANOMALY":        "Anomaly Detection",
    "DIAGNOSTIC":     "Diagnostic",
    "RECOMMENDATION": "Recommendation",
    "HISTORICAL":     "Historical Trend",
}

INTENT_LABELS = {
    "INFORMATIONAL": "Informational",
    "DIAGNOSTIC":    "Diagnostic",
    "PRESCRIPTIVE":  "Prescriptive",
    "PREDICTIVE":    "Predictive",
}

COMPLEXITY_ORDER = ["LOOKUP", "AGGREGATION", "MULTI_STEP"]
COMPLEXITY_LABELS = {
    "LOOKUP":     "Lookup (L1)",
    "AGGREGATION":"Aggregation (L2)",
    "MULTI_STEP": "Multi-step (L3)",
}

STAGE_LABELS = {
    "1": "S1: Zero-context",
    "2": "S2: Sensor-aware",
    "3": "S3: Scenario",
    "4": "S4: Goal-oriented",
}

PERSONA_MAP = {
    "Student/Researchers/Academics":                     "Researcher",
    "Guests/Visitors":                                   "Guest/Visitor",
    "Occupants/Tenants/Employees":                       "Occupant",
    "IT/Data Scientists":                                "IT/Data Sci.",
    "Facility Managers / Building Maintenance Teams":    "Facility Mgr.",
    "Building Owners/Property Managers":                 "Building Owner",
    "Health and Safety Officers":                        "Health & Safety",
    "Sustainability and Energy Management Teams":        "Sustainability",
}

plt.rcParams.update({
    "font.family":       "serif",
    "font.serif":        ["Times New Roman", "DejaVu Serif"],
    "font.size":         9,
    "axes.titlesize":    9,
    "axes.labelsize":    9,
    "xtick.labelsize":   8,
    "ytick.labelsize":   8,
    "legend.fontsize":   8,
    "figure.dpi":        DPI,
    "savefig.dpi":       DPI,
    "savefig.bbox":      "tight",
    "axes.spines.right": False,
    "axes.spines.top":   False,
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple:
    """Wilson score confidence interval for a proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def cramers_v(contingency_table: np.ndarray) -> float:
    """Cramer's V effect size for chi-square test."""
    chi2, _, _, _ = chi2_contingency(contingency_table)
    n = contingency_table.sum()
    r, k = contingency_table.shape
    return math.sqrt(chi2 / (n * (min(r, k) - 1))) if n > 0 else 0.0


def kw_eta_squared(groups: list) -> float:
    """Eta-squared effect size for Kruskal-Wallis."""
    H, _ = kruskal(*groups)
    n = sum(len(g) for g in groups)
    k = len(groups)
    return (H - k + 1) / (n - k) if n > k else 0.0


def savefig(name: str, fig):
    for ext in ("png", "pdf"):
        fig.savefig(OUT_FIGS / f"{name}.{ext}")
    plt.close(fig)
    print(f"  [fig] {name}")


def write_csv(name: str, rows: list, fieldnames: list):
    path = OUT_TABLES / f"{name}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"  [tbl] {name}.csv")


# ---------------------------------------------------------------------------
# Response outcome classifier (5-class)
# ---------------------------------------------------------------------------

def classify_outcome(row: dict) -> str:
    """
    Classify a system response into one of five mutually exclusive outcomes.

    GROUNDED      — response contains specific building data (sensor readings,
                    tables, concrete numbers, room/floor-specific values)
    INFORMATIONAL — general domain knowledge, no specific building data
    DISAMBIGUATION— system asks a clarifying question to narrow the request
    BOUNDARY      — graceful refusal: data not available / out of scope
    FAILED        — timeout or empty response
    """
    err = row.get("error", "").strip().lower()
    resp = row.get("response", "").strip()
    resp_l = resp.lower()

    # ── FAILED ──────────────────────────────────────────────────────────────
    if err in ("timed out", "timeout") or not resp:
        return "FAILED"

    # ── GROUNDED ─────────────────────────────────────────────────────────────
    # Markdown table with numeric data
    if "|" in resp and resp.count("|") >= 4 and any(c.isdigit() for c in resp):
        return "GROUNDED"

    grounded_patterns = [
        "current reading", "sensor reading", "latest reading",
        "temperature:", "humidity:", "co2:", "pm2.5:", "pm10:",
        "kwh", " lux", "ppm", "°c", "°f",
        "average of", "mean value", "minimum:", "maximum:",
        "floor 5", "room 5.", "zone a", "zone b",
        "as of ", "at the time", "recorded at",
        "energy consumption:", "power draw:", "occupancy count",
        "reading at", "data for", "values for",
    ]
    if any(p in resp_l for p in grounded_patterns):
        return "GROUNDED"

    # ── DISAMBIGUATION ───────────────────────────────────────────────────────
    disambiguation_patterns = [
        "which room", "which floor", "which zone", "which sensor",
        "which area", "which space", "which building",
        "please specify", "could you specify",
        "could you clarify", "can you clarify",
        "i need to know", "need more context",
        "what do you mean by", "do you mean",
        "what time period", "which date", "which day",
        "what type of", "are you asking about",
        "1)", "option 1", "a)", "(1)",   # numbered disambiguation menus
    ]
    # Only flag as disambiguation if there is a clear question / option structure
    has_question = "?" in resp
    has_options = any(p in resp_l for p in ["1)", "(1)", "option 1", "a)", "b)"])
    disambig_hit = any(p in resp_l for p in disambiguation_patterns)
    if disambig_hit and (has_question or has_options):
        return "DISAMBIGUATION"

    # ── BOUNDARY ─────────────────────────────────────────────────────────────
    boundary_patterns = [
        "i couldn't find", "i could not find",
        "no sensor data", "no data available",
        "not available in", "not in my knowledge",
        "compliance check", "zone or sensor required",
        "beyond my current", "not supported",
        "unable to retrieve", "unable to access",
        "no results", "no records found",
        "does not have", "no information",
        "this falls outside", "outside the scope",
        "not monitored", "no relevant sensor",
    ]
    if any(p in resp_l for p in boundary_patterns):
        return "BOUNDARY"

    # ── INFORMATIONAL ────────────────────────────────────────────────────────
    # General domain knowledge, explanatory, conceptual
    informational_patterns = [
        "typically", "generally", "in most buildings",
        "smart building", "building management", "hvac",
        "bms", "usually", "commonly", "standard practice",
        "in general", "yes,", "yes.", "no,",
        "this refers to", "this involves",
        "there are several", "common ways",
        "can include", "may include",
        "acoustic", "outdoor environmental",
        "pollutant source", "air quality",
        "energy efficiency", "passive design",
    ]
    if any(p in resp_l for p in informational_patterns):
        return "INFORMATIONAL"

    # Default: treat remaining substantive responses as INFORMATIONAL
    # (they have content but don't fit grounded / boundary categories)
    if len(resp) > 30:
        return "INFORMATIONAL"

    return "FAILED"


def primary_persona(personas_str: str) -> str:
    """Extract first persona from a semicolon-separated persona string."""
    first = personas_str.split(";")[0].strip()
    return PERSONA_MAP.get(first, first[:20])


# ---------------------------------------------------------------------------
# Load and join data
# ---------------------------------------------------------------------------

def load_data() -> list:
    print("Loading data...")
    with open(EVAL_CSV, encoding="utf-8") as f:
        eval_map = {r["question"].strip().lower(): r for r in csv.DictReader(f)}

    with open(CORPUS_CSV, encoding="utf-8") as f:
        corpus = list(csv.DictReader(f))

    joined = []
    for row in corpus:
        q = row["Question"].strip().lower()
        er = eval_map.get(q)
        if er is None:
            continue
        try:
            lat = float(er["latency_sec"])
        except (ValueError, KeyError):
            lat = None
        joined.append({
            "pid":        row["PID"],
            "persona":       primary_persona(row["Personas"]),
            "stage":      row["Stage"],
            "question":   row["Question"],
            "domain":     row["domain_l1"],
            "query_type": row["query_type_l2"],
            "intent":     row["intent"],
            "complexity": row["complexity"],
            "response":   er.get("response", ""),
            "error":      er.get("error", ""),
            "latency":    lat,
            "outcome":    classify_outcome(er),
        })

    print(f"  Joined {len(joined)} rows")
    return joined


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def outcome_counts(rows: list) -> dict:
    c = Counter(r["outcome"] for r in rows)
    return {o: c.get(o, 0) for o in OUTCOME_ORDER}


def answer_rate(rows: list) -> tuple:
    """
    Returns (rate, ci_lo, ci_hi) where 'answered' = GROUNDED + INFORMATIONAL.
    """
    n = len(rows)
    k = sum(1 for r in rows if r["outcome"] in ("GROUNDED", "INFORMATIONAL"))
    if n == 0:
        return (0.0, 0.0, 0.0)
    lo, hi = wilson_ci(k, n)
    return (k / n, lo, hi)


def data_grounded_rate(rows: list) -> tuple:
    n = len(rows)
    k = sum(1 for r in rows if r["outcome"] == "GROUNDED")
    if n == 0:
        return (0.0, 0.0, 0.0)
    lo, hi = wilson_ci(k, n)
    return (k / n, lo, hi)


def latency_stats(rows: list) -> dict:
    lats = [r["latency"] for r in rows if r["latency"] is not None]
    if not lats:
        return {}
    lats_arr = np.array(lats)
    return {
        "n":      len(lats),
        "mean":   float(np.mean(lats_arr)),
        "median": float(np.median(lats_arr)),
        "sd":     float(np.std(lats_arr, ddof=1)),
        "p25":    float(np.percentile(lats_arr, 25)),
        "p75":    float(np.percentile(lats_arr, 75)),
        "p90":    float(np.percentile(lats_arr, 90)),
        "max":    float(np.max(lats_arr)),
    }


# ---------------------------------------------------------------------------
# H1 — Overall metrics summary
# ---------------------------------------------------------------------------

def h1_overall_metrics(rows: list):
    print("\n[H1] Overall metrics...")
    n = len(rows)
    oc = outcome_counts(rows)
    ar, ar_lo, ar_hi = answer_rate(rows)
    dgr, dgr_lo, dgr_hi = data_grounded_rate(rows)
    ls = latency_stats(rows)

    # Print headline
    print(f"  N = {n:,}")
    for o, c in oc.items():
        print(f"  {o:<18}  {c:5}  ({100*c/n:.1f}%)")
    print(f"  Answer rate:   {100*ar:.1f}%  [{100*ar_lo:.1f}–{100*ar_hi:.1f}%]")
    print(f"  Grounded rate: {100*dgr:.1f}%  [{100*dgr_lo:.1f}–{100*dgr_hi:.1f}%]")
    print(f"  Latency median={ls['median']:.2f}s  p90={ls['p90']:.2f}s")

    # Table
    rows_out = []
    for o in OUTCOME_ORDER:
        c = oc[o]
        lo, hi = wilson_ci(c, n)
        rows_out.append({
            "Outcome":     o,
            "Count":       c,
            "Pct":         round(100 * c / n, 2),
            "CI_95_lo":    round(100 * lo, 2),
            "CI_95_hi":    round(100 * hi, 2),
        })
    rows_out.append({
        "Outcome": "TOTAL", "Count": n, "Pct": 100.0,
        "CI_95_lo": "", "CI_95_hi": "",
    })
    rows_out.append({
        "Outcome": "Answer rate (G+I)", "Count": oc["GROUNDED"]+oc["INFORMATIONAL"],
        "Pct": round(100*ar, 2), "CI_95_lo": round(100*ar_lo, 2), "CI_95_hi": round(100*ar_hi, 2),
    })
    rows_out.append({
        "Outcome": "Data-grounded rate", "Count": oc["GROUNDED"],
        "Pct": round(100*dgr, 2), "CI_95_lo": round(100*dgr_lo, 2), "CI_95_hi": round(100*dgr_hi, 2),
    })
    # Latency row
    rows_out.append({
        "Outcome": f"Latency (median/p90/s)", "Count": ls["n"],
        "Pct": round(ls["median"], 2), "CI_95_lo": round(ls["p90"], 2), "CI_95_hi": "",
    })
    write_csv("H1_overall_metrics", rows_out,
              ["Outcome", "Count", "Pct", "CI_95_lo", "CI_95_hi"])

    # Figure — stacked horizontal bar (proportion chart)
    fig, ax = plt.subplots(figsize=(DOUBLE_COL_W * 0.7, 1.4))
    cumulative = 0.0
    for o in OUTCOME_ORDER:
        pct = 100 * oc[o] / n
        ax.barh(0, pct, left=cumulative, color=PALETTE[o], height=0.5,
                label=f"{o.capitalize().replace('_',' ')} ({pct:.1f}%)")
        if pct > 3:
            ax.text(cumulative + pct / 2, 0, f"{pct:.1f}%",
                    ha="center", va="center", fontsize=7, color="white", fontweight="bold")
        cumulative += pct

    ax.set_xlim(0, 100)
    ax.set_xlabel("Percentage of responses (%)")
    ax.set_yticks([])
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.35),
              ncol=3, frameon=False, fontsize=7)
    ax.set_title("OntoSage response outcome distribution (N = {:,})".format(n))
    fig.tight_layout()
    savefig("H1_outcome_distribution", fig)


# ---------------------------------------------------------------------------
# H2 — Answer rate by domain
# ---------------------------------------------------------------------------

def h2_by_domain(rows: list):
    print("\n[H2] Answer rate by domain...")
    domains = sorted(set(r["domain"] for r in rows))
    table_rows = []
    domain_data = {}

    for dom in domains:
        sub = [r for r in rows if r["domain"] == dom]
        oc = outcome_counts(sub)
        ar, ar_lo, ar_hi = answer_rate(sub)
        dgr, _, _ = data_grounded_rate(sub)
        ls = latency_stats(sub)
        domain_data[dom] = (ar, ar_lo, ar_hi, oc, dgr, ls, len(sub))
        table_rows.append({
            "Domain":          dom,
            "Label":           DOMAIN_LABELS.get(dom, dom),
            "N":               len(sub),
            "GROUNDED_n":      oc["GROUNDED"],
            "INFORMATIONAL_n": oc["INFORMATIONAL"],
            "DISAMBIGUATION_n":oc["DISAMBIGUATION"],
            "BOUNDARY_n":      oc["BOUNDARY"],
            "FAILED_n":        oc["FAILED"],
            "Answer_rate_pct": round(100 * ar, 2),
            "AR_CI_lo":        round(100 * ar_lo, 2),
            "AR_CI_hi":        round(100 * ar_hi, 2),
            "Grounded_rate_pct":round(100 * dgr, 2),
            "Latency_median_s": round(ls.get("median", 0), 2),
            "Latency_p90_s":    round(ls.get("p90", 0), 2),
        })

    table_rows.sort(key=lambda x: -x["Answer_rate_pct"])
    write_csv("H2_answer_rate_by_domain", table_rows,
              ["Domain","Label","N","GROUNDED_n","INFORMATIONAL_n","DISAMBIGUATION_n",
               "BOUNDARY_n","FAILED_n","Answer_rate_pct","AR_CI_lo","AR_CI_hi",
               "Grounded_rate_pct","Latency_median_s","Latency_p90_s"])

    # Figure — horizontal grouped bar sorted by answer rate
    sorted_doms = [r["Domain"] for r in table_rows]
    labels = [DOMAIN_LABELS.get(d, d) for d in sorted_doms]
    ars    = [domain_data[d][0] for d in sorted_doms]
    dgrs   = [domain_data[d][4] for d in sorted_doms]
    errors = [[domain_data[d][0] - domain_data[d][1],
               domain_data[d][2] - domain_data[d][0]] for d in sorted_doms]
    errors = np.array(errors).T

    fig, ax = plt.subplots(figsize=(DOUBLE_COL_W, 3.8))
    y = np.arange(len(sorted_doms))
    h = 0.35
    ax.barh(y + h/2, [a*100 for a in ars], height=h, xerr=errors*100,
            color=PALETTE["GROUNDED"], label="Answer rate (G+I)", capsize=2)
    ax.barh(y - h/2, [d*100 for d in dgrs], height=h,
            color=PALETTE["INFORMATIONAL"], alpha=0.8, label="Data-grounded rate")
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Rate (%)")
    ax.set_xlim(0, 105)
    ax.axvline(80, linestyle="--", linewidth=0.6, color="#888888", label="80% reference")
    ax.legend(frameon=False, loc="lower right", fontsize=7)
    ax.set_title("Answer rate and data-grounded rate by domain")
    # Annotate bars
    for i, (d, ar) in enumerate(zip(sorted_doms, ars)):
        n_val = domain_data[d][6]
        ax.text(ar*100 + 1.2, i + h/2, f"n={n_val}", va="center", fontsize=6.5)
    fig.tight_layout()
    savefig("H2_answer_rate_by_domain", fig)


# ---------------------------------------------------------------------------
# H3 — Answer rate by query type
# ---------------------------------------------------------------------------

def h3_by_query_type(rows: list):
    print("\n[H3] Answer rate by query type...")
    qtypes = sorted(set(r["query_type"] for r in rows))
    table_rows = []

    for qt in qtypes:
        sub = [r for r in rows if r["query_type"] == qt]
        oc = outcome_counts(sub)
        ar, ar_lo, ar_hi = answer_rate(sub)
        dgr, _, _ = data_grounded_rate(sub)
        ls = latency_stats(sub)
        table_rows.append({
            "QueryType":        qt,
            "Label":            QUERY_LABELS.get(qt, qt),
            "N":                len(sub),
            "GROUNDED_n":       oc["GROUNDED"],
            "INFORMATIONAL_n":  oc["INFORMATIONAL"],
            "DISAMBIGUATION_n": oc["DISAMBIGUATION"],
            "BOUNDARY_n":       oc["BOUNDARY"],
            "FAILED_n":         oc["FAILED"],
            "Answer_rate_pct":  round(100 * ar, 2),
            "AR_CI_lo":         round(100 * ar_lo, 2),
            "AR_CI_hi":         round(100 * ar_hi, 2),
            "Grounded_rate_pct":round(100 * dgr, 2),
            "Latency_median_s": round(ls.get("median", 0), 2),
        })

    table_rows.sort(key=lambda x: -x["Answer_rate_pct"])
    write_csv("H3_answer_rate_by_query_type", table_rows,
              ["QueryType","Label","N","GROUNDED_n","INFORMATIONAL_n","DISAMBIGUATION_n",
               "BOUNDARY_n","FAILED_n","Answer_rate_pct","AR_CI_lo","AR_CI_hi",
               "Grounded_rate_pct","Latency_median_s"])

    # Stacked bar figure
    labels = [QUERY_LABELS.get(r["QueryType"], r["QueryType"]) for r in table_rows]
    ns     = [r["N"] for r in table_rows]
    fig, ax = plt.subplots(figsize=(DOUBLE_COL_W, 3.2))
    x = np.arange(len(table_rows))
    w = 0.55
    bottom = np.zeros(len(table_rows))
    for outcome in OUTCOME_ORDER:
        vals = [100 * table_rows[i][f"{outcome}_n"] / table_rows[i]["N"]
                for i in range(len(table_rows))]
        ax.bar(x, vals, width=w, bottom=bottom, color=PALETTE[outcome],
               label=outcome.capitalize().replace("_", " "))
        bottom += np.array(vals)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=28, ha="right")
    ax.set_ylabel("Percentage (%)")
    ax.set_ylim(0, 108)
    for i, n_val in enumerate(ns):
        ax.text(i, 101, f"n={n_val}", ha="center", va="bottom", fontsize=6)
    ax.legend(frameon=False, ncol=5, loc="upper center",
              bbox_to_anchor=(0.5, 1.14), fontsize=7)
    ax.set_title("Response outcomes by query type")
    fig.tight_layout()
    savefig("H3_outcome_by_query_type", fig)


# ---------------------------------------------------------------------------
# H4 — Answer rate by complexity
# ---------------------------------------------------------------------------

def h4_by_complexity(rows: list):
    print("\n[H4] Answer rate by complexity...")
    table_rows = []

    for cpx in COMPLEXITY_ORDER:
        sub = [r for r in rows if r["complexity"] == cpx]
        oc = outcome_counts(sub)
        ar, ar_lo, ar_hi = answer_rate(sub)
        dgr, _, _ = data_grounded_rate(sub)
        ls = latency_stats(sub)
        table_rows.append({
            "Complexity":       cpx,
            "Label":            COMPLEXITY_LABELS[cpx],
            "N":                len(sub),
            "GROUNDED_n":       oc["GROUNDED"],
            "INFORMATIONAL_n":  oc["INFORMATIONAL"],
            "DISAMBIGUATION_n": oc["DISAMBIGUATION"],
            "BOUNDARY_n":       oc["BOUNDARY"],
            "FAILED_n":         oc["FAILED"],
            "Answer_rate_pct":  round(100 * ar, 2),
            "AR_CI_lo":         round(100 * ar_lo, 2),
            "AR_CI_hi":         round(100 * ar_hi, 2),
            "Grounded_rate_pct":round(100 * dgr, 2),
            "Latency_mean_s":   round(ls.get("mean", 0), 2),
            "Latency_median_s": round(ls.get("median", 0), 2),
            "Latency_sd_s":     round(ls.get("sd", 0), 2),
            "Latency_p90_s":    round(ls.get("p90", 0), 2),
        })

    write_csv("H4_answer_rate_by_complexity", table_rows,
              ["Complexity","Label","N","GROUNDED_n","INFORMATIONAL_n","DISAMBIGUATION_n",
               "BOUNDARY_n","FAILED_n","Answer_rate_pct","AR_CI_lo","AR_CI_hi",
               "Grounded_rate_pct","Latency_mean_s","Latency_median_s","Latency_sd_s","Latency_p90_s"])

    # Chi-square test across complexity levels
    contingency = np.array([
        [r["GROUNDED_n"] + r["INFORMATIONAL_n"],
         r["DISAMBIGUATION_n"] + r["BOUNDARY_n"] + r["FAILED_n"]]
        for r in table_rows
    ])
    chi2, p_chi, dof, _ = chi2_contingency(contingency)
    v = cramers_v(contingency)
    print(f"  Complexity chi-square: chi2={chi2:.2f}, df={dof}, p={p_chi:.4f}, V={v:.3f}")

    # Dual-axis figure: stacked outcomes + latency line
    fig, ax1 = plt.subplots(figsize=(SINGLE_COL_W * 1.6, 3.0))
    ax2 = ax1.twinx()
    x = np.arange(len(COMPLEXITY_ORDER))
    w = 0.5
    bottom = np.zeros(3)
    for outcome in OUTCOME_ORDER:
        vals = [100 * table_rows[i][f"{outcome}_n"] / table_rows[i]["N"]
                for i in range(3)]
        ax1.bar(x, vals, width=w, bottom=bottom, color=PALETTE[outcome],
                label=outcome.replace("_", " ").title())
        bottom += np.array(vals)

    medians = [r["Latency_median_s"] for r in table_rows]
    ax2.plot(x, medians, "k--o", linewidth=1.2, markersize=4, label="Median latency (s)")
    ax2.set_ylabel("Median latency (s)", fontsize=8)
    ax2.set_ylim(0, max(medians) * 1.6)

    ax1.set_xticks(x)
    ax1.set_xticklabels([COMPLEXITY_LABELS[c] for c in COMPLEXITY_ORDER])
    ax1.set_ylabel("Percentage (%)")
    ax1.set_ylim(0, 110)
    ax1.set_title(f"Outcomes and latency by complexity (chi2={chi2:.1f}, V={v:.2f})")

    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2,
               frameon=False, ncol=3, loc="upper center",
               bbox_to_anchor=(0.5, -0.18), fontsize=7)
    fig.tight_layout()
    savefig("H4_outcome_by_complexity", fig)

    return chi2, p_chi, dof, v


# ---------------------------------------------------------------------------
# H5 — Answer rate by stage
# ---------------------------------------------------------------------------

def h5_by_stage(rows: list):
    print("\n[H5] Answer rate by stage...")
    stages = ["1", "2", "3", "4"]
    table_rows = []

    for s in stages:
        sub = [r for r in rows if r["stage"] == s]
        oc = outcome_counts(sub)
        ar, ar_lo, ar_hi = answer_rate(sub)
        dgr, _, _ = data_grounded_rate(sub)
        ls = latency_stats(sub)
        table_rows.append({
            "Stage":            s,
            "Label":            STAGE_LABELS[s],
            "N":                len(sub),
            "GROUNDED_n":       oc["GROUNDED"],
            "INFORMATIONAL_n":  oc["INFORMATIONAL"],
            "DISAMBIGUATION_n": oc["DISAMBIGUATION"],
            "BOUNDARY_n":       oc["BOUNDARY"],
            "FAILED_n":         oc["FAILED"],
            "Answer_rate_pct":  round(100 * ar, 2),
            "AR_CI_lo":         round(100 * ar_lo, 2),
            "AR_CI_hi":         round(100 * ar_hi, 2),
            "Grounded_rate_pct":round(100 * dgr, 2),
            "Latency_median_s": round(ls.get("median", 0), 2),
        })

    write_csv("H5_answer_rate_by_stage", table_rows,
              ["Stage","Label","N","GROUNDED_n","INFORMATIONAL_n","DISAMBIGUATION_n",
               "BOUNDARY_n","FAILED_n","Answer_rate_pct","AR_CI_lo","AR_CI_hi",
               "Grounded_rate_pct","Latency_median_s"])

    # Chi-square
    contingency = np.array([
        [r["GROUNDED_n"] + r["INFORMATIONAL_n"],
         r["DISAMBIGUATION_n"] + r["BOUNDARY_n"] + r["FAILED_n"]]
        for r in table_rows
    ])
    chi2, p_chi, dof, _ = chi2_contingency(contingency)
    v = cramers_v(contingency)
    print(f"  Stage chi-square: chi2={chi2:.2f}, df={dof}, p={p_chi:.4f}, V={v:.3f}")

    # Figure: answer rate line + grounded rate line across stages + CI ribbon
    fig, ax = plt.subplots(figsize=(SINGLE_COL_W * 1.6, 2.8))
    x = np.arange(4)
    ars  = [r["Answer_rate_pct"] for r in table_rows]
    dgrs = [r["Grounded_rate_pct"] for r in table_rows]
    ci_lo = [r["AR_CI_lo"] for r in table_rows]
    ci_hi = [r["AR_CI_hi"] for r in table_rows]

    ax.fill_between(x, ci_lo, ci_hi, alpha=0.15, color=PALETTE["GROUNDED"])
    ax.plot(x, ars,  "o-", color=PALETTE["GROUNDED"],
            linewidth=1.5, markersize=5, label="Answer rate (G+I)")
    ax.plot(x, dgrs, "s--", color=PALETTE["INFORMATIONAL"],
            linewidth=1.2, markersize=4, label="Data-grounded rate")

    ax.set_xticks(x)
    ax.set_xticklabels([STAGE_LABELS[s] for s in stages], rotation=15, ha="right")
    ax.set_ylabel("Rate (%)")
    ax.set_ylim(0, 105)
    ax.set_title(f"Answer rate across elicitation stages (V={v:.2f}, p={p_chi:.3f})")
    ax.legend(frameon=False, fontsize=7)
    for i, (a, n_v) in enumerate(zip(ars, [r["N"] for r in table_rows])):
        ax.annotate(f"{a:.0f}%", (i, a + 2), ha="center", fontsize=7)
    fig.tight_layout()
    savefig("H5_answer_rate_by_stage", fig)

    return chi2, p_chi, dof, v


# ---------------------------------------------------------------------------
# H6 — Latency analysis (by outcome + by complexity)
# ---------------------------------------------------------------------------

def h6_latency(rows: list):
    print("\n[H6] Latency analysis...")

    # Stats by outcome
    lat_by_outcome = {}
    for o in OUTCOME_ORDER:
        lats = [r["latency"] for r in rows if r["outcome"] == o and r["latency"] is not None]
        if lats:
            lat_by_outcome[o] = lats

    # Kruskal-Wallis across outcomes (excluding FAILED since all ~60s)
    kw_groups = [lat_by_outcome[o] for o in OUTCOME_ORDER[:-1] if o in lat_by_outcome]
    if len(kw_groups) >= 2:
        H_stat, p_kw = kruskal(*kw_groups)
        eta2 = kw_eta_squared(kw_groups)
        print(f"  Latency KW: H={H_stat:.2f}, p={p_kw:.4f}, eta2={eta2:.3f}")
    else:
        H_stat, p_kw, eta2 = 0, 1, 0

    table_rows = []
    for o in OUTCOME_ORDER:
        lats = lat_by_outcome.get(o, [])
        if not lats:
            continue
        s = latency_stats([{"latency": l} for l in lats])
        table_rows.append({
            "Outcome":   o,
            "N":         s["n"],
            "Mean_s":    round(s["mean"], 2),
            "Median_s":  round(s["median"], 2),
            "SD_s":      round(s["sd"], 2),
            "P25_s":     round(s["p25"], 2),
            "P75_s":     round(s["p75"], 2),
            "P90_s":     round(s["p90"], 2),
        })
    write_csv("H6_latency_by_outcome", table_rows,
              ["Outcome","N","Mean_s","Median_s","SD_s","P25_s","P75_s","P90_s"])

    # Figure: box plot per outcome (excluding FAILED to avoid 60s outlier domination)
    plot_outcomes = [o for o in OUTCOME_ORDER[:-1] if o in lat_by_outcome]
    fig, axes = plt.subplots(1, 2, figsize=(DOUBLE_COL_W, 3.0))

    # Left: boxplot by outcome
    ax = axes[0]
    data_plot = [lat_by_outcome[o] for o in plot_outcomes]
    bp = ax.boxplot(data_plot, patch_artist=True, notch=False,
                    medianprops={"color": "black", "linewidth": 1.5},
                    flierprops={"marker": ".", "markersize": 2, "alpha": 0.3})
    for patch, o in zip(bp["boxes"], plot_outcomes):
        patch.set_facecolor(PALETTE[o])
        patch.set_alpha(0.8)
    ax.set_xticks(range(1, len(plot_outcomes)+1))
    ax.set_xticklabels([o.title().replace("_"," ") for o in plot_outcomes],
                       rotation=20, ha="right")
    ax.set_ylabel("Latency (s)")
    ax.set_title(f"Latency by outcome\n(KW H={H_stat:.1f}, p={p_kw:.3f}, η²={eta2:.3f})")

    # Right: latency CDF
    ax2 = axes[1]
    for o in plot_outcomes:
        lats_sorted = sorted(lat_by_outcome[o])
        cdf = np.arange(1, len(lats_sorted)+1) / len(lats_sorted)
        ax2.plot(lats_sorted, cdf * 100, color=PALETTE[o], linewidth=1.2,
                 label=o.title().replace("_"," "))
    ax2.axvline(x=5, linestyle=":", linewidth=0.8, color="gray", label="5 s threshold")
    ax2.axvline(x=10, linestyle="--", linewidth=0.8, color="gray", label="10 s threshold")
    ax2.set_xlabel("Latency (s)")
    ax2.set_ylabel("Cumulative (%)")
    ax2.set_xlim(0, 35)
    ax2.legend(frameon=False, fontsize=6.5)
    ax2.set_title("Latency CDF by outcome")

    fig.tight_layout()
    savefig("H6_latency_analysis", fig)

    return H_stat, p_kw, eta2


# ---------------------------------------------------------------------------
# H7 — Domain × Complexity heatmap
# ---------------------------------------------------------------------------

def h7_domain_complexity_heatmap(rows: list):
    print("\n[H7] Domain × Complexity heatmap...")
    domains = list(DOMAIN_LABELS.keys())
    complexities = COMPLEXITY_ORDER

    # Build matrix: answer rate
    matrix_ar = np.zeros((len(domains), len(complexities)))
    matrix_n  = np.zeros((len(domains), len(complexities)), dtype=int)

    for i, dom in enumerate(domains):
        for j, cpx in enumerate(complexities):
            sub = [r for r in rows if r["domain"] == dom and r["complexity"] == cpx]
            matrix_n[i, j] = len(sub)
            if sub:
                ar, _, _ = answer_rate(sub)
                matrix_ar[i, j] = ar * 100

    # Save table
    heatmap_rows = []
    for i, dom in enumerate(domains):
        row = {"Domain": dom}
        for j, cpx in enumerate(complexities):
            row[cpx + "_AR_pct"] = round(float(matrix_ar[i, j]), 1)
            row[cpx + "_N"] = int(matrix_n[i, j])
        heatmap_rows.append(row)
    cols = ["Domain"] + [c + "_AR_pct" for c in complexities] + [c + "_N" for c in complexities]
    write_csv("H7_domain_complexity_heatmap", heatmap_rows, cols)

    # Figure
    fig, ax = plt.subplots(figsize=(SINGLE_COL_W * 1.8, 3.8))
    # Mask cells with n=0
    masked = np.ma.masked_where(matrix_n == 0, matrix_ar)
    im = ax.imshow(masked, cmap="RdYlGn", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(len(complexities)))
    ax.set_xticklabels([COMPLEXITY_LABELS[c] for c in complexities])
    ax.set_yticks(range(len(domains)))
    ax.set_yticklabels([DOMAIN_LABELS.get(d, d) for d in domains])
    # Annotate cells
    for i in range(len(domains)):
        for j in range(len(complexities)):
            if matrix_n[i, j] > 0:
                txt = f"{matrix_ar[i,j]:.0f}%\n(n={matrix_n[i,j]})"
                color = "white" if matrix_ar[i, j] < 35 or matrix_ar[i, j] > 80 else "black"
                ax.text(j, i, txt, ha="center", va="center", fontsize=6, color=color)
    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.04)
    cbar.set_label("Answer rate (%)", fontsize=8)
    ax.set_title("Answer rate: Domain × Complexity")
    fig.tight_layout()
    savefig("H7_domain_complexity_heatmap", fig)


# ---------------------------------------------------------------------------
# H8 — Domain × Stage heatmap
# ---------------------------------------------------------------------------

def h8_domain_stage_heatmap(rows: list):
    print("\n[H8] Domain × Stage heatmap...")
    domains = list(DOMAIN_LABELS.keys())
    stages  = ["1", "2", "3", "4"]

    matrix_ar = np.zeros((len(domains), 4))
    matrix_n  = np.zeros((len(domains), 4), dtype=int)

    for i, dom in enumerate(domains):
        for j, s in enumerate(stages):
            sub = [r for r in rows if r["domain"] == dom and r["stage"] == s]
            matrix_n[i, j] = len(sub)
            if sub:
                ar, _, _ = answer_rate(sub)
                matrix_ar[i, j] = ar * 100

    heatmap_rows = []
    for i, dom in enumerate(domains):
        row = {"Domain": dom}
        for j, s in enumerate(stages):
            row[f"S{s}_AR_pct"] = round(float(matrix_ar[i, j]), 1)
            row[f"S{s}_N"] = int(matrix_n[i, j])
        heatmap_rows.append(row)
    cols = ["Domain"] + [f"S{s}_AR_pct" for s in stages] + [f"S{s}_N" for s in stages]
    write_csv("H8_domain_stage_heatmap", heatmap_rows, cols)

    fig, ax = plt.subplots(figsize=(SINGLE_COL_W * 1.8, 3.8))
    masked = np.ma.masked_where(matrix_n == 0, matrix_ar)
    im = ax.imshow(masked, cmap="RdYlGn", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(4))
    ax.set_xticklabels([STAGE_LABELS[s] for s in stages], rotation=12, ha="right")
    ax.set_yticks(range(len(domains)))
    ax.set_yticklabels([DOMAIN_LABELS.get(d, d) for d in domains])
    for i in range(len(domains)):
        for j in range(4):
            if matrix_n[i, j] > 0:
                txt = f"{matrix_ar[i,j]:.0f}%\n(n={matrix_n[i,j]})"
                color = "white" if matrix_ar[i, j] < 35 or matrix_ar[i, j] > 80 else "black"
                ax.text(j, i, txt, ha="center", va="center", fontsize=6, color=color)
    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.04)
    cbar.set_label("Answer rate (%)", fontsize=8)
    ax.set_title("Answer rate: Domain × Elicitation Stage")
    fig.tight_layout()
    savefig("H8_domain_stage_heatmap", fig)


# ---------------------------------------------------------------------------
# H9 — Answer rate by persona
# ---------------------------------------------------------------------------

def h9_by_persona(rows: list):
    print("\n[H9] Answer rate by persona...")
    personas = sorted(set(r["persona"] for r in rows))
    table_rows = []

    for persona in personas:
        sub = [r for r in rows if r["persona"] == persona]
        oc = outcome_counts(sub)
        ar, ar_lo, ar_hi = answer_rate(sub)
        dgr, _, _ = data_grounded_rate(sub)
        ls = latency_stats(sub)
        table_rows.append({
            "Persona":             persona,
            "N":                len(sub),
            "GROUNDED_n":       oc["GROUNDED"],
            "INFORMATIONAL_n":  oc["INFORMATIONAL"],
            "DISAMBIGUATION_n": oc["DISAMBIGUATION"],
            "BOUNDARY_n":       oc["BOUNDARY"],
            "FAILED_n":         oc["FAILED"],
            "Answer_rate_pct":  round(100 * ar, 2),
            "AR_CI_lo":         round(100 * ar_lo, 2),
            "AR_CI_hi":         round(100 * ar_hi, 2),
            "Grounded_rate_pct":round(100 * dgr, 2),
            "Latency_median_s": round(ls.get("median", 0), 2),
        })

    table_rows.sort(key=lambda x: -x["Answer_rate_pct"])
    write_csv("H9_answer_rate_by_persona", table_rows,
              ["Persona","N","GROUNDED_n","INFORMATIONAL_n","DISAMBIGUATION_n",
               "BOUNDARY_n","FAILED_n","Answer_rate_pct","AR_CI_lo","AR_CI_hi",
               "Grounded_rate_pct","Latency_median_s"])

    # Figure: horizontal bar with CI whiskers
    fig, ax = plt.subplots(figsize=(DOUBLE_COL_W * 0.8, 3.5))
    labels = [r["Persona"] for r in table_rows]
    ars    = [r["Answer_rate_pct"] for r in table_rows]
    xerr_lo = [r["Answer_rate_pct"] - r["AR_CI_lo"] for r in table_rows]
    xerr_hi = [r["AR_CI_hi"] - r["Answer_rate_pct"] for r in table_rows]
    y = np.arange(len(table_rows))

    ax.barh(y, ars, xerr=[xerr_lo, xerr_hi], color="#0072B2", alpha=0.8,
            capsize=3, height=0.5)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Answer rate (%)")
    ax.set_xlim(0, 110)
    ax.axvline(80, linestyle="--", linewidth=0.6, color="#888888")
    for i, (ar_val, n_val) in enumerate(zip(ars, [r["N"] for r in table_rows])):
        ax.text(ar_val + xerr_hi[i] + 1.5, i, f"n={n_val}", va="center", fontsize=6.5)
    ax.set_title("Answer rate by stakeholder persona (95% CI)")
    fig.tight_layout()
    savefig("H9_answer_rate_by_persona", fig)


# ---------------------------------------------------------------------------
# H10 — Statistical tests summary
# ---------------------------------------------------------------------------

def h10_statistical_tests(rows: list, h4_results, h5_results, h6_results):
    print("\n[H10] Statistical tests summary...")
    h4_chi2, h4_p, h4_dof, h4_v = h4_results
    h5_chi2, h5_p, h5_dof, h5_v = h5_results
    h6_H, h6_p, h6_eta2 = h6_results

    # Additional: intent × answer rate
    intents = sorted(set(r["intent"] for r in rows))
    intent_groups = [[r for r in rows if r["intent"] == i] for i in intents]
    intent_cont = np.array([
        [sum(1 for r in g if r["outcome"] in ("GROUNDED","INFORMATIONAL")),
         sum(1 for r in g if r["outcome"] not in ("GROUNDED","INFORMATIONAL"))]
        for g in intent_groups
    ])
    chi2_intent, p_intent, dof_intent, _ = chi2_contingency(intent_cont)
    v_intent = cramers_v(intent_cont)

    # Stage × complexity interaction
    stage_complexity_groups = defaultdict(list)
    for r in rows:
        stage_complexity_groups[(r["stage"], r["complexity"])].append(r)
    # Build 4x3 contingency
    sc_cont = np.zeros((4, 3), dtype=int)
    for si, s in enumerate(["1","2","3","4"]):
        for ci, c in enumerate(COMPLEXITY_ORDER):
            g = stage_complexity_groups[(s, c)]
            sc_cont[si, ci] = sum(1 for r in g if r["outcome"] in ("GROUNDED","INFORMATIONAL"))
    # chi2 on answered vs total
    sc_total = np.zeros((4, 3), dtype=int)
    for si, s in enumerate(["1","2","3","4"]):
        for ci, c in enumerate(COMPLEXITY_ORDER):
            sc_total[si, ci] = len(stage_complexity_groups[(s, c)])
    sc_not = sc_total - sc_cont
    sc_2col = np.column_stack([sc_cont.flatten(), sc_not.flatten()]).reshape(12, 2)
    # Use Kruskal-Wallis on latency by stage
    stage_lats = [
        [r["latency"] for r in rows if r["stage"] == s and r["latency"] is not None]
        for s in ["1","2","3","4"]
    ]
    H_stage, p_stage_kw = kruskal(*[g for g in stage_lats if g])
    eta2_stage = kw_eta_squared([g for g in stage_lats if g])

    test_rows = [
        {
            "Test":        "Outcome distribution vs. Complexity",
            "Method":      "Chi-square",
            "Statistic":   f"chi2({h4_dof})={h4_chi2:.2f}",
            "p_value":     round(h4_p, 4),
            "Effect_size": f"V={h4_v:.3f}",
            "Interpretation": "small" if h4_v < 0.1 else ("medium" if h4_v < 0.3 else "large"),
            "Significant": "Yes" if h4_p < 0.05 else "No",
        },
        {
            "Test":        "Outcome distribution vs. Stage",
            "Method":      "Chi-square",
            "Statistic":   f"chi2({h5_dof})={h5_chi2:.2f}",
            "p_value":     round(h5_p, 4),
            "Effect_size": f"V={h5_v:.3f}",
            "Interpretation": "small" if h5_v < 0.1 else ("medium" if h5_v < 0.3 else "large"),
            "Significant": "Yes" if h5_p < 0.05 else "No",
        },
        {
            "Test":        "Latency vs. Outcome category",
            "Method":      "Kruskal-Wallis H",
            "Statistic":   f"H={h6_H:.2f}",
            "p_value":     round(h6_p, 4),
            "Effect_size": f"eta2={h6_eta2:.3f}",
            "Interpretation": "small" if h6_eta2 < 0.06 else ("medium" if h6_eta2 < 0.14 else "large"),
            "Significant": "Yes" if h6_p < 0.05 else "No",
        },
        {
            "Test":        "Outcome distribution vs. Intent type",
            "Method":      "Chi-square",
            "Statistic":   f"chi2({dof_intent})={chi2_intent:.2f}",
            "p_value":     round(p_intent, 4),
            "Effect_size": f"V={v_intent:.3f}",
            "Interpretation": "small" if v_intent < 0.1 else ("medium" if v_intent < 0.3 else "large"),
            "Significant": "Yes" if p_intent < 0.05 else "No",
        },
        {
            "Test":        "Latency vs. Elicitation stage",
            "Method":      "Kruskal-Wallis H",
            "Statistic":   f"H={H_stage:.2f}",
            "p_value":     round(p_stage_kw, 4),
            "Effect_size": f"eta2={eta2_stage:.3f}",
            "Interpretation": "small" if eta2_stage < 0.06 else ("medium" if eta2_stage < 0.14 else "large"),
            "Significant": "Yes" if p_stage_kw < 0.05 else "No",
        },
    ]
    write_csv("H10_statistical_tests", test_rows,
              ["Test","Method","Statistic","p_value","Effect_size","Interpretation","Significant"])


# ---------------------------------------------------------------------------
# H11 — Intent analysis
# ---------------------------------------------------------------------------

def h11_by_intent(rows: list):
    print("\n[H11] Answer rate by intent...")
    table_rows = []
    for intent in sorted(INTENT_LABELS.keys()):
        sub = [r for r in rows if r["intent"] == intent]
        if not sub:
            continue
        oc = outcome_counts(sub)
        ar, ar_lo, ar_hi = answer_rate(sub)
        dgr, _, _ = data_grounded_rate(sub)
        ls = latency_stats(sub)
        table_rows.append({
            "Intent":           intent,
            "Label":            INTENT_LABELS[intent],
            "N":                len(sub),
            "GROUNDED_n":       oc["GROUNDED"],
            "INFORMATIONAL_n":  oc["INFORMATIONAL"],
            "DISAMBIGUATION_n": oc["DISAMBIGUATION"],
            "BOUNDARY_n":       oc["BOUNDARY"],
            "FAILED_n":         oc["FAILED"],
            "Answer_rate_pct":  round(100 * ar, 2),
            "AR_CI_lo":         round(100 * ar_lo, 2),
            "AR_CI_hi":         round(100 * ar_hi, 2),
            "Grounded_rate_pct":round(100 * dgr, 2),
            "Latency_median_s": round(ls.get("median", 0), 2),
        })

    write_csv("H11_answer_rate_by_intent", table_rows,
              ["Intent","Label","N","GROUNDED_n","INFORMATIONAL_n","DISAMBIGUATION_n",
               "BOUNDARY_n","FAILED_n","Answer_rate_pct","AR_CI_lo","AR_CI_hi",
               "Grounded_rate_pct","Latency_median_s"])


# ---------------------------------------------------------------------------
# H12 — Coverage bubble chart (domain volume × answer rate × grounded rate)
# ---------------------------------------------------------------------------

def h12_coverage_bubble(rows: list):
    print("\n[H12] Coverage bubble chart...")
    domains = list(DOMAIN_LABELS.keys())
    fig, ax = plt.subplots(figsize=(SINGLE_COL_W * 1.9, 3.5))

    for i, dom in enumerate(domains):
        sub = [r for r in rows if r["domain"] == dom]
        n = len(sub)
        ar, _, _ = answer_rate(sub)
        dgr, _, _ = data_grounded_rate(sub)
        size = max(40, n / 8)
        ax.scatter(ar * 100, dgr * 100, s=size, color="#0072B2", alpha=0.65,
                   edgecolors="white", linewidth=0.5)
        ax.annotate(DOMAIN_LABELS.get(dom, dom),
                    (ar * 100, dgr * 100),
                    xytext=(4, 2), textcoords="offset points",
                    fontsize=6.5, ha="left")

    ax.set_xlabel("Answer rate — Grounded + Informational (%)")
    ax.set_ylabel("Data-grounded rate (%)")
    ax.set_xlim(0, 110)
    ax.set_ylim(0, 110)
    ax.plot([0, 110], [0, 110], "--", color="#bbbbbb", linewidth=0.8,
            label="Grounded = Answer rate")
    ax.axhline(50, linestyle=":", linewidth=0.6, color="#cccccc")
    ax.axvline(75, linestyle=":", linewidth=0.6, color="#cccccc")
    ax.set_title("Domain coverage: answer rate vs. data-grounded rate\n(bubble size \u221d question volume)")
    ax.legend(frameon=False, fontsize=6.5)
    fig.tight_layout()
    savefig("H12_coverage_bubble", fig)


# ---------------------------------------------------------------------------
# H13 — Narrative summary markdown
# ---------------------------------------------------------------------------

def h13_summary(rows: list):
    n = len(rows)
    oc = outcome_counts(rows)
    ar, ar_lo, ar_hi = answer_rate(rows)
    dgr, dgr_lo, dgr_hi = data_grounded_rate(rows)
    ls = latency_stats(rows)
    failed_pct = 100 * oc["FAILED"] / n

    lines = [
        "# H-Phase: OntoSage Evaluation Summary",
        "",
        f"**N** = {n:,} questions drawn from the pre-development survey corpus (81 participants, "
        f"Phases A–G classified)",
        "",
        "## Headline Metrics",
        "",
        f"| Metric | Value | 95% CI |",
        f"|--------|-------|--------|",
        f"| Answer rate (Grounded + Informational) | {100*ar:.1f}% | [{100*ar_lo:.1f}–{100*ar_hi:.1f}%] |",
        f"| Data-grounded rate | {100*dgr:.1f}% | [{100*dgr_lo:.1f}–{100*dgr_hi:.1f}%] |",
        f"| Disambiguation rate | {100*oc['DISAMBIGUATION']/n:.1f}% | — |",
        f"| Graceful refusal rate | {100*oc['BOUNDARY']/n:.1f}% | — |",
        f"| Timeout/failure rate | {failed_pct:.1f}% | — |",
        f"| Median latency | {ls['median']:.2f} s | — |",
        f"| P90 latency | {ls['p90']:.2f} s | — |",
        "",
        "## Outcome Definitions",
        "",
        "- **GROUNDED** — response includes specific building data (sensor readings, tables, measured values)",
        "- **INFORMATIONAL** — general domain knowledge without specific building data",
        "- **DISAMBIGUATION** — system requested clarification with numbered options",
        "- **BOUNDARY** — graceful refusal: data not available or out of scope",
        "- **FAILED** — timeout (60 s limit) or empty response",
        "",
        "## Output Files",
        "",
        "| File | Description |",
        "|------|-------------|",
        "| H1_overall_metrics.csv | Overall outcome counts and rates |",
        "| H2_answer_rate_by_domain.csv | Domain-level answer rates with CI |",
        "| H3_answer_rate_by_query_type.csv | Query-type answer rates |",
        "| H4_answer_rate_by_complexity.csv | L1/L2/L3 complexity analysis |",
        "| H5_answer_rate_by_stage.csv | Stage S1–S4 answer rates |",
        "| H6_latency_by_outcome.csv | Latency statistics by outcome |",
        "| H7_domain_complexity_heatmap.csv | Domain × Complexity matrix |",
        "| H8_domain_stage_heatmap.csv | Domain × Stage matrix |",
        "| H9_answer_rate_by_persona.csv | Persona-based answer rates |",
        "| H10_statistical_tests.csv | All statistical tests with effect sizes |",
        "| H11_answer_rate_by_intent.csv | Intent-type answer rates |",
        "",
        "| Figure | Description |",
        "|--------|-------------|",
        "| H1_outcome_distribution | Stacked proportion bar |",
        "| H2_answer_rate_by_domain | Grouped horizontal bar |",
        "| H3_outcome_by_query_type | Stacked bar by query type |",
        "| H4_outcome_by_complexity | Stacked bar + latency overlay |",
        "| H5_answer_rate_by_stage | Line plot with CI ribbon |",
        "| H6_latency_analysis | Box plot + CDF |",
        "| H7_domain_complexity_heatmap | Heatmap with annotations |",
        "| H8_domain_stage_heatmap | Heatmap with annotations |",
        "| H9_answer_rate_by_persona | Horizontal bar with CI |",
        "| H12_coverage_bubble | Coverage scatter |",
    ]
    path = OUT_TABLES / "H_evaluation_summary.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  [md]  H_evaluation_summary.md")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Phase H: OntoSage Evaluation Analysis")
    print("=" * 60)

    rows = load_data()

    h1_overall_metrics(rows)
    h2_by_domain(rows)
    h3_by_query_type(rows)
    h4_results = h4_by_complexity(rows)
    h5_results = h5_by_stage(rows)
    h6_results = h6_latency(rows)
    h7_domain_complexity_heatmap(rows)
    h8_domain_stage_heatmap(rows)
    h9_by_persona(rows)
    h10_statistical_tests(rows, h4_results, h5_results, h6_results)
    h11_by_intent(rows)
    h12_coverage_bubble(rows)
    h13_summary(rows)

    print("\n" + "=" * 60)
    print("Phase H complete.")
    print(f"  Tables: {OUT_TABLES}")
    print(f"  Figures: {OUT_FIGS}")
    print("=" * 60)


if __name__ == "__main__":
    main()
