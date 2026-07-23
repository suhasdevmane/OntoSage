"""
Synthetic data generator for bldg3 sensors (single-file, no args required).

What it does
- Reads sensors_list.txt (list of sensor names, one per line)
- Reads sensor_uuids.txt (CSV: sensor_name,uuid)
- Filters and orders UUID columns according to sensor_uuids.txt, keeping only
  sensors present in sensors_list.txt. This guarantees:
  - Column 1: datetime
  - Column 2: the UUID of the first sensor in sensor_uuids.txt (e.g., 0cb16549-503f-4919-b664-dd12326c089d for bldg3.AHU.AHU01N.CCV)
  - Column 3: the UUID of the second row in sensor_uuids.txt (e.g., d7d9d3f5-c97b-412e-bc26-7b7b1129af6a)
- Generates ASHRAE-like synthetic values per sensor kind inferred from the name
  (AHU = Air Handling Unit, RM = Room, Zone = specific zone). Temperature,
  humidity, airflow, pressure, valve positions, etc., are generated within
  reasonable standard limits.

Defaults (edit these at the top of the file):
- START_ISO = 2025-08-01T00:00:00+00:00
- END_ISO   = 2025-08-31T00:00:00+00:00   (exclusive; covers up to Aug 30)
- FREQ_SECONDS = 60  (1-minute sampling)

Output
- synthetic_data_wide.csv in the same directory as this script.
"""
from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


# -------------------------------
# User-editable defaults
# -------------------------------
BASE_DIR = Path(__file__).parent
SENSORS_LIST_PATH = BASE_DIR / "sensors_list.txt"
SENSOR_UUIDS_PATH = BASE_DIR / "sensor_uuids.txt"
OUTPUT_CSV_PATH = BASE_DIR / "synthetic_data_wide.csv"

# Time window (exclusive end)
START_ISO = "2025-08-01T00:00:00+00:00"
END_ISO = "2025-08-31T00:00:00+00:00"  # exclusive -> runs through Aug 30th
FREQ_SECONDS = 60  # 1 minute


@dataclass
class SensorProfile:
    name: str
    uuid: str
    kind: str
    min_val: float
    max_val: float
    sigma: float
    binary: bool = False
    integer: bool = False


def _read_sensors_list(path: Path) -> List[str]:
    names: List[str] = []
    if not path.exists():
        return names
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if name:
                names.append(name)
    return names


def _read_sensor_uuids(path: Path) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    if not path.exists():
        return pairs
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or len(row) < 2:
                continue
            name = row[0].strip()
            uid = row[1].strip()
            if name and uid:
                pairs.append((name, uid))
    return pairs


def _infer_kind_and_range(sensor_name: str, context: str) -> Tuple[str, float, float, float, bool, bool]:
    """Infer kind and (min,max,sigma) from sensor name and high-level context.

    Rough ASHRAE/LEED-inspired limits:
    - Zone air temp: 20–24°C occupied, wider 18–28 overall
    - RH: target 30–60%, clamp 10–90%
    - Supply air temp: 12–18°C typical cooling
    - Airflow: generic 0–3 m3/s (zones) or 0–5 m3/s (AHUs)
    - Pressure: 0–1000 Pa typical differentials/static ranges
    - CO2: 400–1200 ppm typical indoor variation
    - Valve/Damper: 0–100 %
    - Binary (Start/Stop, Enable): 0/1
    """
    s = sensor_name.lower()

    def rng(a: float, b: float, sig: float) -> Tuple[float, float, float]:
        return a, b, sig

    # Binary/commands
    if any(tok in s for tok in ["start/stop", "start_stop", "enable", "run_cmd", "run", "cmd"]) and not any(
        tok in s for tok in ["temp", "press", "flow", "rh", "co2", "valve", "damper", "power"]
    ):
        return ("Binary_Command", *rng(0.0, 1.0, 0.5), True, False)

    # Valve / Damper positions
    if any(tok in s for tok in ["ccv", "valve", "valve_position", "damper", "damper_position"]):
        return ("Position_Percent", *rng(0.0, 100.0, 5.0), False, False)

    # Temperatures
    if "outside_air" in s or ".oat" in s:
        return ("Outside_Air_Temperature", *rng(-5.0, 30.0, 0.6), False, False)
    if "supply_air_temp" in s or "supply_air_temperature" in s or "_sat" in s:
        return ("Supply_Air_Temperature", *rng(12.0, 18.0, 0.3), False, False)
    if "return_air_temp" in s or "rat" in s:
        return ("Return_Air_Temperature", *rng(20.0, 26.0, 0.25), False, False)
    if "mixed_air_temp" in s or "mat" in s:
        return ("Mixed_Air_Temperature", *rng(16.0, 24.0, 0.25), False, False)
    if "zone_air_temp" in s or "zone_temp" in s or s.endswith("_temp"):
        return ("Zone_Air_Temperature", *rng(18.0, 28.0, 0.2), False, False)

    # Humidity
    if "humidity" in s or "rh" in s:
        return ("Relative_Humidity", *rng(10.0, 90.0, 2.0), False, False)

    # Air/Water Flow
    if "air_flow" in s or ("flow" in s and "water" not in s):
        if context == "ahu":
            return ("Air_Flow", *rng(0.0, 5.0, 0.08), False, False)
        return ("Air_Flow", *rng(0.0, 3.0, 0.06), False, False)
    if "water_flow" in s or ("flow" in s and "water" in s):
        return ("Water_Flow", *rng(0.0, 50.0, 0.6), False, False)

    # Pressure
    if "static_pressure" in s or "supply_air_static_pressure" in s or "sp" in s:
        return ("Static_Pressure", *rng(0.0, 1000.0, 12.0), False, False)
    if "pressure" in s or "dp" in s:
        return ("Differential_Pressure", *rng(0.0, 750.0, 8.0), False, False)

    # CO2
    if "co2" in s:
        return ("CO2", *rng(400.0, 1200.0, 25.0), False, True)

    # Power/Energy
    if "power" in s:
        return ("Power", *rng(0.0, 20000.0, 250.0), False, False)
    if "energy" in s:
        return ("Energy", *rng(0.0, 1_000_000.0, 500.0), False, False)

    # Fallback: generic zone analog
    return ("Analog", *rng(0.0, 100.0, 1.0), False, False)


def _context_from_name(sensor_name: str) -> str:
    s = sensor_name.upper()
    if ".AHU." in s:
        return "ahu"
    if ".RM" in s or ".ZONE" in s:
        return "zone"
    return "generic"


def _format_value(binary: bool, integer: bool, value: float) -> str:
    if binary:
        return "1" if value >= 0.5 else "0"
    if integer:
        return str(int(round(value)))
    return f"{value:.2f}"


def _daily_phase(ts: datetime) -> float:
    sec = ts.hour * 3600 + ts.minute * 60 + ts.second
    return 2.0 * math.pi * (sec / 86400.0)


def _occupancy_scalar(ts: datetime) -> float:
    h = ts.hour + ts.minute / 60.0
    if h < 6 or h > 21:
        return 0.05
    if 8 <= h <= 18:
        return 1.0
    if 6 <= h < 8:
        return (h - 6) / 2.0
    if 18 < h <= 21:
        return max(0.0, 1.0 - (h - 18) / 3.0)
    return 0.2


def _outside_air_temp(ts: datetime) -> float:
    phase = _daily_phase(ts)
    base = 20.0 + 7.0 * (0.5 * (1 + math.sin(phase - 0.8)))
    val = base + random.gauss(0.0, 0.4)
    return max(-5.0, min(35.0, val))


def _generate_profiles() -> List[SensorProfile]:
    names = _read_sensors_list(SENSORS_LIST_PATH)
    pairs = _read_sensor_uuids(SENSOR_UUIDS_PATH)
    name_set = set(names)
    profiles: List[SensorProfile] = []
    for name, uid in pairs:
        if name not in name_set:
            continue
        ctx = _context_from_name(name)
        kind, mn, mx, sig, is_bin, is_int = _infer_kind_and_range(name, ctx)
        profiles.append(SensorProfile(name=name, uuid=uid, kind=kind, min_val=mn, max_val=mx, sigma=sig, binary=is_bin, integer=is_int))
    return profiles


def _generate_series(profiles: List[SensorProfile], start: datetime, points: int, freq_seconds: int):
    state: Dict[str, float] = {}
    for p in profiles:
        mid = (p.min_val + p.max_val) / 2.0
        span = (p.max_val - p.min_val)
        state[p.uuid] = random.gauss(mid, max(1e-6, span * 0.05))

    for i in range(points):
        ts = start + timedelta(seconds=i * freq_seconds)
        occ = _occupancy_scalar(ts)
        oat = _outside_air_temp(ts)
        row: Dict[str, float] = {}
        for p in profiles:
            val = state[p.uuid]
            step = random.gauss(0.0, p.sigma)
            k = p.kind

            if k == "Outside_Air_Temperature":
                target = oat
                val = val + 0.5 * (target - val) + step
            elif k in ("Zone_Air_Temperature",):
                target = 21.5 + 1.5 * occ
                val = val + 0.20 * (target - val) + step
            elif k in ("Supply_Air_Temperature",):
                cool_target = 14.0 + 2.0 * (1.0 - occ)
                val = val + 0.30 * (cool_target - val) + step
            elif k in ("Return_Air_Temperature", "Mixed_Air_Temperature"):
                target = 22.0 + 1.0 * occ
                val = val + 0.25 * (target - val) + step
            elif k in ("Relative_Humidity",):
                target = 45.0 + 10.0 * (occ - 0.5)  # drift around ~45% RH
                val = val + 0.15 * (target - val) + step
            elif k in ("Air_Flow", "Water_Flow"):
                load = max(0.0, (oat - 18.0) / 12.0)
                target = p.min_val + (p.max_val - p.min_val) * max(occ, load)
                val = val + 0.35 * (target - val) + step
            elif k in ("Static_Pressure", "Differential_Pressure"):
                target = p.min_val + 0.6 * (p.max_val - p.min_val) * occ
                val = val + 0.25 * (target - val) + step
            elif k in ("CO2",):
                base = 420.0
                occ_ppm = 900.0 * occ + 150.0 * random.random()
                target = min(p.max_val, base + occ_ppm)
                val = val + 0.30 * (target - val) + step
            elif k in ("Power",):
                load = 0.5 * occ + 0.5 * max(0.0, (oat - 18.0) / 12.0)
                target = p.min_val + (p.max_val - p.min_val) * load
                val = val + 0.25 * (target - val) + step
            elif k in ("Position_Percent",):
                target = 100.0 * min(1.0, max(0.0, 0.2 + 0.7 * occ + 0.2 * random.random()))
                val = val + 0.40 * (target - val) + step
            elif k in ("Binary_Command",):
                # On during occupied hours
                target = 1.0 if occ > 0.6 else 0.0
                val = val + 0.8 * (target - val) + random.gauss(0.0, 0.05)
            else:
                mid = (p.min_val + p.max_val) / 2.0
                val = val + 0.10 * (mid - val) + step

            # Clamp values to range
            if val < p.min_val:
                val = p.min_val + abs(step) * 0.3
            if val > p.max_val:
                val = p.max_val - abs(step) * 0.3

            state[p.uuid] = val
            row[p.uuid] = val

        yield ts, row


def _write_wide(profiles: List[SensorProfile], start: datetime, end: datetime, freq_seconds: int, out_path: Path) -> None:
    total_seconds = int((end - start).total_seconds())
    if total_seconds <= 0:
        raise ValueError("END_ISO must be after START_ISO")
    points = total_seconds // freq_seconds
    out_path.parent.mkdir(parents=True, exist_ok=True)

    uuids_order = [p.uuid for p in profiles]
    gen = _generate_series(profiles, start, points, freq_seconds)

    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        # Header: datetime then UUIDs (keeps sensor_uuids.txt order filtered by sensors_list.txt)
        w.writerow(["datetime", *uuids_order])
        for ts, row in gen:
            formatted = [_format_value(p.binary, p.integer, row.get(p.uuid, float("nan"))) for p in profiles]
            w.writerow([ts.isoformat(), *formatted])


def main() -> int:
    profiles = _generate_profiles()
    if not profiles:
        print("No matching sensors between sensors_list.txt and sensor_uuids.txt. Nothing to do.")
        return 1

    start = datetime.fromisoformat(START_ISO)
    end = datetime.fromisoformat(END_ISO)
    _write_wide(profiles, start, end, FREQ_SECONDS, OUTPUT_CSV_PATH)
    print(f"Wrote synthetic CSV with {len(profiles)} UUID columns -> {OUTPUT_CSV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
