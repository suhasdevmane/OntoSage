"""
Generate device instances TTL for Brick sensor types listed in sensors_list.txt.

Logic:
- Read sensors_list.txt and extract lines from 'Absolute_Humidity_Sensor' to
  'Zone_CO2_Level_Sensor' (inclusive), preserving order and de-duplicating.
- Read sensor_uuids.txt (CSV: name,uuid) to get ref:hasTimeseriesId per type.
- For each sensor type present in both lists, emit a device instance:
    bldg:<Type>.01 a brick:<Type> ;
        ref:hasExternalReference [ a ref:TimeseriesReference ;
            ref:hasTimeseriesId "<UUID>" ;
            ref:storedAt bldg:database1 ] .

Output file: bldg2_devices_from_sensor_types.ttl (in the same folder)

Notes:
- We do not modify class definitions here; this file only adds device instances.
- Brick class names like 'PM2.5_Level_Sensor' include a '.' and are valid in Turtle
  prefixed names. The example also uses a '.01' suffix.
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).parent
SENSORS_LIST = ROOT / "sensors_list.txt"
UUIDS_CSV = ROOT / "sensor_uuids.txt"
# Align with the committed devices file name
OUT_TTL = ROOT / "bldg2_new_devices_from_sensor_types.ttl"


def read_sensor_types_range(path: Path, start: str, end: str) -> list[str]:
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    try:
        i0 = next(i for i, v in enumerate(lines) if v == start)
    except StopIteration:
        raise RuntimeError(f"Start marker '{start}' not found in {path}")
    try:
        i1 = len(lines) - 1 - next(
            i for i, v in enumerate(reversed(lines)) if v == end
        )
    except StopIteration:
        raise RuntimeError(f"End marker '{end}' not found in {path}")
    # Inclusive slice
    subset = lines[i0 : i1 + 1]
    # De-duplicate while preserving order and skipping empties or stray partial tokens
    seen = set()
    result: list[str] = []
    for v in subset:
        if not v:
            continue
        # Skip building-specific sensor names (we only want types)
        if v.startswith("bldg2."):
            continue
        # Some lines like 'Coldest_'/'Warmest_' may appear; skip those partial tokens
        if v.endswith("_") and not v.endswith("_Sensor"):
            continue
        if v not in seen:
            seen.add(v)
            result.append(v)
    return result


def read_uuid_map(path: Path) -> dict[str, str]:
    m: dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            name = (row[0] or "").strip()
            uuid = (row[1] if len(row) > 1 else "").strip()
            if not name or not uuid:
                continue
            m[name] = uuid
    return m


def build_ttl(devices: list[tuple[str, str]]) -> str:
    prefixes = (
        "@prefix bldg: <http://buildsys.org/ontologies/bldg2#> .\n"
        "@prefix brick: <https://brickschema.org/schema/Brick#> .\n"
        "@prefix ref: <https://brickschema.org/schema/Brick/ref#> .\n"
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n\n"
    )
    blocks: list[str] = []
    for typ, uuid in devices:
        # Example: bldg:Absolute_Humidity_Sensor.01 a brick:Absolute_Humidity_Sensor ; ...
        block = (
            f"bldg:{typ}.01 a brick:{typ} ;\n"
            f"    ref:hasExternalReference [ a ref:TimeseriesReference ;\n"
            f"        ref:hasTimeseriesId \"{uuid}\" ;\n"
            f"        ref:storedAt bldg:database1 ] .\n\n"
        )
        blocks.append(block)
    return prefixes + "".join(blocks)


def main() -> int:
    types = read_sensor_types_range(
        SENSORS_LIST, "Absolute_Humidity_Sensor", "Zone_CO2_Level_Sensor"
    )
    uuid_map = read_uuid_map(UUIDS_CSV)
    devices: list[tuple[str, str]] = []
    missing: list[str] = []
    for t in types:
        uuid = uuid_map.get(t)
        if uuid:
            devices.append((t, uuid))
        else:
            missing.append(t)

    ttl = build_ttl(devices)
    OUT_TTL.write_text(ttl, encoding="utf-8")
    print(
        f"Wrote {len(devices)} device instances to {OUT_TTL.name}. Missing UUIDs for {len(missing)} types."
    )
    if missing:
        print("Missing:")
        for m in missing:
            print(f"  - {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
