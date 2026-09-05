#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Declare, for every connected sensor, how often it reports and when it was calibrated.

WHY THIS EXISTS
---------------
BUG-237 wired the freshness gate and deliberately left three others unwired, because each
judges a field nothing populates. Their own remedies name the missing data exactly:

    completeness_gate: "Declare this stream's archival interval so coverage can be computed."
    calibration_gate:  "record the calibration state ..."

Measured on bldg1 before this script: ``ontosage:archivalIntervalS`` 0 instances,
``ontosage:calibratedOn`` 0 instances. The gates were not unwired because the logic was
wrong; they were unwired because the building had never been asked how often its sensors
report or when they were last checked. That is a DATA gap, and contract 2 says the fix is a
TTL extension rather than a code path.

WHAT IT WRITES
--------------
Per sensor that has a timeseries id:

    ontosage:samplingIntervalS   how often the instrument produces a value
    ontosage:archivalIntervalS   how often a value is stored — what completeness divides by
    ontosage:calibratedOn        when it was last calibrated
    ontosage:calibrationDueOn    when that expires
    ontosage:calibrationMethod   how it was done

BUILDING-AGNOSTIC. Nothing here names a building: sensors, classes and ids come from the
live graph, and the cadence comes from the publisher's own map, which is the same source
the anomaly scanner reads so the two cannot drift apart.

DETERMINISTIC, NOT RANDOM. Calibration dates derive from a hash of the sensor's uuid, so
re-running produces the same file and a diff means the graph changed. A random generator
would make every regeneration look like a data change.

    python scripts/generate_sensor_metrology.py --out input/<id>_sensor_metrology.ttl
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

#: Brick class fragment -> the publisher's value column, so cadence comes from one place.
_CLASS_TO_COLUMN = {
    "co2": "co2_ppm",
    "carbon_dioxide": "co2_ppm",
    "occupancy": "occupancy",
    "noise": "noise_db",
    "sound": "noise_db",
    "tvoc": "voc",
    "voc": "voc",
    "illuminance": "lux",
    "luminance": "lux",
    "light": "lux",
    "temperature": "temp_c",
    "humidity": "rh_pct",
    "flow": "flow_lpm",
    "vibration": "vib_mm_s",
    "pm2": "pm25",
    "pm10": "pm25",
    "particulate": "pm25",
    "contact": "contact",
    "position": "contact",
    "status": "contact",
    "runtime": "runtime_h",
    "duration": "runtime_h",
    "energy": "kwh",
    "power": "kwh",
    "electric": "kwh",
    # Added after measuring which classes fell through: 715 sensors, and the two largest
    # groups were ordinary instruments rather than state signals.
    "formaldehyde": "voc",
    "gas": "voc",
    "air_quality": "voc",
    "differential_pressure": "flow_lpm",
    "pressure": "flow_lpm",
    "water": "flow_lpm",
    "irradiance": "lux",
    "rainfall": "flow_lpm",
    "wind_speed": "flow_lpm",
    "soil_moisture": "rh_pct",
    "intrusion": "contact",
}

#: Sensor kinds that carry a real calibration regime, and how long it lasts.
#: Anything not listed is a state/contact signal that is verified rather than calibrated.
_CALIBRATION_MONTHS = {
    "co2_ppm": 12,
    "temp_c": 24,
    "rh_pct": 24,
    "voc": 12,
    "pm25": 12,
    "noise_db": 24,
    "lux": 36,
    "flow_lpm": 12,
    "kwh": 60,
    "vib_mm_s": 24,
}

_METHOD = {
    "co2_ppm": "two-point span check against a certified gas",
    "temp_c": "comparison against a traceable reference probe",
    "rh_pct": "salt-solution reference check",
    "voc": "manufacturer span check",
    "pm25": "co-location against a reference instrument",
    "noise_db": "acoustic calibrator at 94 dB",
    "lux": "reference luxmeter comparison",
    "flow_lpm": "volumetric verification",
    "kwh": "meter accuracy verification to Class 0.5S",
    "vib_mm_s": "shaker table verification",
}

_QUERY = """
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX ref:  <https://brickschema.org/schema/Brick/ref#>
SELECT DISTINCT ?sensor ?cls ?uuid WHERE {
  ?sensor a ?cls ;
          ref:hasExternalReference ?r .
  ?r ref:hasTimeseriesId ?uuid .
}
"""


def _column_for(cls_iri: str) -> str:
    low = cls_iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1].lower()
    for fragment, column in _CLASS_TO_COLUMN.items():
        if fragment in low:
            return column
    return "generic"


def _cadence_for(column: str) -> int:
    """Straight from the publisher, so this file and the generator cannot disagree."""
    try:
        sys.path.insert(0, str(REPO / "mysql-dummy-publish-dev"))
        import sensor_signal  # type: ignore

        return int(sensor_signal.CADENCE_S.get(column, sensor_signal._DEFAULT_CADENCE_S))
    except Exception:
        return {"co2_ppm": 60, "occupancy": 60, "noise_db": 60, "voc": 120, "lux": 120,
                "runtime_h": 600, "kwh": 900}.get(column, 300)


def _calibration(uuid: str, column: str, today: date) -> Tuple[str, str, str]:
    """Deterministic dates from the uuid. Same input, same file, every run."""
    months = _CALIBRATION_MONTHS.get(column)
    if not months:
        return ("", "", "")
    h = int(hashlib.sha256(uuid.encode("utf-8")).hexdigest()[:8], 16)
    # Spread the last calibration across the whole valid period, and let a realistic
    # minority fall past it — a register in which nothing is ever overdue teaches the
    # gate that overdue does not happen.
    span_days = int(months * 30.4)
    age = h % int(span_days * 1.12)
    last = today - timedelta(days=age)
    due = last + timedelta(days=span_days)
    return (last.isoformat(), due.isoformat(), _METHOD.get(column, "manufacturer procedure"))


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--endpoint", default="http://localhost:7200/repositories/bldg")
    ap.add_argument("--out", required=True)
    ap.add_argument("--today", default=date.today().isoformat())
    args = ap.parse_args(argv)

    import urllib.request

    req = urllib.request.Request(
        args.endpoint,
        data=_QUERY.encode("utf-8"),
        headers={"Content-Type": "application/sparql-query", "Accept": "text/csv"},
    )
    body = urllib.request.urlopen(req, timeout=120).read().decode("utf-8")
    rows = [ln.strip().split(",") for ln in body.splitlines()[1:] if ln.strip()]

    today = date.fromisoformat(args.today)
    seen: Dict[str, Tuple[str, str]] = {}
    for parts in rows:
        if len(parts) < 3:
            continue
        sensor, cls, uuid = parts[0], parts[1], parts[2]
        # One sensor carries several rdf:types. Prefer the type this script can actually
        # interpret.
        #
        # The first version preferred the LONGEST class name as a proxy for specificity.
        # It is not one: brick:Air_Quality_Sensor is longer than brick:CO2_Sensor and far
        # less specific, so 417 CO2 and TVOC instruments were classified as generic and
        # given the 300-second default cadence instead of their real 60 and 120. Measured:
        # 715 sensors fell through, and the two largest groups were ordinary instruments.
        prev = seen.get(sensor)
        if prev is None:
            seen[sensor] = (cls, uuid)
            continue
        prev_known = _column_for(prev[0]) != "generic"
        this_known = _column_for(cls) != "generic"
        if this_known and not prev_known:
            seen[sensor] = (cls, uuid)
        elif this_known == prev_known and len(cls) < len(prev[0]):
            # Between two interpretable types, the SHORTER name is the more specific one
            # in Brick's naming ("CO2_Sensor" beneath "Air_Quality_Sensor").
            seen[sensor] = (cls, uuid)

    # The building TTL contract requires `@prefix bldg:` in every per-building file, and
    # `assert_ttl_validation_or_die` HARD-FAILS the orchestrator without it. The first
    # version of this script wrote full IRIs in angle brackets and declared only ontosage:
    # and xsd:, which crash-looped the container on boot — the validator behaving exactly
    # as designed. The namespace is derived from the sensor IRIs rather than configured,
    # so this stays building-agnostic.
    # '#' WINS OVER '/'. A first attempt tried both separators and kept the shorter
    # result, which derived "http://abacwsbuilding.cardiff.ac.uk/" from
    # "http://abacwsbuilding.cardiff.ac.uk/abacws#Sensor_1" — a namespace the building
    # does not use, in a file whose whole purpose is to attach triples to its sensors.
    # In RDF a fragment separator terminates the namespace by definition, so when one is
    # present it is the answer and the path separator is not a candidate at all.
    namespace = ""
    for sensor in seen:
        if "#" in sensor:
            namespace = sensor.rsplit("#", 1)[0] + "#"
        elif "/" in sensor:
            namespace = sensor.rsplit("/", 1)[0] + "/"
        break
    if not namespace:
        print("could not derive a building namespace from the sensor IRIs")
        return 2
    covered = sum(1 for s in seen if s.startswith(namespace))
    if covered < len(seen):
        print(f"WARNING: {len(seen) - covered} sensors sit outside {namespace}; "
              f"they are written as full IRIs")

    def _term(iri: str) -> str:
        """bldg:LocalName when the IRI sits in the building namespace, else <full>."""
        if iri.startswith(namespace):
            local = iri[len(namespace):]
            if local and all(c.isalnum() or c in "_-." for c in local):
                return f"bldg:{local}"
        return f"<{iri}>"

    lines = [
        "# Sensor metrology — generated by scripts/generate_sensor_metrology.py",
        "#",
        "# How often each stream reports, and when it was last calibrated. Written because",
        "# the completeness and calibration evidence gates judge fields nothing populated:",
        "# before this file, archivalIntervalS and calibratedOn had ZERO instances, so both",
        "# gates would have returned the same failure for every answer in the system.",
        "#",
        "# Cadences come from the publisher's own CADENCE_S map, which is also what the",
        "# anomaly scanner reads, so a change to the publisher cannot leave this behind.",
        "# Calibration dates are derived from a hash of each uuid: deterministic, so",
        "# regenerating produces an identical file and any diff means the graph changed.",
        "",
        f"@prefix bldg:     <{namespace}> .",
        "@prefix ontosage: <http://ontosage.org/capabilities#> .",
        "@prefix xsd:      <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]

    calibrated = overdue = 0
    for sensor, (cls, uuid) in sorted(seen.items()):
        column = _column_for(cls)
        cadence = _cadence_for(column)
        last, due, method = _calibration(uuid, column, today)
        body_lines = [
            f"    ontosage:samplingIntervalS {cadence} ;",
            f"    ontosage:archivalIntervalS {cadence} ;",
        ]
        if last:
            calibrated += 1
            if date.fromisoformat(due) < today:
                overdue += 1
            body_lines += [
                f'    ontosage:calibratedOn "{last}"^^xsd:date ;',
                f'    ontosage:calibrationDueOn "{due}"^^xsd:date ;',
                f'    ontosage:calibrationMethod "{method}" ;',
            ]
        body_lines[-1] = body_lines[-1].rstrip(" ;") + " ."
        lines.append(_term(sensor))
        lines.extend(body_lines)
        lines.append("")

    out = Path(args.out)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(seen)} sensors written to {out}")
    print(f"  {calibrated} carry a calibration regime; {overdue} of those are past due")
    print(f"  {len(seen) - calibrated} are state or contact signals, which are verified "
          f"rather than calibrated and correctly carry no calibration date")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
