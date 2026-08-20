"""
Phase 3 cleanup — delete legacy keyword routing now that semantic routing is the
single source of truth.

PRECONDITION: Phase 2 gate must have passed (run scripts/phase2_enable_and_validate.py
first and review docs/superpowers/results/phase2_gate_*.md).

WHAT THIS DOES
==============
Removes from the codebase:
  1. _CAPABILITY_KW frozenset            in orchestrator/agents/dialogue_agent.py
  2. _STRONG_FACILITY_KW frozenset       in orchestrator/agents/dialogue_agent.py
  3. The two keyword-override blocks     in orchestrator/agents/dialogue_agent.py
       a. cache-hit path (~line 565)
       b. hot-path after LLM (~line 940)
  4. The CAPABILITY_SEMANTIC_ROUTING_ENABLED flag itself (semantic becomes default)
       a. flag definition in shared/config.py
       b. all `if settings.CAPABILITY_SEMANTIC_ROUTING_ENABLED:` guards
  5. CapabilityKB.search() method         in shared/capability_schema.py
  6. capability_agent.py fallback to kb.search()  (the `if not matches` block)
  7. fallback_on_qdrant_failure="keyword" Literal option (only "skip" survives)

VERIFICATION (run after this script):
  $ grep -rn "_CAPABILITY_KW\|_STRONG_FACILITY_KW" orchestrator/ shared/
  (must return zero matches)
  $ grep -rn "CAPABILITY_SEMANTIC_ROUTING_ENABLED" orchestrator/ shared/
  (must return zero matches)
  $ grep -n "def search" shared/capability_schema.py
  (must return zero matches)
  $ pytest tests/ -v
  $ python scripts/survey_live_test.py
  (both must be green)

SAFETY
======
This script is destructive. It backs up every file it touches to .bak_phase3
before editing, and supports --dry-run.

USAGE
=====
    # Show what would be deleted, without modifying files:
    python scripts/phase3_cleanup.py --dry-run

    # Actually do it (after Phase 2 gate passes):
    python scripts/phase3_cleanup.py
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Tuple


ROOT = Path(__file__).resolve().parent.parent


# Each cleanup operation: (description, file_path, transformer_function)
# Each transformer takes the file's text and returns the transformed text.


def _cleanup_capability_kw(text: str) -> str:
    """Remove the _CAPABILITY_KW frozenset definition entirely."""
    # Match from "# Off-ontology capability keywords" comment block through the
    # closing `})` of the frozenset
    pattern = re.compile(
        r"# Off-ontology capability keywords.*?\n_CAPABILITY_KW:\s*frozenset\s*=\s*frozenset\(\{.*?^\}\)\n",
        re.MULTILINE | re.DOTALL,
    )
    return pattern.sub("", text)


def _cleanup_strong_facility_kw(text: str) -> str:
    """Remove the _STRONG_FACILITY_KW frozenset definition entirely."""
    pattern = re.compile(
        r"# Subset of capability keywords that describe STATIC PHYSICAL FEATURES.*?\n_STRONG_FACILITY_KW:\s*frozenset\s*=\s*frozenset\(\{.*?^\}\)\n",
        re.MULTILINE | re.DOTALL,
    )
    return pattern.sub("", text)


def _cleanup_cache_hit_override(text: str) -> str:
    """Remove the cache-hit-path keyword override block (around line 558-587)."""
    # Match from "if cached_result:" path's "# Re-apply capability keyword override"
    # comment through the end of that override block. Keep the `return cached_result`.
    pattern = re.compile(
        r"\n\s*# Re-apply capability keyword override.*?_has_strong_fac\s*=.*?cached_result\[\"general\"\]\s*=\s*False\n",
        re.MULTILINE | re.DOTALL,
    )
    return pattern.sub("\n", text)


def _cleanup_hot_path_override(text: str) -> str:
    """Remove the hot-path-after-LLM keyword override block (around line 938-955)."""
    pattern = re.compile(
        r"\n\s*# ── Capability / off-ontology override ──.*?normalized\[\"general\"\]\s*=\s*False\n\n\s*# NOTE: semantic SOFT override.*?\n.*?\n.*?\n",
        re.MULTILINE | re.DOTALL,
    )
    return pattern.sub("\n", text)


def _cleanup_feature_flag_guards(text: str) -> str:
    """Remove `if settings.CAPABILITY_SEMANTIC_ROUTING_ENABLED:` guards.

    NOTE: this is a targeted simplification — we make the guard always-true by
    deleting the condition (semantic routing becomes unconditional).
    """
    # Multi-line form: `if (\n  settings.CAPABILITY_SEMANTIC_ROUTING_ENABLED\n  and X\n  ...):`
    # becomes `if (\n  X\n  ...):` (remove the line + leading `and`)
    text = re.sub(
        r"^\s*settings\.CAPABILITY_SEMANTIC_ROUTING_ENABLED\s*\n\s*and\s+",
        "",
        text,
        flags=re.MULTILINE,
    )
    # Single-line form: `if settings.CAPABILITY_SEMANTIC_ROUTING_ENABLED and X:` → `if X:`
    text = re.sub(
        r"settings\.CAPABILITY_SEMANTIC_ROUTING_ENABLED\s+and\s+",
        "",
        text,
    )
    # Solo form: `if settings.CAPABILITY_SEMANTIC_ROUTING_ENABLED:` → always-true
    # Replace with True (preserves block) — let the caller manually flatten if desired.
    text = re.sub(
        r"if settings\.CAPABILITY_SEMANTIC_ROUTING_ENABLED\s*:",
        "if True:  # was: CAPABILITY_SEMANTIC_ROUTING_ENABLED (always on after Phase 3)",
        text,
    )
    return text


def _cleanup_flag_definition(text: str) -> str:
    """Remove the CAPABILITY_SEMANTIC_ROUTING_ENABLED field definition from config.py."""
    pattern = re.compile(
        r"\n\s*# ── Capability semantic routing.*?\n.*?\n.*?\n.*?\n\s*CAPABILITY_SEMANTIC_ROUTING_ENABLED:\s*bool\s*=\s*Field\(.*?\n.*?\n.*?\n.*?\n\s*\),?\n",
        re.MULTILINE | re.DOTALL,
    )
    return pattern.sub("\n", text)


def _cleanup_capability_kb_search(text: str) -> str:
    """Remove the CapabilityKB.search() method."""
    pattern = re.compile(
        r"\n\s*def search\(self, query: str, max_results: int = 3\).*?return \[e for _, e in scored\[:max_results\]\]\n",
        re.DOTALL,
    )
    return pattern.sub("\n", text)


def _cleanup_capability_agent_fallback(text: str) -> str:
    """Remove the legacy fallback in capability_agent.py that calls kb.search()
    when pre-fetched matches are missing.

    After Phase 3, semantic routing is the only path — if no matches, return the
    'no information' response immediately (no kb.search() retry).
    """
    pattern = re.compile(
        r"\n\s*if not matches:\n\s*# Legacy fallback: substring search on KB\n\s*matches = kb\.search\(user_query, max_results=3\)\n",
        re.DOTALL,
    )
    return pattern.sub("\n", text)


def _cleanup_fallback_keyword_option(text: str) -> str:
    """Remove the 'keyword' option from fallback_on_qdrant_failure Literal.
    After Phase 3, 'skip' is the only valid option."""
    return text.replace(
        'fallback_on_qdrant_failure: Literal["skip", "keyword"]',
        'fallback_on_qdrant_failure: Literal["skip"]',
    )


def _invert_kb_search_test(text: str) -> str:
    """Invert the test that asserted CapabilityKB.search() exists.
    After Phase 3 deletion, the assertion is the opposite — the method must NOT
    exist.  This keeps the unit-test suite green after cleanup.
    """
    old_block = (
        "def test_capability_kb_search_method_exists_in_phase1():\n"
        '    """Test 7: CapabilityKB.search() still exists in Phase 1 (will be removed in Phase 3).\n'
        "\n"
        "    This guards against accidentally deleting search() before the migration is\n"
        "    complete — it is still the fallback path while the feature flag is OFF.\n"
        "    Phase 3 cleanup explicitly inverts this assertion.\n"
        '    """\n'
        '    assert hasattr(CapabilityKB, "search")\n'
        "    assert callable(CapabilityKB.search)\n"
    )
    new_block = (
        "def test_capability_kb_search_method_removed_after_phase3():\n"
        '    """Test 7 (Phase 3 inversion): CapabilityKB.search() has been removed.\n'
        "\n"
        "    Phase 3 cleanup deleted the legacy substring-search method.  Semantic\n"
        "    routing is now the single source of truth for capability lookup.\n"
        '    """\n'
        '    assert not hasattr(CapabilityKB, "search"), (\n'
        '        "CapabilityKB.search() should be removed after Phase 3 cleanup"\n'
        "    )\n"
    )
    return text.replace(old_block, new_block)


# ── Operation registry ──────────────────────────────────────────────────────────

OPERATIONS: List[Tuple[str, Path, Callable[[str], str]]] = [
    (
        "delete _CAPABILITY_KW frozenset",
        ROOT / "orchestrator/agents/dialogue_agent.py",
        _cleanup_capability_kw,
    ),
    (
        "delete _STRONG_FACILITY_KW frozenset",
        ROOT / "orchestrator/agents/dialogue_agent.py",
        _cleanup_strong_facility_kw,
    ),
    (
        "delete cache-hit-path keyword override",
        ROOT / "orchestrator/agents/dialogue_agent.py",
        _cleanup_cache_hit_override,
    ),
    (
        "delete hot-path keyword override",
        ROOT / "orchestrator/agents/dialogue_agent.py",
        _cleanup_hot_path_override,
    ),
    (
        "flatten feature-flag guards",
        ROOT / "orchestrator/agents/dialogue_agent.py",
        _cleanup_feature_flag_guards,
    ),
    ("delete feature flag from config.py", ROOT / "shared/config.py", _cleanup_flag_definition),
    (
        "delete CapabilityKB.search() method",
        ROOT / "shared/capability_schema.py",
        _cleanup_capability_kb_search,
    ),
    (
        "delete capability_agent kb.search fallback",
        ROOT / "orchestrator/agents/capability_agent.py",
        _cleanup_capability_agent_fallback,
    ),
    (
        "delete 'keyword' option from fallback_on_qdrant_failure",
        ROOT / "shared/capability_schema.py",
        _cleanup_fallback_keyword_option,
    ),
    (
        "invert CapabilityKB.search() existence test",
        ROOT / "tests/test_capability_routing_config.py",
        _invert_kb_search_test,
    ),
]


# ── Runner ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    parser.add_argument(
        "--no-backup", action="store_true", help="Skip .bak_phase3 file backup (NOT RECOMMENDED)"
    )
    args = parser.parse_args()

    print("=" * 72)
    print("  Phase 3 Cleanup -- Capability Semantic Routing")
    print(f"  Dry run: {args.dry_run}")
    print("=" * 72)

    # Group operations by file so we apply all changes to each file in one pass
    by_file: dict = {}
    for desc, path, fn in OPERATIONS:
        by_file.setdefault(path, []).append((desc, fn))

    changes_made = 0
    for path, ops in by_file.items():
        if not path.exists():
            print(f"[skip] {path.relative_to(ROOT)} does not exist")
            continue

        original = path.read_text(encoding="utf-8")
        transformed = original
        applied = []
        for desc, fn in ops:
            before_len = len(transformed)
            transformed = fn(transformed)
            after_len = len(transformed)
            if after_len < before_len:
                applied.append((desc, before_len - after_len))

        if not applied:
            print(f"[noop] {path.relative_to(ROOT)} — no changes (already clean?)")
            continue

        print(f"\n[file] {path.relative_to(ROOT)}")
        for desc, bytes_removed in applied:
            print(f"  - {desc}: -{bytes_removed} bytes")

        if args.dry_run:
            print(f"  (dry-run; no write)")
            continue

        if not args.no_backup:
            backup = path.with_suffix(path.suffix + ".bak_phase3")
            shutil.copy(path, backup)
            print(f"  backup: {backup.relative_to(ROOT)}")

        path.write_text(transformed, encoding="utf-8")
        changes_made += 1

    print("\n" + "=" * 72)
    print(f"  Files modified: {changes_made}")
    print("=" * 72)

    if args.dry_run:
        return

    # Verification grep
    print("\n[verify] grep checks (all must return zero matches):\n")
    checks = [
        (["grep", "-rn", "_CAPABILITY_KW", "orchestrator/", "shared/"], "_CAPABILITY_KW removed"),
        (
            ["grep", "-rn", "_STRONG_FACILITY_KW", "orchestrator/", "shared/"],
            "_STRONG_FACILITY_KW removed",
        ),
        (
            ["grep", "-rn", "CAPABILITY_SEMANTIC_ROUTING_ENABLED", "orchestrator/", "shared/"],
            "feature flag removed",
        ),
    ]
    any_fail = False
    for cmd, label in checks:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            print(f"  [FAIL] {label}:")
            for ln in result.stdout.splitlines()[:5]:
                print(f"         {ln}")
            any_fail = True
        else:
            print(f"  [PASS] {label}")

    if any_fail:
        print(
            "\nSome cleanup operations did not remove all references. "
            "Review the offending lines manually and re-run."
        )
        sys.exit(1)

    print("\nCleanup complete. Recommended next steps:")
    print("  1. Clear stale Python bytecode (Windows + volume-mount race):")
    print("       find orchestrator shared -name __pycache__ -type d | xargs rm -rf")
    print("  2. Force-recreate orchestrator so new code is loaded:")
    print("       docker-compose up -d --force-recreate orchestrator")
    print("  3. Wait for /health, then run the post-cleanup test battery:")
    print("       pytest tests/test_embedding_service.py \\")
    print("              tests/test_capability_routing_config.py \\")
    print("              tests/test_capability_indexer.py \\")
    print("              tests/test_semantic_router.py -q")
    print("       pytest tests/test_capability_e2e.py \\")
    print("              tests/test_floor_n_protection.py \\")
    print("              tests/test_capability_semantic_quality.py -v")
    print("       python scripts/survey_live_test.py")
    print("  4. Compare survey result to tests/baselines/survey_phase1_flag_off.json.")
    print("  5. If all green, apply the CLAUDE.md patch from")
    print("     docs/superpowers/plans/2026-05-21-claude-md-patch.md")
    print("  6. Review diff, then commit (when ready).")


if __name__ == "__main__":
    main()
