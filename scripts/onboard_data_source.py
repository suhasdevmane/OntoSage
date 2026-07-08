#!/usr/bin/env python3
"""Canonical 'add a sensor data source' pipeline (Workstream B5).

THE standard way to bring telemetry into OntoSage. One source of truth, one flow:

  1. Generate Brick points (UUID + label + hasLocation + unit + the standard
     ref:TimeseriesReference{hasTimeseriesId, storedAt}) into an input/ TTL —
     scripts/generate_timeseries_extension.py.
  2. Create NARROW per-modality MySQL tables (uuid, datetime, value) and load the
     readings keyed by UUID — scripts/load_timeseries_to_db.py.
  3. GraphDB ingestion is automatic: the orchestrator's startup loader
     (run_idempotent_uploads) PUTs every input/*.ttl into a per-file named graph
     idempotently. **Do NOT upload the TTL by hand** — that creates duplicate
     triples across graphs. Just restart the orchestrator.

Run this INSIDE the orchestrator container (where MySQL host.docker.internal:3306
resolves with the right grants):

    docker cp scripts/onboard_data_source.py ontosage-orchestrator:/tmp/
    docker cp scripts/load_timeseries_to_db.py ontosage-orchestrator:/tmp/
    docker exec ontosage-orchestrator python /tmp/onboard_data_source.py
    docker restart ontosage-orchestrator      # startup loader ingests the TTL

To add a new modality: append a row to SENSORS in generate_timeseries_extension.py
(csv, value_col, entity local name, Brick class, QUDT unit, narrow table, location,
label), register the table in input/database_registry.yaml + input/building.yaml
storage filter, then run this script. Nothing else changes — the standard
SPARQL->narrow-SQL pipeline serves the new modality automatically.

REMEMBER: input/ is metadata/config only. Raw CSV sensor readings do not belong in
input/ — they are a one-time migration source and live in the database thereafter.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def _run(script: str) -> None:
    print(f"\n=== {script} ===", flush=True)
    runpy.run_path(str(SCRIPTS / script), run_name="__main__")


def main() -> int:
    _run("generate_timeseries_extension.py")  # -> input/*.ttl + uuid map
    try:
        _run("load_timeseries_to_db.py")  # -> narrow tables + rows (needs MySQL)
    except Exception as e:  # pragma: no cover - environment dependent
        print(f"\n[onboard] DB load step failed (run inside the container): {e}", file=sys.stderr)
        return 1
    print(
        "\n[onboard] Done. Restart the orchestrator so the startup loader ingests the "
        "TTL into GraphDB:\n    docker restart ontosage-orchestrator"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
