#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prove that nothing in any backlog was left behind by the V12 plan.

The V12 plan claims to cover every unresolved item recorded anywhere in this
repository.  A claim like that rots the moment somebody opens a new bug, so it is
not written down as prose -- it is re-derived here, on demand, from the sources
themselves.

The audit derives the open set from:

  * ``tasks/FIX_TRACKER.csv``  -- every row whose status is not a closed status,
    PLUS every closed row whose own Verification text admits that a live re-ask
    is still owed.  That second half matters: seven rows sat at ``FIXED`` with
    "LIVE RE-ASK OWED" written into them, which is not the same as fixed.
  * ``tasks/V10_TRACKER.csv`` and ``tasks/V11_TRACKER.csv`` -- every row not
    ``done``.  V5/V6/V7 are out of scope; see the TRACKERS comment below.
  * The supervisor review's own backlog: tickets T01-T10 and regression
    catalogues A01-A16 / B01-B16 (fixed sets, so they are listed here).
  * Findings about the record-keeping itself, which no tracker can hold because
    they are defects IN the trackers.

and then asserts that every derived id is claimed by exactly one row of
``tasks/V12_TRACKER.csv`` (its ``covers`` column), or
appears in ``tasks/V12_WONTDO.csv`` with a stated reason.

Exit 0 = every open item is accounted for.  Exit 1 = something is unclaimed, and
the ids are printed.  It also reports *stale* coverage: a V12 row claiming an id
that no source considers open any more, which is how a plan quietly starts
describing work that is already done.

Usage:
    python scripts/v12_coverage_audit.py            # audit, exit non-zero on gaps
    python scripts/v12_coverage_audit.py --list     # print the derived open set
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import namedtuple
from typing import Dict, List, Set

Item = namedtuple("Item", "source sid title state")

# A tracker status that means the work is finished and verified.  Anything else
# -- including PARTIALLY_FIXED, MITIGATED, READY and FIXED_UNVERIFIED -- is open
# for the purposes of this audit, because each of those words describes work.
FIX_CLOSED = {
    "VERIFIED_LIVE",
    "DEPLOYED",
    "CLOSED",
    "FIXED",
    "DONE",
    "DUPLICATE",
    "WONTFIX",
    "WITHDRAWN",
    "REFUTED",
    "CLOSED_NOT_A_DEFECT",
    "CORRECTED_NOT_A_DEFECT",
    "FIXED (see FIX-030)",
}

# A closed row is still open work if it says so in its own words.  These are the
# phrases the tracker actually uses; a row that merely mentions a "residual" is
# triaged by hand into tasks/V12_WONTDO.csv rather than caught here, because
# most residuals are cosmetic and a few are not.
OWED_RE = re.compile(
    r"LIVE RE-?ASK OWED|LIVE VERIFICATION OWED|\bOWED:|Live re-ask pending",
    re.IGNORECASE,
)
# ...unless a later sentence in the same cell records that it was then done.
OWED_DISCHARGED_RE = re.compile(
    r"LIVE VERIFIED|RE-MEASURE DELIVERED|PROVEN LIVE|VERIFIED \d{4}-\d{2}-\d{2}",
    re.IGNORECASE,
)

# A row can be closed and still name work it did not do.  Most of these
# residuals are cosmetic and a few are the next defect; the audit refuses to
# guess which, so it surfaces every one and requires a human disposition in
# either a V12 row's `covers` or tasks/V12_WONTDO.csv.
RESIDUAL_RE = re.compile(
    r"RESIDUAL|HONEST CAVEAT|REMAINS OPEN|DECISION NEEDED"
    r"|WHY UNVERIFIED|UNVERIFIED:|NOT verified|not yet verified",
    re.IGNORECASE,
)

# V5, V6 and V7 are DELIBERATELY ABSENT.  The user assessed on 2026-09-09 that
# their substance shipped and their trackers carry stale status rather than open
# work, and a spot-check agreed on the load-bearing ones: freshness/staleness,
# provenance exposure (`answer_provenance.py`), specific declines
# (`enablement_hint`) and the baseline harnesses are all present in the code.
# Anything from those plans that is genuinely still wanted must be re-filed as a
# new row in tasks/FIX_TRACKER.csv -- which is what makes it current -- rather
# than resurrected from a three-week-old status column.  Two concepts had NO code
# when checked and are the candidates if that ever happens: CONFLICTED as a
# verification state (V7-T12) and purpose-bound permission (V7-T16).
TRACKERS = {
    "V10": "tasks/V10_TRACKER.csv",
    "V11": "tasks/V11_TRACKER.csv",
}

# The review's backlog is a fixed set published in the PDF, so it is enumerated
# rather than parsed.  Titles are the review's own wording, abbreviated.
REVIEW_TICKETS = {
    "REV-T01": "establish baseline: capability matrix, revision snapshot, LLM inventory, intent manifest",
    "REV-T02": "lock in incidents: exact historical failure set and minimal fixtures",
    "REV-T03": "enforce publication: claim-level verification and authorised final-response policy",
    "REV-T04": "make data failures explicit: typed retrieval outcomes and reference validation",
    "REV-T05": "preserve semantics: normalized request, time resolver, count and aggregation contracts",
    "REV-T06": "govern simulation: provenance labels and operational admissibility",
    "REV-T07": "finish routing contracts: precedence, answer collection, bounded mixed-source behaviour",
    "REV-T08": "prove ARBITER: criterion registry, eligibility/coverage rules, reproducible dossiers",
    "REV-T09": "evaluate and release: held-out results, repeated runs, limitation register, Gate decision",
    "REV-T10": "test portability: second-building readiness and intervention log",
}
REVIEW_CASES = {
    "REV-A01": "two matching sensors; the list function returns declared identifiers, never None silently",
    "REV-A02": "declared sensor with a working reference and rows is recognised as present",
    "REV-A03": "remove the store reference: REFERENCE_MISSING, not physical absence",
    "REV-A04": "unregistered store identifier: specific resolution failure, no substitute backend",
    "REV-A05": "wrong series id, with and without an existence catalogue: no false certainty",
    "REV-A06": "valid series, empty window: existence confirmed independently or left unknown",
    "REV-A07": "frozen clock, yesterday and today seeded apart: the requested day appears throughout",
    "REV-A08": "midnight and DST: boundaries follow the configured zone policy",
    "REV-A09": "more records than the limit: the known total is independent of truncation",
    "REV-A10": "max, min and average over the same data each use their intended operation",
    "REV-A11": "convertible then incompatible units: approved conversion explicit, rest rejected",
    "REV-A12": "duplicates, invalid values, out-of-order stamps: accepted and excluded counts recorded",
    "REV-A13": "two rooms share a label: resolved or clarified, never silently cross-selected",
    "REV-A14": "follow-up changes room or building: incompatible inherited state is cleared",
    "REV-A15": "the same seeded data through each supported adapter returns equivalent results",
    "REV-A16": "mapping or graph revision changes mid-turn: the snapshot policy prevents a mixed result",
    "REV-B01": "two routing rules match: documented priority resolves it and the trace says why",
    "REV-B02": "a supported intent runs and its response adapter is removed: contract validation fails",
    "REV-B03": "ECA positive and negative fixtures: the rule matches correctly, no actuation required",
    "REV-B04": "forced numerical verification failure: claims withheld in text, chart and export",
    "REV-B05": "numbers unchanged, rendered day/unit/room altered: the answer is blocked",
    "REV-B06": "simulated candidate scores best, also transformed: excluded in operational mode",
    "REV-B07": "remove a required criterion: eligibility applies, missing evidence is not rewarded",
    "REV-B08": "weight changes and ties: declared policy holds, limitations stay visible",
    "REV-B09": "future conditions with only observations: a limitation, not invented certainty",
    "REV-B10": "clarification exhausted, ambiguity remains: narrow or abstain, never guess",
    "REV-B11": "unauthorised room or derived sensitive output: policy applies before disclosure",
    "REV-B12": "cache cannot bypass the current authorisation and provenance policy",
    "REV-B13": "irrelevant keyword-sharing document rejected; a contradicting one surfaces the conflict",
    "REV-B14": "observations-plus-procedure: both subclaims sourced, or the unsupported part stated",
    "REV-B15": "timeout, outage and delayed completion: explicit partial outcome, retry distinguishable",
    "REV-B16": "generated execution asked to do something disallowed: limits hold (conditional case)",
}

# Defects in the record-keeping itself.  No tracker can hold these because they
# ARE the trackers; found by the V12 reconciliation sweep on 9 September 2026.
META = {
    "META-TRACKER-DIVERGENCE": "two copies of the V7 tracker disagree and the git-tracked one (docs/) is the stale copy",
    "META-CLAUDEMD-TWO-WORKSTREAMS": "CLAUDE.md declares two ACTIVE WORKSTREAMs at once (V11 in the snapshot, V5 under open issues)",
    "META-CLAUDEMD-STALE-OPEN-LIST": "CLAUDE.md's open-issues list names items that are closed in the fix tracker",
}


def _read(repo: str, rel: str) -> List[Dict[str, str]]:
    path = os.path.join(repo, *rel.split("/"))
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def derive_open_set(repo: str) -> List[Item]:
    """Re-derive every unresolved item from the sources, not from a saved list."""
    items: List[Item] = []

    for r in _read(repo, "tasks/FIX_TRACKER.csv"):
        status = (r.get("Status") or "").strip()
        sid = (r.get("ID") or "").strip()
        title = (r.get("Title") or "").strip()
        if not sid:
            continue
        if status not in FIX_CLOSED:
            items.append(Item("FIX_TRACKER", sid, title, status))
            continue
        blob = " ".join((r.get(k) or "") for k in ("Verification", "Fix_Approach", "Description"))
        m = OWED_RE.search(blob)
        if m and not OWED_DISCHARGED_RE.search(blob[m.end() :]):
            items.append(Item("FIX_TRACKER", sid, title, status + "+owed"))
        elif RESIDUAL_RE.search(blob):
            items.append(Item("FIX_TRACKER", sid, title, status + "+residual"))

    for name, rel in TRACKERS.items():
        for r in _read(repo, rel):
            status = (r.get("status") or "").strip()
            sid = (r.get("turn") or r.get("id") or "").strip()
            if not sid or status == "done":
                continue
            items.append(Item(name, sid, (r.get("title") or "").strip(), status))

    for sid, title in sorted(REVIEW_TICKETS.items()):
        items.append(Item("REVIEW", sid, title, "ticket"))
    for sid, title in sorted(REVIEW_CASES.items()):
        items.append(Item("REVIEW", sid, title, "case"))
    for sid, title in sorted(META.items()):
        items.append(Item("META", sid, title, "finding"))

    return items


def read_coverage(repo: str):
    """Return {source_id: [v12 rows]}, {row id: title}, {row id: {paired rows}}."""
    cover: Dict[str, List[str]] = {}
    titles: Dict[str, str] = {}
    pairs: Dict[str, Set[str]] = {}
    for rel in ("tasks/V12_TRACKER.csv",):
        for r in _read(repo, rel):
            rid = (r.get("id") or "").strip()
            titles[rid] = (r.get("title") or "").strip()
            pairs[rid] = {p for p in re.split(r"[/,\s]+", r.get("pairs_with") or "") if p}
            for sid in (r.get("covers") or "").split():
                cover.setdefault(sid, []).append(rid)
    return cover, titles, pairs


def _is_legitimate_pair(rows: List[str], pairs: Dict[str, Set[str]]) -> bool:
    """A build row and the verify row that names it may share one source id.

    Anything else claimed twice is two rows believing they own the same work,
    which is how an item gets done twice or not at all.
    """
    if len(rows) != 2:
        return False
    a, b = rows
    return b in pairs.get(a, set()) or a in pairs.get(b, set())


def read_wontdo(repo: str) -> Dict[str, str]:
    return {
        (r.get("source_id") or "").strip(): (r.get("disposition") or "").strip()
        for r in _read(repo, "tasks/V12_WONTDO.csv")
    }


def missing_sources(repo: str) -> List[str]:
    """Which inputs are absent.

    ``tasks/`` is gitignored at the user's request, so a fresh clone has the
    audit but none of the CSVs it reads.  Without this check the audit would
    derive only the review's fixed catalogue, find nothing claiming it, and
    report a wall of false gaps -- an instrument that lies when it is starved is
    worse than no instrument.
    """
    needed = (
        ["tasks/FIX_TRACKER.csv"]
        + list(TRACKERS.values())
        + [
            "tasks/V12_TRACKER.csv",
            "tasks/V12_WONTDO.csv",
        ]
    )
    return [rel for rel in needed if not os.path.exists(os.path.join(repo, *rel.split("/")))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--list", action="store_true", help="print the derived open set and stop")
    args = ap.parse_args()

    gone = missing_sources(args.repo)
    if gone:
        print("Cannot audit -- these inputs are absent:")
        for rel in gone:
            print(f"  {rel}")
        print(
            "\n`tasks/` is gitignored, so a fresh clone does not carry the backlog.\n"
            "Run this in the working tree that holds it. Reporting no gaps from a\n"
            "starved run would be worse than reporting nothing."
        )
        return 2

    openset = derive_open_set(args.repo)
    if args.list:
        for i in openset:
            print(f"{i.source:12} {i.sid:24} [{i.state}] {i.title[:70]}")
        print(f"\n{len(openset)} open items derived")
        return 0

    cover, titles, pairs = read_coverage(args.repo)
    wontdo = read_wontdo(args.repo)
    open_ids: Set[str] = {i.sid for i in openset}

    uncovered = [i for i in openset if i.sid not in cover and i.sid not in wontdo]
    doubled = {
        sid: rows
        for sid, rows in cover.items()
        if len(rows) > 1 and not _is_legitimate_pair(rows, pairs)
    }
    stale = {sid: rows for sid, rows in cover.items() if sid not in open_ids}
    stale_wontdo = sorted(sid for sid in wontdo if sid not in open_ids)

    print(f"open items derived   : {len(openset)}")
    print(f"claimed by a V12 row : {sum(1 for i in openset if i.sid in cover)}")
    print(
        f"in the won't-do file : {sum(1 for i in openset if i.sid in wontdo and i.sid not in cover)}"
    )
    print(f"V12 rows             : {len(titles)}")

    ok = True
    if uncovered:
        ok = False
        print(f"\nUNCOVERED ({len(uncovered)}) -- nothing in V12 claims these:")
        for i in uncovered:
            print(f"  {i.source:12} {i.sid:24} [{i.state}] {i.title[:64]}")
    if doubled:
        ok = False
        print(f"\nCLAIMED TWICE ({len(doubled)}) -- an item must have one owner:")
        for sid, rows in sorted(doubled.items()):
            print(f"  {sid:24} claimed by {', '.join(rows)}")
    if stale:
        print(f"\nSTALE COVERAGE ({len(stale)}) -- claimed but no source calls it open:")
        for sid, rows in sorted(stale.items()):
            print(f"  {sid:24} claimed by {', '.join(rows)}")
    if stale_wontdo:
        print(f"\nSTALE WON'T-DO ({len(stale_wontdo)}) -- listed but no source calls it open:")
        for sid in stale_wontdo:
            print(f"  {sid}")

    print(
        "\nOK -- every open item is accounted for."
        if ok
        else "\nFAIL -- the plan does not cover everything."
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
