# /paper-section — Draft or Revise a Single Paper Section

Draft or revise one section of `paper/research paper.tex` against the IMWUT sample paper structure.

## Usage

```
/paper-section <section-name>
```

Examples:
- `/paper-section abstract`
- `/paper-section introduction`
- `/paper-section related-work`
- `/paper-section methodology`
- `/paper-section findings-rq3`
- `/paper-section limitations`

## Steps

1. **Invoke the paper-writing skill.**

2. **Find the section** in `paper/PAPER_INDEX.md` — get the line range.

3. **Read only that line range** from `paper/research paper.tex`. Do NOT read the whole file.

4. **Read the corresponding sample-paper guidance** from `paper/CLAUDE.md` "Sample paper structure" section to know what this section should contain.

5. **Identify data dependencies.** For findings sections (4.x), check `paper/Survey analysis and results/outputs/tables/` for the relevant Phase outputs. If they don't exist yet, STOP and tell the user which phase to run first via the `survey-analysis` skill.

6. **Draft or revise** with these constraints:
   - Match sample-paper section length (abstracts ~300 words, intro ~1500 words, related work ~1500 words, findings ~3000 words)
   - Cite from `paper/references.bib` only — never invent BibTeX keys
   - Replace any `\textcolor{red}{TBD-from-PhaseX}` with real numbers if the table now exists
   - All numerical claims must trace to `outputs/tables/*.csv` (Phase A-G) or `paper/post_design_survey/summary_stats.csv` (15-person evaluation)
   - No emojis (acmart breaks on some unicode)
   - Use `\cite{}` for citations, not `\citep{}` (acmnumeric style)

7. **Write the revised section** with the Edit tool, targeting the exact line range.

8. **Update `paper/PAPER_INDEX.md`** if line counts shifted significantly (>20 lines).

9. **Update `paper/PROGRESS.md`**: mark the section as drafted/revised, log what changed in the "Section history" table.

10. **Compile check** (optional but recommended):
    ```bash
    cd paper && pdflatex -interaction=nonstopmode "research paper.tex" 2>&1 | grep -E "Error|Warning" | head -20
    ```

## What NOT to do

- Don't rewrite whole sections when only a paragraph needs work
- Don't read the 9 MB sample PDF — its structure is summarised in `paper/CLAUDE.md`
- Don't read OntoSage source code to describe the system — read `paper/CLAUDE.md` "System facts mirror"
- Don't add citations without confirming the bib key exists
- Don't fabricate participant counts, percentages, or task-completion stats

## Output

End with a one-line status: `[paper-section] revised <section> — N lines, M citations added, K stats refreshed`
