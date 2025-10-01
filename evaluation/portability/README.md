# Cross-Building Portability Evaluation

This folder provides a small, reproducible harness to demonstrate building-agnostic queries across multiple Brick models (your Abacws testbed plus two synthetic examples). It is decoupled from Docker/Jena so you can run it locally with just Python.

What you get here:
- Two tiny synthetic Brick graphs: a multi-floor office and a single-floor data center (see `buildings/`).
- A set of representative, building-agnostic SPARQL queries (see `queries/`).
- A Python runner that executes every query on every building model and writes results to CSV (see `run_eval.py`).

You can lift the same queries into Fuseki later; the point here is to lock down portable query shapes first.

## Install and run

- Python 3.9+ recommended. Install a single dependency:

```pwsh
pip install rdflib
```

- Execute the runner from the repo root or this folder:

```pwsh
python evaluation/portability/run_eval.py
```

- Outputs go to `evaluation/portability/results/` as CSV files, one per query, with all buildings combined (a `building` column indicates the source model).

## Queries included

- co2_exceeds_setpoint.rq
  - Question: Which zones currently exceed their CO₂ set-point?
  - Assumes each Zone has both a CO₂ sensor and a CO₂ setpoint point with a numeric value.
- ahus_on_top_floor.rq
  - Question: List all air handling units on the top floor.
  - Assumes Floors have an `ex:floorNumber` integer so “top floor” is the max.
- zones_per_floor.rq
  - Question: How many zones per floor?

All queries use Brick classes/properties to remain building-agnostic. Minor helper properties are namespaced under `ex:` to keep the Brick graph small and readable.

## Add your own buildings and queries

- Add a new TTL file under `buildings/` (keep it concise and Brick-compliant where possible).
- Put new queries under `queries/` with a `.rq` extension. They will be auto-discovered.

## Manuscript integration

- Create a subsection “Cross-Building Portability Evaluation” and include:
  - A short description of each building model (floors, zones, equipment).
  - A table per representative question listing the results across buildings (use the CSVs produced here).
  - A brief note on query portability: same query, no changes to the NLU or NL→SPARQL pipeline.

## Notes

- This harness uses rdflib to avoid standing up Fuseki; once stable, load the same TTLs into Fuseki and run the same `.rq` queries there as a final integration step.
- Keep large/generated datasets out of Git; TTLs here are intentionally tiny.
