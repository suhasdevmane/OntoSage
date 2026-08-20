"""
**HISTORICAL — Phase 3 cleanup removed the feature flag this script controls.**
**The script is preserved for reference (it documents the validation protocol)**
**but is no longer needed: semantic routing is now unconditional in main.**

If you need to re-run the regression battery against the current codebase,
run the individual test files directly:
    pytest tests/test_capability_e2e.py tests/test_floor_n_protection.py \\
           tests/test_capability_semantic_quality.py \\
           tests/test_non_regression_intents.py \\
           tests/test_capability_edge_cases.py \\
           tests/test_ontology_integrity.py \\
           tests/perf/test_capability_performance.py -v
    python scripts/survey_live_test.py

────────────────────────────────────────────────────────────────────────────────
Phase 2 enablement + validation script for capability semantic routing.

WHAT THIS DOES
==============
1. Flips CAPABILITY_SEMANTIC_ROUTING_ENABLED=true in .env (backs up old value).
2. Resolves the embedding provider question: either keeps EMBEDDING_PROVIDER=local
   (requires sentence-transformers installed) or switches to openai for the
   duration of testing (--use-openai).
3. Restarts the orchestrator with --force-recreate so the new code path is live.
4. Captures the §17.1 baseline artefacts.
5. Runs the §16 regression battery in order:
       a. Unit tests           (must already pass — sanity)
       b. Integration E2E      (tests/test_capability_e2e.py)
       c. Non-regression       (tests/test_non_regression_intents.py)
       d. Floor-N protection   (tests/test_floor_n_protection.py)
       e. Edge cases           (tests/test_capability_edge_cases.py)
       f. Semantic recall      (tests/test_capability_semantic_quality.py)
       g. Ontology integrity   (tests/test_ontology_integrity.py)
       h. Performance          (tests/perf/test_capability_performance.py)
6. Re-runs scripts/survey_live_test.py and diffs against the pre-refactor baseline.
7. Writes a Phase 2 result summary to docs/superpowers/results/phase2_gate.md.

USAGE
=====
    # Default: keep current EMBEDDING_PROVIDER setting (assumes sentence-transformers
    # is installed in the container, otherwise indexer will fail).
    python scripts/phase2_enable_and_validate.py

    # Recommended for first run: use OpenAI embeddings (skips sentence-transformers
    # dependency, uses the API key already in .env).
    python scripts/phase2_enable_and_validate.py --use-openai

    # Dry run (show what would happen, do not modify .env or restart):
    python scripts/phase2_enable_and_validate.py --dry-run

GATING
======
This script does NOT advance to Phase 3 cleanup automatically. After it runs,
review docs/superpowers/results/phase2_gate.md. If green, the operator runs
the Phase 3 cleanup tasks manually (deleting the keyword frozensets).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
BASELINE_DIR = ROOT / "tests" / "baselines"
RESULTS_DIR = ROOT / "docs" / "superpowers" / "results"


# ── env file mutation ──────────────────────────────────────────────────────────


def update_env(updates: dict, dry_run: bool = False) -> None:
    """Idempotent .env updater. Backs up to .env.bak before editing."""
    text = ENV_FILE.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    out_lines = []
    seen_keys = set()

    for line in lines:
        stripped = line.lstrip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0]
            if key in updates:
                seen_keys.add(key)
                out_lines.append(f"{key}={updates[key]}\n")
                continue
        out_lines.append(line)

    # Append any keys that weren't already in the file
    for k, v in updates.items():
        if k not in seen_keys:
            out_lines.append(f"{k}={v}\n")

    new_text = "".join(out_lines)
    if new_text == text:
        print(f"[env] no changes needed (already set: {list(updates.keys())})")
        return

    if dry_run:
        print(f"[env] DRY RUN — would update: {updates}")
        return

    backup = ENV_FILE.with_suffix(".env.bak")
    shutil.copy(ENV_FILE, backup)
    ENV_FILE.write_text(new_text, encoding="utf-8")
    print(f"[env] updated {list(updates.keys())}; backup at {backup.name}")


# ── docker restart ──────────────────────────────────────────────────────────────


def restart_orchestrator(dry_run: bool = False) -> bool:
    """Force-recreate the orchestrator container, then wait for /health."""
    if dry_run:
        print("[docker] DRY RUN — would force-recreate orchestrator")
        return True

    print("[docker] force-recreating orchestrator container...")
    subprocess.run(
        ["docker-compose", "up", "-d", "--force-recreate", "orchestrator"],
        cwd=ROOT,
        check=True,
    )

    # Wait for /health (max 90s)
    import urllib.request

    print("[docker] waiting for /health to return 200...")
    for i in range(30):
        try:
            r = urllib.request.urlopen("http://localhost:8000/health", timeout=3)
            if r.status == 200:
                print(f"[docker] orchestrator healthy ({i*3}s)")
                return True
        except Exception:
            pass
        time.sleep(3)
    print("[docker] ERROR: orchestrator did not become healthy within 90s")
    return False


# ── baseline capture ───────────────────────────────────────────────────────────


def capture_baselines(dry_run: bool = False) -> dict:
    """Capture §17.1 baseline artefacts. Returns paths of files written."""
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    written = {}

    if dry_run:
        print("[baseline] DRY RUN — would capture Qdrant + GraphDB snapshots")
        return written

    import urllib.request

    try:
        r = urllib.request.urlopen("http://localhost:6333/collections", timeout=10)
        path = BASELINE_DIR / f"qdrant_phase2_{datetime.now():%Y%m%d_%H%M}.json"
        path.write_text(r.read().decode("utf-8"))
        written["qdrant"] = str(path)
    except Exception as e:
        print(f"[baseline] qdrant snapshot failed: {e}")

    try:
        r = urllib.request.urlopen("http://localhost:7200/rest/repositories", timeout=10)
        path = BASELINE_DIR / f"graphdb_phase2_{datetime.now():%Y%m%d_%H%M}.json"
        path.write_text(r.read().decode("utf-8"))
        written["graphdb"] = str(path)
    except Exception as e:
        print(f"[baseline] graphdb snapshot failed: {e}")

    print(f"[baseline] captured: {list(written.keys())}")
    return written


# ── test runner ────────────────────────────────────────────────────────────────


def run_pytest(target: str, label: str, extra_args: Optional[list] = None) -> dict:
    """Run a pytest target and return {label, exit_code, passed, failed, duration_s}."""
    print(f"\n── {label} ───────────────────────────────────────────────────────────")
    args = ["python", "-m", "pytest", target, "-v", "--tb=short", "-q"]
    if extra_args:
        args.extend(extra_args)
    t0 = time.time()
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    duration = time.time() - t0
    out = result.stdout + result.stderr
    # Parse "X passed, Y failed" line
    summary = next(
        (ln for ln in out.splitlines()[-15:] if "passed" in ln or "failed" in ln or "error" in ln),
        "(no summary parsed)",
    )
    print(f"[{label}] exit={result.returncode}, duration={duration:.1f}s — {summary}")
    return {
        "label": label,
        "target": target,
        "exit_code": result.returncode,
        "duration_s": round(duration, 1),
        "summary": summary,
        "stdout_tail": out[-2000:],
    }


# ── main ───────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--use-openai",
        action="store_true",
        help="Switch EMBEDDING_PROVIDER=openai (uses existing OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without modifying .env or restarting docker",
    )
    parser.add_argument(
        "--skip-restart",
        action="store_true",
        help="Skip docker restart (assume orchestrator is already running with new code)",
    )
    args = parser.parse_args()

    updates = {"CAPABILITY_SEMANTIC_ROUTING_ENABLED": "true"}
    if args.use_openai:
        updates["EMBEDDING_PROVIDER"] = "openai"

    print("=" * 72)
    print(f"  Phase 2 Enablement -- Capability Semantic Routing")
    print(f"  Updates: {list(updates.keys())}")
    print(f"  Dry run: {args.dry_run}")
    print("=" * 72)

    update_env(updates, dry_run=args.dry_run)

    if not args.skip_restart:
        if not restart_orchestrator(dry_run=args.dry_run):
            print("[abort] orchestrator did not become healthy. Aborting.")
            sys.exit(1)

    if args.dry_run:
        print("\n[dry-run] would now run the regression battery + survey.")
        return

    capture_baselines()

    # ── §16 regression battery, in order ──
    results = []
    results.append(
        run_pytest(
            "tests/test_embedding_service.py tests/test_capability_routing_config.py "
            "tests/test_capability_indexer.py tests/test_semantic_router.py",
            "unit tests (sanity)",
        )
    )
    results.append(run_pytest("tests/test_capability_e2e.py", "integration: capability E2E"))
    results.append(run_pytest("tests/test_non_regression_intents.py", "non-regression: 16 intents"))
    results.append(run_pytest("tests/test_floor_n_protection.py", "edge: floor-N protection"))
    results.append(run_pytest("tests/test_capability_edge_cases.py", "edge: adversarial"))
    results.append(run_pytest("tests/test_capability_semantic_quality.py", "semantic recall delta"))
    results.append(run_pytest("tests/test_ontology_integrity.py", "ontology integrity"))
    results.append(run_pytest("tests/perf/test_capability_performance.py", "performance"))

    # Survey
    print(f"\n── survey live test ────────────────────────────────────────────")
    survey_out = subprocess.run(
        ["python", "scripts/survey_live_test.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    survey_summary = next(
        (ln for ln in survey_out.stdout.splitlines() if "RESULTS:" in ln),
        "(no summary parsed)",
    )
    print(f"[survey] {survey_summary}")
    results.append(
        {
            "label": "survey live test",
            "target": "scripts/survey_live_test.py",
            "exit_code": survey_out.returncode,
            "duration_s": None,
            "summary": survey_summary,
            "stdout_tail": survey_out.stdout[-2000:],
        }
    )

    # ── Write summary report ──
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = RESULTS_DIR / f"phase2_gate_{datetime.now():%Y-%m-%d_%H%M}.md"
    with report_path.open("w", encoding="utf-8") as fh:
        fh.write(f"# Phase 2 Gate — Capability Semantic Routing\n\n")
        fh.write(f"Run timestamp: {datetime.now().isoformat()}\n\n")
        fh.write(f"Embedding provider: {updates.get('EMBEDDING_PROVIDER', 'unchanged')}\n\n")
        fh.write(f"## Summary\n\n")
        fh.write("| Stage | Exit Code | Duration | Summary |\n")
        fh.write("|---|---|---|---|\n")
        for r in results:
            dur = f"{r['duration_s']}s" if r["duration_s"] else "n/a"
            fh.write(f"| {r['label']} | {r['exit_code']} | {dur} | {r['summary']} |\n")

        any_failed = any(r["exit_code"] != 0 for r in results)
        fh.write(f"\n## Verdict\n\n")
        fh.write(f"**{'GATE FAILED' if any_failed else 'GATE PASSED'}**\n\n")
        if any_failed:
            fh.write("Do not proceed to Phase 3. Investigate failed stages.\n")
        else:
            fh.write("Phase 3 (legacy cleanup) is unblocked.\n")

        fh.write("\n## Detailed Output\n\n")
        for r in results:
            fh.write(f"### {r['label']}\n\n```\n{r['stdout_tail']}\n```\n\n")

    print("\n" + "=" * 72)
    print(f"  Phase 2 report: {report_path.name}")
    print("=" * 72)
    sys.exit(0 if not any_failed else 1)


if __name__ == "__main__":
    main()
