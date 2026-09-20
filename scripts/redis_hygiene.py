# -*- coding: utf-8 -*-
"""Redis memory gate and harness-residue purge (W01).

Why this exists. On 2026-09-18 Redis held 2.135 GB of a 2.00 GB cap under ``allkeys-lru``: about
16,000 conversations created by test harnesses (one per asked question, never deleted, some over
1 MB) against ``CONVERSATION_TTL=0``, which keeps a conversation forever by design. At the cap the
next write evicts something — first the warm answer cache a demo depends on — and it does so
silently. Nothing in the product was wrong; the harnesses were leaking into the product's store.

    python scripts/redis_hygiene.py                 # report: memory, headroom, key families
    python scripts/redis_hygiene.py --purge         # delete harness-prefixed conversations only
    python scripts/redis_hygiene.py --check         # exit 1 when used memory is over 60% of the cap

What --purge will and will not touch. It deletes ``conversation:`` / ``messages:`` keys whose id
begins with a known harness prefix (``conv_``, ``owui_rehearsal-``, ``owui_replay-``,
``owui_diag-``). A real Open WebUI chat is ``owui_<hex>``; sessions, users, caches and the compiled
query cache are never matched. ``--dry-run`` prints what would go.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import Dict, List, Optional, Sequence

#: An id starting with one of these was made by a harness, never by a person.
HARNESS_PREFIXES: Sequence[str] = ("conv_", "owui_rehearsal-", "owui_replay-", "owui_diag-")
KEY_FAMILIES: Sequence[str] = ("conversation", "messages")

#: The plan's W01 acceptance: below 60% of maxmemory.
LIMIT_FRACTION = 0.60


def _cli(container: str, *args: str, timeout: int = 60) -> str:
    out = subprocess.run(
        ["docker", "exec", container, "redis-cli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"redis-cli {' '.join(args)} failed")
    return out.stdout.strip()


def memory(container: str) -> Dict[str, object]:
    """used, cap and policy, in bytes and as a fraction."""
    info = _cli(container, "info", "memory")
    kv = dict(line.split(":", 1) for line in info.splitlines() if ":" in line)
    used = int(kv["used_memory"])
    cap = int(kv.get("maxmemory", "0") or 0)
    return {
        "used": used,
        "cap": cap,
        "fraction": (used / cap) if cap else 0.0,
        "policy": kv.get("maxmemory_policy", "?"),
    }


def _scan(container: str, pattern: str) -> List[str]:
    out = _cli(container, "--scan", "--pattern", pattern, timeout=180)
    return [k for k in out.splitlines() if k]


def harness_keys(container: str) -> List[str]:
    keys: List[str] = []
    for family in KEY_FAMILIES:
        for prefix in HARNESS_PREFIXES:
            keys.extend(_scan(container, f"{family}:{prefix}*"))
    return keys


def purge(container: str, keys: Sequence[str]) -> int:
    """Delete in batches; returns how many keys went."""
    deleted = 0
    for i in range(0, len(keys), 400):
        batch = list(keys[i : i + 400])
        deleted += int(_cli(container, "DEL", *batch, timeout=120) or 0)
    return deleted


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):,.1f} MB"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--container", default="redis-memory-store")
    ap.add_argument("--purge", action="store_true", help="delete harness-prefixed conversations")
    ap.add_argument("--dry-run", action="store_true", help="with --purge: list, delete nothing")
    ap.add_argument("--check", action="store_true", help="exit 1 when over the 60%% limit")
    args = ap.parse_args(argv)

    before = memory(args.container)
    keys = harness_keys(args.container)
    print(
        f"used {_mb(before['used'])} of {_mb(before['cap'])} "
        f"({before['fraction']:.1%}), policy {before['policy']}; "
        f"{len(keys)} harness-prefixed conversation/message keys"
    )
    if args.purge:
        if args.dry_run:
            print(f"dry run: would delete {len(keys)} keys")
        else:
            n = purge(args.container, keys)
            after = memory(args.container)
            print(f"deleted {n}; used now {_mb(after['used'])} ({after['fraction']:.1%})")
            before = after
    if args.check and before["cap"] and before["fraction"] > LIMIT_FRACTION:
        print(f"FAIL: over {LIMIT_FRACTION:.0%} of maxmemory — purge, or the warm cache is at risk")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
