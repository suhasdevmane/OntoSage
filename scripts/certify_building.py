#!/usr/bin/env python
"""Run a building's certification with the stack checked before AND after.

``run_all_graders.py`` already runs every grader and compiles one scorecard. This
wraps it with the thing that has gone wrong three separate times in this project:

* **CAVEAT-173 / BUG-176** — a container was recreated mid-run, and the run
  produced a 9.2%-coverage artifact that meant nothing.
* **BUG-177** — the LLM went down mid-run and its fallback text reads like an
  answer. One such fallback was a row dump that would have graded as a PASS.

Both were found afterwards, by reading rows behind a number that looked wrong.
Nothing stopped either run from starting or from publishing. The rule the project
wrote down — *grading a run is only valid if the stack was healthy for all of it*
— had no enforcement anywhere.

So this brackets the run:

**Before** — every service healthy, the active building is the one you asked for,
the LLM provider actually answers a trivial prompt, and the response cache is
flushed. Any failure aborts before a single question is asked; a run that cannot
be trusted is better not started than explained away later.

**After** — the same checks, plus container start-times compared against the
snapshot taken at the beginning. A container that restarted mid-run invalidates
the artifact, and the artifact says so IN ITS OWN TEXT rather than in a log
nobody re-reads.

Usage:
  python scripts/certify_building.py --expect bldg1
  python scripts/certify_building.py --expect bldg1 --quick
  python scripts/certify_building.py --expect bldg1 --preflight-only
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
HEALTH_URL = "http://127.0.0.1:8000/health"

# Read from the environment, never assumed: the repository name is per-deployment and
# the whole point of these scripts is that they do not carry building literals.
GRAPHDB_URL = os.getenv("GRAPHDB_URL_HOST", "http://127.0.0.1:7200").rstrip("/")
GRAPHDB_REPO = os.getenv("GRAPHDB_REPOSITORY", "bldg")
OUTPUTS = REPO / "scripts" / "outputs"


def _get(url: str, timeout: float = 10.0) -> Tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - local only
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def _active_building() -> Optional[str]:
    """The building the running stack is serving, from its own files."""
    env_building = REPO / "input" / "env.building"
    if not env_building.is_file():
        return None
    for line in env_building.read_text(encoding="utf-8").splitlines():
        if line.startswith("BUILDING_ID="):
            return line.split("=", 1)[1].strip()
    return None


def _container_snapshot() -> Dict[str, str]:
    """{container: started_at}. A change between snapshots means a restart."""
    try:
        out = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
    except Exception:  # pragma: no cover - docker may be absent
        return {}
    snap = {}
    for line in out.splitlines():
        if "\t" in line:
            name, status = line.split("\t", 1)
            snap[name.strip()] = status.strip()
    return snap


def _llm_answers() -> Tuple[bool, str]:
    """Does the configured provider actually answer? BUG-177's exact blind spot.

    A healthy container with a dead model still serves /health, and the fallback
    text reads enough like an answer to grade as one.
    """
    code, body = _get("http://127.0.0.1:8000/health", timeout=20)
    if code != 200:
        return False, f"/health returned {code}"
    try:
        data = json.loads(body)
    except ValueError:
        return True, "health did not return JSON; provider state unknown"
    services = data.get("services") or data.get("data", {}).get("services") or {}
    for key in ("ollama", "llm", "openai"):
        state = str(services.get(key, "")).lower()
        if state and state not in ("ok", "healthy", "skipped", "true"):
            return False, f"provider '{key}' reports '{state}'"
    return True, "provider reports healthy"


#: One sensor has one timeseries reference. Anything materially above 1 means the same
#: reference has been loaded more than once, each copy carrying fresh blank nodes that
#: nothing can dedupe. 1.5 is slack for a building that legitimately declares a second
#: reference on a few points; the disease shows up at 2.8, 27 and 95.
_MAX_REFERENCE_FANOUT = 1.5

_FANOUT_QUERY = (
    "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>\n"
    "SELECT (COUNT(?r) AS ?refs) (COUNT(DISTINCT ?u) AS ?uuids) "
    "WHERE { ?r ref:hasTimeseriesId ?u }"
)


def _graph_is_not_duplicated() -> Tuple[bool, str]:
    """Reference fan-out per UUID, which is what graph bloat looks like from outside.

    BUG-343: the fix that stopped the context-less writer lives in a docker IMAGE, and
    every building's compose project builds its own. bldg3 booted a four-week-old image
    and silently resumed duplicating -- source correct, tests green, suite passing, and
    the deployed thing still broken. No unit test can see that; this can, because it
    measures the symptom rather than trusting the fix.

    A count query is cheap and answers before any question is asked, which is the point:
    grading a duplicated graph produces numbers that mean nothing.
    """
    url = f"{GRAPHDB_URL}/repositories/{GRAPHDB_REPO}"
    try:
        req = urllib.request.Request(
            url,
            data=_FANOUT_QUERY.encode(),
            headers={
                "Content-Type": "application/sparql-query",
                "Accept": "text/csv",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310 - fixed local URL
            rows = r.read().decode("utf-8", "replace").strip().splitlines()
    except Exception as exc:
        # Unknown is not failure: a building may run without GraphDB reachable from here.
        return True, f"reference fan-out unknown ({exc})"

    if len(rows) < 2:
        return True, "reference fan-out unknown (no rows)"
    try:
        refs, uuids = (int(x) for x in rows[1].split(",")[:2])
    except ValueError:
        return True, "reference fan-out unknown (unparseable)"
    if uuids == 0:
        return True, "no timeseries references in the graph"

    fanout = refs / uuids
    if fanout > _MAX_REFERENCE_FANOUT:
        return False, (
            f"reference fan-out {fanout:.2f} copies/UUID ({refs} refs / {uuids} UUIDs) "
            f"-- the graph holds duplicates; rebuild before grading (BUG-343)"
        )
    return True, f"reference fan-out {fanout:.2f} copies/UUID ({uuids} UUIDs)"


def preflight(expect: Optional[str]) -> Tuple[bool, List[str], Dict[str, Any]]:
    checks: List[str] = []
    ok = True

    code, _ = _get(HEALTH_URL, timeout=15)
    healthy = code == 200
    checks.append(f"{'PASS' if healthy else 'FAIL'}  orchestrator /health -> {code or 'no answer'}")
    ok &= healthy

    active = _active_building()
    if expect:
        matched = active == expect
        checks.append(
            f"{'PASS' if matched else 'FAIL'}  active building is {active!r}, expected {expect!r}"
        )
        ok &= matched
    else:
        checks.append(f"INFO  active building is {active!r} (no --expect given)")

    llm_ok, why = _llm_answers()
    checks.append(f"{'PASS' if llm_ok else 'FAIL'}  {why}")
    ok &= llm_ok

    graph_ok, graph_why = _graph_is_not_duplicated()
    checks.append(f"{'PASS' if graph_ok else 'FAIL'}  {graph_why}")
    ok &= graph_ok

    snap = _container_snapshot()
    unhealthy = [n for n, s in snap.items() if "unhealthy" in s.lower()]
    checks.append(
        f"{'PASS' if not unhealthy else 'FAIL'}  {len(snap)} container(s); "
        f"unhealthy: {unhealthy or 'none'}"
    )
    ok &= not unhealthy

    return ok, checks, {"containers": snap, "building": active}


def postflight(before: Dict[str, Any], expect: Optional[str]) -> Tuple[bool, List[str]]:
    ok, checks, after = preflight(expect)
    restarted = [
        n
        for n, s in (before.get("containers") or {}).items()
        if n in (after.get("containers") or {}) and (after["containers"][n] != s)
    ]
    vanished = sorted(set(before.get("containers") or {}) - set(after.get("containers") or {}))
    changed = bool(restarted or vanished)
    checks.append(
        f"{'PASS' if not changed else 'FAIL'}  containers unchanged during the run "
        f"(restarted: {restarted or 'none'}, vanished: {vanished or 'none'})"
    )
    if (before.get("building") or None) != (after.get("building") or None):
        checks.append(
            f"FAIL  the ACTIVE BUILDING changed mid-run: "
            f"{before.get('building')!r} -> {after.get('building')!r}"
        )
        changed = True
    return (ok and not changed), checks


def _flush_cache() -> str:
    try:
        subprocess.run(
            [
                "docker",
                "exec",
                "redis-memory-store",
                "sh",
                "-c",
                'redis-cli --scan --pattern "resp_cache:*" | xargs -r redis-cli DEL',
            ],
            capture_output=True,
            timeout=60,
        )
        return "response cache flushed"
    except Exception as exc:  # pragma: no cover
        return f"cache flush skipped ({exc})"


def _newest_scorecard(since: float) -> Optional[Path]:
    if not OUTPUTS.is_dir():
        return None
    cards = [p for p in OUTPUTS.glob("V5_SCORECARD_*.md") if p.stat().st_mtime >= since - 1]
    return max(cards, key=lambda p: p.stat().st_mtime) if cards else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--expect", help="building id the stack must be serving")
    ap.add_argument("--quick", action="store_true", help="small samples where supported")
    ap.add_argument("--only", help="comma list passed through to run_all_graders")
    ap.add_argument("--preflight-only", action="store_true")
    args = ap.parse_args()

    print("=" * 74)
    print("PREFLIGHT")
    print("=" * 74)
    ok, checks, before = preflight(args.expect)
    for c in checks:
        print(" ", c)
    if not ok:
        print(
            "\nABORTED before asking a single question. A run that cannot be trusted is\n"
            "better not started than explained away afterwards -- this project has three\n"
            "artifacts that had to be thrown away for exactly this (CAVEAT-173, BUG-176,\n"
            "BUG-177)."
        )
        return 2
    print(" ", _flush_cache())
    if args.preflight_only:
        print("\nPreflight only; not running the graders.")
        return 0

    cmd = [sys.executable, str(REPO / "scripts" / "run_all_graders.py")]
    if args.quick:
        cmd.append("--quick")
    if args.only:
        cmd += ["--only", args.only]

    started = time.time()
    print("\n" + "=" * 74)
    print("RUN  " + " ".join(cmd[1:]))
    print("=" * 74, flush=True)
    rc = subprocess.run(cmd, cwd=str(REPO)).returncode
    elapsed = time.time() - started

    print("\n" + "=" * 74)
    print("POSTFLIGHT")
    print("=" * 74)
    still_ok, post = postflight(before, args.expect)
    for c in post:
        print(" ", c)

    card = _newest_scorecard(started)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    verdict = "VALID" if (still_ok and rc == 0) else "INVALID"
    banner = [
        "",
        "---",
        "",
        f"## Run validity: {verdict}",
        "",
        f"- Preflight and postflight both checked at {stamp} ({elapsed / 60:.1f} min run).",
        f"- Graders exited {rc}.",
        "",
    ]
    banner += [f"- {c}" for c in post]
    if verdict == "INVALID":
        banner += [
            "",
            "**Do not publish these numbers.** The stack did not stay healthy for the whole",
            "run, so the figures above describe a system that was partly broken while it was",
            "being measured. Fix the cause and re-run; this project has already had to throw",
            "away three artifacts produced exactly this way.",
        ]
    if card:
        card.write_text(
            card.read_text(encoding="utf-8") + "\n".join(banner) + "\n", encoding="utf-8"
        )
        print(f"\nstamped {card.relative_to(REPO)} -> {verdict}")
    else:
        print(f"\nNo scorecard was produced; verdict {verdict}")

    return 0 if verdict == "VALID" else 1


if __name__ == "__main__":
    sys.exit(main())
