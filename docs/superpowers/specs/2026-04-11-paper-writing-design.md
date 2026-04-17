# OntoSage++ Research Paper Writing Workflow — Design Spec

**Date:** 2026-04-11
**Author:** Suhas Devmane (with Claude assistance)
**Status:** Approved
**Target venue:** Proc. ACM IMWUT (Interactive, Mobile, Wearable and Ubiquitous Technologies)
**Sample paper to mirror:** Guo et al. 2018, "Crowd-AI Camera Sensing in the Real World" (20 pp, `acmsmall`)

---

## Goal

Produce a journal-grade IMWUT paper for OntoSage++ that:
1. Mirrors the section structure of an already-published paper at the same venue (de-risking review)
2. Cites only real numbers from a rigorous survey corpus analysis (no fabricated stats)
3. Can be re-entered by future Claude sessions in **<10k tokens of bootstrap context**, by isolating paper work from OntoSage source

The paper builds on two studies: (1) a Cardiff University SREC-approved Amazon MTurk pre-design survey (5,127 questions, ~60 participants, 50 topic rankings) that informed OntoSage++ requirements, and (2) a 15-person post-deployment evaluation of the implemented system (6 Student/Researcher, 4 IT/Operator, 5 Visitor/Guest) covered by the same SREC approval and stored in `paper/post_design_survey/`.

---

## Background

The author began drafting `paper/research paper.tex` (1,045 lines) before the survey analysis was run. The draft contains:
- A solid technical narrative for OntoSage++
- Real survey design + ethics framing
- **Fabricated headline statistics** (87.3% completion, 66.4% time reduction, 90% effort reduction, 42 participants, 68%/80% Stage 1 vs 2 cluster split) which must be removed before submission

The survey raw data exists in `paper/Survey analysis and results/inputs/`:
- `questions_by_user.csv` (5,127 rows, 4 stages, role labels)
- `topic_rankings.csv` (50 users × 20 topics)
- `question_rankings.csv` (413 within-topic preferences)

A complete `ANALYSIS_METHODOLOGY.md` (Phases A-G) prescribes how to convert raw data into journal-grade evidence, but no analysis script has been written yet.

---

## Approach: Three-track parallel workstreams

### Track 1: Survey analysis pipeline (the evidence)

Execute Phases A-G of `ANALYSIS_METHODOLOGY.md` end-to-end. Each phase produces tables in `outputs/tables/` and figures in `outputs/figures/` that the paper will cite. Phases must run in order (B depends on A, C-F depend on B, G synthesises B-F).

**Owned by:** `survey-analyst` sub-agent + `survey-analysis` skill

**Outputs:**
- `outputs/tables/A2_demographics_table.csv`
- `outputs/tables/B4_corpus_statistics.csv`
- `outputs/tables/C1_stage_stats.csv` + `C3_novelty_analysis.csv`
- `outputs/tables/D1_chi_squared_results.md` + `D3_user_personas.md`
- `outputs/tables/E1_topic_priority_table.csv`
- `outputs/tables/F1_question_preferences_by_topic.csv`
- `outputs/tables/G3_capability_matrix.csv` + `G4_gap_analysis.md`
- ~14 figures (PNG @ 300dpi + PDF for paper)
- `corpus/classified_corpus.csv` (the deliverable corpus, anonymised)

### Track 2: Paper restructure to match sample

Re-skeleton `research paper.tex` section by section to mirror the Guo et al. structure. Replace fabricated stats with Track 1 outputs as soon as each phase completes. The Phase 2 evaluation section cites the 15-person post-deployment study from `paper/post_design_survey/`.

**Owned by:** `paper-agent` sub-agent + `paper-writing` skill + `/paper-section`, `/paper-stats` commands

**Constraints:**
- Match sample's section pacing (abstract 250-300 words, intro 1500-2000, related work 1200-1800, system 2500-3500, findings 3000-4000)
- Citation style: numeric (`acmnumeric`)
- No emojis
- All participant references anonymised (`P01..P60` for the corpus study, `P_pd_01..P_pd_15` for the post-deployment evaluation)
- Ethics statement: SREC COMSC/Ethics/2025/044b (Cardiff)

### Track 3: `.claude/` paper support (token efficiency)

Create scoped agents, skills, commands, and a paper-local CLAUDE.md so future sessions can work on the paper without re-exploring the OntoSage codebase. Target: bootstrap context for any paper-related task ≤10k tokens.

**Files created (Track 3):**
- `.claude/agents/paper-agent.md` — read-only scope: `paper/`
- `.claude/agents/survey-analyst.md` — read-only scope: `Survey analysis and results/`
- `.claude/skills/paper-writing.md` — runbook for editing the .tex
- `.claude/skills/survey-analysis.md` — runbook for executing Phases A-G
- `.claude/commands/paper-section.md` — `/paper-section <name>`
- `.claude/commands/paper-stats.md` — `/paper-stats`
- `paper/CLAUDE.md` — paper workspace context (sample structure summary, system facts mirror, fabricated-stat list)
- `paper/PAPER_INDEX.md` — section→line map for the .tex draft
- `paper/PROGRESS.md` — tracking checklist (phases A-G, paper sections, stat-refresh log)

---

## Decomposition rationale

| Boundary | Why |
|----------|-----|
| Two sub-agents (paper vs survey-analyst) | Survey analysis touches CSVs + Python scripts; paper writing touches .tex + .bib. They have non-overlapping file scopes and benefit from staying isolated. |
| Two skills, not one | Paper editing and statistical analysis use different tool sets and different verification gates. Combining them would dilute both runbooks. |
| Two slash commands | `/paper-section` is a high-frequency surgical edit; `/paper-stats` is a periodic full-sweep refresh. Different cadence, different scope. |
| `paper/CLAUDE.md` (workspace-local) | When user `cd paper`, the loaded context shouldn't include the full OntoSage architecture index. Workspace-local CLAUDE.md gives a focused brief. |
| `PAPER_INDEX.md` separate from `PROGRESS.md` | Index is structural (line ranges, rarely changes), Progress is temporal (status, frequently updated). Splitting reduces edit conflicts. |
| Tracks 1+2 deferred to plan execution | Phases B-G need real compute (LLM batch calls, sentence embeddings, manual coding). Cannot run inside this brainstorming session. |

---

## Data flow

```
inputs/*.csv  ──┐
                │
                ▼
       ┌──────────────────┐
       │ survey-analyst   │   (Phases A-G)
       │ + survey-analysis│
       │   skill          │
       └────────┬─────────┘
                │
                ▼
   outputs/tables/*.csv
   outputs/figures/*.{png,pdf}
   corpus/classified_corpus.csv
                │
                ▼
       ┌──────────────────┐
       │ paper-agent      │   (cite + revise)
       │ + paper-writing  │
       │   skill          │
       │ + /paper-section │
       │ + /paper-stats   │
       └────────┬─────────┘
                │
                ▼
       research paper.tex  →  pdflatex  →  IMWUT submission
```

---

## Components — what each does + how to use it + what it depends on

### `paper-agent.md` (sub-agent)
- **Does:** Reads paper/, references.bib, and survey output CSVs. Edits the .tex.
- **Use via:** `Agent` tool with `subagent_type=paper-agent` (when project surfaces it), or directly invoke `paper-writing` skill in the main session.
- **Depends on:** `paper/CLAUDE.md`, `paper/PAPER_INDEX.md`, `outputs/tables/`.
- **Hard constraint:** Never reads `orchestrator/` source.

### `survey-analyst.md` (sub-agent)
- **Does:** Reads survey CSVs, writes Python scripts, runs them, produces tables/figures.
- **Use via:** Direct `survey-analysis` skill invocation.
- **Depends on:** `inputs/*.csv`, `ANALYSIS_METHODOLOGY.md`.
- **Hard constraint:** Never reads `paper/research paper.tex` or OntoSage source.

### `paper-writing.md` (skill)
- **Does:** Step-by-step runbook for revising sections, refreshing stats, adding figures, compiling.
- **Use when:** Any change to `research paper.tex`.
- **Verification gates:** every section change updates `PROGRESS.md`; every stat refresh logs the source CSV.

### `survey-analysis.md` (skill)
- **Does:** Step-by-step runbook for Phases A-G with reproducibility rules (seeds, anonymisation, effect sizes).
- **Use when:** Running any phase, refreshing analysis.
- **Verification gates:** every phase appends a key finding to `corpus/corpus_summary_stats.md` and ticks PROGRESS.md.

### `/paper-section <name>` (command)
- **Does:** Drafts/revises one section against the sample structure.
- **Workflow:** lookup PAPER_INDEX → read line range → check data dependencies → edit → update PROGRESS.

### `/paper-stats` (command)
- **Does:** Sweeps every fabricated number and TBD marker in the .tex, replaces with real values from `outputs/tables/`.
- **Workflow:** grep → match to CSV → Edit → log → re-grep to verify zero remaining.

### `paper/CLAUDE.md`
- **Does:** Workspace-local context: mission, target venue, sample paper structure summary, fabricated-stat hit list, OntoSage system facts mirror, do-not-load list, compile command.
- **Replaces:** Re-reading the 9 MB sample PDF and the OntoSage codebase index.

### `paper/PAPER_INDEX.md`
- **Does:** Section/subsection → line-range table for `research paper.tex`. Includes figures + tables registry.
- **Replaces:** Reading the full 1,045-line .tex to find a section.

### `paper/PROGRESS.md`
- **Does:** Live tracker for Phase A-G status, paper section status, stat-refresh log, fabricated-stat checklist, submission checklist.
- **Replaces:** Re-discovering progress at session start.

---

## Tradeoffs accepted

- **Plan-only execution this session.** Phases B-G need ~6 sessions of compute (LLM batch + manual coding + statistical runs) and cannot run inside this planning session. The plan is delivered for later execution.
- **Two-agent isolation costs context duplication.** The system facts mirror in `paper/CLAUDE.md` duplicates info from `../CLAUDE.md`. This is an intentional cache: the duplication saves the cost of re-reading `../CLAUDE.md` in every paper session.
- **Manual taxonomy step is unavoidable.** Phase B1 (taxonomy development from 200 sample questions) is the intellectual core and cannot be fully automated. The user must do this themselves or verify the LLM-generated draft.

---

## Out of scope

- Running Phases A-G in this session (delivered as plan instead)
- Writing the final paper text (only restructure + stat refresh; final wording left for human + future sessions)
- Translation/localisation
- Reviewer rebuttal preparation

---

## Success criteria

A future Claude session can:
1. Open `paper/CLAUDE.md` + `PROGRESS.md` + `PAPER_INDEX.md` (≤10k tokens) and immediately know what to do
2. Run `/paper-section findings-rq3` and complete it without reading the whole .tex
3. Run `/paper-stats` and replace every fabricated number with real values, logging each replacement
4. Never trigger a deep exploration of OntoSage source code while writing the paper

The user can:
1. Compile the paper to PDF after Phase A completes (using real participant counts)
2. Hand off to a co-author with `PROGRESS.md` as the only briefing document
3. Cite the 15-person post-deployment evaluation directly from `paper/post_design_survey/summary_stats.csv`
