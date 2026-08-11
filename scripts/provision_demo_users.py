# -*- coding: utf-8 -*-
"""Provision the demo/tester accounts for the ACTIVE building.

Accounts are per-building: OntoSage users live in that building's Postgres volume and
Open WebUI users in its own SQLite, both under ``volumes/<BUILDING_ID>/``. Switching
buildings therefore starts from zero accounts — this script recreates the same roster
from a credentials CSV so every building offers the same logins and roles.

Creates each account in BOTH systems:
  * OntoSage  (username + role)  → drives RBAC: what the answer is allowed to contain
  * Open WebUI (email + password) → the chat login itself

Idempotent: existing accounts are skipped, so it is safe to re-run. Paced under the
API's rate limit (60 requests / 60 s), which is what makes bulk work fail otherwise.

USAGE
    python scripts/provision_demo_users.py user_credentials_bldg1.csv
    python scripts/provision_demo_users.py creds.csv --ontosage-only
CSV columns: username,password,role,email
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
API = "http://127.0.0.1:8000"
CHAT = "http://127.0.0.1:3000"
DELAY = 1.15  # stays inside the fixed 60/60s window


def _env(name: str, default: str = "") -> str:
    import os

    if os.environ.get(name):
        return os.environ[name]
    try:
        for line in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return default


def _call(url: str, payload=None, token=None, method="GET"):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", token)
    for _ in range(6):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return True, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("Retry-After", "60"))
                print(f"    [429] waiting {wait}s…", flush=True)
                time.sleep(wait + 1)
                continue
            return False, e.read().decode()[:120]
        except Exception as e:  # noqa: BLE001
            return False, str(e)[:120]
    return False, "repeated 429s"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", help="credentials CSV: username,password,role,email")
    ap.add_argument("--ontosage-only", action="store_true", help="skip Open WebUI accounts")
    ap.add_argument("--chat-only", action="store_true", help="skip OntoSage accounts")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.csv, encoding="utf-8")))
    building = _env("BUILDING_ID", "unknown")
    print(f"[provision] building={building} · {len(rows)} accounts from {args.csv}")

    token = None
    if not args.chat_only:
        ok, body = _call(
            f"{API}/auth/login",
            {"username": _env("ADMIN_USERNAME"), "password": _env("ADMIN_PASSWORD")},
            method="POST",
        )
        if not ok:
            sys.exit(f"admin login failed: {body}")
        token = body["data"]["session_token"]

    made = skipped = failed = 0
    for r in rows:
        if not args.chat_only:
            ok, body = _call(
                f"{API}/api/v1/admin/users",
                {
                    "username": r["username"],
                    "password": r["password"],
                    "role": r["role"],
                    "email": r.get("email") or None,
                },
                token=token,
                method="POST",
            )
            if ok and body.get("success"):
                made += 1
            elif "already exists" in str(body):
                skipped += 1
            else:
                failed += 1
                print(f"   ontosage FAIL {r['username']}: {str(body)[:90]}")
            time.sleep(DELAY)

        if not args.ontosage_only:
            ok, body = _call(
                f"{CHAT}/api/v1/auths/signup",
                {"name": r["username"], "email": r["email"], "password": r["password"]},
                method="POST",
            )
            if not ok and "already" not in str(body).lower():
                print(f"   chat FAIL {r['email']}: {str(body)[:90]}")
            time.sleep(0.25)

    print(f"[provision] ontosage: created={made} existing={skipped} failed={failed}")
    print("[provision] roles apply on the next question — no restart needed.")


if __name__ == "__main__":
    main()
