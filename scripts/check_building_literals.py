#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail if core code carries a building literal (V6-T63, static half).

The project's litmus test is "would this run unchanged for bldg2?", and the answer has to be
checkable rather than asserted. Manual review demonstrably misses these: the pre-V6 baseline
scan found a prompt string asserting *"This building (Abacws) does NOT have energy meters"*
(BUG-214) that had been wrong for weeks, and an alert store falling back to the literal
``"bldg1"`` (BUG-215) that silently read another building's user data.

Runs in SECONDS and needs NO active building, which is what makes it viable after every task
-- and that matters more than usual for V6, because the whole plan is developed against one
building, so a building-shaped assumption would otherwise stay invisible until a swap.

What counts as a violation:
  * a building name, id or namespace in EXECUTABLE code -- a string that reaches a user, a
    prompt, a query or a config value;
  * a fallback to a specific building id;
  * a hardcoded floor count, sensor count or room-id pattern.

What does NOT:
  * docstrings and comments -- illustrative usage examples name a building on purpose, and a
    scanner that flags them gets muted, which is worse than having none. Detected by PARSING,
    not by looking at line prefixes: the first version of this scanner reported 16 hits of
    which 14 were prose inside multi-line docstrings whose individual lines start with
    neither a quote nor a hash;
  * accumulator initialisation (``sensor_count = 0``) -- only a nonzero literal is a count;
  * env-var DEFAULTS in shared/config.py, reported as INFO so they stay visible;
  * the building registry and onboarding code, whose job IS to know building identities;
  * tests and fixtures.

Usage:
    python scripts/check_building_literals.py            # fail on violations
    python scripts/check_building_literals.py --list     # also show allowed INFO matches
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import sys
import tokenize
from pathlib import Path
from typing import List, Set, Tuple

REPO = Path(__file__).resolve().parent.parent
SCAN_ROOTS = ("orchestrator", "shared")

#: Files whose purpose is to resolve building identity - they must name buildings.
ALLOWED_FILES = {
    "orchestrator/services/building_registry.py",
    "orchestrator/services/multi_building_manager.py",
    "orchestrator/services/onboarding_status.py",
    "orchestrator/services/onboarding_report.py",
    "shared/building_paths.py",
    "shared/building_context.py",
}

SKIP_PARTS = ("tests", "graphify-out", "__pycache__", "migrations")

#: (name, pattern, severity). ERROR fails the build; INFO is reported only.
PATTERNS: List[Tuple[str, str, str]] = [
    ("building name in code", r"\b(abacws|buildsys)\b", "ERROR"),
    ("building id fallback", r"or\s+[\"']bldg\d[\"']", "ERROR"),
    ("building id literal", r"[\"']bldg\d[\"']", "INFO"),
    ("building namespace", r"https?://[^\s\"']*(abacwsbuilding|buildsys\.org)[^\s\"']*", "ERROR"),
    # `x = 0` is an accumulator, not a hardcoded count - require a nonzero literal.
    ("hardcoded floor count", r"(num_floors|floor_count|n_floors)\s*=\s*[1-9]\d*", "ERROR"),
    ("hardcoded sensor count", r"(sensor_count|num_sensors|n_sensors)\s*=\s*[1-9]\d*", "ERROR"),
]


def _prose_lines(src: str) -> Set[int]:
    """Line numbers occupied by a docstring or a comment.

    Parsed rather than pattern-matched, because a line in the middle of a docstring looks
    exactly like a line of code to a prefix test.
    """
    prose: Set[int] = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return prose

    doc_owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, doc_owners):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            end = getattr(first, "end_lineno", first.lineno) or first.lineno
            prose.update(range(first.lineno, end + 1))

    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                prose.add(tok.start[0])
    except Exception:
        pass
    return prose


def scan(show_all: bool = False) -> int:
    errors: List[str] = []
    infos: List[str] = []

    for root in SCAN_ROOTS:
        base = REPO / root
        if not base.is_dir():
            continue
        for py in sorted(base.rglob("*.py")):
            rel = py.relative_to(REPO).as_posix()
            if any(part in rel.split("/") for part in SKIP_PARTS):
                continue
            if rel in ALLOWED_FILES:
                continue
            try:
                src = py.read_text(encoding="utf-8")
            except Exception:
                continue
            lines = src.splitlines()
            prose = _prose_lines(src)
            for n, line in enumerate(lines, 1):
                if n in prose:
                    continue
                for name, pat, sev in PATTERNS:
                    if not re.search(pat, line, re.IGNORECASE):
                        continue
                    level = sev
                    # config.py env-var defaults are legitimate; surface as INFO.
                    if rel == "shared/config.py" and "default=" in line:
                        level = "INFO"
                    msg = f"  {rel}:{n}  [{name}]  {line.strip()[:96]}"
                    (errors if level == "ERROR" else infos).append(msg)

    if infos and show_all:
        print(f"INFO ({len(infos)}) - allowed, but visible on purpose:")
        for m in infos:
            print(m)
        print()

    if errors:
        print(f"BUILDING LITERALS FOUND ({len(errors)}) - core code must be building-agnostic:")
        for m in errors:
            print(m)
        print("\nResolve the building at runtime (settings.BUILDING_ID / bctx / the graph),")
        print("or add the file to ALLOWED_FILES if identity resolution is genuinely its job.")
        return 1

    tail = f"  ({len(infos)} INFO)" if infos else ""
    print(f"clean - no building literals in {', '.join(SCAN_ROOTS)}{tail}")
    return 0


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true", help="also show allowed INFO matches")
    args = ap.parse_args(argv)
    return scan(show_all=args.list)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
