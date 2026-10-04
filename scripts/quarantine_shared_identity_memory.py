# -*- coding: utf-8 -*-
"""F1 part (3), QA-trial plan (2026-10-04): the shared-fallback-identity quarantine.

Why this exists. `resolve_forwarded_user()` (orchestrator/main.py) falls back to the fixed
identity ``"openwebui_user"`` for any request Open WebUI cannot attribute to a real account.
Before this session's fix to `_orchestrator.py`'s two agent-memory call sites, both the
cross-session memory WRITE and READ filtered only by that one shared id with no check that it
was not the fallback -- so every unrecognised tester's question and answer summary (figures
included) landed in, and could be retrieved back from, ONE shared Qdrant partition. The code
fix stops this growing or being read FROM NOW ON; it does nothing about points already there.

This script finds and, only on request, deletes those pre-existing points. It never touches a
point stored under any other user_id -- a real resolved identity's memory is left alone.

    python scripts/quarantine_shared_identity_memory.py                 # dry run: just count
    python scripts/quarantine_shared_identity_memory.py --delete        # actually delete them

Talks to Qdrant's REST API directly (http://localhost:6333 by default, or $QDRANT_URL), the
same collection agent_memory.py uses (`user_memory`). No docker exec, no redis-cli dependency.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict

import httpx

COLLECTION_NAME = "user_memory"
FALLBACK_USER_ID = "openwebui_user"


def _qdrant_url() -> str:
    return os.environ.get("QDRANT_URL", "http://localhost:6333").rstrip("/")


def _count_fallback_points(client: httpx.Client) -> int:
    resp = client.post(
        f"/collections/{COLLECTION_NAME}/points/count",
        json={
            "filter": {
                "must": [{"key": "user_id", "match": {"value": FALLBACK_USER_ID}}],
            },
            "exact": True,
        },
    )
    resp.raise_for_status()
    return int(resp.json()["result"]["count"])


def _total_points(client: httpx.Client) -> int:
    resp = client.get(f"/collections/{COLLECTION_NAME}")
    resp.raise_for_status()
    return int(resp.json()["result"]["points_count"])


def _delete_fallback_points(client: httpx.Client) -> Dict[str, Any]:
    resp = client.post(
        f"/collections/{COLLECTION_NAME}/points/delete",
        json={
            "filter": {
                "must": [{"key": "user_id", "match": {"value": FALLBACK_USER_ID}}],
            },
        },
    )
    resp.raise_for_status()
    return resp.json()["result"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually delete the fallback-identity points. Default is a dry-run count only.",
    )
    args = parser.parse_args()

    with httpx.Client(base_url=_qdrant_url(), timeout=30.0) as client:
        try:
            total = _total_points(client)
        except httpx.HTTPStatusError as exc:
            print(f"Could not reach collection {COLLECTION_NAME!r}: {exc}", file=sys.stderr)
            return 1

        fallback_count = _count_fallback_points(client)
        other_count = total - fallback_count
        print(f"Collection {COLLECTION_NAME!r}: {total} point(s) total.")
        print(f"  Under the shared fallback identity {FALLBACK_USER_ID!r}: {fallback_count}")
        print(f"  Under a real, resolved identity: {other_count}")

        if fallback_count == 0:
            print("Nothing to quarantine.")
            return 0

        if not args.delete:
            print("\nDRY RUN -- nothing deleted. Re-run with --delete to remove these points.")
            return 0

        result = _delete_fallback_points(client)
        print(f"\nDeleted. Qdrant operation status: {result.get('status')}")
        # The delete above is acknowledged asynchronously -- a count taken immediately
        # after can still see the old number for a moment (measured live: 1745 -> 1732
        # on the first recheck, 0 a few seconds later). Poll briefly rather than report
        # a false failure for what is actually a timing artefact, not a failed delete.
        import time

        remaining = _count_fallback_points(client)
        for _ in range(10):
            if remaining == 0:
                break
            time.sleep(1.0)
            remaining = _count_fallback_points(client)
        print(f"Points remaining under {FALLBACK_USER_ID!r}: {remaining}")
        return 0 if remaining == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
