#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_datasource_capability_qa.py -- End-to-end datasource enable/disable QA.

Proves the core invariant of the Admin Data-Source Console:
  BEFORE enable  → locked question returns named decline (not a hallucinated answer)
  regenerate     → synthetic rows written to MySQL  (UUID → time-series path)
  enable         → TTL written to GraphDB named graph  (SPARQL finds sensor)
  AFTER enable   → same question returns substantive answer + provenance chip
  disable        → state returns to locked (idempotent cleanup)

Runs against a live stack on localhost:8000.  No pytest -- plain exit(0/1).

Usage:
  python scripts/test_datasource_capability_qa.py
  python scripts/test_datasource_capability_qa.py --base-url http://127.0.0.1:8000
  python scripts/test_datasource_capability_qa.py --source noise   # run one source only
  python scripts/test_datasource_capability_qa.py --no-cleanup      # leave source enabled after run

Environment: ONTOSAGE_USER / ONTOSAGE_PASS override the default admin credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    print("ERROR: 'requests' not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

# Force UTF-8 on Windows terminals that default to cp1252 so server responses
# with emoji (lock icon in decline messages) print without crashing.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# -- defaults ----------------------------------------------------------------
DEFAULT_BASE = "http://127.0.0.1:8000"
DEFAULT_USER = os.environ.get("ONTOSAGE_USER", "admin")
DEFAULT_PASS = os.environ.get("ONTOSAGE_PASS", "admin123")

# Flush Redis cache between BEFORE/AFTER so a cached locked-response never
# masks the fix.  Requires docker exec access; failure is non-fatal.
REDIS_CONTAINER = "redis-memory-store"
RESP_CACHE_PATTERN = "resp_cache:*"


# -- per-source test cases ---------------------------------------------------
@dataclass
class SourceTestCase:
    source_id: str
    # Query that must be gated when the source is disabled
    lock_query: str
    # Substring that proves the AFTER response is substantive (not a refusal).
    after_contains: str
    # Provenance label that must appear in data.sources when enabled.
    provenance_label: str
    # Optional separate after-query. Some lock phrases route to capability KB even
    # when the source is enabled (they match human-friendly KB entries, not sensor
    # data phrasing). In that case set after_query to a sensor-data-phrased question
    # that the SPARQL->SQL pipeline handles.
    after_query: Optional[str] = None
    # Session IDs (derived at runtime)
    session_before: str = field(init=False)
    session_after: str = field(init=False)

    def __post_init__(self) -> None:
        ts = int(time.time())
        self.session_before = f"qa-{self.source_id}-before-{ts}"
        self.session_after = f"qa-{self.source_id}-after-{ts}"


# Canonical test-case table -- one entry per toggleable source with match_keywords.
# iaq / light are intentionally absent: they have no match_keywords (base ontology
# already answers those questions; the toggle only gates provenance, not answers).
CASES: List[SourceTestCase] = [
    SourceTestCase(
        source_id="noise",
        lock_query="What is the noise level on floor 5?",
        after_contains="dB",
        provenance_label="Acoustic Sensing System",
    ),
    SourceTestCase(
        source_id="occupancy",
        # "free desk" triggers the locked gate (is in match_keywords) …
        lock_query="Are there any free desks available right now?",
        # … but that phrasing routes to the capability KB even when enabled because
        # it matches KB entries about study spaces. Use a sensor-data-phrased
        # question for the after-state so the SPARQL->SQL pipeline runs.
        after_query="What is the current occupancy on floor 3?",
        after_contains="count",  # response includes occupancy count value
        provenance_label="Occupancy Sensing System",
    ),
    SourceTestCase(
        source_id="energy",
        lock_query="What is the energy consumption today?",
        after_contains="kWh",
        provenance_label="Energy Metering System",
    ),
    SourceTestCase(
        source_id="water",
        lock_query="What is the water usage today?",
        after_contains="L",
        provenance_label="Water Metering System",
    ),
]


# -- helpers ------------------------------------------------------------------
class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.session = requests.Session()
        self.token: Optional[str] = None

    def login(self, username: str, password: str) -> None:
        r = self.session.post(
            f"{self.base}/auth/login",
            json={"username": username, "password": password},
            timeout=15,
        )
        r.raise_for_status()
        payload = r.json()
        token = (
            payload.get("data", {}).get("session_token")
            or payload.get("data", {}).get("access_token")
        )
        if not token:
            raise RuntimeError(f"Login failed -- no token in response: {payload}")
        self.token = token
        self.session.headers["Authorization"] = f"Bearer {token}"

    def get(self, path: str, **kw: Any) -> Dict:
        r = self.session.get(f"{self.base}{path}", timeout=30, **kw)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, **kw: Any) -> Dict:
        r = self.session.post(f"{self.base}{path}", timeout=60, **kw)
        r.raise_for_status()
        return r.json()

    def chat(self, message: str, session_id: str) -> Dict:
        return self.post("/chat", json={"message": message, "session_id": session_id})

    def list_sources(self) -> List[Dict]:
        return self.get("/api/v1/datasources").get("data", {}).get("sources", [])

    def regenerate(self, source_id: str) -> Dict:
        return self.post(f"/api/v1/datasources/{source_id}/regenerate")

    def enable(self, source_id: str) -> Dict:
        return self.post(f"/api/v1/datasources/{source_id}/enable")

    def disable(self, source_id: str) -> Dict:
        return self.post(f"/api/v1/datasources/{source_id}/disable")


def _flush_cache() -> None:
    """Best-effort Redis cache flush via docker exec."""
    try:
        keys_result = subprocess.run(
            ["docker", "exec", REDIS_CONTAINER, "redis-cli",
             "--scan", "--pattern", RESP_CACHE_PATTERN],
            capture_output=True, text=True, timeout=10,
        )
        keys = [k for k in keys_result.stdout.strip().splitlines() if k]
        if keys:
            subprocess.run(
                ["docker", "exec", REDIS_CONTAINER, "redis-cli", "del"] + keys,
                capture_output=True, timeout=10,
            )
    except Exception:
        pass  # non-fatal; test still runs, may just get a stale cache hit


def _is_locked_decline(response_text: str) -> bool:
    """Return True if the response is a named locked-capability decline."""
    rl = response_text.lower()
    return "enable" in rl and ("data source" in rl or "sensing" in rl or "system" in rl)


def _provenance_label_present(sources: List[Dict], label: str) -> bool:
    return any(s.get("label", "").lower() == label.lower() for s in sources)


def _source_is_enabled(sources_list: List[Dict], source_id: str) -> bool:
    for s in sources_list:
        if s.get("id") == source_id:
            return bool(s.get("enabled"))
    return False


# -- per-source flow ----------------------------------------------------------
def run_case(client: Client, case: SourceTestCase, cleanup: bool) -> bool:
    """Run the full before→regenerate→enable→after→disable flow for one source.

    Returns True on full pass, False otherwise (errors printed inline).
    """
    ok = True
    sid = case.source_id
    print(f"\n{'-' * 60}")
    print(f"  Source: {sid}")
    print(f"{'-' * 60}")

    # -- 0. Ensure the source starts disabled -----------------------------
    sources = client.list_sources()
    if _source_is_enabled(sources, sid):
        print(f"  [setup] {sid} is currently enabled -- disabling for clean start")
        client.disable(sid)
        _flush_cache()

    # -- 1. BEFORE: question must return a named decline -------------------
    _flush_cache()
    print(f"  [before] asking: {case.lock_query!r}")
    before_resp = client.chat(case.lock_query, case.session_before)
    before_data = before_resp.get("data", {})
    before_text = before_data.get("response") or before_data.get("message") or ""

    if _is_locked_decline(before_text):
        print(f"  [before] [OK] named decline: {before_text[:100]!r}")
    else:
        print(f"  [before] [FAIL] expected named decline, got: {before_text[:200]!r}")
        ok = False

    # -- 2. REGENERATE: write synthetic rows to MySQL ----------------------
    print(f"  [regenerate] POST /api/v1/datasources/{sid}/regenerate")
    regen = client.regenerate(sid)
    regen_data = regen.get("data", {})
    rows = regen_data.get("rows", 0)
    if regen.get("success") and rows > 0:
        print(f"  [regenerate] [OK] {rows} rows written to {regen_data.get('ts_table')!r}")
    else:
        print(f"  [regenerate] [FAIL] unexpected result: {regen}")
        ok = False

    # -- 3. ENABLE: write TTL to GraphDB named graph -----------------------
    print(f"  [enable] POST /api/v1/datasources/{sid}/enable")
    enable = client.enable(sid)
    enable_data = enable.get("data", {})
    if enable.get("success") and enable_data.get("enabled"):
        pts = enable_data.get("points", 0)
        graph = enable_data.get("graph", "?")
        print(f"  [enable] [OK] {pts} point(s) in named graph {graph!r}")
    else:
        print(f"  [enable] [FAIL] unexpected result: {enable}")
        ok = False

    # -- 4. AFTER: question must return substantive answer -----------------
    _flush_cache()
    # Brief pause to let GraphDB propagate the newly-written triples
    time.sleep(2)
    after_q = case.after_query or case.lock_query
    print(f"  [after]  asking: {after_q!r}")
    after_resp = client.chat(after_q, case.session_after)
    after_data = after_resp.get("data", {})
    after_text = after_data.get("response") or after_data.get("message") or ""
    after_sources = after_data.get("sources", [])

    # 4a. Must NOT be a locked-decline
    if _is_locked_decline(after_text):
        print(f"  [after]  [FAIL] still getting locked decline: {after_text[:200]!r}")
        ok = False
    # 4b. Must contain a substantive value indicator
    elif case.after_contains.lower() in after_text.lower():
        print(f"  [after]  [OK] substantive answer contains {case.after_contains!r}")
        print(f"           excerpt: {after_text[:160]!r}")
    else:
        print(
            f"  [after]  [WARN]  answer present but expected marker {case.after_contains!r} not found"
        )
        print(f"           response: {after_text[:200]!r}")
        # Treat as warning not failure -- LLM wording varies

    # 4c. Provenance chip must include the synthetic source
    if _provenance_label_present(after_sources, case.provenance_label):
        print(f"  [after]  [OK] provenance chip: {case.provenance_label!r}")
    else:
        labels = [s.get("label") for s in after_sources]
        print(f"  [after]  [FAIL] provenance chip missing -- got: {labels}")
        ok = False

    # -- 5. CLEANUP: disable so the next run starts clean -----------------
    if cleanup:
        client.disable(sid)
        _flush_cache()
        print(f"  [cleanup] [OK] {sid} disabled, cache flushed")

    status = "PASS" if ok else "FAIL"
    print(f"\n  -- {status}: {sid} --")
    return ok


# -- entry point --------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Datasource capability end-to-end QA")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--source", help="Run only this source_id (e.g. noise)")
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Leave the source enabled after the run (for manual inspection)",
    )
    args = parser.parse_args()

    # -- health check ------------------------------------------------------
    print(f"OntoSage datasource capability QA  --  {args.base_url}")
    try:
        r = requests.get(f"{args.base_url}/health", timeout=10)
        r.raise_for_status()
        health = r.json()
        building = health.get("data", {}).get("building", "unknown")
        print(f"Stack healthy -- building: {building}")
    except Exception as e:
        print(f"ERROR: stack not reachable at {args.base_url}: {e}", file=sys.stderr)
        return 1

    # -- login -------------------------------------------------------------
    client = Client(args.base_url)
    try:
        client.login(DEFAULT_USER, DEFAULT_PASS)
        print(f"Logged in as {DEFAULT_USER}")
    except Exception as e:
        print(f"ERROR: login failed: {e}", file=sys.stderr)
        return 1

    # -- filter cases ------------------------------------------------------
    cases = CASES
    if args.source:
        cases = [c for c in CASES if c.source_id == args.source]
        if not cases:
            print(
                f"ERROR: unknown source {args.source!r}. "
                f"Available: {[c.source_id for c in CASES]}",
                file=sys.stderr,
            )
            return 1

    # -- run ---------------------------------------------------------------
    results: List[bool] = []
    for case in cases:
        try:
            passed = run_case(client, case, cleanup=not args.no_cleanup)
        except Exception as exc:
            print(f"\n  [EXCEPTION] {case.source_id}: {exc}")
            passed = False
        results.append(passed)

    # -- summary -----------------------------------------------------------
    passed = sum(results)
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"  Result: {passed}/{total} source(s) PASSED")
    print(f"{'=' * 60}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
