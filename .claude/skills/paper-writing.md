---
name: paper-writing
description: Use when revising sections of paper/research paper.tex, refreshing statistics from survey outputs, adding figures, or aligning the OntoSage++ draft with the IMWUT sample paper structure.
---

# Paper Writing Runbook — OntoSage++ IMWUT Submission

## Always Start Here

1. Read `paper/PROGRESS.md` — know what is done, what is next
2. Read `paper/PAPER_INDEX.md` — find line ranges for the section you will edit
3. Read ONLY the targeted line range from `paper/research paper.tex` — never the whole file (it is 1000+ lines)

## Target Structure (mirror sample paper)

The sample is Guo et al. 2018 IMWUT (20 pages, `acmsmall`). Match this section order exactly:

| § | Sample paper section | OntoSage++ equivalent | Source data |
|---|---------------------|----------------------|-------------|
| Abstract | 1 paragraph problem + 1 paragraph contribution | Same | Hand-written, refresh stats from `outputs/tables/A2_*` |
| 1 Introduction | Motivation, 4 RQs, contributions list, paper roadmap | Same | RQs already in draft, polish |
| 2 Related Work | 3 sub-streams (HBI, semantic AI, heterogeneity) | Same | Bib in `references.bib` |
| 3 Methodology | Survey design, participants, ethics, analysis approach | Phase 1 study | `ANALYSIS_METHODOLOGY.md` Part 6 |
| 3.1 Participants | Demographics table | Demographics | `outputs/tables/A2_demographics_table.csv` |
| 3.2 Survey Design | Stage 1-4 elicitation | Same | Existing draft sec |
| 3.3 Data Collection | Corpus size, period, ethics | Same | `corpus_summary_stats.md` |
| 3.4 Analysis Approach | Statistical methods | Same | `ANALYSIS_METHODOLOGY.md` Part 3 |
| 4 Findings | RQ1-RQ5 results | Phase 1 results | `outputs/tables/B*-F*.csv` |
| 4.1 Corpus Overview | Domain + intent dist | RQ1 | `B4_corpus_statistics.csv` |
| 4.2 Stage Comparison | Elicitation effect | RQ2 | `C1_stage_stats.csv`, `C3_novelty_*` |
| 4.3 Role-Based | Role × domain | RQ3 | `D1_role_domain_heatmap.png`, `D2_*` |
| 4.4 Topic Priorities | Borda + clustering | RQ4 | `E1_borda_scores.png`, `E2_topic_clusters.md` |
| 4.5 Question Prefs | Within-topic | RQ5 | `F1_question_preferences_by_topic.csv` |
| 5 System Design | OntoSage++ architecture | Existing draft sec 4 | `paper/figures/architecture.pdf` |
| 6 Phase 2 Eval | 15-person post-design study | Existing draft sec 5 | `paper/post_design_survey/responses.csv` + `summary_stats.csv` |
| 7 Discussion | Implications | Same | Synthesis |
| 8 Limitations | Honest constraints | Same | Sample size, simulated data |
| 9 Conclusion | Wrap | Same | — |

## Refreshing Statistics (most common task)

```bash
# 1. List every TBD or fabricated number
grep -n "TBD-from\|87.3\|66.4\|90\\\\%\|42 participants" "paper/research paper.tex"

# 2. For each match, find the corresponding CSV
ls "paper/Survey analysis and results/outputs/tables/"

# 3. Read the CSV, get the real number, Edit the .tex
# 4. Log replacements in paper/PROGRESS.md under "Stat refreshes"
```

## Adding a Figure

```latex
% In research paper.tex at the right section:
\begin{figure}[t]
\centering
\includegraphics[width=\linewidth]{Survey analysis and results/outputs/figures/B4_domain_distribution.pdf}
\caption{Distribution of Level-1 query domains across the corpus (n=5,127). Indoor temperature, air quality, and energy dominate.}
\label{fig:domain-dist}
\end{figure}
```

After adding:
1. Append the figure label to `PAPER_INDEX.md`
2. If using a PNG, also generate a PDF (`convert_svg_to_pdf.py` is in `paper/figures/`)

## Fixing the Fabricated Stats

The current draft contains these PLACEHOLDER numbers that must be replaced before submission:

| Fake stat | Where (approx) | Replace with |
|-----------|----------------|--------------|
| `87.3% task completion` | abstract, sec 6 | `98.3%` (118/120) from `post_design_survey/summary_stats.csv` |
| `66.4% time reduction` | abstract, sec 6 | Recast as qualitative claim or remove until baseline study runs |
| `90% engineering reduction` | abstract, sec 6 | Real T0-T3 effort comparison from §5.3 |
| `42 participants` (Phase 2) | abstract, sec 6 | `15` from `post_design_survey/responses.csv` |
| Mean SUS to add | sec 6 RQ4 | `84.5` from `post_design_survey/summary_stats.csv` |
| `68% Stage 1 Cluster C` | sec 3.4 | Real % from `B4_corpus_statistics.csv` |
| `80% Stage 2 Cluster B` | sec 3.4 | Real % from `B4_corpus_statistics.csv` |
| `Building B/C synthetic` | sec 5 | Mark as "synthetic Brick TTL" — currently honest, keep |

## Compiling the Paper

```bash
cd paper
pdflatex "research paper.tex"
bibtex "research paper"
pdflatex "research paper.tex"
pdflatex "research paper.tex"
```

If `acmart` complains about missing CCS XML, that's OK — placeholder block at line 214.

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| Editing whole file at once | Use `PAPER_INDEX.md` to find line range, edit just that |
| Reading the 9 MB sample PDF every time | Read once, summary is in `paper/CLAUDE.md` "Sample paper structure" |
| Leaving fabricated stats in | Run grep above before every commit |
| Forgetting to anonymise | Never put usernames in the .tex; use `P01..P60` |
| Citing without `references.bib` entry | `grep -n "<key>" paper/references.bib` first |
| Skipping ethics statement | Section 3.3 MUST cite SREC COMSC/Ethics/2025/044b |

## Handoff to survey-analysis Skill

If a section needs new analysis (e.g., "what's the avg complexity per role"), do NOT compute it inline. Switch to the `survey-analysis` skill to add it to the appropriate phase script, regenerate the table, then come back here to cite the result.
