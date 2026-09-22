# -*- coding: utf-8 -*-
"""What safety-critical facts has the ACTIVE building not stated yet? (building-agnostic)

Reads ``config/safety_critical_facts.yaml`` (kinds of fact and the ontology classes that would hold
them), asks the live graph how many instances of each class exist, and writes a checklist of what
the owner still has to supply. A fact the building has not stated is a question the system must
decline; a fact whose own record calls itself "modelled" is one a reader cannot act on.

    python scripts/owner_facts_report.py                     # prints, and writes docs/OWNER_FACTS_CHECKLIST.md
    python scripts/owner_facts_report.py --endpoint http://localhost:7200/repositories/bldg --no-write

Nothing here names a building. Exit status is 0 always (it is a report, not a gate).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

import requests
import yaml

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "config" / "safety_critical_facts.yaml"
NS = "http://ontosage.org/capabilities#"
DEFAULT_ENDPOINT = "http://127.0.0.1:7200/repositories/bldg"

_COUNT = """
PREFIX o: <{ns}>
SELECT (COUNT(DISTINCT ?s) AS ?n)
WHERE {{
  ?s a o:{cls} .
}}
"""

# A record can hold a fact under a class this file did not list: the defibrillator positions live on
# an instance typed FirstAidPoint, so a class-only count reported the fact MISSING while the system
# answered it from that very record (BUG-859). Reporting "not recorded" for a fact that IS answered
# is the dangerous direction of error, so also look for the fact's own words.
_BY_TERM = """
PREFIX o: <{ns}>
SELECT ?s ?terms ?loc WHERE {{
  ?s o:layTerms ?terms .
  OPTIONAL {{ ?s o:locationText ?loc }}
}}
"""

# Words a record uses when it is describing an EXAMPLE rather than a surveyed fact. This is about
# the record's OWN WORDING, not about where its data came from: every record is the building's own.
_HEDGES = ("modelled", "modeled", "placeholder", "assumed", "example", "illustrative",
           "synthetic", "notional", "for demonstration", "not verified", "unverified")


def _select(endpoint: str, query: str, timeout: int = 30) -> List[Dict[str, Any]]:
    r = requests.post(
        endpoint,
        data=query.encode("utf-8"),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return (r.json().get("results") or {}).get("bindings") or []


def held(endpoint: str, classes: List[str]) -> Dict[str, Dict[str, int]]:
    """{class: {"instances": n}} for every class that has at least one instance."""
    out: Dict[str, Dict[str, int]] = {}
    for cls in classes:
        rows = _select(endpoint, _COUNT.format(ns=NS, cls=cls))
        n = int(rows[0]["n"]["value"]) if rows else 0
        if n:
            out[cls] = {"instances": n, "placeholders": 0}
    return out


def by_lay_term(endpoint: str) -> List[Dict[str, str]]:
    """Every record that declares lay terms, with the location text it states."""
    out = []
    for row in _select(endpoint, _BY_TERM.format(ns=NS)):
        out.append({
            "iri": row["s"]["value"],
            "terms": (row.get("terms", {}) or {}).get("value", "").lower(),
            "loc": (row.get("loc", {}) or {}).get("value", ""),
        })
    return out


# Words too generic to identify a fact on their own: matching on them made one fact claim 112
# records. A match must rest on a distinctive word, not on "route" or "point".
_GENERIC = {"point", "points", "route", "routes", "what", "when", "only", "service", "facility",
            "record", "records", "kit", "area", "areas", "adult", "step", "free", "contacts",
            "contact", "hours", "people", "cannot", "stairs", "used", "exits", "level"}


def _WORDS(text: str) -> List[str]:
    return "".join(c if c.isalnum() else " " for c in text.lower()).split()


def _matches_terms(fact: Dict[str, Any], rec: Dict[str, str]) -> bool:
    """True when a record's declared lay terms name this fact.

    Whole words only, and never on a generic one: the first version matched any substring, so
    'route' pulled in 112 unrelated records and the report became noise.
    """
    wanted = {w for w in _WORDS(f"{fact.get('id', '')} {fact.get('label', '')}")
              if len(w) > 3 and w not in _GENERIC}
    declared = [t.strip() for t in rec["terms"].split(",") if t.strip()]
    declared_words = {w for t in declared for w in _WORDS(t)}
    return any(w in declared_words for w in wanted)


def assess(endpoint: str, facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One verdict per fact: MISSING (the building states it nowhere), HEDGED, or RECORDED.

    THERE IS NO LONGER A "PLACEHOLDER" STATE. It was defined by ``ontosage:isSimulated``, which no
    record carries any more: every record is the building's own, and where its data came from is
    stated once in the paper rather than on each row.

    HEDGED survives, and it is about WORDING, not origin. A record whose own text says a position
    is "modelled" or "assumed" has not been surveyed, and for a safety-critical fact -- where the
    defibrillator is, where to muster -- that is the difference between a fact somebody can act on
    and one they cannot. The remedy is to confirm the position and drop the hedge, not to flag it.
    """
    lay = by_lay_term(endpoint)
    results = []
    for fact in facts:
        h = held(endpoint, list(fact.get("classes") or []))
        total = sum(v["instances"] for v in h.values())

        # Records that hold this fact under some OTHER class, found by the words they declare.
        extra = [r for r in lay if _matches_terms(fact, r)]
        hedged = [r for r in extra if any(w in r["loc"].lower() for w in _HEDGES)]
        total += len(extra)
        if extra:
            h = dict(h)
            h["(by lay term)"] = {"instances": len(extra), "placeholders": len(hedged)}

        if total == 0:
            status = "MISSING"
        elif hedged:
            status = "HEDGED"
        else:
            status = "RECORDED"
        results.append({**fact, "held": h, "instances": total, "placeholders": len(hedged),
                        "status": status,
                        "hedged_examples": [f"{r['iri'].rsplit('#', 1)[-1]}: {r['loc']}"
                                            for r in hedged][:3]})
    return results


def render(results: List[Dict[str, Any]], endpoint: str) -> str:
    counts = {s: sum(1 for r in results if r["status"] == s)
              for s in ("MISSING", "HEDGED", "RECORDED")}
    lines = [
        "# Owner facts checklist",
        "",
        f"Generated {date.today().isoformat()} by `scripts/owner_facts_report.py` from `{endpoint}`.",
        "",
        "The system never invents a safety-critical fact: where one is not recorded it says so and names who "
        "to ask. Each line below is a question it currently has to decline.",
        "",
        f"**{counts['MISSING']} missing · {counts['HEDGED']} recorded but hedged · "
        f"{counts['RECORDED']} recorded**",
        "",
        "*HEDGED* means a record exists and the system WILL answer from it, but the record's own "
        "wording calls the fact modelled or assumed. For a safety-critical fact that is the "
        "difference between a position somebody can act on and one they cannot, so it is listed "
        "as owed: confirm it and drop the hedge.",
        "",
        "| fact | status | records | what the record must state |",
        "|---|---|---|---|",
    ]
    for r in results:
        held_txt = ", ".join(f"{k}: {v['instances']}" for k, v in r["held"].items()) or "none"
        lines.append(f"| {r['label']} | **{r['status']}** | {held_txt} | {r.get('must_state', '')} |")
    todo = [r for r in results if r["status"] != "RECORDED"]
    lines += ["", "## To supply", ""]
    if not todo:
        lines.append("Nothing outstanding.")
    for r in todo:
        lines.append(f"- **{r['label']}** — {r['status'].lower()}. {r.get('note', '')}")
        for ex in r.get("hedged_examples") or []:
            lines.append(f"  - the record itself says: *{ex}*")
    lines += [
        "",
        "Record each as an `ontosage:Amenity` (or the register row for it) at the place the "
        "building's own text states, and only that place.",
        "",
    ]
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--out", default=str(REPO / "docs" / "OWNER_FACTS_CHECKLIST.md"))
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    facts = (yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}).get("facts") or []
    try:
        results = assess(args.endpoint, facts)
    except requests.RequestException as exc:
        print(f"could not read the graph at {args.endpoint}: {exc}", file=sys.stderr)
        return 0
    text = render(results, args.endpoint)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(text)
    if not args.no_write:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
