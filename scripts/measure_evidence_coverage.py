#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""I4 (QA-trial plan, 2026-10-04): measure "users get the evidence every time" as a
number, not an assertion.

Reads every stored answer in the files given (default: docs/phase0/*.jsonl and
scratchpad/*.jsonl, de-duplicated by answer text) and reports, over the figure-bearing
subset (publication_gate.has_quantitative_claim):

  * share with a "Sources:" footer (provenance.build_tags' rendered line)
  * share with the full inline evidence panel (D11, <details type="evidence">)
  * share with EITHER (the owner's actual requirement -- a reader sees where a figure
    came from, by whichever mechanism was live when that answer was captured)

What this does NOT measure, and says so rather than silently omitting it: the share of
EVIDENCE RECORDS with at least one bound source, and the unbound-claim rate from
claim_binder -- both need the evidence_record/claim_binding structures, which are not
present in these stored text files. scripts/measure_evidence_coverage_live.py (if ever
written) would read those from a live conversation's Redis state or the D9 projection
once it exists; this script is the text-only half that can run today.

Usage:
    python scripts/measure_evidence_coverage.py
    python scripts/measure_evidence_coverage.py --glob "docs/phase0/tail_*.jsonl"
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrator.services.publication_gate import has_quantitative_claim  # noqa: E402

DEFAULT_GLOBS = ["docs/phase0/*.jsonl", "scratchpad/*.jsonl"]


def _answer_texts(globs: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for pattern in globs:
        for path in glob.glob(pattern):
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or not line.startswith("{"):
                            continue
                        try:
                            rec = json.loads(line)
                        except Exception:
                            continue
                        if not isinstance(rec, dict):
                            continue
                        text = None
                        for key in ("answer", "response", "text", "content"):
                            v = rec.get(key)
                            if isinstance(v, str) and v.strip():
                                text = v
                                break
                        if text and text not in seen:
                            seen.add(text)
                            out.append(text)
            except Exception:
                continue
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--glob", action="append", dest="globs", default=None, help="Glob of jsonl files to read"
    )
    args = parser.parse_args()
    globs = args.globs or DEFAULT_GLOBS

    texts = _answer_texts(globs)
    figure_bearing = [t for t in texts if has_quantitative_claim(t)]
    has_footer = [t for t in figure_bearing if "*Sources:" in t]
    has_panel = [t for t in figure_bearing if '<details type="evidence">' in t]
    has_either = [t for t in figure_bearing if t in set(has_footer) | set(has_panel)]

    print(f"Unique stored answers read: {len(texts)}")
    print(f"Figure-bearing (has_quantitative_claim): {len(figure_bearing)}")
    if figure_bearing:
        n = len(figure_bearing)
        print(
            f"  with a Sources: footer:        {len(has_footer):5d} / {n} = {100*len(has_footer)/n:.1f}%"
        )
        print(
            f"  with the D11 evidence panel:    {len(has_panel):5d} / {n} = {100*len(has_panel)/n:.1f}%"
        )
        print(
            f"  with EITHER (owner's claim):     {len(has_either):5d} / {n} = {100*len(has_either)/n:.1f}%"
        )
    print()
    print(
        "NOT measured here: share of evidence RECORDS with >=1 bound source, and the "
        "unbound-claim rate -- both need evidence_record/claim_binding structures not "
        "present in these stored text files. See this script's own docstring."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
