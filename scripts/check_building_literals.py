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
#: Every tree that ships code, plus the files that describe a deployment.
#:
#: It was ("orchestrator", "shared"). The external review of 2026-09-06 found fifteen real
#: building literals and this guard reported "clean" -- because eleven of them were in
#: `frontend/`, `rag-service/`, `scripts/` and the compose files, which it never opened.
#: A guard whose scope excludes most of the codebase is a guard that certifies the part
#: nobody was worried about.
SCAN_ROOTS = ("orchestrator", "shared", "scripts", "rag-service", "frontend/src")

#: Non-Python files that carry deployment identity. Scanned line by line with the same
#: patterns; there is no docstring notion here, so a `#`-comment prefix is the only
#: exemption.
SCAN_FILES = (
    "docker-compose.yml",
    "docker-compose.bldg2.yml",
    "docker-compose.bldg3.yml",
    "docker-compose.bldgtest.yml",
)

#: Files whose purpose is to resolve building identity - they must name buildings.
ALLOWED_FILES = {
    "orchestrator/services/building_registry.py",
    "orchestrator/services/multi_building_manager.py",
    "orchestrator/services/onboarding_status.py",
    "orchestrator/services/onboarding_report.py",
    "shared/building_paths.py",
    "shared/building_context.py",
    # The guard's own patterns must spell the words it looks for.
    "scripts/check_building_literals.py",
}

SKIP_PARTS = (
    "tests",
    "graphify-out",
    "__pycache__",
    "migrations",
    "node_modules",
    "build",
    "dist",
    ".venv",
)

#: (name, pattern, severity). ERROR fails the build; INFO is reported only.
PATTERNS: List[Tuple[str, str, str]] = [
    ("building name in code", r"\b(abacws|buildsys)\b", "ERROR"),
    ("building id fallback", r"or\s+[\"']bldg\d[\"']", "ERROR"),
    ("building id literal", r"[\"']bldg\d[\"']", "INFO"),
    ("building namespace", r"https?://[^\s\"']*(abacwsbuilding|buildsys\.org)[^\s\"']*", "ERROR"),
    # `x = 0` is an accumulator, not a hardcoded count - require a nonzero literal.
    ("hardcoded floor count", r"(num_floors|floor_count|n_floors)\s*=\s*[1-9]\d*", "ERROR"),
    ("hardcoded sensor count", r"(sensor_count|num_sensors|n_sensors)\s*=\s*[1-9]\d*", "ERROR"),
    # ── added 2026-09-06 (V10 W2-2), each for a literal this guard reported clean ──
    #
    # The city. `cardiff` appears in namespaces, contact addresses and prompt exemplars,
    # and none of the patterns above matches it.
    ("city or campus name in code", r"\bcardiff\b", "ERROR"),
    # A placeholder namespace is worse than a wrong one: it resolves to nothing, so the
    # query returns zero rows and no error. `self_correction_engine` defaulted to
    # `http://example.com/building#` and produced silent empty repairs.
    (
        "placeholder namespace",
        r'https?://(example\.com|example\.org)/[^\s"\']*building',
        "ERROR",
    ),
    # A room identifier CONSTRUCTED from a floor number, or written as an exemplar. The
    # floor-plan service generated fourteen rooms per floor this way when PDF text was
    # empty (BUG-444), and the SPARQL prompt teaches `Room_5.01` in six places.
    (
        "room id in one building's grammar",
        # Paired with REQUIRE_CONTEXT below: this shape alone matched
        # `float(os.environ.get("...", "0.85"))` in three places, and a confidence
        # threshold is not a room.
        #
        # The context requirement is a SEPARATE check rather than a lookahead, because a
        # lookahead anchors at the MATCH position and the context word usually comes
        # first. Written as `(?=.*\bsensor\b)` it silently stopped matching
        # `CONTAINS(STR(?sensor), "5.08")` -- the exemplar it most needed to catch -- and
        # the finding count fell by five, which reads exactly like progress.
        r'["\']\s*(Room[_ ]?)?\d\.\d{2}\s*["\']',
        "ERROR",
    ),
    (
        "room id built from a floor number",
        # Anchored on a DIGIT format spec, so it catches `f"{floor}.{n:02d}"` --
        # fourteen invented rooms per floor (BUG-444) -- and not
        # `f"fp.{building_id}.{floor}.{slug}"`, which composes an id from the
        # building's own values and is exactly what this guard wants to see. The
        # first version flagged three correct lines in floor_plan_pipeline.
        r'\{floor\}\.\{[a-z_]*:?0?\d*d\}',
        "ERROR",
    ),
    # A storage key from one building's registry. `anomaly/diagnosis.py` hardcoded
    # `stored_at: "plant_data"`, which only bldg1's registry defines.
    (
        "datasource key literal",
        r'stored_at["\']?\s*[:=]\s*["\'][a-z_]+_data["\']',
        "ERROR",
    ),
    # A per-building path baked into a mount or a default.
    (
        "building path literal",
        r'["\'./][^\s"\']*(data|input|volumes)/bldg\d',
        "ERROR",
    ),
]

#: Rules that only mean something with a spatial word on the same line.
#:
#: `"5.08"` is a room in `CONTAINS(STR(?sensor), "5.08")` and a threshold in
#: `float(os.environ.get(..., "0.85"))`. Nothing about the literal distinguishes them; the
#: rest of the line does.
REQUIRE_CONTEXT = {
    "room id in one building's grammar": re.compile(
        r"\b(room|zone|space|sensor|floor|storey)\b", re.IGNORECASE
    ),
}


def _js_prose_lines(src: str) -> Set[int]:
    """Line numbers inside a `//` or block comment in a JavaScript file.

    Needed because the Python path parses an AST, and JS has none here. Without it the
    guard reported FIVE of its own fix comments -- the ones explaining which building
    literal was removed and why -- as building literals. A guard that flags the
    documentation of its own findings is one nobody reads twice.
    """
    prose: Set[int] = set()
    in_block = False
    for n, line in enumerate(src.splitlines(), 1):
        s = line.strip()
        if in_block:
            prose.add(n)
            if "*/" in s:
                in_block = False
            continue
        if s.startswith("//") or s.startswith("*"):
            prose.add(n)
        elif s.startswith("/*"):
            prose.add(n)
            in_block = "*/" not in s
    return prose


def _prose_lines(src: str, suffix: str = ".py") -> Set[int]:
    """Line numbers occupied by a docstring or a comment.

    Parsed rather than pattern-matched, because a line in the middle of a docstring looks
    exactly like a line of code to a prefix test.
    """
    if suffix in (".js", ".jsx"):
        return _js_prose_lines(src)
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
        # `.js`/`.jsx` for the frontend, which held four literals this guard never saw:
        # "Abacws SmartBot" in the nav, a `|| "abacws"` fallback in the plan viewer, and a
        # TTL editor placeholder pre-seeded with one building's namespace.
        files = sorted(base.rglob("*.py")) + sorted(base.rglob("*.js")) + sorted(
            base.rglob("*.jsx")
        )
        for py in files:
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
            prose = _prose_lines(src, py.suffix.lower())
            for n, line in enumerate(lines, 1):
                if n in prose:
                    continue
                for name, pat, sev in PATTERNS:
                    if not re.search(pat, line, re.IGNORECASE):
                        continue
                    _ctx = REQUIRE_CONTEXT.get(name)
                    if _ctx is not None and not _ctx.search(line):
                        continue
                    level = sev
                    # config.py env-var defaults are legitimate; surface as INFO.
                    if rel == "shared/config.py" and "default=" in line:
                        level = "INFO"
                    # ── severity depends on WHICH TREE ──────────────────────────
                    #
                    # `orchestrator/`, `shared/`, `frontend/src/` and `rag-service/` must
                    # run unchanged for a building this repo has never seen. A literal
                    # there is a defect.
                    #
                    # `scripts/` is different, and pretending otherwise would make the
                    # guard useless. A generator that writes ONE building's TTL, a QA
                    # battery that asks real questions about the active building, a
                    # one-off extraction from a survey -- each names a building on
                    # purpose, and 26 of the first run's 98 findings were QA questions.
                    # Reported as INFO so they stay countable: the fact that bldg1's data
                    # exists only as hand-written generators IS a finding, just a
                    # different one (V10 W3-2/W3-3), and burying the agnosticism defects
                    # under it would be the way to lose both.
                    if rel.startswith("scripts/"):
                        level = "INFO"
                    msg = f"  {rel}:{n}  [{name}]  {line.strip()[:96]}"
                    (errors if level == "ERROR" else infos).append(msg)

    # ── deployment files ────────────────────────────────────────────────────
    for name in SCAN_FILES:
        f = REPO / name
        if not f.is_file():
            continue
        try:
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                for pname, pat, sev in PATTERNS:
                    _ctx = REQUIRE_CONTEXT.get(pname)
                    if _ctx is not None and not _ctx.search(line):
                        continue
                    if re.search(pat, line, re.IGNORECASE):
                        msg = f"  {name}:{n}  [{pname}]  {line.strip()[:96]}"
                        (errors if sev == "ERROR" else infos).append(msg)
        except Exception:
            continue

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
