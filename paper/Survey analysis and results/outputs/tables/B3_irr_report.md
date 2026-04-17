# Phase B3 — Inter-Rater Reliability Report

**Date drafted:** 2026-04-11
**Sample:** `taxonomy/irr_samples.csv` (300 questions, seed 43)
**Coding contract:** `taxonomy/coding_guide.md`
**Target Cohen's Kappa per dimension:** ≥ 0.70 (substantial agreement)

## Status

This is a **gate-pending** deliverable. The 300-question IRR sample (`irr_samples.csv`) has been generated; two human coders are required to annotate it independently before this report can be finalised.

The sample CSV exposes the deterministic Phase B2 machine labels in `machine_*` columns alongside *empty* coder columns (`domain_l1`, `query_type_l2`, `intent`, `temporal`, `spatial`, `complexity`, `coder_notes`). Coders should fill the empty columns from scratch using only `coding_guide.md` — they should NOT consult the machine labels until after both coders submit.

## Workflow

1. Coder A copies `irr_samples.csv` → `irr_samples_coderA.csv`, fills the six coder columns, returns the file.
2. Coder B does the same → `irr_samples_coderB.csv`.
3. Reviewer runs:

   ```bash
   python "paper/Survey analysis and results/scripts/B3_irr_compute.py"
   ```

   The script computes Cohen's Kappa per dimension and prints disagreements for the discussion round.
4. Coders meet (~90 min) to reconcile disagreements; reconciled codes are written to `irr_samples_reconciled.csv`.
5. Final per-dimension Kappa values are appended to this file.

## Expected (planned) report skeleton

| Dimension | Cohen's Kappa | Agreement % | Notes |
|-----------|---------------|-------------|-------|
| domain_l1 | TBD | TBD | 20-class classification, expect Kappa 0.70-0.80 |
| query_type_l2 | TBD | TBD | 7-class classification, expect Kappa 0.65-0.75 |
| intent | TBD | TBD | 4-class classification, expect Kappa 0.70-0.85 |
| temporal | TBD | TBD | 4-class classification, expect Kappa 0.80-0.90 |
| spatial | TBD | TBD | 6-class classification, expect Kappa 0.70-0.85 |
| complexity | TBD | TBD | 3-class classification, expect Kappa 0.65-0.80 |

## Anticipated discussion topics

Based on the open questions logged in `taxonomy_v1.md`:

1. **DIAGNOSTIC vs ANOMALY** — when "is X too high?" should be coded as ANOMALY (out-of-range check) versus DIAGNOSTIC (cause-seeking).
2. **CAPABILITY scope** — should "can the building do X" and "can the system do X" share a single code?
3. **INFO_REQUEST vs WAYFINDING** — overlap when a query asks for hours of an amenity.

These three categories are the most likely sources of coder disagreement and will need explicit resolution before Phase B4 statistics are reported in the paper.

## Why this report is in `outputs/tables/`

Even though IRR isn't a numeric table, the paper's methodology section needs a single artefact to cite for the reliability gate. This `.md` file is that anchor. Once the kappa values are filled in, it will be referenced in §3.4 of `research paper.tex`.
