#!/usr/bin/env python3
"""Pre-session health routine for the Paper 3 live study (tracker D9). Prints PASS/FAIL per item.

Run it before every participant (about 20 s). Exit code 0 only when every item passes.

    python scripts/study_session_check.py --participant P07
    python scripts/study_session_check.py --participant P07 --no-flush     # inspect only

Items
  1. watchdog   the orchestrator's OS-thread watchdog logged in the last 2 minutes (silence = wedged,
                even while `docker ps` still says healthy; CLAUDE.md Debugging, BUG-1194)
  2. memory     orchestrator memory below --max-gib (default 4; ~1-2 GiB is normal under load)
  3. health     /health returns 200 and status healthy
  4. gateway    the hosted model gateway lists models (key read from .env, never printed)
  5. warm       the measured-modality count has warmed since the orchestrator last started (until it
                has, a decline cannot list what the building measures; BUG-1497)
  6. publisher  the data-publisher container is running (it must keep running: "now" is the wall clock)
  7. caches     the four answer caches are flushed (resp_cache, cache:sparql, cache:intent, cqir_compile)
  8. account    the participant's Open WebUI account signs in, and has NO chats yet (a leftover chat
                would shift the chat-order mapping of practice/tasks/own questions)
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Tuple

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = Path(__file__).resolve().parents[1]
CACHES = ("resp_cache:*", "cache:sparql*", "cache:intent:*", "cqir_compile:*")


def env(name: str) -> str:
    for line in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def sh(*args: str, timeout: int = 30) -> Tuple[int, str]:
    try:
        r = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def http(url: str, payload: dict = None, token: str = "", timeout: int = 15) -> Tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if payload is not None else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode() or "{}"
            try:
                return r.status, json.loads(body)
            except ValueError:
                return r.status, {}
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:  # noqa: BLE001 - any failure is a FAIL line, never a crash
        return 0, {}


def parse_gib(mem: str) -> float:
    m = re.match(r"\s*([\d.]+)\s*([KMG]i?B)", mem)
    if not m:
        return float("inf")
    v, unit = float(m.group(1)), m.group(2)[0]
    return v / 1024 / 1024 if unit == "K" else v / 1024 if unit == "M" else v


def run(participant: str, flush: bool, max_gib: float, creds: Path) -> List[Tuple[str, bool, str]]:
    out: List[Tuple[str, bool, str]] = []
    _, logs = sh("docker", "logs", "--since", "2m", "ontosage-orchestrator")
    n = logs.count("watchdog")
    out.append(("watchdog", n > 0, f"{n} watchdog lines in the last 2 min"))

    _, mem = sh(
        "docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", "ontosage-orchestrator"
    )
    gib = parse_gib(mem.split("/")[0]) if mem else float("inf")
    out.append(("memory", gib < max_gib, f"{gib:.2f} GiB (limit {max_gib})"))

    code, body = http("http://127.0.0.1:8000/health")
    status = ((body.get("data") or {}).get("status")) or body.get("status")
    out.append(("health", code == 200 and status == "healthy", f"HTTP {code}, status={status}"))

    base, key = env("HOSTED_LLM_BASE_URL"), env("HOSTED_LLM_API_KEY")
    if env("MODEL_PROVIDER") == "hosted" and base:
        code, body = http(f"{base.rstrip('/')}/models", token=key)
        ids = [m.get("id") for m in body.get("data", []) if isinstance(m, dict)]
        want = env("HOSTED_LLM_MODEL")
        out.append(
            (
                "gateway",
                code == 200 and (not want or want in ids),
                f"HTTP {code}; {want} listed: {want in ids}",
            )
        )
    else:
        out.append(
            ("gateway", True, f"MODEL_PROVIDER={env('MODEL_PROVIDER')} (not hosted; skipped)")
        )

    # Warm since THIS start: `docker logs` keeps earlier runs' output, so read from StartedAt.
    _, started = sh(
        "docker", "inspect", "--format", "{{.State.StartedAt}}", "ontosage-orchestrator"
    )
    _, since_start = sh(
        "docker", "logs", "--since", started.strip() or "10m", "ontosage-orchestrator", timeout=60
    )
    warmed = "modality counts warmed" in since_start
    out.append(
        (
            "warm",
            warmed,
            (
                "measured-modality count warmed since the last start"
                if warmed
                else "not warmed yet since the last start: wait ~2 min after health (BUG-1497)"
            ),
        )
    )

    _, st = sh("docker", "inspect", "--format", "{{.State.Status}}", "data-publisher")
    out.append(("publisher", st.strip() == "running", f"data-publisher {st.strip() or 'missing'}"))

    if flush:
        counts = []
        for p in CACHES:
            _, keys = sh(
                "docker", "exec", "redis-memory-store", "redis-cli", "--scan", "--pattern", p
            )
            ks = [k for k in keys.split() if k]
            for i in range(0, len(ks), 200):
                sh("docker", "exec", "redis-memory-store", "redis-cli", "DEL", *ks[i : i + 200])
            counts.append(f"{p}={len(ks)}")
        _, left = sh(
            "docker",
            "exec",
            "redis-memory-store",
            "sh",
            "-c",
            " ; ".join(f"redis-cli --scan --pattern '{p}' | wc -l" for p in CACHES),
        )
        remaining = sum(int(x) for x in left.split() if x.isdigit())
        out.append(
            ("caches", remaining == 0, "flushed " + ", ".join(counts) + f"; remaining {remaining}")
        )
    else:
        out.append(("caches", True, "not flushed (--no-flush)"))

    row = None
    if creds.is_file():
        with creds.open(encoding="utf-8") as fh:
            row = next(
                (r for r in csv.DictReader(fh) if r["username"] == f"study_{participant.lower()}"),
                None,
            )
    if row is None:
        out.append(("account", False, f"no credentials row for {participant} in {creds.name}"))
    else:
        code, body = http(
            "http://127.0.0.1:3000/api/v1/auths/signin",
            {"email": row["email"], "password": row["password"]},
        )
        token = body.get("token", "")
        n_chats = None
        if token:
            c2, chats = http("http://127.0.0.1:3000/api/v1/chats/list", token=token)
            if isinstance(chats, list):
                n_chats = len(chats)
            elif isinstance(chats, dict):
                n_chats = len(chats.get("data", chats.get("items", [])) or [])
        ok = bool(token) and n_chats == 0
        out.append(
            (
                "account",
                ok,
                f"{row['email']}: sign-in {'ok' if token else 'FAILED'}; existing chats={n_chats}",
            )
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--participant", required=True, help="e.g. P07")
    ap.add_argument("--no-flush", action="store_true")
    ap.add_argument("--max-gib", type=float, default=4.0)
    ap.add_argument("--credentials", default=str(REPO / "user_credentials_study_bldg1.csv"))
    args = ap.parse_args()
    results = run(args.participant.upper(), not args.no_flush, args.max_gib, Path(args.credentials))
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:10s} {detail}")
    failed = [n for n, ok, _ in results if not ok]
    print("READY" if not failed else f"NOT READY: {', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
