# -*- coding: utf-8 -*-
"""One deduplicated question bank, split into a TUNING pool and a HOLDOUT that is never sampled.

Why this exists
---------------
One GPU gives ~30 s per answer, so ~10,000 questions cannot be run live. The work that CAN be done
offline (see ``scripts/reach_report.py``) needs one list of every question the project owns, with
stable ids, so that two tools looking at "the bank" are looking at the same thing. And any
measurement of the system on unseen questions needs a guarantee that nothing tuned against is in
the set it is measured on. This file provides both.

What is merged (nine sources, in ``SOURCE_ORDER``)
-------------------------------------------------
    catalogue   docs/smart_building_questions.csv, Source = stakeholder_catalogue_37 (37 roles x 80)
    synthetic   docs/smart_building_questions.csv, Source = v5_synthetic_bank
    survey      paper/Survey analysis and results/corpus/classified_corpus.csv
    phase0      docs/phase0/phase0_bank.jsonl (a hand-read subset of the three above)
    probe       scripts/regression_cases.json
    demo        docs/demo_script_questions.txt
    tail_a      docs/phase0/fresh_tail_2026-09-18.txt
    tail_b      docs/phase0/fresh_tail_B_2026-09-18.txt
    guardrail   docs/phase0/guardrail_phrasings_2026-09-18.txt

A question is identified by its NORMALISED text (lowercase, everything outside ``[a-z0-9 ]``
removed, whitespace collapsed). The same question in two sources is ONE bank entry that records
every source it appeared in; its ``primary`` source is the richest one (the order above), so the
per-stakeholder / per-domain metadata survives. ``asked_before`` marks a question that also sits
in a set the system has already been fixed against (phase0, probe, demo, the tails).

The HOLDOUT is defined ONLY by hash
-----------------------------------
``--holdout-hashes`` names a file of sha1 digests, one per line: the sha1 of the UTF-8 bytes of the
question normalised as ``re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()``. A bank question whose
digest is in that file is a holdout question: it is marked, kept out of every sample, and never
printed. This module NEVER opens a file whose name starts with ``tail_C`` as a question source
(``HeldOutPathError``), and the hash reader accepts nothing but 40-hex-digit lines, so a questions
file passed by mistake fails without echoing a line of it.

Three normal forms are hashed per bank question (the exact spec, that with whitespace collapsed,
and that with punctuation turned into spaces first), so a held-out question that differs from a
tuning question only by hyphen or spacing is still excluded. Excluding too much is harmless;
including one held-out question would void the measurement.

Usage
-----
    python scripts/master_bank.py --holdout-hashes H.txt --stats
    python scripts/master_bank.py --holdout-hashes H.txt --sample 200 --seed 7 --emit out.txt
    python scripts/master_bank.py --holdout-hashes H.txt --sample 200 --seed 7 \\
        --source catalogue,synthetic --fresh --emit out.txt

``--emit`` writes the format ``scripts/ask_questions.py --file`` reads (one question per line,
``#`` comments) plus ``out.txt.jsonl`` mapping each line back to its bank id, source and group.
Without a holdout file every command except ``--stats`` refuses to run (fail closed) unless
``--no-holdout`` is given.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

REPO = Path(__file__).resolve().parents[1]

CATALOGUE_SOURCE_NAME = "stakeholder_catalogue_37"
SYNTHETIC_SOURCE_NAME = "v5_synthetic_bank"

#: Richest metadata first. The primary source of a question that appears in several is the first
#: of these that contains it; the small hand-curated sets come last because they carry the least.
SOURCE_ORDER: Tuple[str, ...] = (
    "stakeholder_catalogue_37",
    "synthetic",
    "survey",
    "phase0",
    "probe",
    "demo",
    "tail_a",
    "tail_b",
    "guardrail",
)

#: Sets the system has already been fixed against. A question in any of them is ``asked_before``.
ASKED_BEFORE_SOURCES: frozenset = frozenset(
    {"phase0", "probe", "demo", "tail_a", "tail_b", "guardrail"}
)

HASH_FILE_ENV = "ONTOSAGE_HOLDOUT_HASHES"
#: Where a committed copy of the hashes would live. Looked at after the flag and the env var.
DEFAULT_HASH_FILE = REPO / "docs" / "phase0" / "tail_C_hashes.txt"

_SHA1_LINE = re.compile(r"^[0-9a-f]{40}$")


class HeldOutPathError(ValueError):
    """A question source whose file name marks it as held-out was requested."""


class HoldoutHashesMissing(RuntimeError):
    """No hash file was found, so a tuning pool cannot be proven free of held-out questions."""


# ── normalisation and hashing ───────────────────────────────────────────────────────────


def normalise(text: str) -> str:
    """The holdout spec: lowercase, drop every character outside ``[a-z0-9 ]``, strip."""
    return re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()


def dedup_key(text: str) -> str:
    """The identity of a question: the spec normal form with runs of spaces collapsed."""
    return re.sub(r" +", " ", normalise(text))


def sha1_hex(text: str) -> str:
    """sha1 of the UTF-8 bytes."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()  # nosec B324 - identity, not security


def holdout_digests(text: str) -> Set[str]:
    """Every digest under which a held-out twin of ``text`` could have been recorded."""
    lowered = (text or "").lower()
    spec = normalise(text)
    spaced = re.sub(r"[^a-z0-9 ]", " ", lowered)
    forms = {
        spec,
        re.sub(r" +", " ", spec),
        re.sub(r" +", " ", spaced).strip(),
    }
    return {sha1_hex(f) for f in forms if f}


def clean_text(text: str) -> str:
    """A question as one line: internal whitespace collapsed, ends stripped."""
    return " ".join((text or "").split())


def _refuse_held_out_source(path: Path) -> None:
    """Never let a held-out questions file be read as a source, whatever the caller asked for."""
    if Path(path).name.lower().startswith("tail_c"):
        raise HeldOutPathError(f"refusing to read {Path(path).name}: held-out files are off limits")


# ── the bank ────────────────────────────────────────────────────────────────────────────


@dataclass
class Appearance:
    """One occurrence of a question in one source."""

    source: str
    group: str
    origin: str
    tags: Dict[str, str] = field(default_factory=dict)
    evidence: Dict[str, str] = field(default_factory=dict)


@dataclass
class BankQuestion:
    """One question, once, with everywhere it was seen."""

    id: str
    text: str
    key: str
    primary: str
    group: str
    appearances: List[Appearance]
    holdout: bool = False

    @property
    def sources(self) -> List[str]:
        """Distinct sources this question appeared in, richest first."""
        return sorted({a.source for a in self.appearances}, key=_source_rank)

    @property
    def asked_before(self) -> bool:
        """True when the question is in a set the system was already fixed against."""
        return any(a.source in ASKED_BEFORE_SOURCES for a in self.appearances)

    @property
    def tags(self) -> Dict[str, str]:
        """Tags of the primary appearance."""
        return self.appearances[0].tags

    @property
    def evidence(self) -> Dict[str, str]:
        """Long declared-evidence text of the primary appearance (catalogue rows carry it)."""
        return self.appearances[0].evidence

    def to_dict(self, with_evidence: bool = False) -> Dict[str, object]:
        """A JSON-safe record; the long evidence text is left out unless asked for."""
        out: Dict[str, object] = {
            "id": self.id,
            "text": self.text,
            "primary": self.primary,
            "group": self.group,
            "sources": self.sources,
            "asked_before": self.asked_before,
            "holdout": self.holdout,
            "tags": self.tags,
        }
        if with_evidence:
            out["evidence"] = self.evidence
        return out


def _source_rank(name: str) -> int:
    return SOURCE_ORDER.index(name) if name in SOURCE_ORDER else len(SOURCE_ORDER)


@dataclass
class RawQuestion:
    """A question as a loader found it, before dedup."""

    text: str
    appearance: Appearance


# ── source loaders ──────────────────────────────────────────────────────────────────────

PATHS: Dict[str, Path] = {
    "docs_csv": REPO / "docs" / "smart_building_questions.csv",
    "survey": REPO / "paper" / "Survey analysis and results" / "corpus" / "classified_corpus.csv",
    "phase0": REPO / "docs" / "phase0" / "phase0_bank.jsonl",
    "probe": REPO / "scripts" / "regression_cases.json",
    "demo": REPO / "docs" / "demo_script_questions.txt",
    "tail_a": REPO / "docs" / "phase0" / "fresh_tail_2026-09-18.txt",
    "tail_b": REPO / "docs" / "phase0" / "fresh_tail_B_2026-09-18.txt",
    "guardrail": REPO / "docs" / "phase0" / "guardrail_phrasings_2026-09-18.txt",
}


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return str(path)


def _csv_rows(path: Path) -> Iterator[Tuple[int, Dict[str, str]]]:
    _refuse_held_out_source(path)
    csv.field_size_limit(10**7)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for number, row in enumerate(csv.DictReader(handle), start=2):
            yield number, row


def load_docs_csv(path: Path) -> List[RawQuestion]:
    """The catalogues and the synthetic bank, split by the file's own Source column."""
    out: List[RawQuestion] = []
    for number, row in _csv_rows(path):
        text = clean_text(row.get("Question", ""))
        if not text:
            continue
        origin = f"{_rel(path)}:{number}"
        source_col = row.get("Source", "")
        if source_col == CATALOGUE_SOURCE_NAME:
            appearance = Appearance(
                "stakeholder_catalogue_37",
                row.get("Stakeholder_Role") or "(no role)",
                origin,
                tags={
                    "orig_id": row.get("ID", ""),
                    "section": row.get("Section", ""),
                    "priority": row.get("Priority", ""),
                    "complexity_l": row.get("Complexity_L", ""),
                    "readiness_r": row.get("Readiness_R", ""),
                    "answer_type": row.get("Answer_Type", ""),
                    "required_data_sources": row.get("Required_Data_Sources", ""),
                },
                evidence={
                    "Authoritative_Sources": row.get("Authoritative_Sources", ""),
                    "Sensors_Required": row.get("Sensors_Required", ""),
                },
            )
        elif source_col == SYNTHETIC_SOURCE_NAME:
            appearance = Appearance(
                "synthetic",
                row.get("Category") or "(no category)",
                origin,
                tags={
                    "orig_id": row.get("ID", ""),
                    "register": row.get("Register", ""),
                    "role": row.get("Stakeholder_Role", ""),
                    "required_data_sources": row.get("Required_Data_Sources", ""),
                    "answer_type": row.get("Answer_Type", ""),
                },
                evidence={"Answer_Boundary": row.get("Answer_Boundary", "")},
            )
        else:
            # A source this module does not know is kept, under its own label, never dropped.
            appearance = Appearance(
                f"other:{source_col or 'unlabelled'}",
                row.get("Category") or row.get("Stakeholder_Role") or "(none)",
                origin,
                tags={"orig_id": row.get("ID", "")},
            )
        out.append(RawQuestion(text, appearance))
    return out


def load_survey(path: Path) -> List[RawQuestion]:
    """The survey corpus (about 7,000 rows, about 6,100 distinct questions)."""
    out: List[RawQuestion] = []
    for number, row in _csv_rows(path):
        text = clean_text(row.get("Question", ""))
        if not text:
            continue
        out.append(
            RawQuestion(
                text,
                Appearance(
                    "survey",
                    row.get("domain_l1") or "(none)",
                    f"{_rel(path)}:{number}",
                    tags={
                        "pid": row.get("PID", ""),
                        "personas": row.get("Personas", ""),
                        "stage": row.get("Stage", ""),
                        "query_type_l2": row.get("query_type_l2", ""),
                        "intent": row.get("intent", ""),
                        "temporal": row.get("temporal", ""),
                        "spatial": row.get("spatial", ""),
                        "complexity": row.get("complexity", ""),
                    },
                ),
            )
        )
    return out


def load_phase0(path: Path) -> List[RawQuestion]:
    """The 147-question hand-read bank."""
    _refuse_held_out_source(path)
    out: List[RawQuestion] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            text = clean_text(row.get("question", ""))
            if not text:
                continue
            out.append(
                RawQuestion(
                    text,
                    Appearance(
                        "phase0",
                        row.get("stakeholder") or row.get("category") or "(none)",
                        f"{_rel(path)}:{number}",
                        tags={
                            "orig_id": str(row.get("id", "")),
                            "origin_source": str(row.get("source", "")),
                            "category": str(row.get("category", "")),
                        },
                        evidence={"boundary": str(row.get("boundary", ""))},
                    ),
                )
            )
    return out


def load_probe(path: Path) -> List[RawQuestion]:
    """The regression probe: one case per question."""
    _refuse_held_out_source(path)
    out: List[RawQuestion] = []
    for number, case in enumerate(json.loads(path.read_text(encoding="utf-8")), start=1):
        text = clean_text(case.get("question", ""))
        if not text:
            continue
        out.append(
            RawQuestion(
                text,
                Appearance(
                    "probe",
                    case.get("group") or "(none)",
                    f"{_rel(path)}:case {number}",
                    tags={
                        "expect_intent": str(case.get("expect_intent") or ""),
                        "forbid_intent": str(case.get("forbid_intent") or ""),
                        "building": str(case.get("building") or ""),
                    },
                ),
            )
        )
    return out


_SECTION_RE = re.compile("^#\\s*[─-╿-]{2,}\\s*(.*?)\\s*[─-╿-]{2,}\\s*$")


def load_text_lines(path: Path, source: str, group: Optional[str] = None) -> List[RawQuestion]:
    """One question per line; ``#`` lines are comments, and a ``# ── Name ──`` line names a group."""
    _refuse_held_out_source(path)
    out: List[RawQuestion] = []
    current = group or "(ungrouped)"
    with path.open(encoding="utf-8") as handle:
        for number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                header = _SECTION_RE.match(line)
                if header and header.group(1) and group is None:
                    current = re.sub(r"\s*\(.*\)\s*$", "", header.group(1)).strip() or current
                continue
            out.append(
                RawQuestion(
                    clean_text(line),
                    Appearance(source, current, f"{_rel(path)}:{number}"),
                )
            )
    return out


def default_sources(paths: Optional[Dict[str, Path]] = None) -> List[RawQuestion]:
    """Every raw question from every default source, in file order."""
    p = paths or PATHS
    raw: List[RawQuestion] = []
    raw += load_docs_csv(p["docs_csv"])
    raw += load_survey(p["survey"])
    raw += load_phase0(p["phase0"])
    raw += load_probe(p["probe"])
    raw += load_text_lines(p["demo"], "demo")
    raw += load_text_lines(p["tail_a"], "tail_a", group="unscripted tail")
    raw += load_text_lines(p["tail_b"], "tail_b", group="unscripted tail")
    raw += load_text_lines(p["guardrail"], "guardrail", group="guardrail rewording")
    return raw


# ── the holdout file ────────────────────────────────────────────────────────────────────


def read_hash_file(path: Path) -> Set[str]:
    """The digests in a hash file. Any line that is not a sha1 digest is an error, unprinted."""
    hashes: Set[str] = set()
    with Path(path).open(encoding="utf-8") as handle:
        for number, raw in enumerate(handle, start=1):
            line = raw.strip().lower()
            if not line or line.startswith("#"):
                continue
            if not _SHA1_LINE.match(line):
                raise ValueError(f"{Path(path).name}: line {number} is not a sha1 digest")
            hashes.add(line)
    return hashes


def find_hash_file(explicit: Optional[str] = None) -> Optional[Path]:
    """The hash file to use: the flag, then $ONTOSAGE_HOLDOUT_HASHES, then the repo default."""
    candidates: List[Optional[str]] = [explicit, os.environ.get(HASH_FILE_ENV)]
    for candidate in candidates:
        if candidate:
            return Path(candidate)
    return DEFAULT_HASH_FILE if DEFAULT_HASH_FILE.is_file() else None


@dataclass
class Bank:
    """The merged bank plus what is known about the holdout."""

    questions: List[BankQuestion]
    raw_counts: Dict[str, int]
    hashes: Set[str]
    hash_file: Optional[str]
    empty_skipped: int = 0

    def tuning(self) -> List[BankQuestion]:
        """Every question that is not held out — the only pool anything may be drawn from."""
        return [q for q in self.questions if not q.holdout]

    def holdout(self) -> List[BankQuestion]:
        """Bank questions matched by a held-out digest (never printed by the CLI)."""
        return [q for q in self.questions if q.holdout]

    def by_id(self) -> Dict[str, BankQuestion]:
        """id to question."""
        return {q.id: q for q in self.questions}


def build_bank(
    raw: Sequence[RawQuestion],
    hashes: Optional[Iterable[str]] = None,
    hash_file: Optional[str] = None,
) -> Bank:
    """Deduplicate ``raw`` by normalised text, give stable ids, and mark the holdout by hash."""
    digests = set(hashes or ())
    by_key: Dict[str, List[Appearance]] = {}
    first_text: Dict[str, str] = {}
    counts: Counter = Counter()
    empty = 0
    for item in raw:
        counts[item.appearance.source] += 1
        key = dedup_key(item.text)
        if not key:
            empty += 1
            continue
        by_key.setdefault(key, []).append(item.appearance)
        first_text.setdefault(key, item.text)

    used: Set[str] = set()
    questions: List[BankQuestion] = []
    for key, appearances in by_key.items():
        appearances = sorted(appearances, key=lambda a: _source_rank(a.source))
        width = 12
        qid = "MB-" + sha1_hex(key)[:width]
        while qid in used:  # a truncated-hash collision: lengthen, deterministically
            width += 2
            qid = "MB-" + sha1_hex(key)[:width]
        used.add(qid)
        text = first_text[key]
        questions.append(
            BankQuestion(
                id=qid,
                text=text,
                key=key,
                primary=appearances[0].source,
                group=appearances[0].group,
                appearances=appearances,
                holdout=bool(digests) and bool(holdout_digests(text) & digests),
            )
        )
    questions.sort(key=lambda q: (_source_rank(q.primary), q.group, q.id))
    return Bank(questions, dict(counts), digests, hash_file, empty)


def load_bank(
    hash_file: Optional[str] = None,
    require_holdout: bool = True,
    paths: Optional[Dict[str, Path]] = None,
    extra: Optional[Sequence[Tuple[str, Path]]] = None,
) -> Bank:
    """Load every default source (plus ``extra`` NAME=PATH text files) and mark the holdout.

    ``require_holdout`` makes a missing hash file an error rather than an empty holdout: without
    the file nothing proves the tuning pool is free of held-out questions.
    """
    found = find_hash_file(hash_file)
    hashes: Set[str] = set()
    if found is not None and found.is_file():
        hashes = read_hash_file(found)
    elif require_holdout:
        raise HoldoutHashesMissing(
            "no holdout hash file: pass --holdout-hashes PATH (or set "
            f"{HASH_FILE_ENV}); use --no-holdout only to look, never to sample"
        )
    raw = default_sources(paths)
    for name, path in extra or ():
        raw += load_text_lines(Path(path), name)
    return build_bank(raw, hashes, str(found) if found else None)


# ── the sampler ─────────────────────────────────────────────────────────────────────────

Stratum = Tuple[str, str]


def allocate(sizes: Dict[Stratum, int], n: int, mode: str = "proportional") -> Dict[Stratum, int]:
    """How many questions to draw from each stratum. Sums to ``min(n, total)``, never above a size.

    ``proportional``: shares follow stratum size by largest remainder, and once ``n`` is at least
    the number of strata every stratum keeps one. ``equal``: as even as the sizes allow.
    """
    total = sum(sizes.values())
    keys = sorted(sizes)
    if n <= 0 or not keys:
        return {k: 0 for k in keys}
    if n >= total:
        return dict(sizes)
    if mode == "equal":
        return _allocate_equal(sizes, keys, n)
    raw = {k: n * sizes[k] / total for k in keys}
    alloc = {k: int(raw[k]) for k in keys}
    if n >= len(keys):
        alloc = {k: max(1, alloc[k]) for k in keys}
    left = n - sum(alloc.values())
    if left > 0:
        order = sorted(keys, key=lambda k: (-(raw[k] - int(raw[k])), k))
        while left > 0:
            moved = False
            for k in order:
                if left > 0 and alloc[k] < sizes[k]:
                    alloc[k] += 1
                    left -= 1
                    moved = True
            if not moved:
                break
    while left < 0:  # the one-per-stratum floor overshot: take from the largest shares
        order = sorted(keys, key=lambda k: (-alloc[k], k))
        for k in order:
            if left < 0 and alloc[k] > (1 if n >= len(keys) else 0):
                alloc[k] -= 1
                left += 1
    return alloc


def _allocate_equal(sizes: Dict[Stratum, int], keys: List[Stratum], n: int) -> Dict[Stratum, int]:
    alloc = {k: 0 for k in keys}
    open_keys = list(keys)
    remaining = n
    while remaining > 0 and open_keys:
        share, extra = divmod(remaining, len(open_keys))
        progressed = 0
        for index, k in enumerate(list(open_keys)):
            want = share + (1 if index < extra else 0)
            give = min(want, sizes[k] - alloc[k])
            alloc[k] += give
            progressed += give
            if alloc[k] >= sizes[k]:
                open_keys.remove(k)
        remaining -= progressed
        if progressed == 0:
            break
    return alloc


def sample(
    bank: Bank,
    n: int,
    seed: int,
    sources: Optional[Sequence[str]] = None,
    fresh_only: bool = False,
    allocation: str = "proportional",
) -> List[BankQuestion]:
    """A seeded sample stratified by (primary source, group). Never returns a holdout question.

    The pool is ``bank.tuning()``: a held-out question is not filtered out at the end, it is never
    in the candidate list. ``sources`` keeps questions that appear in ANY of the named sources;
    ``fresh_only`` also drops anything already asked (phase0, probe, demo, the tails).
    """
    wanted = set(sources or ())
    pool = [
        q
        for q in bank.tuning()
        if (not wanted or wanted & set(q.sources)) and not (fresh_only and q.asked_before)
    ]
    strata: Dict[Stratum, List[BankQuestion]] = defaultdict(list)
    for q in pool:
        strata[(q.primary, q.group)].append(q)
    quota = allocate({k: len(v) for k, v in strata.items()}, n, allocation)
    chosen: List[BankQuestion] = []
    for key in sorted(strata):
        members = sorted(strata[key], key=lambda q: q.id)
        rng = random.Random(f"{seed}|{key[0]}|{key[1]}")
        chosen.extend(rng.sample(members, quota[key]))
    random.Random(f"{seed}|order").shuffle(chosen)  # interleave strata so any prefix is mixed
    return chosen


# ── reporting ───────────────────────────────────────────────────────────────────────────


def stats(bank: Bank) -> Dict[str, object]:
    """Counts a person needs before trusting the bank; holdout questions appear only as a count."""
    unique_by_primary = Counter(q.primary for q in bank.questions)
    tuning_by_primary = Counter(q.primary for q in bank.tuning())
    overlaps: Counter = Counter()
    for q in bank.questions:
        sources = q.sources
        if len(sources) > 1:
            overlaps["+".join(sources)] += 1
    groups: Dict[str, Dict[str, int]] = defaultdict(dict)
    for q in bank.tuning():
        groups[q.primary][q.group] = groups[q.primary].get(q.group, 0) + 1
    matched = len(bank.holdout())
    return {
        "hash_file": bank.hash_file,
        "holdout_hashes": len(bank.hashes),
        "holdout_matched_in_bank": matched,
        "holdout_hashes_not_in_bank": len(bank.hashes) - _matched_hashes(bank),
        "raw_rows_by_source": {s: bank.raw_counts.get(s, 0) for s in _ordered(bank.raw_counts)},
        "empty_rows_skipped": bank.empty_skipped,
        "unique_questions": len(bank.questions),
        "tuning_pool": len(bank.tuning()),
        "tuning_asked_before": sum(1 for q in bank.tuning() if q.asked_before),
        "tuning_fresh": sum(1 for q in bank.tuning() if not q.asked_before),
        "unique_by_primary_source": {s: unique_by_primary[s] for s in _ordered(unique_by_primary)},
        "tuning_by_primary_source": {s: tuning_by_primary[s] for s in _ordered(tuning_by_primary)},
        "source_overlaps": dict(overlaps.most_common()),
        "groups_by_primary_source": {
            s: dict(sorted(g.items(), key=lambda kv: (-kv[1], kv[0])))
            for s, g in sorted(groups.items(), key=lambda kv: _source_rank(kv[0]))
        },
    }


def _matched_hashes(bank: Bank) -> int:
    """How many distinct digests some bank question matched."""
    hit: Set[str] = set()
    for q in bank.holdout():
        hit |= holdout_digests(q.text) & bank.hashes
    return len(hit)


def _ordered(names: Iterable[str]) -> List[str]:
    return sorted(names, key=lambda s: (_source_rank(s), s))


def print_stats(info: Dict[str, object]) -> None:
    """Human-readable form of :func:`stats`."""
    print(f"holdout hash file      : {info['hash_file'] or '(none - pool NOT protected)'}")
    print(f"holdout hashes         : {info['holdout_hashes']}")
    print(f"  matched a bank text  : {info['holdout_matched_in_bank']} bank question(s), excluded")
    print(
        f"  matched no bank text : {info['holdout_hashes_not_in_bank']} (expected: not in these files)"
    )
    print(f"unique questions       : {info['unique_questions']}")
    print(f"tuning pool            : {info['tuning_pool']}")
    print(f"  asked before         : {info['tuning_asked_before']}")
    print(f"  fresh                : {info['tuning_fresh']}")
    print("\nraw rows by source     :", info["raw_rows_by_source"])
    print("primary source (unique):", info["unique_by_primary_source"])
    print("primary source (tuning):", info["tuning_by_primary_source"])
    print("\nsources sharing a question:")
    for combo, count in (info["source_overlaps"] or {}).items():  # type: ignore[union-attr]
        print(f"  {count:6d}  {combo}")
    print("\ngroups per primary source:")
    for source, groups in info["groups_by_primary_source"].items():  # type: ignore[union-attr]
        print(
            f"  {source}: {len(groups)} groups, largest {max(groups.values())}, smallest "
            f"{min(groups.values())}"
        )


def emit(questions: Sequence[BankQuestion], path: Path, header: str) -> None:
    """Write ``path`` (one question per line, ask_questions.py format) and ``path.jsonl``."""
    lines = [f"# {line}" for line in header.splitlines()]
    for q in questions:
        text = q.text.lstrip("#").strip()  # a leading # would read as a comment
        lines.append(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sidecar = Path(str(path) + ".jsonl")
    with sidecar.open("w", encoding="utf-8", newline="\n") as handle:
        for index, q in enumerate(questions, start=1):
            handle.write(
                json.dumps(
                    {
                        "n": index,
                        "id": q.id,
                        "primary": q.primary,
                        "group": q.group,
                        "asked_before": q.asked_before,
                        "text": q.text,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def main(argv: Optional[List[str]] = None) -> int:
    """CLI."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--holdout-hashes", help="file of sha1 digests of held-out questions")
    ap.add_argument(
        "--no-holdout", action="store_true", help="run without a hash file (never sample)"
    )
    ap.add_argument("--stats", action="store_true", help="counts, overlaps, holdout numbers")
    ap.add_argument("--sample", type=int, default=0, metavar="N", help="draw N tuning questions")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--source", default="", help=f"comma list from {', '.join(SOURCE_ORDER)}")
    ap.add_argument("--fresh", action="store_true", help="drop questions asked before")
    ap.add_argument("--allocation", choices=("proportional", "equal"), default="proportional")
    ap.add_argument("--emit", metavar="PATH", help="write the sample, one question per line")
    ap.add_argument("--dump", metavar="PATH", help="write the whole TUNING pool as JSON lines")
    ap.add_argument(
        "--extra",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="add a text file of questions as source NAME (never a tail_C file)",
    )
    args = ap.parse_args(argv)

    extra: List[Tuple[str, Path]] = []
    for spec in args.extra:
        name, _, path = spec.partition("=")
        extra.append((name.strip(), Path(path)))
    sampling = bool(args.sample or args.emit or args.dump)
    try:
        bank = load_bank(
            args.holdout_hashes,
            require_holdout=sampling and not args.no_holdout,
            extra=extra,
        )
    except (HoldoutHashesMissing, HeldOutPathError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.no_holdout and sampling:
        print("error: --no-holdout cannot be combined with sampling or dumping", file=sys.stderr)
        return 2
    if args.stats or not sampling:
        print_stats(stats(bank))
    if args.dump:
        with Path(args.dump).open("w", encoding="utf-8", newline="\n") as handle:
            for q in bank.tuning():
                handle.write(json.dumps(q.to_dict(), ensure_ascii=False) + "\n")
        print(f"\nwrote {len(bank.tuning())} tuning questions to {args.dump}")
    if args.sample:
        sources = [s.strip() for s in args.source.split(",") if s.strip()]
        drawn = sample(bank, args.sample, args.seed, sources, args.fresh, args.allocation)
        header = (
            f"master_bank sample: n={len(drawn)} seed={args.seed} allocation={args.allocation} "
            f"source={','.join(sources) or 'all'} fresh_only={args.fresh}\n"
            f"drawn from a tuning pool of {len(bank.tuning())}; "
            f"{len(bank.hashes)} held-out digests excluded"
        )
        by_source = Counter(q.primary for q in drawn)
        print(f"\nsampled {len(drawn)} questions: {dict(by_source)}")
        if args.emit:
            emit(drawn, Path(args.emit), header)
            print(f"wrote {args.emit} and {args.emit}.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
