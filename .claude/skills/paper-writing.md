---
name: paper-writing
description: Use when revising sections of paper/research paper.tex, checking a statistic against its source, regenerating a table or figure, or building the PDF. Covers the OntoSage IMWUT submission.
---

# Paper writing runbook — OntoSage, IMWUT

Read `.claude/rules/imwut-boundaries.md` before drafting or editing prose. It is the style
contract and it takes precedence over general writing advice.

## Start here

1. `paper/PROGRESS.md` — what changed, in what order, and what is still owed
2. `paper/PAPER_INDEX.md` — section-to-line map
3. Read only the line range you will edit. The file is 2,100+ lines.

## Current state (verified 2026-09-24)

- **48 pages**, 0 errors, 0 undefined references
- **13,775 words** of core prose against IMWUT's recommended 8,000–10,000 — about 3,300 over
- **117 `\ph{xxx}` placeholders** awaiting the N=30 deployment study; 30 itself is real
- 19 tables, 12 figures

## Section map

| § | Title | Source of its numbers |
|---|---|---|
| 1 | Introduction | — |
| 2 | Related Work | `references.bib` |
| 3 | Phase 1: Understanding Stakeholder Intentions (14 subsections, pp. 5–20) | `Survey analysis and results/outputs/tables/` |
| 3.1 | Study Design: Staged Prompting | `SURVEY_PROTOCOL.md` |
| 3.3 | Analysis: Taxonomy Development | `B3_irr_report.md` |
| 3.5 | Stage Comparison: The Context Gap | `C1_stage_stats.csv`, `Z_domain_by_stage.csv`, `Z_intent_by_stage.csv` |
| 3.6 | Complexity Preference by Persona | `F2_complexity_preference_by_persona.csv` |
| 3.8 | Aggregate Topic Priorities | `E1_topic_priority_table.csv`, `E1_kendalls_w.md` |
| 3.10 | Question Complexity Preferences | `F1_overall_level_preference.csv` |
| 3.13 | What Stakeholders Said Would Make Them Trust It | `Z_stage5_vision_themes.csv` |
| 3.14 | Extending Coverage Beyond the Sampled Personas | `generated/catalogue-roles.csv` |
| 4 | OntoSage (13 subsections) | live graph; `generated/building-characteristics.csv` |
| 5 | Evaluation Deployment | `post_design_survey/responses.csv` (pilot; N=30 pending) |
| 6 | Results | `H*_*.csv`, `H10_statistical_tests.csv` |
| 7 | Discussion | — |
| 8 | Limitations and Future Work | — |
| 9 | Conclusion | — |
| A–I | Appendices, after the references | as above |

## The rule that matters most

**Every number in the paper traces to a file that produced it.** Nine defect classes have been
found in this paper and all nine were numeric. Two chi-square values were stale against
`H10_statistical_tests.csv`; all 24 cells of one table panel were stale; four figure counts
were wrong; one table row silently merged cells. None was visible on the page.

```bash
cd paper
python verify_claims.py                  # every table cell vs its source
python verify_claims.py --prose-suspects # claims that match NO source anywhere
python verify_claims.py --null-test      # why naive value-matching does not work
```

A claim that fails `--prose-suspects` is almost certainly stale: it failed the most permissive
test available. A claim that *passes* proves nothing — that pool accepts invented numbers 97%
of the time, which is exactly why the tool reports its own false-match rate.

## Regenerating tables and figures

```bash
cd paper
python scripts/gen_tables.py --list          # which tables are generated, which are authored
python scripts/gen_tables.py --all
python scripts/live_building_facts.py        # Building A vs the LIVE graph (needs the stack up)
python scripts/count_records.py              # the 41 registers and their 1,467 rows
cd "Survey analysis and results"
python scripts/Z_paper_derived_tables.py     # panels the phase scripts never emitted
python scripts/Z_stage5_vision_analysis.py   # Stage 5 open responses
```

Six of eight formerly hand-authored tables now have generators. `tab:guards` and
`tab:adaptation-components` remain authored — nothing checks them, so read them by hand.

**Building A facts must come from the live graph, not from a regex over `input/*.ttl`.** The
regex cannot see the loaded TBox or any inference and gave wrong answers for five of six
counts. Start the stack (`docker compose up -d`), then run `live_building_facts.py`.

## Figures

`figures/*.xml` is the source of record; the `.pdf` is an export. Correcting a number in the
paper without correcting the XML means the next re-export reverts it.

```bash
cd paper/figures
python check_figure_integrity.py          # overlapping boxes, dangling edges, value drift
python sync_diagram_values.py             # re-apply measured values
python restack_columns.py <file>.xml      # re-size boxes to their text after editing
python fix_footer.py                      # re-pin the full-width footer
"/c/Program Files/draw.io/draw.io.exe" --no-sandbox --export --format pdf --crop \
    --output fig_name.pdf fig_name.xml
```

A figure fitted to `\textwidth` renders its 12 pt type at `12 × 395.82 / width` points. At
1,130 units wide that is about 4 pt. **Height does not affect this** — only width does.

## Building

```bash
cd paper
./build.sh          # one pass, for prose edits
./build.sh full     # three passes + bibtex, after any label, ref, cite or float change
```

`pdflatex` exits 0 on errors it recovered from and still writes a PDF, so read the script's
verdict. `pdflatex … | tail` reports *tail's* exit code, not LaTeX's.

## Pitfalls

| Pitfall | What happens |
|---|---|
| Patching the `.tex` through a shell heredoc | Escapes arrive mangled. `\b` became a literal BACKSPACE and matched nothing; `\texttt` became a TAB; `\\` became `\` and merged table rows. **Write the script to a file and run it.** |
| A script that prints "ok" then raises | It exits before writing. Two edit batches were silently lost this way. Write once, then **re-read from disk to prove the change landed**. |
| Editing the `.tex` during a build | LaTeX reads as it goes; errors point at lines that no longer exist. |
| Replacing `\ph{xxx}` with a plausible value | Turns a pending value into an apparent measurement. |
| Trusting a regex over Turtle for graph facts | It cannot see inference. GraphDB is the authority. |
| Reading the 9 MB sample PDF | The structure summary is in `paper/CLAUDE.md`. |
| Citing without a bib entry | `grep -n "<key>" paper/references.bib` first. |

## Handing off

New analysis belongs in a phase script under `Survey analysis and results/scripts/`, not
computed inline and pasted. Add it there, regenerate the table, then cite the result here —
that is what keeps `verify_claims.py` able to check it.
