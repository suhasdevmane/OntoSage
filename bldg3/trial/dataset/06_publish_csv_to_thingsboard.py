"""
Publish synthetic_data_wide.csv to ThingsBoard via HTTP transport.

Assumptions:
- Each UUID column header is the device access token (created earlier when devices were provisioned).
- One numeric value per device per timestamp; we'll publish under telemetry key 'value' by default.

Defaults (safe, no env needed):
- Publishes ALL devices and ALL rows (full CSV) by default.
- Batches points per device into chunks of 200 to reduce HTTP overhead.
- Posts to http://localhost:8080 (ThingsBoard HTTP transport) by default.

Environment overrides (optional):
- TB_HTTP_BASE: base URL (default: http://localhost:8080)
- TB_KEY_NAME: telemetry key name (default: value)
- DEVICE_LIMIT: max number of devices to publish (default: 0 means ALL)
- ROW_LIMIT: max number of rows to publish (default: 0 means ALL)
- START_ROW: starting row offset (default: 0)
- BATCH_SIZE: number of points per HTTP post per device (default: 200)
- CSV_PATH: path to CSV (default: ./synthetic_data_wide.csv)
- CONCURRENCY: number of devices processed in parallel (default: 4)
- DRY_RUN: set to '1' to not send, only print what would be sent

Usage:
  python 06_publish_csv_to_thingsboard.py

Notes:
- To publish all rows/devices, set DEVICE_LIMIT and ROW_LIMIT high. Start small first.
- If you see 401, verify the device token exists and matches the column header.
"""
from __future__ import annotations

import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import requests


BASE_DIR = Path(__file__).parent
CSV_PATH = Path(os.getenv("CSV_PATH", str(BASE_DIR / "synthetic_data_wide.csv")))
TB_HTTP_BASE = os.getenv("TB_HTTP_BASE", "http://localhost:8080")
KEY_NAME = os.getenv("TB_KEY_NAME", "value")
DEVICE_LIMIT = int(os.getenv("DEVICE_LIMIT", "0"))
ROW_LIMIT = int(os.getenv("ROW_LIMIT", "0"))
START_ROW = int(os.getenv("START_ROW", "0"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "200"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "4"))
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"


def iso_to_epoch_ms(iso_str: str) -> int:
    # Allow Z suffix; ensure timezone-aware
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def load_csv_slice() -> tuple[List[str], List[List[str]]]:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"CSV not found: {CSV_PATH}")
    with CSV_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        if not header or header[0].lower() != "datetime":
            raise ValueError("First header column must be 'datetime'")
        # 0 or negative means ALL device columns
        tokens = header[1:] if DEVICE_LIMIT <= 0 else header[1:1 + DEVICE_LIMIT]

        # Skip rows before START_ROW and then take ROW_LIMIT
        rows: List[List[str]] = []
        idx = 0
        for row in reader:
            if not row:
                continue
            if idx < START_ROW:
                idx += 1
                continue
            if ROW_LIMIT > 0 and len(rows) >= ROW_LIMIT:
                break
            rows.append(row)
            idx += 1

        return tokens, rows


def build_payloads_for_device(token: str, rows: List[List[str]], token_col_index: int) -> List[dict]:
    payloads: List[dict] = []
    for row in rows:
        ts_iso = row[0]
        val_raw = row[token_col_index]
        if val_raw == "" or val_raw is None:
            continue
        try:
            val = float(val_raw)
        except ValueError:
            # Non-numeric; send as string
            val = val_raw
        payloads.append({
            "ts": iso_to_epoch_ms(ts_iso),
            "values": {KEY_NAME: val}
        })
    return payloads


def post_batches(session: requests.Session, token: str, payloads: List[dict]) -> tuple[int, int]:
    url = f"{TB_HTTP_BASE}/api/v1/{token}/telemetry"
    total = 0
    failures = 0
    for i in range(0, len(payloads), BATCH_SIZE):
        batch = payloads[i:i + BATCH_SIZE]
        if DRY_RUN:
            print(f"DRY-RUN POST {url} points={len(batch)}")
            total += len(batch)
            continue
        resp = session.post(url, json=batch, timeout=30)
        if not resp.ok:
            failures += len(batch)
            print(f"POST failed token={token} status={resp.status_code} body={resp.text[:300]}")
        else:
            total += len(batch)
    return total, failures


def process_device(token: str, rows: List[List[str]], token_col_index: int) -> tuple[str, int, int]:
    with requests.Session() as session:
        payloads = build_payloads_for_device(token, rows, token_col_index)
        sent, failed = post_batches(session, token, payloads)
        return token, sent, failed


def _fallback_publish_mqtt(tokens: List[str], rows: List[List[str]]) -> tuple[int, int]:
    """Fallback to MQTT when HTTP is unreachable. Returns (total_sent, total_failed)."""
    try:
        import paho.mqtt.client as mqtt  # lazy import so HTTP-only users don't need it
    except Exception:
        print("MQTT fallback unavailable: paho-mqtt not installed")
        return 0, len(tokens) * len(rows)

    # Use same defaults as the MQTT script
    mqtt_host = os.getenv("MQTT_HOST", "localhost")
    mqtt_port = int(os.getenv("MQTT_PORT", "1884"))
    key_name = KEY_NAME

    def iso_to_epoch_ms_local(iso_str: str) -> int:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)

    total = 0
    failures = 0
    for col_offset, token in enumerate(tokens, start=1):
        client = mqtt.Client()
        client.username_pw_set(token)
        try:
            client.connect(mqtt_host, mqtt_port, keepalive=30)
        except Exception as e:
            print(f"MQTT connect failed for token={token}: {e}")
            failures += len(rows)
            continue
        client.loop_start()
        try:
            for row in rows:
                ts_ms = iso_to_epoch_ms_local(row[0])
                val_raw = row[col_offset]
                if val_raw == "" or val_raw is None:
                    continue
                try:
                    val = float(val_raw)
                except ValueError:
                    val = val_raw
                payload = {"ts": ts_ms, "values": {key_name: val}}
                info = client.publish("v1/devices/me/telemetry", payload=str(payload).replace("'", '"'), qos=0)
                if info.rc == 0:
                    total += 1
                else:
                    failures += 1
        finally:
            client.loop_stop()
            client.disconnect()
    return total, failures


def main() -> int:
    tokens, rows = load_csv_slice()
    if not tokens:
        print("No device tokens (columns) found to publish")
        return 1
    if not rows:
        print("No rows selected to publish; adjust ROW_LIMIT/START_ROW")
        return 1

    print(f"TB base={TB_HTTP_BASE} devices={len(tokens)} rows={len(rows)} key='{KEY_NAME}' dry_run={DRY_RUN}")

    futures = []
    results: Dict[str, tuple[int, int]] = {}
    try:
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            for col_offset, token in enumerate(tokens, start=1):
                futures.append(pool.submit(process_device, token, rows, col_offset))
            for fut in as_completed(futures):
                token, sent, failed = fut.result()
                results[token] = (sent, failed)
                print(f"device token={token} sent={sent} failed={failed}")
    except requests.exceptions.RequestException as e:
        # Likely connection refused/closed on HTTP transport; try MQTT fallback
        print(f"HTTP transport error: {e}. Falling back to MQTT...")
        total, failures = _fallback_publish_mqtt(tokens, rows)
        print(f"MQTT fallback complete. total sent={total}, failures={failures}")
        return 0 if failures == 0 else 2

    total = sum(s for s, _ in results.values())
    failures = sum(f for _, f in results.values())
    print(f"Done. total points sent={total} failures={failures} devices={len(results)}")
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())


# $env:TB_HTTP_BASE = 'http://localhost:8080'
# $env:DEVICE_LIMIT = '999999'
# $env:ROW_LIMIT    = '999999999'
# $env:BATCH_SIZE   = '200'   # tune 100–500
# $env:CONCURRENCY  = '2'     # start low; raise after verifying
# Remove-Item Env:DRY_RUN -ErrorAction SilentlyContinue

# python "c:\Users\suhas\Documents\GitHub\OntoBot\bldg3\trial\dataset\06_publish_csv_to_thingsboard.py"