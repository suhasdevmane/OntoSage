"""Merge extended and schema NL->SPARQL datasets across multiple buildings (bldg1, bldg2, bldg3, ...).

Previous version merged just 4 files (bldg2/bldg3). This generalized version:

Scans one or more building directories for files matching:
    * *_dataset_extended.json   (extended dataset files)
    * *_schema_dataset.json     (schema/ontology dataset files)

All matching files (e.g., potentially 36 total across buildings & variants) are merged into:
    merged_extended_datasets.json
    merged_schema_datasets.json

Deduplication:
    - Key: (question, sparql)
    - First occurrence wins; subsequent duplicates skipped.

Normalization / Augmentation:
    - Adds 'source_building' (derived from filename token like 'bldg1', 'bldg2', etc.)
    - Ensures 'entities' always a list
    - Trims whitespace on 'question' and 'sparql'
    - Preserves 'category' and 'notes' if present

CLI Usage Examples:
    # Explicit directories
    python merge_buildings_datasets.py \
            --building-dirs Transformers/t5_base/training/bldg1 \
                                            Transformers/t5_base/training/bldg2 \
                                            Transformers/t5_base/training/bldg3 \
            --out-dir Transformers/t5_base/training

    # Backwards compatible flags (still supported) + auto include bldg1
    python merge_buildings_datasets.py --bldg1-dir training/bldg1 --bldg2-dir training/bldg2 --bldg3-dir training/bldg3

Exit codes:
    - Raises if no matching files discovered for a required category (extended/schema) unless --allow-missing-type used.

Note: PREFIX blocks are assumed omitted inside individual datasets; this tool does not modify SPARQL bodies.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import List, Dict, Tuple, Any, Iterable
import re

EXTENDED_SUFFIX = '_dataset_extended.json'
SCHEMA_SUFFIX = '_schema_dataset.json'


BUILDING_PATTERN = re.compile(r"\b(bldg[0-9]+)\b", re.IGNORECASE)


def derive_building_name(path: Path) -> str:
    """Attempt to infer building identifier from filename or parent directory.
    Falls back to 'unknown'.
    """
    fname = path.stem  # without .json
    m = BUILDING_PATTERN.search(fname)
    if m:
        return m.group(1).lower()
    # try parent
    for part in path.parts[::-1]:
        m2 = BUILDING_PATTERN.search(part)
        if m2:
            return m2.group(1).lower()
    return 'unknown'

def load_json(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required dataset file: {path}")
    with path.open('r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Dataset file {path} is not a JSON list")
    return data


def normalize_record(rec: Dict[str, Any], source_building: str) -> Dict[str, Any]:
    q = (rec.get('question') or '').strip()
    sp = (rec.get('sparql') or '').strip()
    ents = rec.get('entities')
    if ents is None:
        ents = []
    elif isinstance(ents, str):
        # attempt simple newline split
        ents = [e.strip() for e in ents.split('\n') if e.strip()]
    elif isinstance(ents, list):
        ents = [str(e).strip() for e in ents if str(e).strip()]
    else:
        ents = []

    category = rec.get('category') or ''
    notes = rec.get('notes') or ''

    return {
        'question': q,
        'entities': ents,
        'sparql': sp,
        'category': category,
        'notes': notes,
        'source_building': source_building
    }


def merge_sets(all_records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generic merge across arbitrary number of records from many buildings."""
    merged: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    for rec in all_records:
        key = (rec.get('question',''), rec.get('sparql',''))
        if key in seen:
            continue
        seen.add(key)
        merged.append(rec)
    return merged


def collect_expected_files(base_dirs: List[Path], suffix: str) -> List[Path]:
    """Collect exactly one expected file per building directory (building name inferred).
    Expected filename pattern: <building><suffix>, e.g. bldg1_dataset_extended.json
    Missing files are warned and skipped.
    """
    files: List[Path] = []
    for d in base_dirs:
        if not d.exists():
            print(f"[WARN] Missing building directory: {d}")
            continue
        # building id assumed to match folder name (bldg1, bldg2, ...)
        bname = d.name.lower()
        candidate = d / f"{bname}{suffix}"
        if candidate.exists():
            files.append(candidate)
        else:
            print(f"[WARN] Expected file not found: {candidate}")
    return files


def main():
    # No-argument execution: fixed directories relative to this script.
    script_dir = Path(__file__).parent
    dirs = [script_dir / 'bldg1', script_dir / 'bldg2', script_dir / 'bldg3']
    out_dir = script_dir  # save outputs alongside script
    extended_out = 'merged_extended_datasets.json'
    schema_out = 'merged_schema_datasets.json'

    ext_files = collect_expected_files(dirs, EXTENDED_SUFFIX)
    schema_files = collect_expected_files(dirs, SCHEMA_SUFFIX)

    if not ext_files:
        print(f"[ERROR] No extended dataset files found (expected 3: bldg1/2/3). Aborting.")
        return
    if not schema_files:
        print(f"[ERROR] No schema dataset files found (expected 3: bldg1/2/3). Aborting.")
        return

    all_ext: List[Dict[str, Any]] = []
    for p in ext_files:
        bname = derive_building_name(p)
        raw = load_json(p)
        for idx, r in enumerate(raw):
            nr = normalize_record(r, bname)
            nr['_meta'] = {
                'source_file': str(p),
                'source_index': idx,
                'building': bname,
                'type': 'extended'
            }
            nr['record_id'] = f"{bname}-ext-{idx}"
            all_ext.append(nr)
    all_schema: List[Dict[str, Any]] = []
    for p in schema_files:
        bname = derive_building_name(p)
        raw = load_json(p)
        for idx, r in enumerate(raw):
            nr = normalize_record(r, bname)
            nr['_meta'] = {
                'source_file': str(p),
                'source_index': idx,
                'building': bname,
                'type': 'schema'
            }
            nr['record_id'] = f"{bname}-sch-{idx}"
            all_schema.append(nr)

    # Keep raw copies (non-deduplicated)
    raw_ext = list(all_ext)
    raw_schema = list(all_schema)

    merged_ext = merge_sets(all_ext)
    merged_schema = merge_sets(all_schema)

    # Mark duplicates in raw sets (any record beyond first unique occurrence)
    def annotate_dups(raw: List[Dict[str, Any]], unique: List[Dict[str, Any]]):
        unique_keys = {(r['question'], r['sparql']): r for r in unique}
        seen_pairs = set()
        for rec in raw:
            key = (rec['question'], rec['sparql'])
            if key in seen_pairs:
                rec['_meta']['duplicate'] = True
            else:
                rec['_meta']['duplicate'] = False
                seen_pairs.add(key)
    annotate_dups(raw_ext, merged_ext)
    annotate_dups(raw_schema, merged_schema)

    # Stats
    def make_stats(raw: List[Dict[str, Any]], unique: List[Dict[str, Any]]):
        return {
            'input_total': len(raw),
            'unique_total': len(unique),
            'duplicates_removed': len(raw) - len(unique),
            'duplication_ratio': round(1 - (len(unique) / len(raw)) if raw else 0, 4)
        }
    stats = {
        'extended': make_stats(raw_ext, merged_ext),
        'schema': make_stats(raw_schema, merged_schema)
    }

    ext_out_path = out_dir / extended_out
    schema_out_path = out_dir / schema_out
    raw_ext_out_path = out_dir / ('raw_' + extended_out)
    raw_schema_out_path = out_dir / ('raw_' + schema_out)
    stats_path = out_dir / 'merge_stats.json'

    with ext_out_path.open('w', encoding='utf-8') as f:
        json.dump(merged_ext, f, ensure_ascii=False, indent=2)
    with schema_out_path.open('w', encoding='utf-8') as f:
        json.dump(merged_schema, f, ensure_ascii=False, indent=2)
    with raw_ext_out_path.open('w', encoding='utf-8') as f:
        json.dump(raw_ext, f, ensure_ascii=False, indent=2)
    with raw_schema_out_path.open('w', encoding='utf-8') as f:
        json.dump(raw_schema, f, ensure_ascii=False, indent=2)
    with stats_path.open('w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    def summarize(files: List[Path], merged: List[Dict[str, Any]], label: str):
        counts: Dict[str, int] = {}
        for p in files:
            b = derive_building_name(p)
            counts[b] = counts.get(b, 0) + len(load_json(p))
        print(f"Merged {label}:")
        for b, c in sorted(counts.items()):
            print(f"  {b}: {c}")
        print(f"  -> Unique merged {label}: {len(merged)}")

    summarize(ext_files, merged_ext, 'extended')
    summarize(schema_files, merged_schema, 'schema')
    print("Stats summary:")
    print(json.dumps(stats, indent=2))
    print("Outputs written:")
    print(f"  Deduplicated extended: {ext_out_path}")
    print(f"  Deduplicated schema:   {schema_out_path}")
    print(f"  Raw extended:          {raw_ext_out_path}")
    print(f"  Raw schema:            {raw_schema_out_path}")
    print(f"  Stats:                 {stats_path}")

if __name__ == '__main__':
    main()
