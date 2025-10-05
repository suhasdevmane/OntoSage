"""
Generate synthetic time-series data (no CSV) and publish directly to ThingsBoard.

What this does
- Uses the same generation logic as 04_generate_synthetic_data.py (embedded here) to synthesize values
  for the UUIDs listed in sensor_uuids.txt filtered by sensors_list.txt.
- Streams telemetry to ThingsBoard via MQTT transport (QoS 1) so data is persisted into Cassandra
  and visible on dashboards. No CSV files are written.

Defaults (safe)
- Generates one day of 1-minute data for a fixed window (edit in code below; default Aug 1 → Aug 2, 2025 UTC).
- Publishes ALL devices from sensor_uuids.txt that are present in sensors_list.txt.
- Publishes to MQTT at localhost:1884 (ThingsBoard container maps 1883->1884).
- Logging shows per-device progress with percent, rate, and ETA.

Environment overrides (optional)
- START_ISO: e.g. 2025-08-01T00:00:00+00:00 (default: value set in code)
- END_ISO:   e.g. 2025-08-02T00:00:00+00:00 (default: value set in code)
- FREQ_SECONDS: sampling frequency (default: 60)
- DEVICE_LIMIT: 0 means ALL (default: 0)
- KEY_NAME: telemetry key name (default: value)
- MQTT_HOST (default: localhost)
- MQTT_PORT (default: 1884)
- SLEEP_MS: per-message delay (default: 1)
- LOG_LEVEL: DEBUG|INFO|WARNING|ERROR (default: INFO)
- LOG_FILE: optional path to also write logs
- PROGRESS_EVERY: log every N messages per device (default: 5000)
"""
from __future__ import annotations

import csv
import json
import logging
import math
import os
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

try:
    import paho.mqtt.client as mqtt
except Exception:
    raise SystemExit("paho-mqtt is required. Install with: pip install paho-mqtt")


# -------------------------------
# Config & logging
# -------------------------------
BASE_DIR = Path(__file__).parent
SENSORS_LIST_PATH = BASE_DIR / "sensors_list.txt"
SENSOR_UUIDS_PATH = BASE_DIR / "sensor_uuids.txt"

"""
Edit these two lines to change the default generation window (ISO 8601 with timezone).
If START_ISO/END_ISO environment variables are set, they will override these defaults.
"""
DEFAULT_START_ISO = "2025-08-01T00:00:00+00:00"
DEFAULT_END_ISO = "2025-08-30T00:00:00+00:00"

START_ISO = os.getenv("START_ISO") or DEFAULT_START_ISO
END_ISO = os.getenv("END_ISO") or DEFAULT_END_ISO
START_DT = datetime.fromisoformat(START_ISO)
END_DT = datetime.fromisoformat(END_ISO)

FREQ_SECONDS = int(os.getenv("FREQ_SECONDS", "60"))
DEVICE_LIMIT = int(os.getenv("DEVICE_LIMIT", "0"))
KEY_NAME = os.getenv("KEY_NAME", "value")
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1884"))
SLEEP_MS = int(os.getenv("SLEEP_MS", "0"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", "").strip()
PROGRESS_EVERY = int(os.getenv("PROGRESS_EVERY", "5000"))

_handlers = [logging.StreamHandler()]
if LOG_FILE:
    try:
        _handlers.append(logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"))
    except Exception:
        pass
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=_handlers,
)
log = logging.getLogger("tb-generator-publisher")


# -------------------------------
# Generation logic (from 04_...)
# -------------------------------
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
    s = sensor_name.lower()

    def rng(a: float, b: float, sig: float) -> Tuple[float, float, float]:
        return a, b, sig

    if any(tok in s for tok in ["start/stop", "start_stop", "enable", "run_cmd", "run", "cmd"]) and not any(
        tok in s for tok in ["temp", "press", "flow", "rh", "co2", "valve", "damper", "power"]
    ):
        return ("Binary_Command", *rng(0.0, 1.0, 0.5), True, False)

    if any(tok in s for tok in ["ccv", "valve", "valve_position", "damper", "damper_position"]):
        return ("Position_Percent", *rng(0.0, 100.0, 5.0), False, False)

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

    if "humidity" in s or "rh" in s:
        return ("Relative_Humidity", *rng(10.0, 90.0, 2.0), False, False)

    if "air_flow" in s or ("flow" in s and "water" not in s):
        if context == "ahu":
            return ("Air_Flow", *rng(0.0, 5.0, 0.08), False, False)
        return ("Air_Flow", *rng(0.0, 3.0, 0.06), False, False)
    if "water_flow" in s or ("flow" in s and "water" in s):
        return ("Water_Flow", *rng(0.0, 50.0, 0.6), False, False)

    if "static_pressure" in s or "supply_air_static_pressure" in s or "sp" in s:
        return ("Static_Pressure", *rng(0.0, 1000.0, 12.0), False, False)
    if "pressure" in s or "dp" in s:
        return ("Differential_Pressure", *rng(0.0, 750.0, 8.0), False, False)

    if "co2" in s:
        return ("CO2", *rng(400.0, 1200.0, 25.0), False, True)

    if "power" in s:
        return ("Power", *rng(0.0, 20000.0, 250.0), False, False)
    if "energy" in s:
        return ("Energy", *rng(0.0, 1_000_000.0, 500.0), False, False)

    return ("Analog", *rng(0.0, 100.0, 1.0), False, False)


def _context_from_name(sensor_name: str) -> str:
    s = sensor_name.upper()
    if ".AHU." in s:
        return "ahu"
    if ".RM" in s or ".ZONE" in s:
        return "zone"
    return "generic"


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
        if DEVICE_LIMIT > 0 and len(profiles) >= DEVICE_LIMIT:
            break
    return profiles


def _iso_to_epoch_ms(ts: datetime) -> int:
    return int(ts.timestamp() * 1000)


def _generate_series(profiles: List[SensorProfile], start: datetime, points: int, freq_seconds: int):
    state: Dict[str, float] = {}
    for p in profiles:
        mid = (p.min_val + p.max_val) / 2.0
        span = (p.max_val - p.min_val)
        raw_init = random.gauss(mid, max(1e-6, span * 0.05))

        # Normalize initial value respecting sensor type semantics
        if p.binary:
            norm_init = 1.0 if raw_init >= 0.5 * (p.min_val + p.max_val) else 0.0
        elif p.integer:
            norm_init = int(round(raw_init))
        else:
            norm_init = round(raw_init, 2)
        state[p.uuid] = norm_init

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
                target = 45.0 + 10.0 * (occ - 0.5)
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
                target = 1.0 if occ > 0.6 else 0.0
                val = val + 0.8 * (target - val) + random.gauss(0.0, 0.05)
            else:
                mid = (p.min_val + p.max_val) / 2.0
                val = val + 0.10 * (mid - val) + step

            if val < p.min_val:
                val = p.min_val + abs(step) * 0.3
            if val > p.max_val:
                val = p.max_val - abs(step) * 0.3

            state[p.uuid] = val
            # Final rounding / coercion rules before storing row value
            if p.binary:
                # Keep strictly 0 or 1
                val_out = 1.0 if val >= 0.5 * (p.min_val + p.max_val) else 0.0
            elif p.integer:
                val_out = int(round(val))
            else:
                val_out = round(float(val), 2)
            row[p.uuid] = val_out

        yield ts, row


# -------------------------------
# Publish (MQTT, QoS=1)
# -------------------------------
def _publish_device_mqtt(token: str, points: List[Tuple[datetime, float]], key_name: str) -> tuple[int, int]:
    # Prefer new callback API when available
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except Exception:
        client = mqtt.Client()

    connected = threading.Event()

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            connected.set()
            log.debug(f"[{token[:8]}] connected")
        else:
            log.warning(f"[{token[:8]}] connect rc={rc}")

    client.on_connect = on_connect
    client.username_pw_set(token)
    try:
        client.reconnect_delay_set(min_delay=1, max_delay=5)
    except Exception:
        pass
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    connected.wait(timeout=10)

    sent = 0
    failed = 0
    start_ts = time.time()
    total = len(points)

    for idx, (ts, val) in enumerate(points, start=1):
        payload = {"ts": _iso_to_epoch_ms(ts), "values": {key_name: val}}
        try:
            info = client.publish("v1/devices/me/telemetry", payload=json.dumps(payload), qos=1)
            attempts = 0
            while info.rc != mqtt.MQTT_ERR_SUCCESS and attempts < 3:
                attempts += 1
                time.sleep(0.1 * attempts)
                info = client.publish("v1/devices/me/telemetry", payload=json.dumps(payload), qos=1)
            info.wait_for_publish()
            if getattr(info, "is_published", None) and info.is_published():
                sent += 1
            else:
                if info.rc == mqtt.MQTT_ERR_SUCCESS:
                    sent += 1
                else:
                    failed += 1
        except Exception as e:
            failed += 1
            if failed <= 3:
                log.debug(f"[{token[:8]}] publish error: {e}")

        if SLEEP_MS > 0:
            time.sleep(SLEEP_MS / 1000.0)

        if PROGRESS_EVERY > 0 and (idx % PROGRESS_EVERY == 0):
            elapsed = max(1e-6, time.time() - start_ts)
            rate = sent / elapsed
            percent = (idx / total) * 100.0 if total else 0.0
            remaining = max(0, total - idx)
            eta_sec = remaining / rate if rate > 0 else 0
            log.info(f"[{token[:8]}] progress: {percent:5.1f}% sent={sent} failed={failed} rate={rate:,.1f}/s ETA={eta_sec:,.0f}s")

    client.loop_stop()
    client.disconnect()
    dur = max(1e-6, time.time() - start_ts)
    log.info(f"[{token[:8]}] done: sent={sent} failed={failed} took={dur:,.1f}s rate={sent/dur:,.1f}/s")
    return sent, failed


def main() -> int:
    if END_DT <= START_DT:
        log.error("END_ISO must be after START_ISO")
        return 2

    profiles = _generate_profiles()
    if not profiles:
        log.error("No matching sensors between sensors_list.txt and sensor_uuids.txt. Nothing to do.")
        return 1

    total_seconds = int((END_DT - START_DT).total_seconds())
    points_count = total_seconds // FREQ_SECONDS
    log.info(
        f"Generating+publishing from {START_DT.isoformat()} to {END_DT.isoformat()} every {FREQ_SECONDS}s | devices={len(profiles)} | host={MQTT_HOST}:{MQTT_PORT}"
    )

    # Build a list of per-device series once, streaming row-by-row would require re-iterating for each device
    # We construct an in-memory list of points for each device token to publish sequentially.
    per_device: Dict[str, List[Tuple[datetime, float]]] = {p.uuid: [] for p in profiles}
    for ts, row in _generate_series(profiles, START_DT, points_count, FREQ_SECONDS):
        for p in profiles:
            per_device[p.uuid].append((ts, row.get(p.uuid)))

    overall_sent = 0
    overall_failed = 0
    for idx, p in enumerate(profiles, start=1):
        log.info(f"Publishing {idx}/{len(profiles)} token={p.uuid} name={p.name} kind={p.kind}")
        s, f = _publish_device_mqtt(p.uuid, per_device[p.uuid], KEY_NAME)
        overall_sent += s
        overall_failed += f

    log.info(f"All done. total_sent={overall_sent} total_failed={overall_failed} devices={len(profiles)}")
    return 0 if overall_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


# Example usage in PowerShell (adjust dates as needed):

# $env:START_ISO='2025-08-01T00:00:00+00:00'
# $env:END_ISO='2025-08-02T00:00:00+00:00'
# $env:DEVICE_LIMIT='50'
# $env:LOG_LEVEL='INFO'
# $env:PROGRESS_EVERY='5000'
# python "c:\Users\suhas\Documents\GitHub\OntoBot\bldg3\trial\dataset\07_generate_and_publish_to_thingsboard.py"