"""
Phase I: Borda Score × Analytical Demand Analysis

Cross-references topic priority (Borda scores from Phase E) with the percentage of rankers
who preferred the L4 expert-level query first (from Phase F), revealing which topics are
both high-priority AND drive analytical demand.

Outputs:
  outputs/tables/I1_borda_vs_l4_demand.csv
  outputs/figures/I1_borda_vs_l4_demand.{png,pdf}
"""

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.join(SCRIPT_DIR, "..")
TABLES = os.path.join(BASE_DIR, "outputs", "tables")
FIGURES = os.path.join(BASE_DIR, "outputs", "figures")
os.makedirs(FIGURES, exist_ok=True)

# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------
e1 = pd.read_csv(os.path.join(TABLES, "E1_topic_priority_table.csv"))
f1 = pd.read_csv(os.path.join(TABLES, "F1_question_preferences_by_topic.csv"))

# Compute L4 analytical demand: % of users who ranked L4 (expert) first
f1_l4 = f1[f1["Level"] == 4].copy()
f1_l4["pct_l4_rank1"] = f1_l4["rank1_count"] / f1_l4["n_users"] * 100

df = e1[["TopicID", "TopicLabel", "borda_score"]].merge(
    f1_l4[["TopicID", "n_users", "pct_l4_rank1"]], on="TopicID"
)
df = df.rename(columns={"borda_score": "Borda", "n_users": "n_rankers", "pct_l4_rank1": "PctL4First"})
df["PctL4First"] = df["PctL4First"].round(1)

# ---------------------------------------------------------------------------
# 2. Assign clusters (from E2 dendrogram, 4-cluster cut)
# ---------------------------------------------------------------------------
CLUSTER_MEMBERS = {
    1: [1, 2, 4, 7],           # Indoor Comfort & Occupancy
    2: [3, 14, 15, 16, 17, 18], # Digital Infrastructure & Access
    3: [10, 11, 12],            # Environmental Sustainability
    4: [5, 6, 8, 9, 13, 19, 20], # Critical Systems
}
CLUSTER_LABELS = {
    1: "Indoor Comfort & Occupancy",
    2: "Digital Infrastructure & Access",
    3: "Environmental Sustainability",
    4: "Critical Systems",
}
CLUSTER_COLORS = {1: "#e74c3c", 2: "#3498db", 3: "#2ecc71", 4: "#f39c12"}

topic_to_cluster = {tid: cid for cid, tids in CLUSTER_MEMBERS.items() for tid in tids}
df["Cluster"] = df["TopicID"].map(topic_to_cluster)
df["Color"] = df["Cluster"].map(CLUSTER_COLORS)

SHORT_LABELS = {
    "Indoor Temperature Control": "Temperature",
    "Air Quality & Ventilation": "Air Quality",
    "Lighting & Daylight": "Lighting",
    "Noise & Acoustics": "Noise",
    "Energy Consumption": "Energy",
    "Security & Access Control": "Security",
    "Fire Safety & Emergency": "Fire Safety",
    "Water Management": "Water",
    "Occupancy & Space Utilisation": "Occupancy",
    "Waste & Recycling": "Waste",
    "Renewable Energy & Solar": "Renewable Energy",
    "Green Spaces & Biodiversity": "Green Spaces",
    "Health & Well-being": "Health",
    "IoT Sensors & Data Analytics": "IoT/Analytics",
    "Lifts, Stairs & Internal Transport": "Lifts/Transport",
    "Parking & EV Charging": "Parking/EV",
    "Building Automation & AI": "Bldg Automation",
    "User Apps & Digital Interaction": "User Apps",
    "Building Maintenance & Faults": "Maintenance",
    "Carbon Footprint & Net Zero": "Carbon/Net Zero",
}
df["ShortLabel"] = df["TopicLabel"].map(SHORT_LABELS).fillna(df["TopicLabel"])

# Save table
df.to_csv(os.path.join(TABLES, "I1_borda_vs_l4_demand.csv"), index=False)
print(f"[I1] Saved table to {TABLES}/I1_borda_vs_l4_demand.csv")

# ---------------------------------------------------------------------------
# 3. Scatter plot
# ---------------------------------------------------------------------------
med_borda = df["Borda"].median()
med_l4 = df["PctL4First"].median()

fig, ax = plt.subplots(figsize=(10.5, 7.5))

for _, row in df.iterrows():
    ax.scatter(
        row["Borda"], row["PctL4First"],
        s=row["n_rankers"] * 5 + 30,
        color=row["Color"],
        alpha=0.80,
        edgecolors="white",
        linewidth=0.6,
        zorder=3,
    )
    # Position label to avoid common overlaps
    ha = "left" if row["Borda"] < med_borda else "right"
    offset_x = 9 if ha == "left" else -9
    offset_y = 3 if row["PctL4First"] < 45 else -12
    ax.annotate(
        row["ShortLabel"],
        xy=(row["Borda"], row["PctL4First"]),
        xytext=(offset_x, offset_y),
        textcoords="offset points",
        fontsize=8,
        ha=ha,
        va="bottom",
        color="#333333",
    )

# Median reference lines
ax.axvline(med_borda, color="#aaaaaa", linestyle="--", linewidth=0.9, zorder=1)
ax.axhline(med_l4, color="#aaaaaa", linestyle="--", linewidth=0.9, zorder=1)

# Quadrant annotations
def qa(ax, x, y, text):
    ax.text(x, y, text, fontsize=7, color="#888888", va="center", ha="center",
            style="italic", bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.6, ec="none"))

qa(ax, med_borda + 150, med_l4 + 18, "High priority\n+ High analytical demand\n(analytical hot-spot)")
qa(ax, med_borda - 180, med_l4 + 18, "Low priority\n+ High analytical demand\n(niche experts)")
qa(ax, med_borda + 150, med_l4 - 7,  "High priority\n+ Low analytical demand\n(fast-lookup tier)")
qa(ax, med_borda - 180, med_l4 - 7,  "Low priority\n+ Low analytical demand\n(low ROI)")

# Legend
legend_patches = [
    mpatches.Patch(color=CLUSTER_COLORS[c], label=CLUSTER_LABELS[c])
    for c in sorted(CLUSTER_LABELS)
]
size_handle = ax.scatter([], [], s=50, color="#888888", alpha=0.7, label="n=10 rankers (size ∝ n)")
ax.legend(
    handles=legend_patches + [size_handle],
    loc="lower right",
    fontsize=8.5,
    framealpha=0.9,
    title="Topic cluster",
    title_fontsize=8,
)

ax.set_xlabel("Borda Priority Score  (higher = more important to users)", fontsize=11)
ax.set_ylabel("% Users Ranking L4 Expert Query First  (higher = more analytical demand)", fontsize=11)
ax.set_title(
    "Smart Building Topic Priority vs. Analytical Query Demand  ($N$=20 topics)",
    fontsize=12, fontweight="bold",
)
ax.set_xlim(390, 1260)
ax.set_ylim(-2, 62)
ax.grid(True, alpha=0.25, zorder=0)

plt.tight_layout()
for ext in ("png", "pdf"):
    out = os.path.join(FIGURES, f"I1_borda_vs_l4_demand.{ext}")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"[I1] Saved {out}")
plt.close()

# ---------------------------------------------------------------------------
# 4. Console summary for paper text verification
# ---------------------------------------------------------------------------
print("\n=== I1 Summary for paper text ===")
print(f"Median Borda score: {med_borda:.0f}")
print(f"Median L4-first %%: {med_l4:.1f}%%")

print("\nTop-right quadrant (High Borda AND High L4%%):")
top_right = df[(df["Borda"] > med_borda) & (df["PctL4First"] > med_l4)].sort_values("Borda", ascending=False)
print(top_right[["ShortLabel", "Borda", "PctL4First", "n_rankers"]].to_string(index=False))

print("\nBottom-right quadrant (High Borda, Low L4%%):")
bot_right = df[(df["Borda"] > med_borda) & (df["PctL4First"] <= med_l4)].sort_values("Borda", ascending=False)
print(bot_right[["ShortLabel", "Borda", "PctL4First", "n_rankers"]].to_string(index=False))

print("\nTop-left quadrant (Low Borda, High L4%% — niche experts):")
top_left = df[(df["Borda"] <= med_borda) & (df["PctL4First"] > med_l4)].sort_values("PctL4First", ascending=False)
print(top_left[["ShortLabel", "Borda", "PctL4First", "n_rankers"]].to_string(index=False))
