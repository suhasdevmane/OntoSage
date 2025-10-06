#!/usr/bin/env python
"""
Cross-Building Portability Evaluation Harness
=============================================
Action Plan Ref: #7

Loads multiple building ontologies (real + synthetic), optionally applies reasoning,
executes a canonical NL query set via NL2SPARQL + Fuseki or offline mapping, and
computes portability metrics.

Current Status: Scaffold / skeleton. Fill in integration points where marked.

Planned Metrics:
- translation_exact: proportion of NL queries whose generated SPARQL exactly matches a gold template (optional)
- execution_success: SPARQL executes without error & returns bindings when expected
- semantic_shape_consistency: result shape (variable set) matches reference across buildings
- reasoning_delta: difference in success when reasoning enabled vs disabled

Output:
- JSON metrics file per run
- Markdown summary table (optionally auto-injected into manuscript assets)
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

try:
    from rdflib import Graph
except ImportError:
    print("rdflib required (pip install rdflib)", file=sys.stderr)
    raise

# Optional: pyshacl for reasoning or owlrl
try:
    from owlrl import DeductiveClosure, OWLRL_Semantics
    OWL_AVAILABLE = True
except ImportError:
    OWL_AVAILABLE = False

@dataclass
class BuildingConfig:
    name: str
    ttl_path: str
    fuseki_dataset: Optional[str] = None  # Future: remote dataset name

@dataclass
class QueryCase:
    nl: str
    expect_nonempty: bool = True
    gold_sparql: Optional[str] = None  # if available for exact match scoring
    reasoning_required: bool = False

# Canonical NL queries (placeholder examples)
CANONICAL_QUERIES: List[QueryCase] = [
    QueryCase(nl="List all temperature sensors", expect_nonempty=True),
    QueryCase(nl="Average CO2 per floor last month", expect_nonempty=False, reasoning_required=True),
    QueryCase(nl="Rooms having both temperature and humidity sensors", expect_nonempty=True),
    QueryCase(nl="Which rooms exceed CO2 threshold?", expect_nonempty=False),
    QueryCase(nl="Count distinct sensor types", expect_nonempty=True),
]

# Placeholder: integrate actual NL2SPARQL translation

def translate_nl_to_sparql(question: str) -> str:
    # TODO integrate with running nl2sparql service or local model call
    # For now, return a dummy SPARQL selecting ?s
    return "SELECT ?s WHERE { ?s a <https://brickschema.org/schema/Brick#Sensor> } LIMIT 10"

# Placeholder: execute SPARQL (local RDFLib version)

def execute_sparql_local(g: Graph, sparql: str) -> Tuple[bool, List[Dict[str, Any]]]:
    try:
        qres = g.query(sparql)
        rows = []
        for row in qres:
            # Map variable names to str values
            binding = {var: str(row[var]) for var in row.labels}
            rows.append(binding)
        return True, rows
    except Exception as e:
        return False, []

# Reasoning toggle

def apply_reasoning_if_requested(g: Graph, enable: bool) -> Graph:
    if not enable:
        return g
    if not OWL_AVAILABLE:
        print("OWL RL package not installed; skipping reasoning", file=sys.stderr)
        return g
    closure = DeductiveClosure(OWLRL_Semantics, rdfs_closure=True, owl_closure=True)
    closure.expand(g)
    return g

# Metrics accumulation

def eval_building(building: BuildingConfig, queries: List[QueryCase], reasoning: bool) -> Dict[str, Any]:
    g = Graph().parse(building.ttl_path, format='turtle')
    g = apply_reasoning_if_requested(g, reasoning)
    total = len(queries)
    translation_exact = 0
    execution_success = 0
    nonempty_hits = 0
    shape_consistency: Dict[str, int] = {}

    per_query: List[Dict[str, Any]] = []

    for qc in queries:
        sparql = translate_nl_to_sparql(qc.nl)
        exact = int(qc.gold_sparql is not None and sparql.strip() == qc.gold_sparql.strip())
        ok, rows = execute_sparql_local(g, sparql)
        execution_success += int(ok)
        nonempty = int(bool(rows))
        if qc.expect_nonempty:
            nonempty_hits += nonempty
        # result shape variables
        shape_key = ','.join(sorted(rows[0].keys())) if rows else 'EMPTY'
        shape_consistency[shape_key] = shape_consistency.get(shape_key, 0) + 1
        per_query.append({
            "question": qc.nl,
            "sparql": sparql,
            "executed": ok,
            "row_count": len(rows),
            "nonempty": bool(rows),
            "exact_translation": bool(exact),
            "reasoning_required": qc.reasoning_required,
        })
        translation_exact += exact

    metrics = {
        "building": building.name,
        "reasoning": reasoning,
        "counts": {
            "total_queries": total,
            "translation_exact": translation_exact,
            "execution_success": execution_success,
            "nonempty_hits": nonempty_hits,
        },
        "rates": {
            "translation_exact": translation_exact / total if total else 0.0,
            "execution_success": execution_success / total if total else 0.0,
            "nonempty_hit_rate": nonempty_hits / total if total else 0.0,
        },
        "shape_distribution": shape_consistency,
        "queries": per_query,
    }
    return metrics


def main():
    ap = argparse.ArgumentParser(description="Run cross-building portability evaluation (scaffold)")
    ap.add_argument('--buildings', nargs='+', help='List of building name=path/to.ttl', required=True)
    ap.add_argument('--out', required=True, help='Output JSON path')
    ap.add_argument('--reasoning', action='store_true', help='Enable OWL RL reasoning')
    args = ap.parse_args()

    buildings: List[BuildingConfig] = []
    for b in args.buildings:
        if '=' not in b:
            print(f"Invalid building spec '{b}' (expected name=ttlpath)", file=sys.stderr)
            sys.exit(1)
        name, path = b.split('=', 1)
        if not os.path.exists(path):
            print(f"TTL not found: {path}", file=sys.stderr)
            sys.exit(1)
        buildings.append(BuildingConfig(name=name, ttl_path=path))

    all_results = []
    for bcfg in buildings:
        print(f"Evaluating {bcfg.name} reasoning={args.reasoning}")
        metrics = eval_building(bcfg, CANONICAL_QUERIES, reasoning=args.reasoning)
        all_results.append(metrics)

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump({"results": all_results}, f, indent=2)
    print(f"Wrote portability metrics: {args.out}")
    # Example run (after generating synthetic buildings):
    #   python scripts/run_portability_eval.py \
    #       --buildings office=datasets/buildings/bldg_office8/bldg_office8.ttl lab=datasets/buildings/lab1/lab1.ttl \
    #       --out eval/portability_office_lab.json --reasoning

if __name__ == '__main__':
    main()
