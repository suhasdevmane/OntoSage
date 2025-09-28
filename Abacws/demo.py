"""demo.py
Send periodic dummy data for device 'node_5.20' to the Abacws API (Postgres-backed) so it appears live in the visualiser.

Features:
- Ensures the device exists (creates if missing)
- Sends random telemetry payload every N seconds using PUT /api/devices/{deviceName}/data
- Supports graceful shutdown (Ctrl+C)
- Optional base URL & interval via env vars

Env Vars:
  ABACWS_API_BASE   default: http://localhost:5000/api
  DEVICE_NAME       default: node_5.20
  INTERVAL_SEC      default: 5
  FLOOR             default: 5
  API_KEY           (optional) if API endpoints are protected with x-api-key in your deployment

Example run:
  python demo.py
  ABACWS_API_BASE=http://localhost:5000/api INTERVAL_SEC=2 python demo.py

After starting this script, open the visualiser (http://localhost:8090) and select the device.
You should see latest value updates (depending on visualiser polling/stream configuration).
"""
from __future__ import annotations
import os
import sys
import time
import json
import random
import signal
from typing import Any, Dict

try:
    import requests  # type: ignore
except ImportError:
    print("This script requires the 'requests' package. Install with: pip install requests")
    sys.exit(1)

API_BASE = os.environ.get("ABACWS_API_BASE", "http://localhost:5000/api")
DEVICE_NAME = os.environ.get("DEVICE_NAME", "node_5.03")
INTERVAL = float(os.environ.get("INTERVAL_SEC", "5"))
FLOOR = int(os.environ.get("FLOOR", "5"))
API_KEY = os.environ.get("API_KEY")  # optional

HEADERS = {"Content-Type": "application/json"}
if API_KEY:
    HEADERS["x-api-key"] = API_KEY

# Basic sample types you can expand
DEVICE_TYPE = "demo_sensor"

running = True

def handle_sig(signum, frame):  # noqa: D401
    global running
    running = False
    print("\nStopping...")

signal.signal(signal.SIGINT, handle_sig)
signal.signal(signal.SIGTERM, handle_sig)


def api_url(path: str) -> str:
    return f"{API_BASE.rstrip('/')}/{path.lstrip('/')}"


def ensure_device_exists() -> None:
    """Create the demo device if it does not already exist."""
    # List devices quickly (could also GET /devices/node_5.20)
    try:
        r = requests.get(api_url("devices"), timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"Failed to list devices: {e}")
        sys.exit(1)

    devices = r.json()
    if any(d.get("name") == DEVICE_NAME for d in devices):
        print(f"Device '{DEVICE_NAME}' already exists.")
        return

    payload = {
        "name": DEVICE_NAME,
        "type": DEVICE_TYPE,
        "floor": FLOOR,
        "position": {"x": 281.344, "y": 70.0, "z": -87.645},  # Use provided legacy coordinate
        "pinned": False,
    }
    try:
        cr = requests.post(api_url("devices"), headers=HEADERS, data=json.dumps(payload), timeout=10)
        if cr.status_code in (200, 201):
            print(f"Created device '{DEVICE_NAME}'.")
        elif cr.status_code == 409:
            print(f"Device '{DEVICE_NAME}' already existed (409). Proceeding.")
        else:
            print(f"Unexpected create status {cr.status_code}: {cr.text}")
    except Exception as e:
        print(f"Failed to create device: {e}")
        sys.exit(1)


def generate_payload(counter: int) -> Dict[str, Any]:
    # Example telemetry; adjust keys to what your visualiser expects (it reads generic JSON + timestamp)
    return {
        "uv_light": {"value": round(random.uniform(0.0, 1.0), 2), "units": "UV Index"},
        "loudness": {"value": round(random.uniform(30.0, 80.0), 1), "units": "dB"},
        "pm1.0atmospheric": {"value": round(random.uniform(5.0, 20.0), 1), "units": "µg/m³"},
        "pm2.5atmospheric": {"value": round(random.uniform(10.0, 30.0), 1), "units": "µg/m³"},
        "visible_light": {"value": random.randint(200, 600), "units": "Lux"},
        "ir_light": {"value": random.randint(200, 600), "units": "Lux"},
        "mq5_sensor_voltage": {"value": round(random.uniform(0.5, 1.0), 2), "units": "Volts"},
        "humidity": {"value": round(random.uniform(15.0, 60.0), 2), "units": "%"},
        "luminance": {"value": round(random.uniform(20.0, 50.0), 2), "units": "cd/m²"},
        "no2": {"value": random.randint(100, 300), "units": ""},
    }


def send_data_loop():
    ensure_device_exists()
    print(f"Sending dummy data for '{DEVICE_NAME}' every {INTERVAL} seconds to {API_BASE} (Ctrl+C to stop) ...")
    counter = 0
    while running:
        counter += 1
        payload = generate_payload(counter)
        try:
            # PUT /devices/{deviceName}/data (202 Accepted expected)
            r = requests.put(api_url(f"devices/{DEVICE_NAME}/data"), headers=HEADERS, data=json.dumps(payload), timeout=10)
            if r.status_code not in (200, 202):
                print(f"Warning: unexpected status {r.status_code}: {r.text[:120]}")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] Sent: {payload}")
        except Exception as e:
            print(f"Error sending data: {e}")
        # Sleep with small increments to allow fast shutdown
        slept = 0.0
        while running and slept < INTERVAL:
            time.sleep(min(0.5, INTERVAL - slept))
            slept += 0.5
    print("Sender stopped.")


if __name__ == "__main__":
    send_data_loop()
