import json
import csv
import argparse
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Any

"""
Compute stratified metrics for reasoning classes C1..C4.

Expected input: a JSONL or JSON file with a list of records. Each record should contain:
{
  "id": str,
  "class": "C1"|"C2"|"C3"|"C4",
  "pred_sparql": str,
  "gold_sparql": str,
  "sparql_parsable": bool,              # whether pred_sparql parsed
  "exec_success": bool,                 # whether execution produced expected-type result
  "pred_entities": ["iri_or_uuid", ...],
  "gold_entities": ["iri_or_uuid", ...],
  "semantic_alignment": bool,          # human-judged or heuristic
  "microservice_success": bool|null    # only for C4, else null/omitted
}

Output: CSV with columns: class, SV, EX, EG_F1, SI, MS
"""

def micro_f1(pred: List[str], gold: List[str]) -> float:
    ps = Counter(pred)
    gs = Counter(gold)
    # true positives: intersection sum of counts
    tp = sum((ps & gs).values())
    fp = sum((ps - gs).values())
    fn = sum((gs - ps).values())
    if tp == 0 and fp == 0 and fn == 0:
        return 1.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def load_records(path: str) -> List[Dict[str, Any]]:
    if path.endswith('.jsonl'):
        with open(path, 'r', encoding='utf-8') as f:
            return [json.loads(line) for line in f if line.strip()]
    elif path.endswith('.json'):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'records' in data:
                return data['records']
            if isinstance(data, list):
                return data
            raise ValueError('Unsupported JSON structure')
    else:
        raise ValueError('Unsupported file extension (use .jsonl or .json)')


def compute_metrics(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        c = r.get('class')
        if c in {'C1', 'C2', 'C3', 'C4'}:
            buckets[c].append(r)
    out: Dict[str, Dict[str, float]] = {}
    for cls, rs in buckets.items():
        n = len(rs)
        if n == 0:
            continue
        sv = sum(1 for r in rs if r.get('sparql_parsable')) / n
        ex = sum(1 for r in rs if r.get('exec_success')) / n
        eg_f1_vals = [micro_f1(r.get('pred_entities') or [], r.get('gold_entities') or []) for r in rs]
        eg = sum(eg_f1_vals) / n
        si = sum(1 for r in rs if r.get('semantic_alignment')) / n
        ms_vals = [r.get('microservice_success') for r in rs if r.get('microservice_success') is not None]
        ms = (sum(1 for v in ms_vals if v) / len(ms_vals)) if (cls == 'C4' and len(ms_vals) > 0) else None
        out[cls] = {
            'SV': sv * 100,
            'EX': ex * 100,
            'EG_F1': eg,
            'SI': si * 100,
            'MS': (ms * 100) if ms is not None else None,
        }
    return out


def main():
    parser = argparse.ArgumentParser(description='Compute reasoning class metrics (C1..C4).')
    parser.add_argument('--input', required=True, help='Path to JSONL/JSON evaluation file')
    parser.add_argument('--output', required=True, help='Path to CSV output')
    args = parser.parse_args()

    records = load_records(args.input)
    metrics = compute_metrics(records)

    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Class', 'SV', 'EX', 'EG_F1', 'SI', 'MS'])
        for cls in ['C1', 'C2', 'C3', 'C4']:
            m = metrics.get(cls, {})
            sv = f"{m.get('SV', 0):.0f}"
            ex = f"{m.get('EX', 0):.0f}"
            eg = f"{m.get('EG_F1', 0):.2f}"
            si = f"{m.get('SI', 0):.0f}"
            ms_val = m.get('MS')
            ms = f"{ms_val:.0f}" if ms_val is not None else 'n/a'
            writer.writerow([cls, sv, ex, eg, si, ms])

    print(f"Wrote metrics to {args.output}")


if __name__ == '__main__':
    main()
