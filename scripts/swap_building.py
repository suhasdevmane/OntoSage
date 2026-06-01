#!/usr/bin/env python3
"""swap_building.py — Phase 12C, the canonical "switch this orchestrator to a
new building" CLI for OntoSage v1.

OntoSage v1 serves one building at a time.  Switching to a new building means:

  1. The new building's files (TTLs, DWGs, PDFs, building.yaml, capability.yaml,
     intents.yaml, personas/) already exist under `input/<new_building_id>/`.
  2. The `.env` file's `BUILDING_ID` is set to `<new_building_id>`.
  3. The orchestrator is restarted.

Manual step 2 is easy to forget and a typo silently breaks SPARQL.  This script
does the swap end-to-end, fails loudly on any inconsistency, and (optionally)
archives the old building's input directory so you can roll back.

Examples
--------

Dry-run (recommended first):

    python scripts/swap_building.py --to bldg2 --dry-run

Live swap with the old `bldg1` archived to `input/_archive/bldg1_<ts>/`:

    python scripts/swap_building.py --to bldg2 --archive

Swap and skip archiving (the old dir is left in place):

    python scripts/swap_building.py --to bldg2

Future (Onto-community)
-----------------------

When OntoSage v2 (Onto-community) supports multiple simultaneous buildings,
this script becomes the "register a new building" tool.  The `--to` flag will
add the building to a list rather than replacing the active one.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

# Allow running as `python scripts/swap_building.py` without installing the
# repo as a package.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# Output helpers — keep it terminal-friendly, no rich/colour dependencies.
# ─────────────────────────────────────────────────────────────────────────────


def _info(msg: str) -> None:
    print(f"  {msg}")


def _ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def _warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def _err(msg: str) -> None:
    print(f"  [FAIL] {msg}", file=sys.stderr)


def _section(title: str) -> None:
    print()
    print(f"== {title} ==")


# ─────────────────────────────────────────────────────────────────────────────
# Validation steps — each returns (ok: bool, detail: str).
# ─────────────────────────────────────────────────────────────────────────────


def _check_input_dir_exists(new_bldg: str, input_root: Path) -> Tuple[bool, str]:
    target = input_root / new_bldg
    if target.is_dir():
        return True, f"{target} exists"
    return False, (
        f"{target} does NOT exist. Drop the new building's files into "
        f"`{target}/` before running this swap (building.yaml, TTLs, DWGs, "
        "PDFs, capability.yaml, intents.yaml, personas/)."
    )


def _check_building_yaml(new_bldg: str, input_root: Path) -> Tuple[bool, dict, str]:
    yml = input_root / new_bldg / "building.yaml"
    if not yml.is_file():
        return False, {}, (
            f"building.yaml missing at {yml}. Every building requires a "
            "building.yaml declaring building_id, building_name, and "
            "ontology_namespace."
        )

    try:
        import yaml  # type: ignore
    except ImportError as e:
        return False, {}, f"PyYAML required to read {yml}: {e}"

    try:
        with open(yml, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as e:
        return False, {}, f"failed to parse {yml}: {e}"

    required = ("building_id", "ontology_namespace")
    missing = [k for k in required if not data.get(k)]
    if missing:
        return False, data, (
            f"{yml} is missing required keys: {missing}. "
            "At minimum: building_id, ontology_namespace."
        )

    declared_id = data["building_id"]
    if declared_id != new_bldg:
        return False, data, (
            f"{yml} declares building_id={declared_id!r} but the directory is "
            f"{new_bldg!r}. They must match — pick one and align both."
        )

    return True, data, f"{yml} declares ontology_namespace={data['ontology_namespace']!r}"


def _check_ttl_consistency(
    new_bldg: str, namespace: str, prefix: str, input_root: Path
) -> Tuple[bool, str]:
    """Reuse the Phase 12B validator so swap-time checks == startup checks."""
    try:
        from orchestrator.services.ttl_validator import validate_building_ttls
    except ImportError as e:
        return False, f"could not import ttl_validator: {e}"

    report = validate_building_ttls(
        building_id=new_bldg,
        declared_namespace=namespace,
        building_prefix=prefix,
        input_root=input_root,
    )

    if not report.ok:
        details = "\n            ".join(str(f) for f in report.hard_failures)
        return False, (
            f"TTL validation failed for `{new_bldg}` "
            f"({len(report.hard_failures)} hard failure(s)):\n"
            f"            {details}"
        )

    if report.warnings:
        for w in report.warnings:
            _warn(str(w))

    return True, f"{report.ttl_files_checked} TTL file(s) validated"


# ─────────────────────────────────────────────────────────────────────────────
# .env mutation — surgical, keep formatting and other lines intact.
# ─────────────────────────────────────────────────────────────────────────────


_BUILDING_ID_LINE = re.compile(r"^\s*BUILDING_ID\s*=.*$", re.MULTILINE)


def _update_env_file(env_path: Path, new_bldg: str, *, dry_run: bool) -> Tuple[bool, str]:
    if not env_path.is_file():
        # Create a minimal .env from scratch.
        if dry_run:
            return True, f"would create {env_path} with BUILDING_ID={new_bldg}"
        env_path.write_text(f"BUILDING_ID={new_bldg}\n", encoding="utf-8")
        return True, f"created {env_path} with BUILDING_ID={new_bldg}"

    body = env_path.read_text(encoding="utf-8")

    if _BUILDING_ID_LINE.search(body):
        new_body = _BUILDING_ID_LINE.sub(f"BUILDING_ID={new_bldg}", body, count=1)
        action = f"updated BUILDING_ID in {env_path} -> {new_bldg}"
    else:
        suffix = "" if body.endswith("\n") else "\n"
        new_body = f"{body}{suffix}BUILDING_ID={new_bldg}\n"
        action = f"appended BUILDING_ID={new_bldg} to {env_path}"

    if dry_run:
        return True, f"would {action}"

    env_path.write_text(new_body, encoding="utf-8")
    return True, action


# ─────────────────────────────────────────────────────────────────────────────
# Old-building archival
# ─────────────────────────────────────────────────────────────────────────────


def _flush_response_cache(redis_container: str, *, dry_run: bool) -> Tuple[bool, str]:
    """Phase 15B-1 — flush only the response-cache keys, not the entire DB.

    Auth sessions, conversation state, and floor-plan caches are NOT touched.
    We target the `resp_cache:*` namespace used by the response cache layer
    (see orchestrator/services/response_cache.py).  Falling back to FLUSHDB
    is too destructive — it would log out every active user.
    """
    if dry_run:
        return True, (
            f"would `docker exec {redis_container} redis-cli --scan --pattern "
            "'resp_cache:*' | xargs redis-cli del` (no actual delete)"
        )

    # `redis-cli --scan` is non-blocking (vs. KEYS *); safe on any DB size.
    # The two-stage pipe lets us delete batched in case the key count is huge.
    cmd = (
        f"docker exec {redis_container} sh -c "
        "\"redis-cli --scan --pattern 'resp_cache:*' | "
        "xargs -r redis-cli del\""
    )
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return False, (
                f"redis flush returned exit={result.returncode}; "
                f"stderr={result.stderr.strip()[:200]}"
            )
        deleted = result.stdout.strip() or "0"
        return True, f"flushed response cache (deleted ~{deleted} keys)"
    except subprocess.TimeoutExpired:
        return False, "redis flush timed out after 15s"
    except FileNotFoundError:
        return False, (
            "docker CLI not on PATH — skipping cache flush.  Run "
            f"`docker exec {redis_container} redis-cli FLUSHDB` manually "
            "after restarting the orchestrator if you see stale answers."
        )


def _archive_old_building(
    old_bldg: Optional[str], input_root: Path, *, dry_run: bool
) -> Tuple[bool, str]:
    if not old_bldg or old_bldg == "":
        return True, "no previous BUILDING_ID found — nothing to archive"

    old_dir = input_root / old_bldg
    if not old_dir.is_dir():
        return True, f"no old input dir {old_dir} — nothing to archive"

    archive_root = input_root / "_archive"
    ts = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    dest = archive_root / f"{old_bldg}_{ts}"

    if dry_run:
        return True, f"would move {old_dir} -> {dest}"

    archive_root.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old_dir), str(dest))
    return True, f"moved {old_dir} -> {dest}"


# ─────────────────────────────────────────────────────────────────────────────
# Active-BUILDING_ID detection — read .env if it exists, else None.
# ─────────────────────────────────────────────────────────────────────────────


def _current_building_id(env_path: Path) -> Optional[str]:
    if not env_path.is_file():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*BUILDING_ID\s*=\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Swap the active OntoSage building to a new BUILDING_ID."
    )
    parser.add_argument(
        "--to", required=True, metavar="NEW_BUILDING_ID",
        help="The new building id (must match input/<NEW_BUILDING_ID>/).",
    )
    parser.add_argument(
        "--from", dest="from_bldg", metavar="OLD_BUILDING_ID",
        help="Override the auto-detected current building id.",
    )
    parser.add_argument(
        "--archive", action="store_true",
        help="Move input/<old>/ to input/_archive/<old>_<timestamp>/.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would change without writing anything.",
    )
    parser.add_argument(
        "--env", default=".env",
        help="Path to the .env file to update (default: .env).",
    )
    parser.add_argument(
        "--input-root", default="input",
        help="Path to the input/ root (default: input).",
    )
    parser.add_argument(
        "--no-cache-flush", action="store_true",
        help=(
            "Skip flushing the Redis response cache after the swap.  By "
            "default the swap clears Redis so the new building's queries "
            "don't return the old building's cached answers."
        ),
    )
    parser.add_argument(
        "--redis-container", default="redis-memory-store",
        help=(
            "Docker container name for Redis (used by --cache-flush).  "
            "Default matches docker-compose.yml."
        ),
    )
    args = parser.parse_args()

    input_root = Path(args.input_root).resolve()
    env_path = Path(args.env).resolve()
    new_bldg = args.to

    print(f"OntoSage building swap   ->   {new_bldg}")
    print(f"  input root: {input_root}")
    print(f"  .env file : {env_path}")
    if args.dry_run:
        print("  mode      : DRY-RUN (no writes)")

    # 1. Detect current
    current = args.from_bldg or _current_building_id(env_path)
    if current == new_bldg:
        _warn(f"BUILDING_ID is already {new_bldg} — nothing to do.")
        return 0

    _section("Validating new building")

    ok, msg = _check_input_dir_exists(new_bldg, input_root)
    (_ok if ok else _err)(msg)
    if not ok:
        return 2

    ok, building_data, msg = _check_building_yaml(new_bldg, input_root)
    (_ok if ok else _err)(msg)
    if not ok:
        return 2

    namespace = building_data["ontology_namespace"]
    prefix = (
        building_data.get("building_prefix")
        or building_data.get("ontology_prefix")
        or "bldg"
    )

    ok, msg = _check_ttl_consistency(new_bldg, namespace, prefix, input_root)
    (_ok if ok else _err)(msg)
    if not ok:
        return 2

    _section("Applying swap")

    if args.archive:
        ok, msg = _archive_old_building(current, input_root, dry_run=args.dry_run)
        (_ok if ok else _err)(msg)

    ok, msg = _update_env_file(env_path, new_bldg, dry_run=args.dry_run)
    (_ok if ok else _err)(msg)

    # Phase 15B-1: flush the response cache so the new building's queries
    # don't return the old building's cached answers.  Auth sessions and
    # conversation state are NOT touched — only `resp_cache:*` keys.
    if not args.no_cache_flush:
        ok, msg = _flush_response_cache(args.redis_container, dry_run=args.dry_run)
        (_ok if ok else _warn)(msg)

    _section("Next steps")
    if args.dry_run:
        print("  - re-run without --dry-run to apply the changes")
    else:
        print("  - docker-compose restart orchestrator")
        print("    (or: docker-compose up -d orchestrator)")
        print("  - watch logs: docker-compose logs -f orchestrator")
        print("    The TTL validator runs first; mismatches will hard-fail boot.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
