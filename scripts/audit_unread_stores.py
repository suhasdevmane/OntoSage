#!/usr/bin/env python
"""Find data this system STORES that nothing reads back.

Why this exists
---------------
Five separate capabilities in this codebase shipped correct, tested, and with no
invoker: the institutional feed adapter, ``AssetStatus`` triples, ``ServiceSchedule``
triples, ``link_to_work_order()``, and Module P's amenity vocabulary. Each was
authored, each had passing tests, and each was externally indistinguishable from
the feature being absent -- the system answered "I have no information" while
holding exactly that. The detector is cheap and mechanical: *for every kind of
data stored, find the code that reads it back.* Applied to the graph, it found
all five. This applies the same question to the relational stores.

What it does
------------
Static analysis. For every SQL table it can see:

* WRITES  -- ``INSERT INTO t``, ``REPLACE INTO t``, ``UPDATE t``, ``COPY t``
* READS   -- ``FROM t``, ``JOIN t``
* DDL     -- ``CREATE TABLE t``

and reports the tables that are written but never read, plus the columns declared
in a ``CREATE TABLE`` whose names appear nowhere else in the repository.

What it cannot see
------------------
Stated plainly, because a finding nobody can act on is worse than no finding:

* Table names built at runtime (``f"{modality}_data"``) -- reported separately as
  DYNAMIC rather than silently counted as unread.
* Readers outside this repository -- Grafana panels, OpenWebUI, a DBA at a prompt.
* Reads through an ORM or a query assembled from fragments.

So the output is a list of *questions to ask*, not a list of defects. Every hit
needs a human to confirm the data is genuinely orphaned before anything is
deleted.

Run:
  python scripts/audit_unread_stores.py            # human-readable report
  python scripts/audit_unread_stores.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set

REPO = Path(__file__).resolve().parents[1]
SCAN_DIRS = ["orchestrator", "shared", "scripts", "data", "tests"]
SCAN_SUFFIXES = {".py", ".sql"}

# A SQL identifier, optionally backticked or quoted.
_IDENT = r"[`\"\[]?(\w+)[`\"\]]?"

WRITE_RE = [
    re.compile(rf"\binsert\s+(?:ignore\s+)?into\s+{_IDENT}", re.I),
    re.compile(rf"\breplace\s+into\s+{_IDENT}", re.I),
    re.compile(rf"\bupdate\s+{_IDENT}\s+set\b", re.I),
    re.compile(rf"\bcopy\s+{_IDENT}\s*\(", re.I),
]
READ_RE = [
    re.compile(rf"\bfrom\s+{_IDENT}", re.I),
    re.compile(rf"\bjoin\s+{_IDENT}", re.I),
]
DDL_RE = re.compile(rf"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?{_IDENT}", re.I)
# An interpolated table name: INSERT INTO {table}, f"SELECT ... FROM {modality}_data"
DYNAMIC_RE = re.compile(r"\b(?:insert\s+into|from|join|update)\s+[`\"]?\{", re.I)

# A Python import is not a table read.
_PY_FROM_NOISE = re.compile(r"^\s*(?:from\s+[\w.]+\s+import|import)\b")

# Words that match the grammar but are never table names.
STOPWORDS = {
    "select",
    "where",
    "dual",
    "information_schema",
    "table",
    "values",
    "set",
    "the",
    "a",
    "an",
    "this",
    "that",
    "it",
    "them",
    "here",
    "and",
    "or",
    "not",
    "none",
    "true",
    "false",
    "self",
    "python",
    "typing",
    "pathlib",
    "datetime",
    "collections",
}


def _files(root_dir: Optional[Path] = None) -> List[Path]:
    base = root_dir or REPO
    dirs = SCAN_DIRS if root_dir is None else ["."]
    me = Path(__file__).resolve()
    out: List[Path] = []
    for d in dirs:
        root = base / d
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.suffix.lower() not in SCAN_SUFFIXES or ".worktrees" in p.parts:
                continue
            # This file's own prose describes SQL; it is not SQL. Scanning it
            # reported "whose" as an unread table, out of the sentence explaining
            # what an unread column is.
            if p.resolve() == me:
                continue
            out.append(p)
    return sorted(out)


def scan(root_dir: Optional[Path] = None) -> Dict[str, object]:
    writes: Dict[str, Set[str]] = defaultdict(set)
    reads: Dict[str, Set[str]] = defaultdict(set)
    ddl: Dict[str, Set[str]] = defaultdict(set)
    dynamic: Set[str] = set()
    corpus: List[str] = []

    for path in _files(root_dir):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        corpus.append(text)
        rel = str(path.relative_to(root_dir or REPO)).replace("\\", "/")
        if DYNAMIC_RE.search(text):
            dynamic.add(rel)
        for line in text.splitlines():
            if _PY_FROM_NOISE.match(line):
                continue
            for rx in WRITE_RE:
                for m in rx.finditer(line):
                    t = m.group(1).lower()
                    if t not in STOPWORDS:
                        writes[t].add(rel)
            for rx in READ_RE:
                for m in rx.finditer(line):
                    t = m.group(1).lower()
                    if t not in STOPWORDS:
                        reads[t].add(rel)
        for m in DDL_RE.finditer(text):
            t = m.group(1).lower()
            if t not in STOPWORDS:
                ddl[t].add(rel)

    known = set(writes) | set(ddl)
    unread = sorted(t for t in known if t not in reads)

    # A table read through a runtime-built name -- SELECT ... FROM {modality}_data --
    # has no literal FROM to find, so "no reader" would be a lie about the seven
    # narrow modality tables the MySQL adapter serves every sensor question from.
    # Split the finding by how much is actually known: a table whose name appears
    # NOWHERE but its own write site is a strong signal; one named in a registry or
    # a modality map is almost certainly reached that way, and the audit says which
    # files to look in rather than pretending to have decided.
    elsewhere = _mentions_outside_sql(unread, {**writes, **ddl}, root_dir=root_dir)
    strong = sorted(t for t in unread if not elsewhere.get(t))
    weak = sorted(t for t in unread if elsewhere.get(t))
    return {
        "writes": {k: sorted(v) for k, v in writes.items()},
        "reads": {k: sorted(v) for k, v in reads.items()},
        "ddl": {k: sorted(v) for k, v in ddl.items()},
        "dynamic_files": sorted(dynamic),
        "unread_tables": unread,
        "unread_no_other_mention": strong,
        "unread_but_named_elsewhere": weak,
        "mentions": elsewhere,
        "corpus": corpus,
    }


#: Where a table name can legitimately appear without a literal SQL read: a
#: datasource registry, a modality map, a compose file, a migration note.
_MENTION_SUFFIXES = {".py", ".sql", ".yaml", ".yml", ".json", ".md", ".ttl", ".env"}


def _mentions_outside_sql(
    tables: List[str],
    written_in: Dict[str, Set[str]],
    *,
    root_dir: Optional[Path] = None,
) -> Dict[str, List[str]]:
    """For each table, the files naming it that are not its own write/DDL site."""
    if not tables:
        return {}
    base = root_dir or REPO
    out: Dict[str, List[str]] = {}
    patterns = {t: re.compile(rf"\b{re.escape(t)}\b", re.I) for t in tables}
    dirs = ["."] if root_dir else SCAN_DIRS + ["config", "input", "bldg1", "bldg2", "bldg3"]
    for d in dirs:
        root = base / d
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.suffix.lower() not in _MENTION_SUFFIXES or ".worktrees" in p.parts:
                continue
            if p.resolve() == Path(__file__).resolve():
                continue  # this file's own prose is not evidence of anything
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = str(p.relative_to(base)).replace("\\", "/")
            for t, rx in patterns.items():
                if rel in written_in.get(t, set()):
                    continue
                if rx.search(text):
                    out.setdefault(t, []).append(rel)
    return {k: sorted(set(v)) for k, v in out.items()}


_DDL_BLOCK = re.compile(
    rf"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?{_IDENT}\s*\((.*?)\n\s*\)", re.I | re.S
)
_NOT_A_COLUMN = {
    "primary",
    "key",
    "unique",
    "index",
    "constraint",
    "foreign",
    "check",
    "fulltext",
    "spatial",
}


def unread_columns(corpus: List[str]) -> Dict[str, List[str]]:
    """Columns declared in a CREATE TABLE whose name appears nowhere else."""
    blob = "\n".join(corpus)
    out: Dict[str, List[str]] = {}
    for text in corpus:
        for m in _DDL_BLOCK.finditer(text):
            table = m.group(1).lower()
            cols = []
            for raw in m.group(2).split("\n"):
                first = raw.strip().strip(",").split(" ")[0].strip('`"[]')
                if not first or not re.fullmatch(r"\w+", first):
                    continue
                if first.lower() in _NOT_A_COLUMN:
                    continue
                cols.append(first)
            orphans = [c for c in cols if len(re.findall(rf"\b{re.escape(c)}\b", blob)) <= 1]
            if orphans:
                out.setdefault(table, []).extend(orphans)
    return {k: sorted(set(v)) for k, v in out.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description="Find stored data nothing reads back.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    result = scan()
    cols = unread_columns(result["corpus"])  # type: ignore[arg-type]
    result.pop("corpus")

    if args.json:
        print(json.dumps({**result, "unread_columns": cols}, indent=2))
        return 0

    strong: List[str] = result["unread_no_other_mention"]  # type: ignore[assignment]
    weak: List[str] = result["unread_but_named_elsewhere"]  # type: ignore[assignment]
    mentions: Dict[str, List[str]] = result["mentions"]  # type: ignore[assignment]
    writes: Dict[str, List[str]] = result["writes"]  # type: ignore[assignment]
    ddl: Dict[str, List[str]] = result["ddl"]  # type: ignore[assignment]

    print("=" * 78)
    print("Written, and named nowhere else in the repository")
    print("=" * 78)
    if not strong:
        print("\nNothing. (Static analysis only -- see the module docstring.)")
    for t in strong:
        where = writes.get(t) or ddl.get(t, [])
        print(f"\n  {t}")
        print(f"      written/declared in: {', '.join(where[:4])}")
        print("      read in:             (nothing found)")

    if weak:
        print("\n" + "-" * 78)
        print("No literal SQL read, but named elsewhere -- probably reached through a")
        print("query built at runtime. Look before concluding anything.")
        print("-" * 78)
        for t in weak:
            print(f"  {t}: {', '.join(mentions.get(t, [])[:3])}")

    if cols:
        print("\n" + "-" * 78)
        print("Columns declared in a CREATE TABLE and named nowhere else")
        print("-" * 78)
        for t, cs in sorted(cols.items()):
            print(f"  {t}: {', '.join(cs)}")

    dyn: List[str] = result["dynamic_files"]  # type: ignore[assignment]
    if dyn:
        print("\n" + "-" * 78)
        print(f"Files that build table names at runtime ({len(dyn)}) -- invisible to this scan")
        print("-" * 78)
        for f in dyn[:15]:
            print(f"  {f}")
        if len(dyn) > 15:
            print(f"  ...and {len(dyn) - 15} more")

    print("\nEvery hit is a QUESTION, not a defect: confirm there is no reader outside")
    print("this repository before deleting anything.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
