"""
Bulk-create ThingsBoard devices from a CSV file (name,uuid) without using the UI.

Interpretation:
- First column: device name (string)
- Second column: desired access token (uuid or any unique string)

What this script does:
1) Authenticates as Tenant Admin
2) For each (name, token) pair:
   - If a device with that name exists, reuse it; otherwise create it
   - Set/override the device credentials to ACCESS_TOKEN = token

Environment variables (PowerShell examples shown below):
  TB_BASE            Base URL for ThingsBoard REST (default http://localhost:8082)
  TB_TENANT_EMAIL    Tenant admin email (default tenant@thingsboard.org)
  TB_TENANT_PASSWORD Tenant admin password (default tenant)
  TB_DEVICE_TYPE     Default device type when creating (default 'default')

Usage (PowerShell):
  $env:TB_BASE = 'http://localhost:8082'
  $env:TB_TENANT_EMAIL = 'tenant@thingsboard.org'
  $env:TB_TENANT_PASSWORD = 'tenant'
  $env:TB_DEVICE_TYPE = 'sensor'
  python create_devices_from_csv.py sensor_uuids.txt

Notes:
- You can re-run safely to upsert tokens.
- If you get 401s, confirm TB_BASE points to the port mapped to 9090 in docker-compose (8082 in this repo).
"""
from __future__ import annotations

import csv
import os
import sys
from typing import Optional, Tuple

try:
    import requests
except Exception as e:
    print("Error: 'requests' package is required. Install with 'pip install requests'.")
    raise


def tb_base() -> str:
    # Default to localhost mapping from compose; override with TB_BASE if needed
    return os.getenv("TB_BASE", "http://localhost:8082").rstrip("/")


def login(email: str, password: str) -> str:
    url = f"{tb_base()}/api/auth/login"
    resp = requests.post(url, json={"username": email, "password": password}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("token") or data.get("jwtToken")


def get_device_by_name(token: str, name: str) -> Optional[dict]:
    # ThingsBoard CE supports lookup by exact name
    url = f"{tb_base()}/api/tenant/devices?deviceName={requests.utils.quote(name)}"
    headers = {"X-Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 404:
        return None
    # In some versions, this endpoint may not exist; fall back to paged search
    if resp.status_code == 400:
        # Fallback: search first page; adjust if you have many devices
        url2 = f"{tb_base()}/api/tenant/devices?pageSize=100&page=0&textSearch={requests.utils.quote(name)}"
        r2 = requests.get(url2, headers=headers, timeout=15)
        if r2.ok:
            data = r2.json() or {}
            for item in data.get("data", []):
                if item.get("name") == name:
                    return item
            return None
    resp.raise_for_status()
    return None


def create_device(token: str, name: str, dev_type: str) -> dict:
    url = f"{tb_base()}/api/device"
    headers = {"X-Authorization": f"Bearer {token}"}
    payload = {"name": name, "type": dev_type}
    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_device_credentials(token: str, device_id: str) -> dict:
    """Fetch credentials using both API variants for compatibility.

    Prefer newer path endpoint, then fall back to legacy query param.
    """
    headers = {"X-Authorization": f"Bearer {token}"}
    base = tb_base()
    # Preferred: path param (newer TB)
    url2 = f"{base}/api/device/{device_id}/credentials"
    resp2 = requests.get(url2, headers=headers, timeout=15)
    if resp2.ok:
        try:
            return resp2.json() or {}
        except ValueError:
            return {}
    # Fallback: query param
    url1 = f"{base}/api/device/credentials?deviceId={device_id}"
    resp1 = requests.get(url1, headers=headers, timeout=15)
    if resp1.ok:
        try:
            return resp1.json() or {}
        except ValueError:
            return {}
    # Neither worked; raise with details
    raise requests.HTTPError(
        f"GET creds failed: primary={resp2.status_code} {resp2.text} | alt={resp1.status_code} {resp1.text}",
        response=resp2 if resp2 is not None else resp1,
    )


def save_device_credentials(token: str, device_id: str, credentials_id: Optional[str], new_token: str) -> dict:
    """Update device credentials to a specific access token.

    ThingsBoard 3.6 expects PUT for updates (POST attempts to create and will 400 if creds already exist).
    We'll default to PUT, include creds id when known, and if server still complains, try the alternate flow.
    """
    base = tb_base()
    headers = {"X-Authorization": f"Bearer {token}"}

    payload = {
        "credentialsType": "ACCESS_TOKEN",
        "credentialsId": new_token,
        "deviceId": {"entityType": "DEVICE", "id": device_id},
    }
    if credentials_id:
        payload["id"] = {"entityType": "DEVICE_CREDENTIALS", "id": credentials_id}

    # If we have an existing credentials id, prefer POST update with 'id' in a minimal form (TB 3.6 path)
    # Also try a minimal 'id' representation if the full entity object is not accepted by validator
    if credentials_id:
        payload_with_min_id = {
            "id": {"id": credentials_id},
            "credentialsType": "ACCESS_TOKEN",
            "credentialsId": new_token,
            "deviceId": {"id": device_id},
        }
        url_post = f"{base}/api/device/credentials"
        resp = requests.post(url_post, json=payload_with_min_id, headers=headers, timeout=15)
        if resp.ok:
            return resp.json()

    # If we get a 400 complaining credentials already specified, fall back to fetching id and retry
    if 'resp' in locals() and resp is not None and resp.status_code == 400 and "already specified" in (resp.text or "").lower():
        # Try to fetch credentials to get the id, then retry PUT with id
        try:
            creds = get_device_credentials(token, device_id)
            cred_id = creds.get("id", {}).get("id") if isinstance(creds.get("id"), dict) else creds.get("id")
            if cred_id:
                # Retry POST update with the resolved id
                retry_payload = {
                    "id": {"id": cred_id},
                    "credentialsType": "ACCESS_TOKEN",
                    "credentialsId": new_token,
                    "deviceId": {"id": device_id},
                }
                url_post_retry = f"{base}/api/device/credentials"
                resp2 = requests.post(url_post_retry, json=retry_payload, headers=headers, timeout=15)
                if resp2.ok:
                    return resp2.json()
                # If still failing, raise with new context
                raise requests.HTTPError(
                    f"POST creds (with id) failed {resp2.status_code}: {resp2.text}", response=resp2
                )
        except Exception:
            # proceed to raise original error below
            pass

    # As a last resort, try POST only when there is no credentials id and the server might accept create
    if not credentials_id:
        url_post = f"{base}/api/device/credentials"
        resp3 = requests.post(url_post, json=payload, headers=headers, timeout=15)
        if resp3.ok:
            return resp3.json()
        raise requests.HTTPError(f"POST creds failed {resp3.status_code}: {resp3.text}", response=resp3)

    # Default: raise the original PUT failure
    msg = resp.text
    raise requests.HTTPError(f"PUT creds failed {resp.status_code}: {msg}", response=resp)


def parse_line(row: list[str]) -> Optional[Tuple[str, str]]:
    if not row:
        return None
    # expect at least 2 columns: name,uuid
    name = (row[0] or "").strip()
    token = (row[1] if len(row) > 1 else "").strip()
    if not name:
        return None
    if not token:
        # If token missing, we can still create the device; token will be auto-assigned by TB
        return name, ""
    return name, token


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: python create_devices_from_csv.py <sensor_uuids.txt>")
        return 2
    path = argv[1]
    email = os.getenv("TB_TENANT_EMAIL", "tenant@thingsboard.org")
    password = os.getenv("TB_TENANT_PASSWORD", "tenant")
    dev_type = os.getenv("TB_DEVICE_TYPE", "default")

    try:
        token = login(email, password)
    except Exception as e:
        print(f"Login failed: {e}")
        return 1

    created = 0
    updated = 0
    skipped = 0

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for line_no, row in enumerate(reader, start=1):
            parsed = parse_line(row)
            if not parsed:
                skipped += 1
                continue
            name, access_token = parsed
            try:
                existing = get_device_by_name(token, name)
                if existing:
                    device_id = existing.get("id", {}).get("id") or existing.get("id")
                    if not device_id:
                        print(f"[{line_no}] Found device '{name}' but no ID in response; skipping")
                        skipped += 1
                        continue
                    # Set or update credentials if a token is provided
                    if access_token:
                        creds = get_device_credentials(token, device_id)
                        current_token = (creds or {}).get("credentialsId")
                        if current_token == access_token:
                            print(f"[{line_no}] Device '{name}' already has desired token; no change")
                            skipped += 1
                        else:
                            cred_id = creds.get("id", {}).get("id") if isinstance(creds.get("id"), dict) else creds.get("id")
                            save_device_credentials(token, device_id, cred_id, access_token)
                            updated += 1
                            print(f"[{line_no}] Updated token for existing device '{name}'")
                    else:
                        print(f"[{line_no}] Device '{name}' exists; no token provided; left unchanged")
                        skipped += 1
                else:
                    new_dev = create_device(token, name, dev_type)
                    device_id = new_dev.get("id", {}).get("id")
                    if not device_id:
                        print(f"[{line_no}] Created device '{name}' but did not get a device ID; skipping token set")
                        created += 1
                        continue
                    if access_token:
                        save_device_credentials(token, device_id, None, access_token)
                    created += 1
                    print(f"[{line_no}] Created device '{name}' with token set")
            except requests.HTTPError as he:
                body = getattr(he, 'response', None).text if getattr(he, 'response', None) else ''
                print(f"[{line_no}] HTTP error for '{name}': {he} | body={body}")
                skipped += 1
            except Exception as e:
                print(f"[{line_no}] Error for '{name}': {e}")
                skipped += 1

    print(f"Done. created={created}, updated={updated}, skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))


# Usage: python create_devices_from_sensor_uuid_to_tb.py sensor_uuids.txt