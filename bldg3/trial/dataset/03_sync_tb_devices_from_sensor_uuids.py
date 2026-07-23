import os
import sys
import csv
import time
import json
from typing import Dict, List, Tuple, Optional

import requests


def read_sensor_uuids(file_path: str) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or len(row) < 2:
                continue
            name, uid = row[0].strip(), row[1].strip()
            if name and uid:
                pairs.append((name, uid))
    return pairs


class TBClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.token: Optional[str] = None

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Authorization"] = f"Bearer {self.token}"
        return headers

    def login(self) -> None:
        url = f"{self.base_url}/api/auth/login"
        resp = self.session.post(url, json={"username": self.username, "password": self.password})
        resp.raise_for_status()
        data = resp.json()
        self.token = data.get("token") or data.get("accessToken")
        if not self.token:
            raise RuntimeError("Failed to obtain ThingsBoard JWT token from login response")

    def get_device_by_name(self, name: str) -> Optional[Dict]:
        url = f"{self.base_url}/api/tenant/devices?deviceName={requests.utils.quote(name)}"
        resp = self.session.get(url, headers=self._headers())
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json() if resp.text else None

    def list_all_devices(self, page_size: int = 1000) -> List[Dict]:
        # Paginated fetch of all tenant devices
        devices: List[Dict] = []
        page = 0
        while True:
            url = f"{self.base_url}/api/tenant/devices?pageSize={page_size}&page={page}"
            resp = self.session.get(url, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", []) if isinstance(data, dict) else []
            devices.extend(items)
            has_next = bool(data.get("hasNext")) if isinstance(data, dict) else False
            if not has_next or not items:
                break
            page += 1
        return devices

    def create_device(self, name: str, label: Optional[str] = None, device_type: Optional[str] = None) -> Dict:
        url = f"{self.base_url}/api/device"
        payload: Dict[str, Optional[str]] = {"name": name}
        if label:
            payload["label"] = label
        if device_type:
            payload["type"] = device_type
        resp = self.session.post(url, headers=self._headers(), data=json.dumps(payload))
        resp.raise_for_status()
        return resp.json()

    def update_device(self, device: Dict) -> Dict:
        # ThingsBoard uses the same POST /api/device to create or update; include 'id' to update
        url = f"{self.base_url}/api/device"
        resp = self.session.post(url, headers=self._headers(), data=json.dumps(device))
        resp.raise_for_status()
        return resp.json()

    def delete_device(self, device_id: str) -> None:
        url = f"{self.base_url}/api/device/{device_id}"
        resp = self.session.delete(url, headers=self._headers())
        if resp.status_code not in (200, 202):
            resp.raise_for_status()

    def get_device_credentials(self, device_id: str) -> Dict:
        url = f"{self.base_url}/api/device/{device_id}/credentials"
        resp = self.session.get(url, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def update_device_credentials(self, creds_obj: Dict) -> Dict:
        url = f"{self.base_url}/api/device/credentials"
        resp = self.session.post(url, headers=self._headers(), data=json.dumps(creds_obj))
        resp.raise_for_status()
        return resp.json()

    def ensure_access_token(self, device_id: str, desired_token: str) -> Tuple[bool, str]:
        creds = self.get_device_credentials(device_id)
        current = creds.get("credentialsId")
        if current == desired_token:
            return False, current or ""
        # Update token
        creds["credentialsType"] = "ACCESS_TOKEN"
        creds["credentialsId"] = desired_token
        updated = self.update_device_credentials(creds)
        return True, updated.get("credentialsId", "")


def sync_devices(
    tb: TBClient,
    desired_pairs: List[Tuple[str, str]],
    label: str,
    device_type: str,
    dry_run: bool = True,
) -> None:
    desired_names = {name for name, _ in desired_pairs}
    desired_by_name = {name: token for name, token in desired_pairs}

    # Fetch all existing devices once
    existing = tb.list_all_devices()
    # Map of all devices by name (first occurrence wins)
    all_by_name: Dict[str, Dict] = {}
    for dev in existing:
        name = dev.get("name")
        if name and name not in all_by_name:
            all_by_name[name] = dev
    # Subset under our label scope (for safe deletions)
    labeled_by_name: Dict[str, Dict] = {dev.get("name"): dev for dev in existing if (dev.get("label") or "") == label}

    actions: List[str] = []

    # Plan deletions for any labeled device not in desired list
    for name, dev in labeled_by_name.items():
        if name not in desired_names:
            actions.append(f"DELETE device '{name}' id={dev.get('id', {}).get('id')}")
            if not dry_run:
                tb.delete_device(dev.get("id", {}).get("id"))

    # Create/update desired devices
    for name, token in desired_pairs:
        if name in all_by_name:
            dev = all_by_name[name]
            dev_id = dev.get("id", {}).get("id")
            # Ensure label and type
            needs_meta_update = (dev.get("label") or "") != label or (dev.get("type") or "") != device_type
            if dry_run:
                if needs_meta_update:
                    actions.append(f"UPDATE device meta for '{name}' -> label='{label}', type='{device_type}'")
                actions.append(f"ENSURE TOKEN for '{name}' -> {token}")
            else:
                if needs_meta_update:
                    desired_dev = {
                        "id": dev.get("id"),
                        "name": dev.get("name"),
                        "type": device_type,
                        "label": label,
                    }
                    tb.update_device(desired_dev)
                changed, new_token = tb.ensure_access_token(dev_id, token)
                if changed:
                    actions.append(f"UPDATED TOKEN for '{name}' -> {new_token}")
        else:
            actions.append(f"CREATE device '{name}' with label='{label}', type='{device_type}', token={token}")
            if not dry_run:
                created = tb.create_device(name=name, label=label, device_type=device_type)
                dev_id = created.get("id", {}).get("id")
                tb.ensure_access_token(dev_id, token)

    # Print summary
    print("\nPlanned actions:" if dry_run else "\nActions performed:")
    for a in actions:
        print(" - ", a)
    print(
        f"\nSummary: desired={len(desired_pairs)} | existing(total)={len(all_by_name)} | existing(label={label})={len(labeled_by_name)} | dry_run={dry_run}"
    )


def verify_devices(tb: TBClient, desired_pairs: List[Tuple[str, str]], label: str) -> int:
    desired_by_name = {name: token for name, token in desired_pairs}
    existing = tb.list_all_devices()
    mismatches = 0

    # Only consider devices under the label scope
    for dev in existing:
        if (dev.get("label") or "") != label:
            continue
        name = dev.get("name")
        if name not in desired_by_name:
            print(f"EXTRA device present (not in file): {name}")
            mismatches += 1
            continue
        # Check token
        dev_id = dev.get("id", {}).get("id")
        creds = tb.get_device_credentials(dev_id)
        token = creds.get("credentialsId")
        if token != desired_by_name[name]:
            print(f"TOKEN MISMATCH for {name}: tb='{token}' vs file='{desired_by_name[name]}'")
            mismatches += 1

    # Check missing devices
    existing_names = {dev.get("name") for dev in existing if (dev.get("label") or "") == label}
    for name in desired_by_name.keys():
        if name not in existing_names:
            print(f"MISSING device (in file, not in TB): {name}")
            mismatches += 1

    if mismatches == 0:
        print(f"All devices under label '{label}' match sensor_uuids file.")
    else:
        print(f"Total mismatches: {mismatches}")
    return mismatches


def main():
    sensor_file = os.environ.get("SENSOR_UUIDS_FILE", os.path.join(os.path.dirname(__file__), "sensor_uuids.txt"))
    tb_url = os.environ.get("TB_URL", "http://localhost:8082")
    tb_user = os.environ.get("TB_USERNAME", "tenant@thingsboard.org")
    tb_pass = os.environ.get("TB_PASSWORD", "tenant")
    tb_label = os.environ.get("TB_LABEL", "bldg3")
    device_type = os.environ.get("TB_DEVICE_TYPE", "bldg3-sensor")
    dry_run = os.environ.get("DRY_RUN", "true").lower() in ("1", "true", "yes")
    verify_only = os.environ.get("VERIFY_ONLY", "false").lower() in ("1", "true", "yes")

    pairs = read_sensor_uuids(sensor_file)
    if not pairs:
        print(f"No name,uuid pairs found in {sensor_file}")
        sys.exit(2)

    tb = TBClient(tb_url, tb_user, tb_pass)
    tb.login()

    if verify_only:
        rc = verify_devices(tb, pairs, tb_label)
        sys.exit(0 if rc == 0 else 1)

    sync_devices(tb, pairs, tb_label, device_type, dry_run=dry_run)
    # Always verify after non-dry run
    if not dry_run:
        print("\nVerifying...")
        rc = verify_devices(tb, pairs, tb_label)
        sys.exit(0 if rc == 0 else 1)


if __name__ == "__main__":
    main()
