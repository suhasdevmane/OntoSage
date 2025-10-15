# Dev Directory

Action Plan Ref: #8 Repository Refactor

Holds experimental models, training scripts, notebooks, and prototype evaluation harnesses. Keeps the production surface (`/deploy`) clean.

## Planned Structure
- `models/` – (Git LFS pointers or symlinks) for checkpoints (T5, decider classifiers, optional LoRA adapters)
- `training/` – fine-tuning scripts for NL→SPARQL (T5) and summarizer LoRA
- `notebooks/` – exploratory data analysis & reasoning experiments
- `profiling/` – performance & latency measurement scripts
- `evaluation/` – portability runs, reasoning delta metrics, advanced SPARQL accuracy

## Data Hygiene
Large artifacts should be tracked with Git LFS or excluded (.gitignore) if regenerated deterministically from scripts.

## Repro Targets
Provide `dev/MAKE_STEPS.md` capturing deterministic recipe:
1. Generate synthetic buildings
2. Augment NL→SPARQL dataset (v2)
3. Train translator
4. Run portability harness
5. Produce manuscript tables
