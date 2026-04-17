"""Phase G — Framework Synthesis (RQ6).

Cross-references corpus taxonomy (B), topic priorities (E), and question
preferences (F) to produce:

  outputs/tables/G1_classification_framework.md
  outputs/tables/G2_capability_matrix.csv
  outputs/figures/G3_framework_architecture.{png,pdf}
  outputs/tables/G4_gap_analysis.md
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
CORPUS = ROOT / "corpus"


# ---------------------------------------------------------------------------
# G1 — Classification framework write-up
# ---------------------------------------------------------------------------


CLASSIFICATION_FRAMEWORK = """# Phase G1 — OntoSage++ Query Classification Framework

## Inputs and outputs

- **Input:** raw natural-language question text (English, 1-50 words)
- **Output:** a six-tuple
  - `domain_l1` ∈ {{20 codes; see `taxonomy_v1.md`}}
  - `query_type_l2` ∈ {{STATUS, HISTORICAL, COMPARISON, DIAGNOSTIC, ANOMALY, RECOMMENDATION, CAPABILITY}}
  - `intent` ∈ {{INFO_REQUEST, ANALYSIS, ACTION, WAYFINDING}}
  - `temporal` ∈ {{INSTANT, RECENT, HISTORICAL_RANGE, NONE}}
  - `spatial` ∈ {{POINT, ZONE, FLOOR, BUILDING, CAMPUS, NONE}}
  - `complexity` ∈ {{LOOKUP, AGGREGATION, MULTI_STEP}}

## Pipeline

1. **Lexical pre-pass.** Lower-case, normalise unicode, expand common
   smart-building abbreviations (CO2, IAQ, HVAC, AHU, VAV).
2. **Domain & query-type classifier.** A deterministic regex + lexicon
   stack (Phase B2) provides a strong baseline. The lexicon is the
   evidence base for the LLM-driven classifier; replacement with an
   Anthropic Batch API run is a drop-in upgrade.
3. **Intent classifier.** Cue-word lookup (recommendation verbs,
   diagnostic verbs, comparators) decides the four-way intent label.
4. **Temporal & spatial taggers.** Simple regex over time expressions
   ("last week", "yesterday", "today") and space references ("zone",
   "floor", "room", "building").
5. **Complexity router.** Counts the number of independent clauses and
   the presence of aggregation operators (avg, total, max, min, trend)
   to assign LOOKUP / AGGREGATION / MULTI_STEP.

## Validation

- Phase B2 deterministic baseline classifies the full N=5,127 corpus.
  Coverage of on-topic domains (excluding OTHER) is **{on_topic_pct:.1f}%**
  ({on_topic_n} of {n_total} questions).
- Phase B3 inter-rater reliability gate is the substantive Kappa floor
  (target ≥ 0.70 per dimension). The IRR sample (`taxonomy/irr_samples.csv`)
  is ready; two independent coders annotate it before publication.
"""


def write_classification_framework() -> None:
    df = pd.read_csv(CORPUS / "classified_corpus.csv")
    n_total = len(df)
    on_topic_n = int((df["domain_l1"] != "OTHER").sum())
    on_topic_pct = 100 * on_topic_n / n_total
    text = CLASSIFICATION_FRAMEWORK.format(
        n_total=n_total,
        on_topic_n=on_topic_n,
        on_topic_pct=on_topic_pct,
    )
    (OUT / "tables" / "G1_classification_framework.md").write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# G2 — Capability matrix
# ---------------------------------------------------------------------------


def build_capability_matrix() -> pd.DataFrame:
    corpus = pd.read_csv(CORPUS / "classified_corpus.csv")
    priorities = pd.read_csv(OUT / "tables" / "E1_topic_priority_table.csv")
    level_pref = pd.read_csv(OUT / "tables" / "F1_overall_level_preference.csv")

    type_volumes = corpus["query_type_l2"].value_counts().to_dict()
    type_complexity_share = (
        corpus.groupby("query_type_l2")["complexity"].value_counts(normalize=True).unstack(fill_value=0)
    )

    median_priority = priorities["mean_rank"].median()
    top_topics = priorities.head(5)["TopicLabel"].tolist()
    bot_topics = priorities.tail(5)["TopicLabel"].tolist()

    rows = []
    for qtype, volume in type_volumes.items():
        cmplx = type_complexity_share.loc[qtype] if qtype in type_complexity_share.index else None
        if cmplx is not None:
            agg_share = float(cmplx.get("AGGREGATION", 0.0) + cmplx.get("MULTI_STEP", 0.0))
        else:
            agg_share = 0.0
        # Priority tier follows volume + analytical share
        if volume >= 1000 or agg_share > 0.4:
            tier = "P1 — must support at launch"
        elif volume >= 200:
            tier = "P2 — required within 6 months"
        else:
            tier = "P3 — desirable, longer term"
        rows.append(
            {
                "query_type": qtype,
                "corpus_volume": int(volume),
                "share_pct": round(100 * volume / len(corpus), 2),
                "analytical_share_pct": round(100 * agg_share, 2),
                "priority_tier": tier,
            }
        )
    matrix = pd.DataFrame(rows).sort_values("corpus_volume", ascending=False)
    matrix.attrs["top_topics"] = top_topics
    matrix.attrs["bot_topics"] = bot_topics
    matrix.attrs["median_priority"] = median_priority
    matrix.attrs["preferred_level_mean_rank"] = float(
        level_pref.sort_values("mean_rank").iloc[0]["mean_rank"]
    )
    return matrix


# ---------------------------------------------------------------------------
# G3 — Architecture diagram (matplotlib block diagram)
# ---------------------------------------------------------------------------


def plot_architecture() -> None:
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6)
    ax.axis("off")

    boxes = [
        ("NL parser", 0.5, 2.4, 1.7, 1.2, "#cfe2f3"),
        ("Intent\nclassifier", 2.6, 2.4, 1.7, 1.2, "#cfe2f3"),
        ("Domain\nrouter", 4.7, 2.4, 1.7, 1.2, "#cfe2f3"),
        ("Data source\nselector", 6.8, 2.4, 1.9, 1.2, "#cfe2f3"),
        ("Response\ngenerator", 9.0, 2.4, 1.9, 1.2, "#cfe2f3"),
    ]
    for label, x, y, w, h, color in boxes:
        ax.add_patch(mpatches.FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.05", linewidth=1.2,
            edgecolor="#444", facecolor=color))
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
                fontsize=10, weight="bold")

    # Arrows
    for x1, x2 in [(2.2, 2.6), (4.3, 4.7), (6.4, 6.8), (8.7, 9.0)]:
        ax.annotate("", xy=(x2, 3.0), xytext=(x1, 3.0),
                    arrowprops=dict(arrowstyle="->", lw=1.5, color="#444"))

    # Evidence callouts
    callouts = [
        (1.35, 1.0, "Lexical normaliser\n(B2)"),
        (3.45, 1.0, "Phase B2 lexicon\n+ Phase B3 IRR"),
        (5.55, 1.0, "20 L1 domains\nfrom Phase B"),
        (7.75, 1.0, "GraphDB / SQL\n/ analytics"),
        (9.95, 1.0, "Markdown +\nplots + tables"),
    ]
    for x, y, txt in callouts:
        ax.text(x, y, txt, ha="center", va="top", fontsize=8, color="#333")

    # Top: data sources strip
    sources = [
        (0.5, 5.0, "RDF / Brick KG", "#fff2cc"),
        (3.0, 5.0, "Time-series DB", "#fff2cc"),
        (5.5, 5.0, "Standards JSON", "#fff2cc"),
        (8.0, 5.0, "Persona registry", "#fff2cc"),
        (10.5, 5.0, "Workflow memory", "#fff2cc"),
    ]
    for x, y, label, color in sources:
        ax.add_patch(mpatches.FancyBboxPatch(
            (x - 0.8, y - 0.35), 1.6, 0.7, boxstyle="round,pad=0.05",
            linewidth=1.0, edgecolor="#666", facecolor=color))
        ax.text(x, y, label, ha="center", va="center", fontsize=9)

    ax.text(6.0, 5.85, "Knowledge & state sources", ha="center",
            va="center", fontsize=9, style="italic")
    ax.text(6.0, 0.25, "OntoSage++ query pipeline (instantiates the framework)",
            ha="center", va="center", fontsize=10, weight="bold")

    plt.tight_layout()
    plt.savefig(OUT / "figures" / "G3_framework_architecture.png", dpi=300)
    plt.savefig(OUT / "figures" / "G3_framework_architecture.pdf")
    plt.close()


# ---------------------------------------------------------------------------
# G4 — Gap analysis
# ---------------------------------------------------------------------------


def write_gap_analysis(matrix: pd.DataFrame) -> None:
    corpus = pd.read_csv(CORPUS / "classified_corpus.csv")
    other_n = int((corpus["domain_l1"] == "OTHER").sum())
    other_pct = 100 * other_n / len(corpus)
    multi_n = int((corpus["complexity"] == "MULTI_STEP").sum())
    multi_pct = 100 * multi_n / len(corpus)
    diag_n = int((corpus["query_type_l2"] == "DIAGNOSTIC").sum())
    rec_n = int((corpus["query_type_l2"] == "RECOMMENDATION").sum())
    anom_n = int((corpus["query_type_l2"] == "ANOMALY").sum())

    text = f"""# Phase G4 — Gap Analysis

The capability matrix (G2) lists what the corpus demands of a smart-building NL
interface. This file enumerates the *gaps* — query types that current commercial
or research systems cannot serve fully — split into three categories.

## 1. Data-availability gaps

| Gap | Evidence | Implication |
|-----|----------|-------------|
| Off-ontology requests | {other_n} questions ({other_pct:.1f}%) classified as OTHER (Phase B2). | Brick / 223 schemas do not yet model amenity, wayfinding, or hospitality concepts that occupants and guests routinely ask about. |
| Cross-system fusion | RECOMMENDATION ({rec_n}) and ANOMALY ({anom_n}) queries assume joined sensor + standards + occupancy data. | Storage adapter routing must federate at least three back-ends transparently. |

## 2. Reasoning gaps

| Gap | Evidence | Implication |
|-----|----------|-------------|
| Multi-step reasoning | {multi_n} MULTI_STEP questions ({multi_pct:.1f}%) require chained retrieval, computation, and synthesis. | Single-shot SPARQL or single-shot SQL is insufficient; an orchestrator with intermediate state is required (OntoSage++ uses LangGraph). |
| Diagnostic causation | {diag_n} DIAGNOSTIC queries ask "why" rather than "what". | Need a causal model layer (rule-based or ML) on top of telemetry. |

## 3. Integration gaps

| Gap | Evidence | Implication |
|-----|----------|-------------|
| Persona-aware response | Phase D shows distinct domain mixes per role; Phase F shows distinct level preferences per role. | The response generator must consult a persona registry, not just template strings. |
| Standards-aware answers | RECOMMENDATION queries reference comfort, energy, and air-quality thresholds. | The system must surface ASHRAE / WELL / BREEAM thresholds inline, not buried in references. |
| Live state vs. historical | Mix of INSTANT, RECENT, HISTORICAL_RANGE temporal labels. | Caching and freshness policies must vary by intent (status = sub-second; historical = minutes is fine). |

## Future work hooks

1. Replace the deterministic Phase B2 classifier with an LLM-backed labeller and
   re-validate Kappa on the same IRR sample to compare gains.
2. Expand the Brick / 223 alignment layer to absorb the OTHER bucket (mostly
   amenity, wayfinding, and policy queries from guests and occupants).
3. Add a closed-loop feedback log so production responses feed Phase B-style
   corpus statistics, allowing the priority tiers in G2 to drift with usage.
"""
    (OUT / "tables" / "G4_gap_analysis.md").write_text(text, encoding="utf-8")


def append_summary(matrix: pd.DataFrame) -> None:
    path = ROOT / "corpus" / "corpus_summary_stats.md"
    p1 = matrix[matrix["priority_tier"].str.startswith("P1")]
    p1_types = ", ".join(p1["query_type"].tolist())
    line = f"- Phase G: P1 query types = {p1_types}.\n"
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if "Phase G:" in existing:
            new = []
            for ln in existing.splitlines(keepends=True):
                new.append(line if ln.lstrip().startswith("- Phase G:") else ln)
            path.write_text("".join(new), encoding="utf-8")
        else:
            path.write_text(existing.rstrip() + "\n" + line, encoding="utf-8")
    else:
        path.write_text(line, encoding="utf-8")


def main() -> None:
    write_classification_framework()
    matrix = build_capability_matrix()
    matrix.to_csv(OUT / "tables" / "G2_capability_matrix.csv", index=False)
    plot_architecture()
    write_gap_analysis(matrix)
    append_summary(matrix)

    print("Phase G done.")
    print(matrix.to_string(index=False))


if __name__ == "__main__":
    main()
