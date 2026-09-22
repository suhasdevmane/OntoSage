# -*- coding: utf-8 -*-
"""Remove ``ontosage:isSimulated`` from a building's TTL (building-agnostic).

WHY. The building's 680 installed sensors report real readings and the rest of the estate is
modelled on them. That is disclosed once, in the paper, not hedged inside every answer — so the
system stops distinguishing the two. A reading is a reading; a record is a record.

WHY NOT rdflib. Re-serialising the graph would produce valid Turtle and throw away every comment
and all the formatting, and these files are maintained by hand: the comments explain where each
register came from. So this is careful text surgery instead, and it VERIFIES the result by parsing
every file and counting triples.

THE CASE THAT BREAKS A NAIVE DELETE. 1,796 of the occurrences are the LAST predicate of their
block::

    ontosage:answerText "..." ;
    ontosage:isSimulated true .

Deleting that line alone leaves the block ending in ``;`` with no terminator, and the file no longer
parses. Where the removed line ends the statement, the previous predicate line inherits the ``.``.

    python scripts/strip_simulated_flag.py --dir bldg1           # apply
    python scripts/strip_simulated_flag.py --dir bldg1 --check   # report, change nothing

Nothing here names a building: point it at whichever directory holds the TTL.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

REPO = Path(__file__).resolve().parent.parent

#: A predicate line for the flag, whatever its object form: `true`, `"true"^^xsd:boolean`, `false`.
_FLAG_LINE = re.compile(r"^\s*(?:\w+:)?isSimulated\s+.*?\s*([;.])\s*$", re.IGNORECASE)

#: A line that ends a statement (so it can absorb the terminator of a removed last predicate).
_ENDS_WITH_SEMICOLON = re.compile(r";\s*$")


def strip_text(text: str) -> Tuple[str, int]:
    """Return (new text, lines removed). Comments are left alone; they are prose, not triples."""
    lines = text.splitlines(keepends=False)
    out: List[str] = []
    removed = 0
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            out.append(line)
            continue
        m = _FLAG_LINE.match(line)
        if not m:
            out.append(line)
            continue
        removed += 1
        if m.group(1) == ".":
            # This line ENDED the statement. Hand the full stop back to the previous predicate,
            # or the block loses its terminator and the file stops parsing.
            for i in range(len(out) - 1, -1, -1):
                prev = out[i]
                if not prev.strip() or prev.lstrip().startswith("#"):
                    continue
                if _ENDS_WITH_SEMICOLON.search(prev):
                    out[i] = _ENDS_WITH_SEMICOLON.sub(" .", prev)
                break
    return ("\n".join(out) + ("\n" if text.endswith("\n") else "")), removed


def count_triples(path: Path) -> int:
    import rdflib

    g = rdflib.Graph()
    g.parse(str(path), format="turtle")
    return len(g)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="directory holding the building's .ttl files")
    ap.add_argument("--check", action="store_true", help="report only; write nothing")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    root = Path(args.dir)
    files = sorted(p for p in root.glob("*.ttl"))
    if not files:
        print(f"no .ttl under {root}")
        return 2

    total_removed = total_before = total_after = 0
    touched = failed = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        if "isSimulated" not in text:
            continue
        new, removed = strip_text(text)
        if removed == 0:
            continue                       # only comments mentioned it
        before = count_triples(path)
        backup = path.with_suffix(path.suffix + ".presimflag")
        if not args.check:
            backup.write_text(text, encoding="utf-8")
            path.write_text(new, encoding="utf-8")
        try:
            after = count_triples(path) if not args.check else before - removed
        except Exception as exc:
            print(f"  BROKE {path.name}: {exc}")
            if not args.check:
                path.write_text(text, encoding="utf-8")   # put it back; never ship a broken file
                backup.unlink(missing_ok=True)
            failed += 1
            continue
        if not args.check:
            backup.unlink(missing_ok=True)
        lost = before - after
        flag = "" if lost == removed else f"  <-- expected -{removed}, got -{lost}"
        print(f"  {path.name:52s} -{removed:5d} triples {before} -> {after}{flag}")
        touched += 1
        total_removed += removed
        total_before += before
        total_after += after

    verb = "would remove" if args.check else "removed"
    print(f"\n{verb} {total_removed} flag triple(s) from {touched} file(s)")
    if not args.check:
        print(f"graph: {total_before} -> {total_after} triples in the files touched")
    if failed:
        print(f"{failed} file(s) would not parse after the edit and were left unchanged")
        return 1
    left = sum(1 for p in files
               if re.search(r"^\s*(?:\w+:)?isSimulated\b", p.read_text(encoding="utf-8"), re.M))
    print(f"files still declaring the flag: {left}")
    return 0 if left == 0 or args.check else 1


if __name__ == "__main__":
    sys.exit(main())
