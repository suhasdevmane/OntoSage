# /paper-stats — Refresh All Numerical Claims from Survey Outputs

Find every fabricated or `TBD` number in `paper/research paper.tex` and replace it with the real value from `paper/Survey analysis and results/outputs/tables/`.

## Usage

```
/paper-stats
```

(no arguments)

## Steps

1. **Invoke the paper-writing skill.**

2. **List all output tables:**
   ```bash
   ls "paper/Survey analysis and results/outputs/tables/"
   ```
   If this is empty, STOP and tell the user to run `survey-analysis` Phase A first.

3. **Find every TBD marker:**
   ```bash
   grep -n "TBD-from\|\\\\textcolor{red}" "paper/research paper.tex"
   ```

4. **Find every fabricated stat from the original draft:**
   ```bash
   grep -n -E "87\.3|66\.4|90\\\\%|42 participants|68\\\\%|80\\\\%" "paper/research paper.tex"
   ```

5. **For each match**, follow this lookup chain:
   | Claim | Source CSV | Column |
   |-------|------------|--------|
   | Total participants (corpus) | `A2_demographics_table.csv` | `users` (sum) |
   | Questions per stage | `A3_user_summary.csv` | `s1_q..s4_q` (sum) |
   | Domain distribution % | `B4_corpus_statistics.csv` | `domain_pct` |
   | Stage 1 vs 2 cluster shift | `C1_stage_stats.csv` | `cluster_pct_by_stage` |
   | Role × domain Chi² | `D1_chi_squared_results.md` | `chi2_stat`, `p_value`, `cramers_v` |
   | Topic Borda scores | `E1_topic_priority_table.csv` | `borda_score` |
   | IRR Cohen's Kappa | `B3_irr_report.md` | `kappa_per_dimension` |
   | Post-eval participants (15) | `paper/post_design_survey/summary_stats.csv` | `Total Participants` |
   | Mean SUS score | `paper/post_design_survey/summary_stats.csv` | `Mean SUS Score` |
   | Task completion % | `paper/post_design_survey/summary_stats.csv` | `Mean Task Completion` |
   | Adoption intent % | `paper/post_design_survey/summary_stats.csv` | `Q3 Yes (would adopt)` |

6. **Edit the .tex** with the Edit tool, one match at a time. Always include enough surrounding context in `old_string` to make the edit unique.

7. **Log every replacement** in `paper/PROGRESS.md` under a new "Stat refresh — YYYY-MM-DD" section:
   ```
   - line N: "87.3% completion" → "<real value>%" (from <csv>)
   - line M: "TBD-from-PhaseB" → "<real value>" (from <csv>)
   ```

8. **Re-grep** to confirm zero remaining placeholders:
   ```bash
   grep -c "TBD-from\|87\.3\|66\.4" "paper/research paper.tex"
   ```
   Should print `0`.

9. **Compile check:**
   ```bash
   cd paper && pdflatex -interaction=nonstopmode "research paper.tex" 2>&1 | tail -20
   ```

## Hard rules

- **Never invent a number.** If a CSV doesn't have the value, leave the TBD in place and report the gap.
- **Always cite the source CSV** in `PROGRESS.md` so the next reviewer can verify.
- **Two valid sources only:** Phase A-G outputs in `Survey analysis and results/outputs/tables/` and the post-deployment evaluation in `paper/post_design_survey/`. Anything not in those folders cannot be cited as a measurement.

## Output

End with:
```
[paper-stats] refreshed N stats from M tables. K placeholders remain (listed above).
```
