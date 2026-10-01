# -*- coding: utf-8 -*-
"""Do the decline classifiers recognise the declines this system actually emits?

WHY THIS EXISTS
---------------
Three modules in this repository decide, from prose alone, whether a reply is a decline:

* ``orchestrator/services/publication_gate.is_decline`` -- the shared classifier, read by
  the publication gate and by anything reasoning about whether an answer has a claim to
  withhold;
* ``scripts/grade_answers_rubric.is_decline`` -- the grader's, which decides the
  GOOD_DECLINE bucket;
* ``scripts/regression_answerability.classify`` -- the evidence-pack gate's, which decides
  whether a question that used to answer still answers.

All three are **marker lists**, and CAVEAT-887 records what that costs: one question
produced THREE honest decline wordings in a single day, each needing its own marker, each
found only when the gate reported a false regression. CAVEAT-952 records the consequence
one step further on -- ``publication_gate.is_decline`` returns False for the commonest
decline the system emits, ``"I couldn't answer that from <building>'s records."``

The wording of a decline is generated, so a hand-written list will keep losing. But the
LEADS are not generated: they are string literals in the modules that emit them. So this
script does not restate them. It **derives** the candidate lead set from the source by
parsing it, and reports which leads each classifier fails to recognise.

WHAT IT DOES NOT DO
-------------------
It does not decide that a derived literal IS a decline. The derivation rule is a first-
person inability construction at the start of the string, which is a syntactic test; a
refusal ("I can't answer that -- this building never tracks individuals") matches it too
and is deliberately a different kind. The script reports the set; a human decides which
entries belong in a marker list, and then ``--verify`` proves the addition moves none of
the 73 stored pack answers. That order is the standing rule (lessons #141): an
intermediate broader pattern moved two of them and was rejected for it.

OFFLINE. Parses source and reads the committed evidence pack. No network, no live system.
Building-agnostic: no building name appears, and every placeholder in a derived template
is filled from ``--building``, default a placeholder that is not any real building.

USAGE
    python scripts/audit_decline_markers.py                    # derive and report
    python scripts/audit_decline_markers.py --emitters-only    # just the derived leads
    python scripts/audit_decline_markers.py --verify           # the 73-answer guard
    python scripts/audit_decline_markers.py --strict           # exit 1 on any miss
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: A first-person statement of inability, at the START of the string. Leading markdown
#: emphasis, a quotation mark or an emoji is skipped, because the emitting code writes
#: "**I can't answer that.**" as often as the bare sentence.
#:
#: This is a SYNTACTIC rule and is meant to over-capture rather than under-capture: a
#: refusal and a transient read failure both match it, and both are legitimately NOT the
#: same kind as an honest absence. The script reports; it does not classify.
LEAD_RULE = re.compile(
    r"^[\W\d_]{0,6}I\s*[’']?\s*"
    r"(?:m\s+sorry"
    r"|can\s*[’']?\s*t"
    r"|cannot"
    r"|could\s*n\s*[’']?\s*o?t"
    r"|do\s*n\s*[’']?\s*o?t\s+have"
    r"|do\s+not\s+have"
    r"|have\s+no\b"
    r"|found\s+no\b"
    r"|did\s*n\s*[’']?\s*o?t\s+find"
    r"|did\s+not\s+find"
    r"|was\s+not\s+able"
    r"|am\s+not\s+able"
    r"|won\s*[’']?\s*t\s+(?:guess|tell)"
    r")",
    re.I,
)

#: Where the placeholder in a derived template is filled from. A real building name would
#: make this file building-specific, which design contract #3 forbids, and a name that
#: looks real would make a reader think the literal contained it.
PLACEHOLDER = "{}"
DEFAULT_FILL = "<name>"

#: Directories under ``orchestrator/`` whose string literals are answer text. Everything
#: else is skipped so a docstring or a log message cannot enter the derived set.
EMITTER_ROOTS: Tuple[str, ...] = ("orchestrator",)
SKIP_PARTS: Tuple[str, ...] = ("__pycache__", "tests")


@dataclass(frozen=True)
class Lead:
    """One decline lead, as the source writes it."""

    module: str
    lineno: int
    template: str

    @property
    def probe(self) -> str:
        """The template with its placeholders filled, ready to hand a classifier."""
        return self.template.replace(PLACEHOLDER, DEFAULT_FILL)

    @property
    def variants(self) -> List[Tuple[str, str]]:
        """Every surface form this one template can produce, as (label, text).

        An interpolation is not always filled. ``clarification.py`` writes
        ``f"I couldn't answer that{about} from {name}'s records."`` where ``about`` is
        either empty or ``" about **Room 2.01**"``, so ONE literal emits two sentences and
        a marker list can match one and miss the other. That is BUG-876's exact shape -- a
        referent inserted into the middle of a fixed marker -- so both forms are probed and
        a disagreement between them is reported rather than averaged away.
        """
        if PLACEHOLDER not in self.template:
            return [("literal", self.template)]
        return [
            ("empty fill", self.template.replace(PLACEHOLDER, "")),
            ("named fill", self.template.replace(PLACEHOLDER, DEFAULT_FILL)),
        ]

    @property
    def key(self) -> str:
        return self.template.strip().lower()


# ─────────────────────────────────────────────────────────────────────────────────────────
# derivation
# ─────────────────────────────────────────────────────────────────────────────────────────


def _render(node: ast.AST) -> Optional[str]:
    """A string constant, or an f-string with each interpolation as ``{}``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: List[str] = []
        for piece in node.values:
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                parts.append(piece.value)
            else:
                parts.append(PLACEHOLDER)
        return "".join(parts)
    return None


def _string_nodes(tree: ast.AST) -> Iterable[ast.AST]:
    """Every string-valued node, WITHOUT the constants inside an f-string.

    Walking naively yields both ``f"I couldn't answer that from {x}'s records."`` and its
    fragment ``"I couldn't answer that from "``, and the fragment is not a lead -- it is
    half of one. Counting both inflates the derived set and produces a probe string that
    the emitting code never writes.
    """
    inner: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for piece in node.values:
                inner.add(id(piece))
    for node in ast.walk(tree):
        if id(node) in inner:
            continue
        if isinstance(node, (ast.Constant, ast.JoinedStr)):
            yield node


def derive_leads(repo: Path, roots: Sequence[str] = EMITTER_ROOTS) -> List[Lead]:
    """Parse the emitting source and return every first-person-inability lead in it."""
    leads: List[Lead] = []
    seen: set = set()
    for root in roots:
        base = repo / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if any(part in SKIP_PARTS for part in path.parts):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            docstrings = {
                id(n.body[0].value)
                for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and n.body
                and isinstance(n.body[0], ast.Expr)
                and isinstance(n.body[0].value, ast.Constant)
                and isinstance(n.body[0].value.value, str)
            }
            for node in _string_nodes(tree):
                if id(node) in docstrings:
                    continue
                text = _render(node)
                if not text:
                    continue
                text = text.strip()
                # A lead is a sentence opening, not a paragraph. A literal long enough to
                # be a whole explanation is still a lead if it STARTS like one, so only
                # the opening is kept for the probe.
                if not LEAD_RULE.match(text):
                    continue
                lead = Lead(
                    module=path.relative_to(repo).as_posix(),
                    lineno=getattr(node, "lineno", 0),
                    template=text,
                )
                if lead.key in seen:
                    continue
                seen.add(lead.key)
                leads.append(lead)
    return leads


def first_sentence(text: str, limit: int = 160) -> str:
    """The lead's own first sentence -- what a classifier sees before anything else."""
    flat = " ".join(text.split())
    cut = re.split(r"(?<=[.!?])\s", flat, maxsplit=1)[0]
    return cut[:limit]


# ─────────────────────────────────────────────────────────────────────────────────────────
# the classifiers under test
# ─────────────────────────────────────────────────────────────────────────────────────────


def classifiers() -> Dict[str, Callable[[str], bool]]:
    """Every decline classifier in the repo, each as text -> is-a-decline."""
    out: Dict[str, Callable[[str], bool]] = {}
    try:
        from orchestrator.services.publication_gate import is_decline as pg

        out["publication_gate.is_decline"] = pg
    except Exception as exc:  # pragma: no cover - import guard
        print(f"[warn] publication_gate not importable: {exc}", file=sys.stderr)
    try:
        from scripts.grade_answers_rubric import is_decline as gr

        out["grade_answers_rubric.is_decline"] = gr
    except Exception as exc:  # pragma: no cover
        print(f"[warn] grade_answers_rubric not importable: {exc}", file=sys.stderr)
    try:
        from scripts.regression_answerability import classify

        out["regression_answerability.classify"] = lambda text: classify(text) in (
            "declined",
            "refused",
        )
    except Exception as exc:  # pragma: no cover
        print(f"[warn] regression_answerability not importable: {exc}", file=sys.stderr)
    return out


# ─────────────────────────────────────────────────────────────────────────────────────────
# the 73-answer guard
# ─────────────────────────────────────────────────────────────────────────────────────────


def pack_distribution(pack: Path) -> Optional[Dict[str, Dict[str, int]]]:
    """How each classifier splits the stored pack answers.

    CLAUDE.md's rule: every change to a marker list is verified against all 73 stored
    answers, because an intermediate broader pattern moved two of them and was rejected
    for it. This is that verification, run for all three classifiers at once so a change
    to one cannot be checked against the wrong baseline.
    """
    answers = pack / "answers.jsonl"
    if not answers.is_file():
        return None
    rows = [
        json.loads(line)
        for line in answers.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    out: Dict[str, Dict[str, int]] = {}
    for name, fn in classifiers().items():
        decl = sum(1 for r in rows if fn(r.get("answer") or ""))
        out[name] = {"n": len(rows), "decline": decl, "not_decline": len(rows) - decl}
    try:
        from scripts.regression_answerability import classify

        kinds: Dict[str, int] = {}
        for r in rows:
            k = classify(r.get("answer") or "")
            kinds[k] = kinds.get(k, 0) + 1
        out["regression_answerability.classify (3-way)"] = dict(
            sorted(kinds.items())
        )  # type: ignore[assignment]
    except Exception:  # pragma: no cover
        pass
    return out


# ─────────────────────────────────────────────────────────────────────────────────────────
# report
# ─────────────────────────────────────────────────────────────────────────────────────────


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument(
        "--root",
        action="append",
        default=None,
        help="source tree to derive leads from (default: orchestrator)",
    )
    ap.add_argument(
        "--pack",
        default=str(REPO / "docs" / "supervisor_evidence_pack"),
        help="the stored evidence pack, for the 73-answer guard",
    )
    ap.add_argument(
        "--focus",
        action="append",
        default=None,
        metavar="SUBSTRING",
        help="restrict the derived set to modules whose path contains this; repeatable. "
        "CAVEAT-952 names clarification.py and capability_agent.py, so "
        "--focus clarification.py --focus capability_agent.py --focus fallback_wording.py "
        "is the row's own scope.",
    )
    ap.add_argument("--emitters-only", action="store_true", help="print the derived leads")
    ap.add_argument("--verify", action="store_true", help="print the pack distribution only")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when a classifier misses a lead its own source emits",
    )
    ap.add_argument("--out", help="also write the report here")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover
        pass

    repo = Path(args.repo)
    leads = derive_leads(repo, args.root or EMITTER_ROOTS)
    if args.focus:
        leads = [lead for lead in leads if any(f in lead.module for f in args.focus)]
        if not leads:
            print(f"no leads in modules matching {args.focus}", file=sys.stderr)
            return 2
    lines: List[str] = []

    def w(line: str = "") -> None:
        lines.append(line)

    if args.emitters_only:
        w(f"# {len(leads)} decline leads derived from " f"{', '.join(args.root or EMITTER_ROOTS)}")
        w("")
        by_mod: Dict[str, List[Lead]] = {}
        for lead in leads:
            by_mod.setdefault(lead.module, []).append(lead)
        for mod in sorted(by_mod):
            w(f"## {mod} ({len(by_mod[mod])})")
            for lead in by_mod[mod]:
                w(f"  {lead.lineno:>6}  {first_sentence(lead.template)}")
            w("")
        report = "\n".join(lines)
        print(report)
        if args.out:
            Path(args.out).write_text(report + "\n", encoding="utf-8")
        return 0

    dist = pack_distribution(Path(args.pack))

    if args.verify:
        w("# The 73-answer guard")
        w("")
        if dist is None:
            w(f"pack not present at {args.pack}")
        else:
            for name, counts in dist.items():
                w(f"- `{name}`: {counts}")
        report = "\n".join(lines)
        print(report)
        if args.out:
            Path(args.out).write_text(report + "\n", encoding="utf-8")
        return 0

    cls = classifiers()
    w("# Do the decline classifiers know the wording this system emits?")
    w("")
    w(
        f"Derived from `{'`, `'.join(args.root or EMITTER_ROOTS)}` by parsing the source: "
        f"**{len(leads)} distinct first-person-inability leads** in "
        f"{len({lead.module for lead in leads})} modules."
    )
    w("")
    w("The derivation rule is syntactic and deliberately over-captures: a refusal and a")
    w("transient read failure both match it and are legitimately a different KIND from an")
    w("honest absence. What matters below is the SIZE of the gap, and which leads sit in it.")
    w("")

    misses: Dict[str, List[Tuple[Lead, List[str]]]] = {name: [] for name in cls}
    split: Dict[str, List[Lead]] = {name: [] for name in cls}
    for lead in leads:
        for name, fn in cls.items():
            failed: List[str] = []
            for label, text in lead.variants:
                try:
                    ok = bool(fn(text))
                except Exception:  # pragma: no cover - a classifier that throws is a miss
                    ok = False
                if not ok:
                    failed.append(label)
            if failed:
                misses[name].append((lead, failed))
                if len(failed) < len(lead.variants):
                    split[name].append(lead)

    w(
        "| classifier | leads recognised in every form | leads missed | "
        "recall over the derived set | missed in only SOME forms |"
    )
    w("|---|---:|---:|---:|---:|")
    for name in cls:
        miss = len(misses[name])
        hit = len(leads) - miss
        w(f"| `{name}` | {hit} | {miss} | {hit/len(leads)*100:.1f}% | {len(split[name])} |")
    w("")
    w("`missed in only SOME forms` is the BUG-876 shape: one literal, two surface forms,")
    w("a marker that spans one of them. A non-zero column there is a defect even when the")
    w("recall column looks acceptable.")
    w("")

    for name in cls:
        if not misses[name]:
            continue
        w(f"## `{name}` -- {len(misses[name])} missed lead(s)")
        w("")
        for lead, failed in misses[name]:
            forms = "" if len(failed) == len(lead.variants) else f" [only: {', '.join(failed)}]"
            w(f"- `{lead.module}:{lead.lineno}`{forms} -- {first_sentence(lead.template)}")
        w("")

    w("## The 73-answer guard (lessons #141)")
    w("")
    if dist is None:
        w(f"Pack not present at `{args.pack}`, so no change to a marker list can be")
        w("verified. That is a blocking condition, not a skip.")
    else:
        w("Any change to a marker list must leave these unchanged unless the move is the")
        w("point of the change and is recorded as such.")
        w("")
        for name, counts in dist.items():
            w(f"- `{name}`: {counts}")
    w("")

    report = "\n".join(lines)
    print(report)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report + "\n", encoding="utf-8")
        print(f"\nwrote {out}", file=sys.stderr)

    if args.strict and any(misses.values()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
