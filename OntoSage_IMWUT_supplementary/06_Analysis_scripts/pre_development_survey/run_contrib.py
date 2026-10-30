"""Contributor-only rerun of the Stage 5 ranking analyses (coordinator follow-up, 28 Oct). Scratch tool.

A ranking account counts as a contributor when its username (trimmed, lower-cased, inner spaces collapsed) has at
least one question in inputs/questions_by_user.csv. The originals are never touched:

1. copies the inputs, the corpus, outputs/tables, outputs/intermediate and the three scripts E, F and I into
   phase1_repro/contrib_work/Survey analysis and results/;
2. keeps, in the copies of inputs/topic_rankings.csv and inputs/question_rankings.csv, only contributor accounts;
3. changes two hard-coded figure titles in the copies (E_topic_priorities.py "across 50 rankers";
   Z_paper_combined_figures.py rho = -0.25, p = 0.29) so that they print what the data say;
4. runs E_topic_priorities.py, F_question_preferences.py, I_borda_vs_analytical_demand.py and Z_paper_combined_figures.py;
5. copies the aggregate outputs (no usernames) to paper/generated/phase1/contrib/ with the suffix _contrib, checks that
   none of them holds a username, and deletes the whole working copy (which does hold usernames).

Usage: python -I run_contrib.py
"""
import csv
import io
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PAPER, "Survey analysis and results")
WORK = os.path.join(HERE, "contrib_work")
DST = os.path.join(WORK, "Survey analysis and results")
OUT = os.path.join(PAPER, "generated", "phase1", "contrib")

SCRIPTS = ["E_topic_priorities.py", "F_question_preferences.py", "I_borda_vs_analytical_demand.py",
           "Z_paper_combined_figures.py"]
KEEP = {  # file in the working copy (relative to contrib_work/) -> name in generated/phase1/contrib/
    "Survey analysis and results/outputs/tables/E1_topic_priority_table.csv": "E1_topic_priority_table_contrib.csv",
    "Survey analysis and results/outputs/tables/E1_kendalls_w.md": "E1_kendalls_w_contrib.md",
    "Survey analysis and results/outputs/tables/E2_topic_clusters.md": "E2_topic_clusters_contrib.md",
    "Survey analysis and results/outputs/tables/F1_overall_level_preference.csv":
        "F1_overall_level_preference_contrib.csv",
    "Survey analysis and results/outputs/tables/F1_question_preferences_by_topic.csv":
        "F1_question_preferences_by_topic_contrib.csv",
    "Survey analysis and results/outputs/tables/I1_borda_vs_l4_demand.csv": "I1_borda_vs_l4_demand_contrib.csv",
    "Survey analysis and results/outputs/figures/E1_borda_scores.pdf": "E1_borda_scores_contrib.pdf",
    "Survey analysis and results/outputs/figures/E1_borda_scores.png": "E1_borda_scores_contrib.png",
    "Survey analysis and results/outputs/figures/F2_complexity_preference.pdf": "F2_complexity_preference_contrib.pdf",
    "Survey analysis and results/outputs/figures/F2_complexity_preference.png": "F2_complexity_preference_contrib.png",
    "figures/fig_borda_vs_l4.pdf": "fig_borda_vs_l4_contrib.pdf",
}
# One hard-coded title is made to print what the data say (the scripts are otherwise unchanged):
# E_topic_priorities.py writes "across 50 rankers". (Z_paper_combined_figures.py computed rho and p itself
# from 29 Oct 2026, so its patch was removed.)
PATCHES = {
    "E_topic_priorities.py": (
        'plt.title("Topic prioritisation — Borda count across 50 rankers")',
        'plt.title(f"Topic prioritisation — Borda count across {int(table[\'n_rankers\'].max())} rankers")'),
}


def norm_user(u: str) -> str:
    return " ".join((u or "").strip().lower().split())


def read_rows(path: str):
    with io.open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return reader.fieldnames, list(reader)


def write_rows(path: str, fields, rows) -> None:
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    if os.path.exists(WORK):
        shutil.rmtree(WORK)
    os.makedirs(os.path.join(DST, "scripts"))
    for sub in ("inputs", "corpus"):
        shutil.copytree(os.path.join(SRC, sub), os.path.join(DST, sub))
    shutil.copytree(os.path.join(SRC, "outputs", "tables"), os.path.join(DST, "outputs", "tables"),
                    ignore=shutil.ignore_patterns("complexity_master_table.csv"))
    shutil.copytree(os.path.join(SRC, "outputs", "intermediate"), os.path.join(DST, "outputs", "intermediate"))
    os.makedirs(os.path.join(DST, "outputs", "figures"))
    for name in SCRIPTS:
        shutil.copy2(os.path.join(SRC, "scripts", name), os.path.join(DST, "scripts", name))

    _, qbu = read_rows(os.path.join(SRC, "inputs", "questions_by_user.csv"))
    contributors = {norm_user(r["Username"]) for r in qbu}
    report = []
    for name in ("topic_rankings.csv", "question_rankings.csv"):
        fields, rows = read_rows(os.path.join(SRC, "inputs", name))
        kept = [r for r in rows if norm_user(r["Username"]) in contributors]
        write_rows(os.path.join(DST, "inputs", name), fields, kept)
        accounts = {norm_user(r["Username"]) for r in rows}
        kept_accounts = {norm_user(r["Username"]) for r in kept}
        report.append(f"{name}: kept {len(kept)} of {len(rows)} rows, {len(kept_accounts)} of {len(accounts)} accounts")

    for name, (old, new) in PATCHES.items():
        path = os.path.join(DST, "scripts", name)
        text = io.open(path, encoding="utf-8").read()
        if text.count(old) != 1:
            raise SystemExit(f"{name}: the title to patch was not found exactly once; not patching")
        io.open(path, "w", encoding="utf-8").write(text.replace(old, new))
    for rel in KEEP:
        p = os.path.join(WORK, rel)
        if os.path.exists(p):
            os.remove(p)

    env = dict(os.environ, PYTHONHASHSEED="0", MPLBACKEND="Agg", SOURCE_DATE_EPOCH="0")
    log = []
    failed = 0
    for name in SCRIPTS:
        proc = subprocess.run([sys.executable, "-I", os.path.join("scripts", name)], cwd=DST, capture_output=True,
                              text=True, env=env, timeout=1800)
        failed += proc.returncode != 0
        log.append(f"===== {name}: exit {proc.returncode}\n{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}")
        print(f"{name:<36} exit {proc.returncode}")

    os.makedirs(OUT, exist_ok=True)
    missing = []
    for rel, dest in KEEP.items():
        p = os.path.join(WORK, rel)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(OUT, dest))
        else:
            missing.append(rel)

    leaks = []
    for dest in KEEP.values():
        p = os.path.join(OUT, dest)
        if not os.path.exists(p) or dest.endswith((".pdf", ".png")):
            continue
        t = io.open(p, encoding="utf-8", errors="ignore").read().lower()
        leaks += [dest for u in contributors if len(u) > 3 and u in t]
    log_text = "\n".join(report) + "\n" + "\n".join(log)
    log_text_l = log_text.lower()
    leaks += ["contrib_log.txt" for u in contributors if len(u) > 3 and u in log_text_l]
    if not leaks:
        io.open(os.path.join(HERE, "contrib_log.txt"), "w", encoding="utf-8").write(log_text)
    shutil.rmtree(WORK)       # the working copy holds usernames
    for line in report:
        print(line)
    print(f"outputs copied to {os.path.relpath(OUT, PAPER)}; missing: {missing or 'none'}; username leaks: "
          f"{sorted(set(leaks)) or 'none'}; working copy deleted")
    return 1 if failed or missing or leaks else 0


if __name__ == "__main__":
    sys.exit(main())
