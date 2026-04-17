"""Phase E — Topic Prioritisation Analysis (RQ4).

Outputs:
  outputs/tables/E1_topic_priority_table.csv
  outputs/tables/E1_kendalls_w.md
  outputs/figures/E1_borda_scores.{png,pdf}
  outputs/figures/E2_topic_dendrogram.{png,pdf}
  outputs/tables/E2_topic_clusters.md
  outputs/figures/E3_priority_vs_volume_scatter.{png,pdf}

Methods:
  E1 — Per-topic mean / median / mode rank, Borda count (rank-1 = 20 pts ... rank-20 = 1 pt),
       Kendall's W across all 50 users, bootstrap 95% CI on mean rank
  E2 — Spearman correlation of (topic, topic) over users -> distance = 1 - rho ->
       hierarchical clustering with average linkage, dendrogram
  E3 — Top-5 vs bottom-5 topics; scatter mean rank against question volume per topic
       proxied via classified_corpus.csv keyword match
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import dendrogram, linkage
from scipy.spatial.distance import squareform
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
INPUTS = ROOT / "inputs"
CORPUS = ROOT / "corpus"

RNG = np.random.default_rng(42)


def long_form(topic_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in topic_df.iterrows():
        for k in range(1, 21):
            tid = r.get(f"Rank_{k}_ID")
            tlabel = r.get(f"Rank_{k}_Label")
            if pd.isna(tid):
                continue
            rows.append(
                {
                    "Username": r["Username"],
                    "TopicID": int(tid),
                    "TopicLabel": str(tlabel),
                    "Rank": k,
                }
            )
    return pd.DataFrame(rows)


def kendalls_w(matrix: np.ndarray) -> float:
    n, k = matrix.shape
    if n <= 1 or k <= 1:
        return float("nan")
    rank_sums = matrix.sum(axis=0)
    s = float(((rank_sums - rank_sums.mean()) ** 2).sum())
    denom = (n * n) * (k * (k * k - 1)) / 12.0
    return s / denom if denom else float("nan")


def topic_priority_table(long_df: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    topic_labels = (
        long_df.drop_duplicates("TopicID").set_index("TopicID")["TopicLabel"].to_dict()
    )
    topics = sorted(topic_labels.keys())

    user_topic = long_df.pivot(index="Username", columns="TopicID", values="Rank")
    user_topic = user_topic[topics]

    rows = []
    for tid in topics:
        ranks = user_topic[tid].dropna()
        borda = float((21 - ranks).sum())
        # Bootstrap 95% CI on mean rank
        boot = []
        arr = ranks.to_numpy()
        if len(arr):
            for _ in range(1000):
                idx = RNG.integers(0, len(arr), size=len(arr))
                boot.append(arr[idx].mean())
        lo, hi = (np.percentile(boot, [2.5, 97.5]) if boot else (np.nan, np.nan))
        rows.append(
            {
                "TopicID": tid,
                "TopicLabel": topic_labels[tid],
                "n_rankers": int(ranks.notna().sum()),
                "mean_rank": round(float(ranks.mean()), 3),
                "median_rank": float(ranks.median()),
                "mode_rank": int(ranks.mode().iloc[0]) if len(ranks.mode()) else np.nan,
                "borda_score": borda,
                "ci95_low": round(float(lo), 3),
                "ci95_high": round(float(hi), 3),
            }
        )
    table = pd.DataFrame(rows).sort_values("borda_score", ascending=False)

    full = user_topic.dropna(axis=0, how="any")
    w = kendalls_w(full.to_numpy()) if len(full) >= 2 else float("nan")
    return table, w


def plot_borda(table: pd.DataFrame) -> None:
    sub = table.sort_values("borda_score", ascending=True)
    plt.figure(figsize=(9, 7))
    colors = ["#2c7fb8" if i >= len(sub) - 5 else "#bdbdbd" for i in range(len(sub))]
    colors = [
        "#d73027" if i < 5 else c for i, c in enumerate(colors)
    ]
    plt.barh(range(len(sub)), sub["borda_score"], color=colors)
    plt.yticks(range(len(sub)), sub["TopicLabel"], fontsize=8)
    plt.xlabel("Borda score (higher = higher priority)")
    plt.title("Topic prioritisation — Borda count across 50 rankers")
    plt.tight_layout()
    plt.savefig(OUT / "figures" / "E1_borda_scores.png", dpi=300)
    plt.savefig(OUT / "figures" / "E1_borda_scores.pdf")
    plt.close()


def topic_clustering(long_df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray, list[str]]:
    topic_labels = (
        long_df.drop_duplicates("TopicID").set_index("TopicID")["TopicLabel"].to_dict()
    )
    topics = sorted(topic_labels.keys())
    user_topic = long_df.pivot(index="Username", columns="TopicID", values="Rank")[topics]
    user_topic = user_topic.dropna(axis=0, how="any")

    rho_mat = np.zeros((len(topics), len(topics)))
    for i, a in enumerate(topics):
        for j, b in enumerate(topics):
            if i == j:
                rho_mat[i, j] = 1.0
            else:
                rho, _ = spearmanr(user_topic[a], user_topic[b])
                rho_mat[i, j] = rho if not np.isnan(rho) else 0.0
    dist = 1 - rho_mat
    np.fill_diagonal(dist, 0.0)
    dist = (dist + dist.T) / 2
    condensed = squareform(dist, checks=False)
    linkage_matrix = linkage(condensed, method="average")
    labels = [topic_labels[t] for t in topics]
    return pd.DataFrame(rho_mat, index=labels, columns=labels), linkage_matrix, labels


def plot_dendrogram(linkage_matrix: np.ndarray, labels: list[str]) -> None:
    plt.figure(figsize=(11, 6))
    dendrogram(linkage_matrix, labels=labels, leaf_rotation=45, leaf_font_size=8)
    plt.title("Topic clustering — average linkage on (1 - Spearman) distance")
    plt.ylabel("Distance")
    plt.tight_layout()
    plt.savefig(OUT / "figures" / "E2_topic_dendrogram.png", dpi=300)
    plt.savefig(OUT / "figures" / "E2_topic_dendrogram.pdf")
    plt.close()


def cluster_writeup(rho: pd.DataFrame, linkage_matrix: np.ndarray, labels: list[str]) -> str:
    from scipy.cluster.hierarchy import fcluster

    cl4 = fcluster(linkage_matrix, t=4, criterion="maxclust")
    out = ["# Phase E2 — Topic clusters (4-cluster cut)\n"]
    for cid in sorted(set(cl4)):
        members = [labels[i] for i, c in enumerate(cl4) if c == cid]
        out.append(f"## Cluster {cid} ({len(members)} topics)")
        out.extend(f"- {m}" for m in members)
        out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# E3 — Priority vs volume
# ---------------------------------------------------------------------------


TOPIC_KEYWORDS: dict[str, list[str]] = {
    "Indoor Temperature Control": ["temperature", "thermal", "warm", "cold", "heat", "cool"],
    "Air Quality & Ventilation": ["air quality", "ventilation", "co2", "humidity", "pollution", "iaq"],
    "Lighting": ["light", "lumin", "brightness", "lamp", "illum"],
    "Energy Consumption": ["energy", "kwh", "power", "consumption", "electric"],
    "Water Usage": ["water", "leak", "tap", "plumbing"],
    "Noise & Acoustics": ["noise", "sound", "acoustic", "loud", "decibel"],
    "Occupancy & Space Use": ["occupancy", "space", "room avail", "people count", "presence"],
    "Fire Safety & Emergency": ["fire", "smoke", "emergency", "alarm", "evacuat"],
    "Security & Access": ["security", "door", "access", "intrusion", "lock"],
    "Maintenance Issues": ["maintenance", "repair", "broken", "fault"],
    "Weather Conditions": ["weather", "rain", "wind", "outdoor", "storm"],
    "Green Spaces & Biodiversity": ["green", "plant", "biodiversity", "park", "garden"],
    "Indoor Air Pollution": ["pollution", "smog", "voc", "no2", "ozone", "particulate"],
    "Renewable Energy": ["solar", "renewable", "battery", "wind turbine", "pv"],
    "Transport & Parking": ["parking", "transport", "bike", "ev", "vehicle"],
    "Waste Management": ["waste", "recycle", "trash", "bin"],
    "Cleanliness & Hygiene": ["clean", "hygiene", "sanitation", "toilet", "bathroom"],
    "User Apps & Digital Interaction": ["app", "interface", "digital", "dashboard", "ui"],
    "Comfort & Wellbeing": ["comfort", "wellbeing", "well being"],
    "Smart Building Features": ["smart", "automation", "iot"],
}


def topic_volume(corpus: pd.DataFrame, topic_labels: list[str]) -> pd.Series:
    text = corpus["Question"].astype(str).str.lower()
    counts = {}
    for label in topic_labels:
        kws = TOPIC_KEYWORDS.get(label, [])
        if not kws:
            counts[label] = 0
            continue
        mask = pd.Series(False, index=corpus.index)
        for kw in kws:
            mask |= text.str.contains(kw, regex=False, na=False)
        counts[label] = int(mask.sum())
    return pd.Series(counts, name="volume")


def plot_priority_vs_volume(table: pd.DataFrame, volume: pd.Series) -> None:
    df = table.set_index("TopicLabel")[["mean_rank"]].join(volume)
    df = df.dropna()
    plt.figure(figsize=(8, 6))
    plt.scatter(df["volume"], df["mean_rank"], s=80, c="steelblue", edgecolors="black")
    for label, row in df.iterrows():
        plt.annotate(label, (row["volume"], row["mean_rank"]), fontsize=7,
                     xytext=(4, 4), textcoords="offset points")
    plt.gca().invert_yaxis()
    plt.xlabel("Question volume in corpus (keyword-matched)")
    plt.ylabel("Mean priority rank (lower = higher priority)")
    plt.title("Priority vs question volume by topic")
    plt.tight_layout()
    plt.savefig(OUT / "figures" / "E3_priority_vs_volume_scatter.png", dpi=300)
    plt.savefig(OUT / "figures" / "E3_priority_vs_volume_scatter.pdf")
    plt.close()


def append_summary(table: pd.DataFrame, w: float) -> None:
    path = ROOT / "corpus" / "corpus_summary_stats.md"
    top3 = ", ".join(table.head(3)["TopicLabel"].tolist())
    bot3 = ", ".join(table.tail(3)["TopicLabel"].tolist())
    line = (
        f"- Phase E: top-3 topics = {top3}; bottom-3 = {bot3}; "
        f"overall Kendall's W = {w:.3f}.\n"
    )
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if "Phase E:" in existing:
            new = []
            for ln in existing.splitlines(keepends=True):
                new.append(line if ln.lstrip().startswith("- Phase E:") else ln)
            path.write_text("".join(new), encoding="utf-8")
        else:
            path.write_text(existing.rstrip() + "\n" + line, encoding="utf-8")
    else:
        path.write_text(line, encoding="utf-8")


def main() -> None:
    topic_df = pd.read_csv(INPUTS / "topic_rankings.csv")
    long_df = long_form(topic_df)

    table, w = topic_priority_table(long_df)
    table.to_csv(OUT / "tables" / "E1_topic_priority_table.csv", index=False)
    (OUT / "tables" / "E1_kendalls_w.md").write_text(
        f"# Phase E1 — Inter-user agreement\n\n"
        f"- N rankers (complete) = {int(topic_df.shape[0])}\n"
        f"- Kendall's W = {w:.4f}\n"
        f"- Interpretation: Schmidt (1997) — 0.1 weak, 0.3 moderate, 0.5 strong agreement.\n",
        encoding="utf-8",
    )
    plot_borda(table)

    rho, linkage_matrix, labels = topic_clustering(long_df)
    rho.to_csv(OUT / "tables" / "E2_topic_corr_matrix.csv")
    plot_dendrogram(linkage_matrix, labels)
    (OUT / "tables" / "E2_topic_clusters.md").write_text(
        cluster_writeup(rho, linkage_matrix, labels), encoding="utf-8"
    )

    corpus = pd.read_csv(CORPUS / "classified_corpus.csv")
    vol = topic_volume(corpus, table["TopicLabel"].tolist())
    plot_priority_vs_volume(table, vol)

    append_summary(table, w)

    print("Phase E done.")
    print(f"Kendall's W (overall) = {w:.4f}")
    print("Top-5 topics by Borda:")
    print(table.head(5)[["TopicLabel", "borda_score", "mean_rank"]].to_string(index=False))
    print("Bottom-5 topics by Borda:")
    print(table.tail(5)[["TopicLabel", "borda_score", "mean_rank"]].to_string(index=False))


if __name__ == "__main__":
    main()
