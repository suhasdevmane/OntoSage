"""W2 reproduction of the 2025 survey analysis (plan 21, W2). Scratch tool; never touches the originals.

1. Copies the parts of paper/Survey analysis and results/ that the deterministic scripts need into
   draft1Nov_work/phase1_repro/work/Survey analysis and results/ (the folder name is kept, because
   Z_paper_combined_figures.py writes to <folder>/../figures).
2. Deletes, in the copy, every file the scripts below are expected to write, so a file that is not
   regenerated is missing rather than silently identical.
3. Runs the scripts in pipeline order with the copy as their root, logging stdout/stderr.
4. Leaves the comparison to diff_repro.py.

Not run: B3_irr_llm_coder.py (an LLM pass), H_evaluation_analysis.py (corpus replay, not used),
J_* (LLM), K/L (not in the W2 list), J_complexity_standalone.py (holds an API key; not copied).

Usage: python -I run_repro.py
"""
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(PAPER, "Survey analysis and results")
WORK = os.path.join(HERE, "work")
DST = os.path.join(WORK, "Survey analysis and results")

SCRIPTS = [
    "A_data_preparation.py",
    "B_corpus_classification.py",
    "B4_corpus_statistics.py",
    "C_stage_comparison.py",
    "D_persona_analysis.py",
    "D_role_analysis.py",
    "E_topic_priorities.py",
    "F_question_preferences.py",
    "G_framework_synthesis.py",          # extra: writes G2_capability_matrix.csv, read by Z_paper_derived_tables
    "I_borda_vs_analytical_demand.py",
    "Z_paper_derived_tables.py",
    "Z_paper_combined_figures.py",
    "B3_irr_compute.py",                 # extra: deterministic kappa from the stored LLM coder output
]

# files the scripts above write (relative to DST); deleted in the copy before running
EXPECTED = [
    "outputs/intermediate/username_to_pid.csv",
    "outputs/tables/A2_demographics_table.csv", "outputs/tables/A3_user_summary.csv",
    "corpus/classified_corpus.csv",
    "outputs/tables/B4_corpus_statistics.csv", "outputs/tables/B4_domain_by_stage.csv",
    "outputs/tables/B4_intent_by_complexity.csv",
    "outputs/tables/C1_stage_stats.csv", "outputs/tables/C1_stage_tests.md",
    "outputs/tables/C2_stage_evolution_table.md", "outputs/tables/C3_novelty_analysis.csv",
    "outputs/tables/D1_persona_domain_counts.csv", "outputs/tables/D1_persona_domain_pct.csv",
    "outputs/tables/D1_role_domain_counts.csv", "outputs/tables/D1_role_domain_pct.csv",
    "outputs/tables/D1_chi_squared_results.md", "outputs/tables/D2_persona_topic_rank.csv",
    "outputs/tables/D2_role_topic_rank.csv", "outputs/tables/D2_concordance_table.csv",
    "outputs/tables/D3_user_personas.md",
    "outputs/tables/E1_topic_priority_table.csv", "outputs/tables/E1_kendalls_w.md",
    "outputs/tables/E2_topic_corr_matrix.csv", "outputs/tables/E2_topic_clusters.md",
    "outputs/tables/F1_question_preferences_by_topic.csv", "outputs/tables/F1_overall_level_preference.csv",
    "outputs/tables/F2_complexity_preference_by_persona.csv",
    "outputs/tables/G1_classification_framework.md", "outputs/tables/G2_capability_matrix.csv",
    "outputs/tables/G4_gap_analysis.md",
    "outputs/tables/I1_borda_vs_l4_demand.csv",
    "outputs/tables/Z_intent_by_stage.csv", "outputs/tables/Z_domain_by_stage.csv",
    "outputs/tables/Z_paper_constants.csv",
    "outputs/tables/B3_irr_report.md",
]


def copy_tree() -> None:
    if os.path.exists(WORK):
        shutil.rmtree(WORK)
    os.makedirs(DST)
    for sub in ("inputs", "taxonomy", "corpus"):
        shutil.copytree(os.path.join(SRC, sub), os.path.join(DST, sub))
    os.makedirs(os.path.join(DST, "scripts"))
    for name in SCRIPTS:
        shutil.copy2(os.path.join(SRC, "scripts", name), os.path.join(DST, "scripts", name))
    out = os.path.join(DST, "outputs")
    shutil.copytree(os.path.join(SRC, "outputs", "tables"), os.path.join(out, "tables"),
                    ignore=shutil.ignore_patterns("complexity_master_table.csv"))
    shutil.copytree(os.path.join(SRC, "outputs", "intermediate"), os.path.join(out, "intermediate"))
    os.makedirs(os.path.join(out, "figures"))
    shutil.copy2(os.path.join(SRC, "outputs", "survey_evaluation_results.csv"), out)
    for rel in EXPECTED:
        p = os.path.join(DST, rel)
        if os.path.exists(p):
            os.remove(p)


def run_all() -> int:
    log_path = os.path.join(HERE, "repro_log.txt")
    failures = 0
    env = dict(os.environ, PYTHONHASHSEED="0", MPLBACKEND="Agg", SOURCE_DATE_EPOCH="0")
    with open(log_path, "w", encoding="utf-8") as log:
        for name in SCRIPTS:
            t0 = time.time()
            proc = subprocess.run([sys.executable, "-I", os.path.join("scripts", name)], cwd=DST,
                                  capture_output=True, text=True, env=env, timeout=1800)
            dt = time.time() - t0
            status = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
            failures += proc.returncode != 0
            log.write(f"===== {name}: {status} in {dt:.1f}s\n")
            log.write(proc.stdout[-6000:])
            if proc.stderr.strip():
                log.write("\n----- stderr (tail)\n" + proc.stderr[-6000:])
            log.write("\n")
            print(f"{name:<38} {status} ({dt:.1f}s)")
    missing = [rel for rel in EXPECTED if not os.path.exists(os.path.join(DST, rel))]
    print(f"expected outputs not produced: {len(missing)}")
    for rel in missing:
        print("   MISSING", rel)
    return 1 if failures or missing else 0


def second_pass() -> int:
    """The stored A3_user_summary.csv names its persona column PrimaryRole; A_data_preparation.py as it now stands
    writes PrimaryPersona, which D_role_analysis.py and F_question_preferences.py cannot read. The two files are
    otherwise identical (checked row by row), so rename the header in the COPY and re-run those two scripts, as the
    original run evidently did (its D_role and F outputs are timestamped after A3 was rewritten)."""
    a3 = os.path.join(DST, "outputs", "tables", "A3_user_summary.csv")
    with open(a3, encoding="utf-8") as fh:
        text = fh.read()
    header, rest = text.split("\n", 1)
    with open(a3, "w", encoding="utf-8", newline="") as fh:
        fh.write(header.replace("PrimaryPersona", "PrimaryRole") + "\n" + rest)
    log_path = os.path.join(HERE, "repro_log.txt")
    failures = 0
    env = dict(os.environ, PYTHONHASHSEED="0", MPLBACKEND="Agg", SOURCE_DATE_EPOCH="0")
    with open(log_path, "a", encoding="utf-8") as log:
        log.write("##### SECOND PASS: A3 header PrimaryPersona -> PrimaryRole in the copy\n")
        for name in ("D_role_analysis.py", "F_question_preferences.py"):
            proc = subprocess.run([sys.executable, "-I", os.path.join("scripts", name)], cwd=DST,
                                  capture_output=True, text=True, env=env, timeout=1800)
            status = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
            failures += proc.returncode != 0
            log.write(f"===== {name} (second pass): {status}\n{proc.stdout[-6000:]}\n")
            if proc.stderr.strip():
                log.write("----- stderr (tail)\n" + proc.stderr[-6000:] + "\n")
            print(f"{name:<38} second pass {status}")
    missing = [rel for rel in EXPECTED if not os.path.exists(os.path.join(DST, rel))]
    print(f"expected outputs not produced after the second pass: {len(missing)}")
    return 1 if failures or missing else 0


if __name__ == "__main__":
    copy_tree()
    first = run_all()
    sys.exit(second_pass())
