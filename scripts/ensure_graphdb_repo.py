#!/usr/bin/env python3
"""
ensure_graphdb_repo.py — building-agnostic GraphDB repository provisioning.

A fresh GraphDB volume has NO repositories, so the ttl_uploader has nowhere to load
the building's ontology and the boot would halt. This waits for GraphDB, then creates
the configured repository from a standard config if it does not already exist. The repo
id is the SAME for every building (buildings differ by namespace/data, not repo), so one
config serves all.

Idempotent: does nothing if the repo already exists. Building-agnostic: repo id + URL from
env; config path is a plain file.

Env:  GRAPHDB_HTTP (default http://127.0.0.1:7200), GRAPHDB_REPOSITORY (default bldg),
      GRAPHDB_REPO_CONFIG (default config/graphdb_repo_bldg.ttl)
"""
from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request

GRAPHDB = os.environ.get("GRAPHDB_HTTP", "http://127.0.0.1:7200")
REPO = os.environ.get("GRAPHDB_REPOSITORY", "bldg")
CONFIG = os.environ.get("GRAPHDB_REPO_CONFIG", "config/graphdb_repo_bldg.ttl")


def _get(url: str, timeout: int = 5):
    return urllib.request.urlopen(urllib.request.Request(url), timeout=timeout)


def _wait_ready(deadline_s: int = 180) -> None:
    end = time.time() + deadline_s
    while time.time() < end:
        try:
            if _get(f"{GRAPHDB}/rest/repositories").status == 200:
                return
        except Exception:
            pass
        time.sleep(3)
    raise SystemExit(f"[repo] GraphDB not ready at {GRAPHDB} after {deadline_s}s")


def _repo_exists() -> bool:
    try:
        body = _get(f"{GRAPHDB}/rest/repositories").read().decode("utf-8", "replace")
        return f'"{REPO}"' in body or f"/repositories/{REPO}" in body
    except Exception:
        return False


def _create() -> None:
    if not os.path.exists(CONFIG):
        raise SystemExit(f"[repo] repo config not found: {CONFIG}")
    # GraphDB REST multipart: field name 'config' = the repo config TTL.
    boundary = "----ontosagerepoboundary"
    with open(CONFIG, "rb") as fh:
        cfg = fh.read()
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="config"; filename="config.ttl"\r\n'
            f"Content-Type: text/turtle\r\n\r\n"
        ).encode()
        + cfg
        + f"\r\n--{boundary}--\r\n".encode()
    )
    req = urllib.request.Request(
        f"{GRAPHDB}/rest/repositories",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        print(f"[repo] created repository '{REPO}' (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise SystemExit(f"[repo] create failed HTTP {e.code}: {detail}")


def main() -> int:
    _wait_ready()
    if _repo_exists():
        print(f"[repo] repository '{REPO}' already exists — nothing to do")
        return 0
    _create()
    return 0


if __name__ == "__main__":
    sys.exit(main())
