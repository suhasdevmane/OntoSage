#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the frozen, pre-registered compound-question evaluation sets (tasks/V2_COMPOUND_PLAN.md §5).

WHAT IT PRODUCES (all under eval/compound/)
-------------------------------------------
* ``SPENT_210.jsonl``   - the 210 catalogue questions already asked during development on
  2026-10-07, reproduced from the draw that produced them (seed 20261007), so the exclusion is
  auditable.
* ``T-REAL.jsonl``      - the PRIMARY held-out test: real survey questions (classified_corpus.csv,
  complexity MULTI_STEP or AGGREGATION) never asked or shown during development, filtered by
  CODEBOOK.md for genuine compoundness (shapes C1-C6), at most 2 per participant, stratified
  across shapes as far as the pool allows, each labelled FULL / PARTIAL / NONE for bldg1.
* ``T-REAL-SUPPLEMENT.jsonl`` - the same, from LOOKUP rows, filed SEPARATELY because the specified
  pool yields far fewer than 80 (MANIFEST.json says why and what the owner must decide).
* ``T-CAT.jsonl``       - the SECONDARY held-out test: catalogue items never shown to
  development, at most 2 per persona, same labels.
* ``DEV.jsonl``         - every other extracted catalogue question: the ONLY set the v2 developer
  may use.
* ``HELDOUT_HASHES.txt`` - sha256 per held-out question (normalised), for tools that must skip them.
* ``MANIFEST.json``     - sha256 of every file, counts, seeds and the freeze statement.

INPUTS FROZEN AT FREEZE TIME
----------------------------
* ``EXCLUSION_SNAPSHOT.json`` - every reason a question is spent (asked, logged, printed, quoted,
  present in a development artefact, or a near-duplicate of one). Sources that keep changing
  after the freeze (answer files, logs, transcripts, scratchpads) are read ONLY by ``--rescan``,
  so a v1/v2 capture written into scripts/outputs later cannot change the sets.
* ``LABELS.json`` - the codebook judgements, keyed by a hash of the question, never by its text.
  SEALED with the test files: it shows each held-out item's shape and facets.

DETERMINISM
-----------
Every ordering is a sha256 of (fixed seed string + item key) or Python's ``random`` with a fixed
integer seed. A plain run rebuilds every output in memory and reports any byte that differs.

    python eval/compound/build_sets.py                 # verify the frozen outputs
    python eval/compound/build_sets.py --write         # (re)write them
    python eval/compound/build_sets.py --rescan        # freeze time only: rebuild the snapshot

THIS FILE CONTAINS NO TEST-QUESTION TEXT AND NO ITEM-LEVEL LABEL, and neither does CODEBOOK.md.
Do not print the contents of the sealed files anywhere a developer can read them.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

CORPUS_CSV = REPO / "paper" / "Survey analysis and results" / "corpus" / "classified_corpus.csv"
CATALOGUE_DIR = REPO / "QuestionBank" / "Talking_Abacws_37_Stakeholder_Catalogues"
MASTER_REPORT = "Talking_Abacws_Master_Technical_Report.pdf"
BANK_CSV = REPO / "tasks" / "smart_building_questions.csv"
PLAN_MD = REPO / "tasks" / "V2_COMPOUND_PLAN.md"
SNAPSHOT_PATH = HERE / "EXCLUSION_SNAPSHOT.json"
LABELS_PATH = HERE / "LABELS.json"
CODEBOOK_PATH = HERE / "CODEBOOK.md"

FREEZE_DATE = "2026-10-07"

# --- the draw that produced the 210 spent catalogue questions (given, reproduced exactly) ----
SEED_SPENT_210 = 20261007
SPENT_PER_PERSONA = 6

# --- what the parent session printed to its own terminal while planning ----------------------
# scratchpad/unseen_compound.py: random.seed(1); random.sample(<unseen MULTI_STEP rows>, 20).
# Those 20 questions were shown to the developer, so they are spent. Reproduced exactly.
PARENT_PEEK_SEED = 1
PARENT_PEEK_N = 20

# --- this builder's own seeds -----------------------------------------------------------------
ORDER_SEED_REAL = "compound-eval/T-REAL/2026-10-07"
ORDER_SEED_CAT = "compound-eval/T-CAT/2026-10-07"
TARGET_REAL = 80
TARGET_CAT = 60
MAX_PER_PID = 2
MAX_PER_PERSONA = 2

# --- matching parameters ------------------------------------------------------------------------
NEAR_DUP_JACCARD = 0.8  # token-set Jaccard at or above which two questions are one question
BULK_THRESHOLD = 500  # a unit holding >= this many distinct source questions is a bulk copy
MIN_MATCH_TOKENS = 5  # shorter questions are never matched by containment (too generic)
PREFIX_TOKENS = 12  # a displayed question may be truncated: its first 12 tokens are enough ...
PREFIX_MIN_LEN = 14  # ... but only for questions of at least 14 tokens

RX1 = re.compile(r"\bquestion:\s*(.+?\?)", re.IGNORECASE)
RX2 = re.compile(r"\bQUESTION\s+([A-Z][^?]{10,280}\?)")
LEAD = re.compile(
    r"^(?:CATEGORY\s+\d+\s+)?(?:[A-Z]{2,4}-\d{3}\s+)?(?:[A-Z][A-Z \-/']{6,60}\s+)?"
)

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")

# ------------------------------------------------------------------------------------------------
# Exposure-scan scope (used only by --rescan). Everything a developer of this system reads or
# writes while changing it: the repository, every Claude Code session scratchpad and background
# task output for this project, the session transcripts and persisted tool results, the user's
# project memory, and the two live stores whose text is not compressed on disk.
# ------------------------------------------------------------------------------------------------
TEMP_PROJECT_DIR = Path(
    r"C:\Users\suhas\AppData\Local\Temp\claude\c--Users-suhas-Documents-GitHub-OntoSage"
)
CLAUDE_PROJECT_DIR = Path(r"C:\Users\suhas\.claude\projects\c--Users-suhas-Documents-GitHub-OntoSage")
# This builder's own working folder and its own transcript are excluded: they hold the pool it
# had to read in order to label it, and scanning them would exclude every candidate.
BUILDER_WORK_DIRNAME = "cmp_eval_builder"
BUILDER_TRANSCRIPT_MARKER = "CMPEVAL-NONCE-Q7X2K9"

TEXT_EXTS = {
    ".py", ".md", ".txt", ".json", ".jsonl", ".csv", ".tsv", ".yaml", ".yml", ".ttl", ".log",
    ".tex", ".html", ".htm", ".js", ".jsx", ".ts", ".tsx", ".sql", ".ini", ".cfg", ".toml",
    ".rst", ".xml", ".out", ".err", ".ps1", ".sh", ".bib", ".ipynb", ".sparql", ".rq", ".n3",
    ".nt", ".output", ".bak", ".fixed", ".before", ".after",
}
SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
                  ".pytest_cache", ".ruff_cache", "site-packages"}
# Relative to REPO. volumes/ is scanned separately (only its uncompressed text stores);
# outputs/data holds 2.9 GB of numeric reading dumps (checked: no question/query/prompt key).
SKIP_REPO_RELDIRS = {"volumes", "eval/compound", "outputs/data", "dxf_originals"}
MAX_FILE_BYTES = 60 * 1024 * 1024


# ================================================================================================
# Normalisation
# ================================================================================================
def norm_ws(text: str) -> str:
    """Lowercase + collapsed whitespace: the rule the plan states for 'already asked'."""
    return _WS.sub(" ", (text or "").strip().lower())


def norm_p(text: str) -> str:
    """Lowercase, punctuation stripped, whitespace collapsed (draw_tail.py's rule)."""
    return " ".join(_PUNCT.sub(" ", (text or "").lower()).split())


def toks(text: str) -> List[str]:
    return norm_p(text).split()


def short_hash(text: str, n: int = 10) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def order_key(seed: str, key: str) -> str:
    return hashlib.sha256((seed + "|" + key).encode("utf-8")).hexdigest()


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def near_duplicate_join(
    queries: Dict[str, List[str]],
    refs: Dict[str, List[str]],
    threshold: float,
    self_prefix: str = "",
) -> Dict[str, Tuple[float, str]]:
    """Best reference with token-set Jaccard >= threshold, per query (prefix-filtered join).

    Standard all-pairs prefix filtering: with tokens ordered by ascending global frequency, two
    sets with Jaccard >= t always share a token within the first |x| - ceil(t*|x|) + 1 tokens of
    each. A reference named ``self_prefix + query_id`` is the query itself and is skipped. Sets
    of fewer than 3 tokens are never matched.
    """
    freq: Counter = Counter()
    qsets = {q: set(t) for q, t in queries.items() if len(set(t)) >= 3}
    rsets = {r: set(t) for r, t in refs.items() if len(set(t)) >= 3}
    for s in list(qsets.values()) + list(rsets.values()):
        freq.update(s)

    def prefix(s: Set[str]) -> List[str]:
        ordered = sorted(s, key=lambda w: (freq[w], w))
        return ordered[: len(ordered) - math.ceil(threshold * len(ordered)) + 1]

    index: Dict[str, List[str]] = defaultdict(list)
    for rid, s in rsets.items():
        for w in prefix(s):
            index[w].append(rid)
    out: Dict[str, Tuple[float, str]] = {}
    for qid, a in qsets.items():
        seen: Set[str] = set()
        best: Tuple[float, str] = (0.0, "")
        for w in prefix(a):
            for rid in index.get(w, ()):
                if rid in seen:
                    continue
                seen.add(rid)
                if self_prefix and rid == self_prefix + qid:
                    continue
                b = rsets[rid]
                if min(len(a), len(b)) / max(len(a), len(b)) < threshold:
                    continue
                j = len(a & b) / len(a | b)
                if j > best[0] or (j == best[0] and rid < best[1]):
                    best = (j, rid)
        if best[0] >= threshold:
            out[qid] = best
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ================================================================================================
# Sources
# ================================================================================================
def load_corpus() -> List[Dict[str, str]]:
    """The 7,151-row survey corpus, in file order, with a stable key per row."""
    rows: List[Dict[str, str]] = []
    with CORPUS_CSV.open(encoding="utf-8-sig", newline="") as fh:
        for i, r in enumerate(csv.DictReader(fh)):
            r = dict(r)
            r["_row"] = str(i)
            r["_key"] = "r%04d_%s" % (i, short_hash(norm_p(r["Question"])))
            rows.append(r)
    return rows


def corpus_candidates(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    return [r for r in rows if r["complexity"] in ("MULTI_STEP", "AGGREGATION")]


def catalogue_pdfs() -> List[Path]:
    return [p for p in sorted(CATALOGUE_DIR.glob("*.pdf")) if p.name != MASTER_REPORT]


def extract_pages(cache: Optional[Path] = None) -> Dict[str, List[str]]:
    """Page texts per persona (persona = the PDF's file stem), newlines replaced by spaces.

    The optional cache is keyed by every PDF's sha256 so a stale cache can never be used.
    """
    pdfs = catalogue_pdfs()
    fingerprint = {p.name: sha256_file(p) for p in pdfs}
    if cache and cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("fingerprint") == fingerprint:
            return data["pages"]
    import pdfplumber  # imported lazily: only needed when the cache is cold

    pages: Dict[str, List[str]] = {}
    for pdf in pdfs:
        texts: List[str] = []
        with pdfplumber.open(str(pdf)) as doc:
            for page in doc.pages:
                texts.append((page.extract_text() or "").replace("\n", " "))
        pages[pdf.stem] = texts
    if cache:
        cache.write_text(json.dumps({"fingerprint": fingerprint, "pages": pages}), encoding="utf-8")
    return pages


def _matches(texts: Sequence[str], regexes: Sequence[re.Pattern]) -> List[str]:
    out: List[str] = []
    for text in texts:
        for rx in regexes:
            for m in rx.finditer(text):
                q = m.group(1).strip()
                if 15 < len(q) < 300:
                    out.append(q)
    return out


def reproduce_spent_210(pages: Dict[str, List[str]]) -> List[Dict[str, str]]:
    """Reproduce the 2026-10-07 development draw exactly.

    Pass 1: every persona with RX1 only. Pass 2: ONLY the personas that got 0 in pass 1,
    re-extracted with RX1 then RX2 per page. Then random.seed(20261007) and, iterating personas
    in sorted(name) order, random.sample(qs, min(6, len(qs))) for each non-empty list. Raw text,
    before the LEAD cleanup.
    """
    lists: Dict[str, List[str]] = {}
    for name, texts in pages.items():
        lists[name] = _matches(texts, [RX1])
    for name in [n for n, q in lists.items() if not q]:
        lists[name] = _matches(pages[name], [RX1, RX2])
    random.seed(SEED_SPENT_210)
    drawn: List[Dict[str, str]] = []
    for name in sorted(lists):
        qs = lists[name]
        if not qs:
            continue
        for q in random.sample(qs, min(SPENT_PER_PERSONA, len(qs))):
            drawn.append({"persona": name, "question": q})
    return drawn


def clean_catalogue_text(raw: str) -> str:
    c = LEAD.sub("", raw, count=1).strip()
    return c if len(c) >= 15 else raw


def extract_catalogue_items(pages: Dict[str, List[str]]) -> List[Dict[str, object]]:
    """Every catalogue question: RX1 then RX2 per page, 15 < len < 300, LEAD-cleaned."""
    items: List[Dict[str, object]] = []
    for persona in sorted(pages):
        for page_no, text in enumerate(pages[persona]):
            for rx_name, rx in (("RX1", RX1), ("RX2", RX2)):
                for m in rx.finditer(text):
                    raw = m.group(1).strip()
                    if not (15 < len(raw) < 300):
                        continue
                    clean = clean_catalogue_text(raw)
                    key = "c_%s" % short_hash(persona + "|" + norm_p(clean), 12)
                    items.append(
                        {
                            "key": key,
                            "persona": persona,
                            "raw": raw,
                            "question": clean,
                            "page": page_no + 1,
                            "regex": rx_name,
                        }
                    )
    return items


def load_bank_catalogue_norms() -> Dict[str, str]:
    """Normalised text -> bank ID, for the 2,960 catalogue rows of the 4,060-question bank."""
    out: Dict[str, str] = {}
    with BANK_CSV.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("Source") == "stakeholder_catalogue_37":
                out.setdefault(norm_p(r["Question"]), r["ID"])
    return out


def load_bank_all_texts() -> List[str]:
    with BANK_CSV.open(encoding="utf-8-sig", newline="") as fh:
        return [r["Question"] for r in csv.DictReader(fh)]


def plan_quoted_examples() -> List[str]:
    """Every quoted phrase of >= 3 words in the v2 plan: the developer wrote and read them."""
    text = PLAN_MD.read_text(encoding="utf-8", errors="replace")
    found = re.findall(r"[\"\u201c]([^\"\u201c\u201d]{8,240})[\"\u201d]", text)
    return [f for f in found if len(f.split()) >= 3]


# ================================================================================================
# The structured "already asked" rule, and the parent's terminal peek
# ================================================================================================
def _parent_norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _walk_keys(obj: object, keys: Set[str], out: Set[str], normf) -> None:
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            for k, v in o.items():
                if k in keys and isinstance(v, str):
                    out.add(normf(v))
                elif isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(o, list):
            stack.extend(o)


def structured_seen(normf) -> Set[str]:
    """Strings under a question/q/query key in docs/**/*.json(l), scripts/outputs/*.json(l).

    Mirrors scratchpad/unseen_compound.py exactly (whole-file parse AND per-line parse).
    """
    files: List[Path] = []
    files += sorted(REPO.glob("docs/**/*.jsonl"))
    files += sorted(REPO.glob("docs/**/*.json"))
    files += sorted(REPO.glob("scripts/outputs/*.json"))
    files += sorted(REPO.glob("scripts/outputs/*.jsonl"))
    keys = {"question", "q", "query"}
    seen: Set[str] = set()
    for f in files:
        try:
            raw = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                _walk_keys(json.loads(line), keys, seen, normf)
            except Exception:  # noqa: BLE001
                continue
        try:
            _walk_keys(json.loads(raw), keys, seen, normf)
        except Exception:  # noqa: BLE001
            pass
    return seen


def parent_peek(rows: Sequence[Dict[str, str]]) -> List[str]:
    """The 20 MULTI_STEP rows scratchpad/unseen_compound.py printed (row keys)."""
    seen = structured_seen(_parent_norm)
    ms = [
        r for r in rows if r["complexity"] == "MULTI_STEP" and _parent_norm(r["Question"]) not in seen
    ]
    random.seed(PARENT_PEEK_SEED)
    return [r["_key"] for r in random.sample(ms, min(PARENT_PEEK_N, len(ms)))]


# ================================================================================================
# Exposure scan (--rescan only)
# ================================================================================================
class ContainmentMatcher:
    """Find which known questions occur, as whole token runs, inside a text."""

    def __init__(self, patterns: Dict[str, List[str]]) -> None:
        self.index: Dict[Tuple[str, str, str, str], List[Tuple[str, List[str]]]] = defaultdict(list)
        for pid, tk in patterns.items():
            if len(tk) < MIN_MATCH_TOKENS:
                continue
            self.index[tuple(tk[:4])].append((pid, tk))
            if len(tk) >= PREFIX_MIN_LEN:
                self.index[tuple(tk[:4])].append((pid, tk[:PREFIX_TOKENS]))
        self.first = {k[0] for k in self.index}

    def find(self, tokens: List[str]) -> Set[str]:
        hits: Set[str] = set()
        first = self.first
        index = self.index
        n = len(tokens)
        for i in range(n - 3):
            if tokens[i] not in first:
                continue
            cands = index.get((tokens[i], tokens[i + 1], tokens[i + 2], tokens[i + 3]))
            if not cands:
                continue
            for pid, pat in cands:
                if pid in hits:
                    continue
                if tokens[i : i + len(pat)] == pat:
                    hits.add(pid)
        return hits


def _decode(data: bytes) -> str:
    head = data[:4096]
    if head.startswith(b"\xff\xfe") or head.startswith(b"\xfe\xff") or (
        head and head.count(b"\x00") > len(head) // 4
    ):
        try:
            return data.decode("utf-16", errors="ignore")
        except Exception:  # noqa: BLE001
            pass
    return data.decode("utf-8", errors="ignore")


def _json_strings(obj: object, out: List[str]) -> None:
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, str):
            out.append(o)
        elif isinstance(o, dict):
            for k, v in o.items():
                out.append(str(k))
                stack.append(v)
        elif isinstance(o, list):
            stack.extend(o)


def _text_of(path: Path, data: bytes) -> str:
    """Readable text of a file. JSON is parsed so escaped newlines do not glue tokens together."""
    text = _decode(data)
    if path.suffix.lower() in (".json", ".jsonl", ".ipynb"):
        parts: List[str] = []
        try:
            _json_strings(json.loads(text), parts)
            return "\n".join(parts)
        except Exception:  # noqa: BLE001
            pass
        ok = False
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                _json_strings(json.loads(line), parts)
                ok = True
            except Exception:  # noqa: BLE001
                parts.append(line)
        if ok:
            return "\n".join(parts)
    return text


def _iter_files(root: Path, skip_rel: Set[str], base: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        rel = d.relative_to(base).as_posix() if d != base else ""
        keep = []
        for dn in dirnames:
            if dn in SKIP_DIR_NAMES or dn == BUILDER_WORK_DIRNAME:
                continue
            r = (rel + "/" + dn) if rel else dn
            if r in skip_rel:
                continue
            keep.append(dn)
        dirnames[:] = keep
        for fn in filenames:
            yield d / fn


def scan_units() -> Iterator[Tuple[str, str]]:
    """Yield (unit_id, text) for every development artefact in scope."""
    # 1. the repository (text files), its worktrees included
    for p in _iter_files(REPO, SKIP_REPO_RELDIRS, REPO):
        if p.suffix.lower() not in TEXT_EXTS:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size == 0 or size > MAX_FILE_BYTES:
            if size > MAX_FILE_BYTES:
                yield ("SKIPPED_LARGE:" + p.relative_to(REPO).as_posix(), "")
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        yield ("repo:" + p.relative_to(REPO).as_posix(), _text_of(p, data))
    # 2. live stores whose text is stored uncompressed (Postgres heap/WAL, Open WebUI sqlite)
    vol = REPO / "volumes"
    if vol.exists():
        for bdir in sorted(vol.iterdir()):
            if not bdir.is_dir():
                continue
            for sub in ("postgres", "postgres-user-data", "open-webui"):
                sd = bdir / sub
                if not sd.exists():
                    continue
                for p in _iter_files(sd, set(), sd):
                    if sub == "open-webui" and ".db" not in p.name:
                        continue
                    try:
                        size = p.stat().st_size
                        if size == 0 or size > MAX_FILE_BYTES:
                            continue
                        data = p.read_bytes()
                    except OSError:
                        continue
                    yield ("volume:" + p.relative_to(REPO).as_posix(), data.decode("utf-8", "ignore"))
    # 3. every session scratchpad / background-task output of this project
    if TEMP_PROJECT_DIR.exists():
        for p in _iter_files(TEMP_PROJECT_DIR, set(), TEMP_PROJECT_DIR):
            if p.suffix.lower() not in TEXT_EXTS and p.suffix:
                continue
            try:
                size = p.stat().st_size
                if size == 0 or size > MAX_FILE_BYTES:
                    continue
                data = p.read_bytes()
            except OSError:
                continue
            yield ("temp:" + p.relative_to(TEMP_PROJECT_DIR).as_posix(), _text_of(p, data))
    # 4. session transcripts (one unit per message line) + persisted tool results + memory
    if CLAUDE_PROJECT_DIR.exists():
        for p in _iter_files(CLAUDE_PROJECT_DIR, set(), CLAUDE_PROJECT_DIR):
            rel = p.relative_to(CLAUDE_PROJECT_DIR).as_posix()
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size == 0:
                continue
            if p.suffix.lower() == ".jsonl":
                try:
                    head = p.read_bytes()
                except OSError:
                    continue
                if BUILDER_TRANSCRIPT_MARKER.encode() in head:
                    continue  # this builder's own transcript
                for n, line in enumerate(head.decode("utf-8", "ignore").splitlines()):
                    line = line.strip()
                    if not line:
                        continue
                    parts: List[str] = []
                    try:
                        _json_strings(json.loads(line), parts)
                        text = "\n".join(parts)
                    except Exception:  # noqa: BLE001
                        text = line
                    yield ("transcript:%s#%d" % (rel, n), text)
            elif p.suffix.lower() in TEXT_EXTS and size <= MAX_FILE_BYTES:
                try:
                    data = p.read_bytes()
                except OSError:
                    continue
                if BUILDER_TRANSCRIPT_MARKER.encode() in data:
                    continue
                yield ("claude:" + rel, _text_of(p, data))


def asked_log_queries() -> Set[str]:
    """Every user_query the orchestrator logged as answered (outputs/query_results/*.json)."""
    out: Set[str] = set()
    qdir = REPO / "outputs" / "query_results"
    if not qdir.exists():
        return out
    for p in sorted(qdir.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(d, dict) and isinstance(d.get("user_query"), str):
            out.add(norm_p(d["user_query"]))
    return out


SURVEY_ANALYSIS_MARK = "Survey analysis and results/"


def unit_category(unit: str) -> str:
    """Coarse category of a scanned unit, used to apply and to report the exposure policy.

    ``survey_analysis`` is the survey-analysis pipeline's own working files (corpus copies,
    taxonomy coding samples, inter-rater logs, duplicate reports) wherever a copy of that tree
    sits. They were read to classify the survey, not to build or test the system, so a question
    that appears ONLY there is not treated as exposed (CODEBOOK.md §7). Every other category is.
    """
    kind, _, path = unit.partition(":")
    if SURVEY_ANALYSIS_MARK in path:
        return "survey_analysis"
    if kind == "transcript":
        return "session_transcript"
    if kind == "claude":
        return "session_files"
    if kind == "volume":
        return "live_store"
    if kind == "temp":
        return "session_scratchpad"
    inner = path
    for wt in (".claude/worktrees/", ".worktrees/"):
        if inner.startswith(wt):
            inner = inner[len(wt):].partition("/")[2]
    if inner.startswith("outputs/query_results/"):
        return "asked_query_log"
    if inner.startswith(("scripts/outputs/", "outputs/")) or (
        inner.startswith("docs/") and inner.endswith((".json", ".jsonl", ".csv"))
    ):
        return "run_outputs"
    if inner.startswith(("orchestrator/", "shared/", "tests/", "scripts/", "rag-service/")):
        return "code_and_tests"
    if inner.startswith(("tasks/", "docs/")) or inner.endswith(".md"):
        return "plans_docs_trackers"
    if inner.startswith("paper/"):
        return "paper_sources"
    if inner.startswith(("ontology/", "input/", "bldg", "config/", "Datasets/Ontology/")):
        return "ontology_and_building_data"
    return "repo_other"


def rescan(
    rows: Sequence[Dict[str, str]],
    cat_items: Sequence[Dict[str, object]],
    spent: Sequence[Dict[str, str]],
) -> Dict[str, object]:
    """Compute every exclusion reason from the mutable sources and return the snapshot."""
    t0 = time.time()
    # ---- structured rule (as stated) and its punctuation-insensitive twin ----
    seen_ws = structured_seen(norm_ws)
    seen_p = {norm_p(s) for s in seen_ws}
    peek = set(parent_peek(rows))
    asked_logs = asked_log_queries()

    # ---- containment patterns: every corpus question, every catalogue question ----
    corpus_text_to_keys: Dict[str, List[str]] = defaultdict(list)
    for r in rows:
        corpus_text_to_keys[norm_p(r["Question"])].append(r["_key"])
    cat_text_to_keys: Dict[str, List[str]] = defaultdict(list)
    for it in cat_items:
        cat_text_to_keys[norm_p(str(it["question"]))].append(str(it["key"]))
        cat_text_to_keys[norm_p(str(it["raw"]))].append(str(it["key"]))
    pat_corpus = {"T" + short_hash(t, 16): t.split() for t in corpus_text_to_keys}
    tid_corpus = {"T" + short_hash(t, 16): t for t in corpus_text_to_keys}
    pat_cat = {"K" + short_hash(t, 16): t.split() for t in cat_text_to_keys}
    tid_cat = {"K" + short_hash(t, 16): t for t in cat_text_to_keys}
    m_corpus = ContainmentMatcher(pat_corpus)
    m_cat = ContainmentMatcher(pat_cat)

    # per key: up to 8 sample units, the number of units, and every unit category seen
    corpus_units: Dict[str, List[str]] = defaultdict(list)
    corpus_n: Counter = Counter()
    corpus_cats: Dict[str, Set[str]] = defaultdict(set)
    cat_units: Dict[str, List[str]] = defaultdict(list)
    cat_n: Counter = Counter()
    cat_cats: Dict[str, Set[str]] = defaultdict(set)
    bulk_units: List[Dict[str, object]] = []
    skipped: List[str] = []
    n_units = 0
    n_chars = 0
    for unit, text in scan_units():
        if unit.startswith("SKIPPED_LARGE:"):
            skipped.append(unit.split(":", 1)[1])
            continue
        n_units += 1
        n_chars += len(text)
        tk = norm_p(text).split()
        if len(tk) < MIN_MATCH_TOKENS:
            continue
        hc = m_corpus.find(tk)
        hk = m_cat.find(tk)
        bulk_c = len(hc) >= BULK_THRESHOLD
        bulk_k = len(hk) >= BULK_THRESHOLD
        if bulk_c or bulk_k:
            bulk_units.append({"unit": unit, "corpus_hits": len(hc), "catalogue_hits": len(hk)})
        cat_of_unit = unit_category(unit)
        if hc and not bulk_c:
            for tid in hc:
                for key in corpus_text_to_keys[tid_corpus[tid]]:
                    corpus_n[key] += 1
                    corpus_cats[key].add(cat_of_unit)
                    if len(corpus_units[key]) < 8:
                        corpus_units[key].append(unit)
        if hk and not bulk_k:
            for tid in hk:
                for key in cat_text_to_keys[tid_cat[tid]]:
                    cat_n[key] += 1
                    cat_cats[key].add(cat_of_unit)
                    if len(cat_units[key]) < 8:
                        cat_units[key].append(unit)
    # the exposure policy: any category except the survey-analysis pipeline's own files
    corpus_exposed = {k for k, cs in corpus_cats.items() if cs - {"survey_analysis"}}
    cat_exposed = {k for k, cs in cat_cats.items() if cs - {"survey_analysis"}}

    # ---- reasons per corpus row (every row, so a later extension uses this same freeze) ----
    reasons_real: Dict[str, List[str]] = defaultdict(list)
    for r in rows:
        k = r["_key"]
        if norm_ws(r["Question"]) in seen_ws:
            reasons_real[k].append("ASKED_STATED_RULE")
        elif norm_p(r["Question"]) in seen_p:
            reasons_real[k].append("ASKED_PUNCTUATION_VARIANT")
        if k in peek:
            reasons_real[k].append("SHOWN_PARENT_PEEK")
        if k in corpus_exposed:
            reasons_real[k].append("EXPOSED")

    # ---- near-duplicates of anything spent / shown / quoted ----
    ref_texts: Dict[str, str] = {}
    for s in seen_p:
        ref_texts["asked:" + short_hash(s)] = s
    for s in asked_logs:
        ref_texts["asked_log:" + short_hash(s)] = s
    for r in rows:
        if r["_key"] in corpus_exposed or r["_key"] in peek:
            ref_texts["corpus:" + r["_key"]] = norm_p(r["Question"])
    for i, s in enumerate(plan_quoted_examples()):
        ref_texts["plan:%02d" % i] = norm_p(s)
    for s in load_bank_all_texts():
        ref_texts["bank:" + short_hash(norm_p(s))] = norm_p(s)
    best_ref = near_duplicate_join(
        {r["_key"]: norm_p(r["Question"]).split() for r in rows},
        {rid: t.split() for rid, t in ref_texts.items()},
        NEAR_DUP_JACCARD,
        self_prefix="corpus:",
    )
    for k, (_, rid) in best_ref.items():
        reasons_real[k].append("NEAR_DUPLICATE_OF:" + rid)

    # ---- reasons per catalogue item ----
    spent_raw = {s["question"] for s in spent}
    spent_norm = {norm_p(s["question"]) for s in spent}
    spent_norm |= {norm_p(clean_catalogue_text(s["question"])) for s in spent}
    reasons_cat: Dict[str, List[str]] = defaultdict(list)
    for it in cat_items:
        k = str(it["key"])
        if it["raw"] in spent_raw:
            reasons_cat[k].append("SPENT_210_RAW")
        elif norm_p(str(it["question"])) in spent_norm:
            reasons_cat[k].append("SPENT_210_TEXT")
        if k in cat_exposed:
            reasons_cat[k].append("EXPOSED")
    cat_refs: Dict[str, List[str]] = {}
    for t in spent_norm:
        cat_refs["SPENT_210:" + short_hash(t)] = t.split()
    for it in cat_items:
        if str(it["key"]) in cat_exposed:
            cat_refs["EXPOSED_ITEM:" + str(it["key"])] = norm_p(str(it["question"])).split()
    for t in seen_p | asked_logs:
        cat_refs["ASKED:" + short_hash(t)] = t.split()
    unflagged = {
        str(it["key"]): norm_p(str(it["question"])).split()
        for it in cat_items
        if not reasons_cat.get(str(it["key"]))
    }
    for k, (_, rid) in near_duplicate_join(
        unflagged, cat_refs, NEAR_DUP_JACCARD, self_prefix="EXPOSED_ITEM:"
    ).items():
        reasons_cat[k].append("NEAR_DUPLICATE_OF:" + rid.split(":")[0])

    snapshot = {
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "freeze_date": FREEZE_DATE,
        "corpus_csv_sha256": sha256_file(CORPUS_CSV),
        "catalogue_pdf_sha256": {p.name: sha256_file(p) for p in catalogue_pdfs()},
        "parameters": {
            "bulk_threshold": BULK_THRESHOLD,
            "near_dup_jaccard": NEAR_DUP_JACCARD,
            "min_match_tokens": MIN_MATCH_TOKENS,
            "prefix_tokens": PREFIX_TOKENS,
            "prefix_min_len": PREFIX_MIN_LEN,
        },
        "scan": {
            "units_scanned": n_units,
            "chars_scanned": n_chars,
            "seconds": round(time.time() - t0, 1),
            "skipped_large_files": skipped,
            "bulk_units_ignored": bulk_units,
            "structured_seen_strings": len(seen_ws),
            "asked_query_log_distinct_queries": len(asked_logs),
            "roots": [
                "repository text files (excluding %s)" % sorted(SKIP_REPO_RELDIRS),
                "volumes/*/{postgres,postgres-user-data} raw files; volumes/*/open-webui/*.db*",
                str(TEMP_PROJECT_DIR) + " (all sessions' scratchpads and task outputs)",
                str(CLAUDE_PROJECT_DIR) + " (transcripts per message, tool results, memory)",
            ],
            "not_scannable": [
                "Redis dump (LZF-compressed), MongoDB (WiredTiger-compressed), GraphDB/Qdrant stores",
                "terminal output never written to disk or to a transcript",
            ],
        },
        "exposure_policy": (
            "A unit holding >= %d distinct source questions is a bulk copy and is ignored. Every "
            "other unit in scope exposes the questions it holds, EXCEPT units inside a "
            "'Survey analysis and results' tree (the survey-analysis pipeline's own files), which "
            "are recorded under survey_analysis but do not exclude." % BULK_THRESHOLD
        ),
        "parent_peek_keys": sorted(peek),
        "real_exclusions": {k: v for k, v in sorted(reasons_real.items()) if v},
        "cat_exclusions": {k: v for k, v in sorted(reasons_cat.items()) if v},
        "real_candidates_seen_only_in_survey_analysis": sorted(
            r["_key"] for r in corpus_candidates(rows)
            if corpus_cats.get(r["_key"]) == {"survey_analysis"}
        ),
        "corpus_exposure_detail": {
            k: {"n_units": corpus_n[k], "categories": sorted(corpus_cats[k]),
                "sample_units": corpus_units[k]}
            for k in sorted(corpus_cats)
        },
        "catalogue_exposure_detail": {
            k: {"n_units": cat_n[k], "categories": sorted(cat_cats[k]),
                "sample_units": cat_units[k]}
            for k in sorted(cat_cats)
        },
    }
    return snapshot


# ================================================================================================
# Pools
# ================================================================================================
def real_pool(
    rows: Sequence[Dict[str, str]], snapshot: Dict[str, object]
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    """Unseen, de-duplicated corpus candidates, with the accounting for each step."""
    excl: Dict[str, List[str]] = snapshot["real_exclusions"]  # type: ignore[assignment]
    cands = corpus_candidates(rows)
    stats: Dict[str, object] = {"candidates": len(cands)}
    stated = [r for r in cands if "ASKED_STATED_RULE" not in excl.get(r["_key"], [])]
    stats["after_stated_rule"] = len(stated)
    unseen = [r for r in cands if not excl.get(r["_key"])]
    stats["after_all_integrity_exclusions"] = len(unseen)
    reason_counts: Counter = Counter()
    for r in cands:
        for reason in excl.get(r["_key"], []):
            reason_counts[reason.split(":")[0]] += 1
    stats["exclusion_reason_counts"] = dict(reason_counts)
    # de-duplicate within the pool: first occurrence in corpus order wins
    kept: List[Dict[str, str]] = []
    kept_sets: List[Set[str]] = []
    dup = 0
    for r in unseen:
        a = set(norm_p(r["Question"]).split())
        if any(jaccard(a, b) >= NEAR_DUP_JACCARD for b in kept_sets):
            dup += 1
            continue
        kept.append(r)
        kept_sets.append(a)
    stats["within_pool_duplicates_dropped"] = dup
    stats["pool_screened_by_codebook"] = len(kept)
    return kept, stats


# The SUPPLEMENT (see CODEBOOK.md §5). The pre-registered T-REAL pool (MULTI_STEP + AGGREGATION)
# yields far fewer than 80 unseen compound questions, because most of those rows were already
# asked to the system. So, at the same freeze and under the same codebook and exclusions, LOOKUP
# rows - whose complexity label is an LLM classification and does not exclude compound questions
# - are screened too, and drawn into a SEPARATE file. This rule was fixed before any LOOKUP row
# was read; it only decides which rows are screened, never how they are labelled.
SUPPLEMENT_SIGNAL = re.compile(
    r"\b(and|also|versus|vs|compared?|comparison|than|against|exceeds?|while|when|whenever|"
    r"during|after|before|since|each|per|across|every|most|least|highest|lowest|busiest|"
    r"quietest|both|between|correlat\w*|relationship|related|relate|affects?|affected|"
    r"affecting|impacts?|depends?|differ\w*|weekdays?|weekends?|peak|off-peak|yesterday|"
    r"last (week|month|year)|this (week|month|year)|floors|areas|zones|rooms)\b",
    re.IGNORECASE,
)


def supplement_pool(
    rows: Sequence[Dict[str, str]],
    snapshot: Dict[str, object],
    real_pool_rows: Sequence[Dict[str, str]],
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    """Unseen LOOKUP rows carrying a compound signal word, de-duplicated against T-REAL's pool."""
    excl: Dict[str, List[str]] = snapshot["real_exclusions"]  # type: ignore[assignment]
    look = [r for r in rows if r["complexity"] == "LOOKUP"]
    unseen = [r for r in look if not excl.get(r["_key"])]
    signal = [r for r in unseen if SUPPLEMENT_SIGNAL.search(r["Question"])]
    kept: List[Dict[str, str]] = []
    real_sets = [set(norm_p(r["Question"]).split()) for r in real_pool_rows]
    kept_sets: List[Set[str]] = []
    dup_real = 0
    dup_within = 0
    for r in signal:
        a = set(norm_p(r["Question"]).split())
        if any(jaccard(a, b) >= NEAR_DUP_JACCARD for b in real_sets):
            dup_real += 1
            continue
        if any(jaccard(a, b) >= NEAR_DUP_JACCARD for b in kept_sets):
            dup_within += 1
            continue
        kept.append(r)
        kept_sets.append(a)
    stats = {
        "lookup_rows": len(look),
        "lookup_rows_after_integrity_exclusions": len(unseen),
        "with_compound_signal_word": len(signal),
        "near_duplicates_of_t_real_pool_dropped": dup_real,
        "within_pool_duplicates_dropped": dup_within,
        "pool_screened_by_codebook": len(kept),
    }
    return kept, stats


def cat_pool(
    cat_items: Sequence[Dict[str, object]],
    snapshot: Dict[str, object],
    bank_norms: Dict[str, str],
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], Dict[str, object]]:
    """(DEV-eligible items after de-duplication, T-CAT-eligible subset, accounting)."""
    excl: Dict[str, List[str]] = snapshot["cat_exclusions"]  # type: ignore[assignment]
    stats: Dict[str, object] = {"extracted": len(cat_items)}
    # within-persona de-duplication: identical text, or a header-junk superstring of another item
    by_persona: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for it in cat_items:
        by_persona[str(it["persona"])].append(it)
    deduped: List[Dict[str, object]] = []
    dropped_dup = 0
    dropped_junk = 0
    for persona in sorted(by_persona):
        items = by_persona[persona]
        norms = [norm_p(str(it["question"])) for it in items]
        seen_n: Set[str] = set()
        for i, it in enumerate(items):
            n = norms[i]
            if n in seen_n:
                dropped_dup += 1
                continue
            if any(j != i and len(norms[j]) >= 15 and len(norms[j]) < len(n) and n.endswith(norms[j])
                   for j in range(len(items))):
                dropped_junk += 1
                continue
            seen_n.add(n)
            deduped.append(it)
    stats["dropped_exact_duplicates"] = dropped_dup
    stats["dropped_header_superstrings"] = dropped_junk
    stats["after_dedup"] = len(deduped)
    spent = [it for it in deduped if any(r.startswith("SPENT_210") for r in excl.get(str(it["key"]), []))]
    stats["spent_210_matched_items"] = len(spent)
    remaining = [it for it in deduped if not any(r.startswith("SPENT_210") for r in excl.get(str(it["key"]), []))]
    stats["not_spent"] = len(remaining)
    eligible: List[Dict[str, object]] = []
    for it in remaining:
        k = str(it["key"])
        if excl.get(k):
            continue
        if norm_p(str(it["question"])) not in bank_norms:
            continue  # not a clean, canonical catalogue question (two-column merge or header junk)
        eligible.append(it)
    stats["tcat_eligible_before_codebook"] = len(eligible)
    reason_counts: Counter = Counter()
    for it in remaining:
        for reason in excl.get(str(it["key"]), []):
            reason_counts[reason.split(":")[0]] += 1
    stats["exclusion_reason_counts_not_spent"] = dict(reason_counts)
    stats["not_bank_matched_not_spent"] = sum(
        1 for it in remaining if norm_p(str(it["question"])) not in bank_norms
    )
    return remaining, eligible, stats


# ================================================================================================
# Labels (sealed in LABELS.json) and selection
# ================================================================================================
SHAPES = ("C1", "C2", "C3", "C4", "C5", "C6")
NC_CODES = (
    "NC:SINGLE", "NC:CAPABILITY", "NC:PROCEDURE", "NC:OPINION", "NC:GENERIC",
    "NC:HYPOTHETICAL", "NC:EXPLAIN", "NC:OFFTOPIC", "NC:UNCLEAR", "NC:DUPLICATE",
    "NC:PLAN_EXAMPLE",
)
ANSWERABILITY = ("FULL", "PARTIAL", "NONE")
ORDER_SEED_SUPP = "compound-eval/T-REAL-SUPPLEMENT/2026-10-07"

Label = Tuple[str, str, Tuple[str, ...], str]  # (decision, answerability, facets, note)


def load_labels() -> Dict[str, Dict[str, Label]]:
    """The frozen codebook judgements. Every one is validated before any selection runs."""
    raw = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    out: Dict[str, Dict[str, Label]] = {}
    for part in ("real", "supplement", "cat"):
        labels: Dict[str, Label] = {}
        for key, v in raw[part].items():
            lab: Label = (v["decision"], v["answerability"], tuple(v["facets"]), v["note"])
            if lab[0] not in SHAPES and lab[0] not in NC_CODES:
                raise ValueError("bad decision %r for %s" % (lab[0], key))
            if lab[0] in SHAPES:
                if lab[1] not in ANSWERABILITY or not lab[2]:
                    raise ValueError("compound item without answerability/facets: %s" % key)
                if lab[1] in ("PARTIAL", "NONE") and not lab[3]:
                    raise ValueError("PARTIAL/NONE without a note: %s" % key)
            labels[key] = lab
        out[part] = labels
    return out


def allocate_quotas(target: int, avail: Dict[str, int]) -> Dict[str, int]:
    """Equal shares across shapes; a shape short of its share gives the rest to the others."""
    quota = {s: 0 for s in SHAPES}
    remaining = target
    left = sorted(SHAPES, key=lambda s: (avail.get(s, 0), s))
    while left:
        s = left.pop(0)
        share = remaining // (len(left) + 1)
        quota[s] = min(avail.get(s, 0), share)
        remaining -= quota[s]
    for s in SHAPES:  # integer-division remainder: C1 first, as the plan leads with C1
        if remaining <= 0:
            break
        spare = avail.get(s, 0) - quota[s]
        if spare > 0:
            take = min(spare, remaining)
            quota[s] += take
            remaining -= take
    return quota


def stratified_pick(
    pool: Sequence[Dict[str, str]],
    labels: Dict[str, Label],
    seed: str,
    target: int,
    per_pid: Counter,
    already_by_shape: Optional[Counter] = None,
) -> Tuple[List[Dict[str, str]], Dict[str, object]]:
    """Pick compound rows towards equal shares per shape, honouring the per-participant cap.

    ``per_pid`` is updated in place, so a second call (the supplement) continues the cap.
    ``already_by_shape`` counts picks made by an earlier call, so the shares are balanced over
    the union of both calls.
    """
    already = already_by_shape or Counter()
    by_shape: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for r in pool:
        if labels[r["_key"]][0] in SHAPES:
            by_shape[labels[r["_key"]][0]].append(r)
    for s in by_shape:
        by_shape[s].sort(key=lambda r: order_key(seed, r["_key"]))
    avail = {s: 0 for s in SHAPES}
    for s in SHAPES:  # what each shape can contribute under the cap, counted on its own
        trial = Counter(per_pid)
        for r in by_shape.get(s, []):
            if trial[r["PID"]] < MAX_PER_PID:
                trial[r["PID"]] += 1
                avail[s] += 1
    union_quota = allocate_quotas(
        target + sum(already.values()), {s: avail[s] + already[s] for s in SHAPES}
    )
    quota = {s: max(0, union_quota[s] - already[s]) for s in SHAPES}
    chosen: List[Dict[str, str]] = []
    got = {s: 0 for s in SHAPES}
    for s in sorted(SHAPES, key=lambda s: (avail[s], s)):  # scarcest shape first
        for r in by_shape.get(s, []):
            if got[s] >= quota[s]:
                break
            if per_pid[r["PID"]] >= MAX_PER_PID:
                continue
            chosen.append(r)
            per_pid[r["PID"]] += 1
            got[s] += 1
    short = target - len(chosen)  # a shortfall caused by the cap goes to the other shapes
    taken = {r["_key"] for r in chosen}
    for s in SHAPES:
        for r in by_shape.get(s, []):
            if short <= 0:
                break
            if r["_key"] in taken or per_pid[r["PID"]] >= MAX_PER_PID:
                continue
            chosen.append(r)
            taken.add(r["_key"])
            per_pid[r["PID"]] += 1
            got[s] += 1
            short -= 1
    stats = {
        "compound_in_pool_by_shape": {s: len(by_shape.get(s, [])) for s in SHAPES},
        "available_under_participant_cap": avail,
        "quota": quota,
        "selected_by_shape": got,
    }
    return chosen, stats


def select_cat(
    eligible: Sequence[Dict[str, object]], labels: Dict[str, Label]
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    """One per persona, then a second for personas in seeded order; each pick takes the shape
    least represented so far (ties: seeded order)."""
    by_persona: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for it in eligible:
        if labels[str(it["key"])][0] in SHAPES:
            by_persona[str(it["persona"])].append(it)
    for p in by_persona:
        by_persona[p].sort(key=lambda it: order_key(ORDER_SEED_CAT, str(it["key"])))
    counts = {s: 0 for s in SHAPES}
    chosen: List[Dict[str, object]] = []
    taken: Set[str] = set()

    def pick(persona: str) -> None:
        cands = [it for it in by_persona[persona] if str(it["key"]) not in taken]
        if not cands:
            return
        best = min(range(len(cands)), key=lambda i: (counts[labels[str(cands[i]["key"])][0]], i))
        it = cands[best]
        chosen.append(it)
        taken.add(str(it["key"]))
        counts[labels[str(it["key"])][0]] += 1

    personas = sorted(by_persona)
    for p in personas:
        if len(chosen) < TARGET_CAT:
            pick(p)
    for p in sorted(personas, key=lambda p: order_key(ORDER_SEED_CAT, "round2|" + p)):
        if len(chosen) < TARGET_CAT and sum(1 for it in chosen if it["persona"] == p) < MAX_PER_PERSONA:
            pick(p)
    stats = {
        "personas_with_compound_items": len(by_persona),
        "compound_items_in_pool": sum(len(v) for v in by_persona.values()),
        "selected_by_shape": counts,
    }
    return chosen, stats


# ================================================================================================
# Outputs
# ================================================================================================
def heldout_norm(text: str) -> str:
    """The HELDOUT_HASHES rule: lowercase, whitespace collapsed, stripped, trailing '?' removed."""
    t = " ".join((text or "").lower().split())
    return t.rstrip("?").rstrip()


def _four_grams(tokens: List[str]) -> Set[Tuple[str, ...]]:
    return {tuple(tokens[i : i + 4]) for i in range(max(0, len(tokens) - 3))}


def leaks(dev_text: str, test_text: str) -> bool:
    """True when a DEV item would show a test item: near-duplicate, or holds half its 4-grams."""
    a, b = toks(dev_text), toks(test_text)
    if jaccard(set(a), set(b)) >= NEAR_DUP_JACCARD:
        return True
    gb = _four_grams(b)
    if not gb:
        return False
    return len(gb & _four_grams(a)) / len(gb) >= 0.5


def jsonl_bytes(records: Iterable[Dict[str, object]]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records).encode("utf-8")


def emit(path: Path, data: bytes, write: bool, report: List[str]) -> str:
    digest = hashlib.sha256(data).hexdigest()
    if path.exists() and path.read_bytes() == data:
        report.append("unchanged  %s" % path.name)
    elif write:
        path.write_bytes(data)
        report.append("written    %s" % path.name)
    else:
        report.append("DIFFERS    %s (run with --write to regenerate)" % path.name)
    return digest


def real_record(prefix: str, i: int, r: Dict[str, str], lab: Label) -> Dict[str, object]:
    dec, ans, facets, note = lab
    return {
        "id": "%s%03d" % (prefix, i),
        "question": r["Question"],
        "pid": r["PID"],
        "persona": r["Personas"],
        "shape": dec,
        "answerability": ans,
        "facets_needed": list(facets),
        "answerability_note": note if ans != "FULL" else "",
        "corpus_complexity": r["complexity"],
        "corpus_query_type": r["query_type_l2"],
    }


def build(args: argparse.Namespace) -> int:
    rows = load_corpus()
    pages = extract_pages(Path(args.pages_cache) if args.pages_cache else None)
    spent = reproduce_spent_210(pages)
    cat_items = extract_catalogue_items(pages)
    bank_norms = load_bank_catalogue_norms()

    if args.rescan:
        snap = rescan(rows, cat_items, spent)
        SNAPSHOT_PATH.write_text(
            json.dumps(snap, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print("snapshot written: %s (%d units, %.0fs)" % (
            SNAPSHOT_PATH, snap["scan"]["units_scanned"], snap["scan"]["seconds"]))
    snap = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    if snap.get("corpus_csv_sha256") != sha256_file(CORPUS_CSV):
        print("ERROR: the corpus changed after the snapshot was frozen")
        return 2
    if snap.get("catalogue_pdf_sha256") != {p.name: sha256_file(p) for p in catalogue_pdfs()}:
        print("ERROR: the catalogue PDFs changed after the snapshot was frozen")
        return 2

    labels = load_labels()
    pool, rstats = real_pool(rows, snap)
    supp, sstats = supplement_pool(rows, snap, pool)
    dev_rest, cat_eligible, cstats = cat_pool(cat_items, snap, bank_norms)

    # every pool item must be labelled: the codebook was applied to the WHOLE of each pool
    for name, items, labs in (
        ("T-REAL", [r["_key"] for r in pool], labels["real"]),
        ("supplement", [r["_key"] for r in supp], labels["supplement"]),
        ("T-CAT", [str(it["key"]) for it in cat_eligible], labels["cat"]),
    ):
        missing = [k for k in items if k not in labs]
        if missing:
            print("ERROR: %d %s pool items have no label" % (len(missing), name))
            return 3

    # ---- T-REAL, then the supplement continuing the same participant cap ----
    per_pid: Counter = Counter()
    chosen_r, sel_r = stratified_pick(pool, labels["real"], ORDER_SEED_REAL, TARGET_REAL, per_pid)
    real_shapes = Counter(labels["real"][r["_key"]][0] for r in chosen_r)
    chosen_s, sel_s = stratified_pick(
        supp, labels["supplement"], ORDER_SEED_SUPP, max(0, TARGET_REAL - len(chosen_r)),
        per_pid, already_by_shape=real_shapes,
    )
    chosen_r.sort(key=lambda r: order_key(ORDER_SEED_REAL, "id|" + r["_key"]))
    chosen_s.sort(key=lambda r: order_key(ORDER_SEED_SUPP, "id|" + r["_key"]))
    real_records = [
        real_record("R", i, r, labels["real"][r["_key"]]) for i, r in enumerate(chosen_r, 1)
    ]
    supp_records = [
        real_record("X", i, r, labels["supplement"][r["_key"]]) for i, r in enumerate(chosen_s, 1)
    ]

    # ---- T-CAT ----
    chosen_c, sel_c = select_cat(cat_eligible, labels["cat"])
    chosen_c.sort(key=lambda it: order_key(ORDER_SEED_CAT, "id|" + str(it["key"])))
    cat_records: List[Dict[str, object]] = []
    for i, it in enumerate(chosen_c, 1):
        dec, ans, facets, note = labels["cat"][str(it["key"])]
        cat_records.append({
            "id": "C%03d" % i,
            "question": it["question"],
            "persona": it["persona"],
            "shape": dec,
            "answerability": ans,
            "facets_needed": list(facets),
            "answerability_note": note if ans != "FULL" else "",
        })

    # ---- DEV: every remaining extracted catalogue question that cannot show a test item ----
    test_texts = [str(r["question"]) for r in real_records + supp_records + cat_records]
    chosen_keys = {str(it["key"]) for it in chosen_c}
    dev_records: List[Dict[str, object]] = []
    dev_leak_removed = 0
    for it in dev_rest:
        if str(it["key"]) in chosen_keys:
            continue
        if any(leaks(str(it["question"]), t) for t in test_texts):
            dev_leak_removed += 1
            continue
        dev_records.append({
            "id": "",
            "question": it["question"],
            "persona": it["persona"],
            "bank_id": bank_norms.get(norm_p(str(it["question"]))),
            "pdf_page": it["page"],
        })
    for i, d in enumerate(dev_records, 1):
        d["id"] = "D%04d" % i

    spent_records = [
        {"id": "S%03d" % i, "persona": s["persona"], "question": s["question"]}
        for i, s in enumerate(spent, 1)
    ]
    hashes = sorted({
        hashlib.sha256(heldout_norm(str(r["question"])).encode("utf-8")).hexdigest()
        for r in real_records + supp_records + cat_records
    })

    report: List[str] = []
    write = bool(args.write)
    digests: Dict[str, str] = {}
    digests["T-REAL.jsonl"] = emit(HERE / "T-REAL.jsonl", jsonl_bytes(real_records), write, report)
    digests["T-REAL-SUPPLEMENT.jsonl"] = emit(
        HERE / "T-REAL-SUPPLEMENT.jsonl", jsonl_bytes(supp_records), write, report
    )
    digests["T-CAT.jsonl"] = emit(HERE / "T-CAT.jsonl", jsonl_bytes(cat_records), write, report)
    digests["DEV.jsonl"] = emit(HERE / "DEV.jsonl", jsonl_bytes(dev_records), write, report)
    digests["SPENT_210.jsonl"] = emit(
        HERE / "SPENT_210.jsonl", jsonl_bytes(spent_records), write, report
    )
    digests["HELDOUT_HASHES.txt"] = emit(
        HERE / "HELDOUT_HASHES.txt", ("\n".join(hashes) + "\n").encode("utf-8"), write, report
    )
    for name, path in (
        ("LABELS.json", LABELS_PATH),
        ("EXCLUSION_SNAPSHOT.json", SNAPSHOT_PATH),
        ("CODEBOOK.md", CODEBOOK_PATH),
        ("build_sets.py", Path(__file__).resolve()),
    ):
        digests[name] = sha256_file(path)

    def dist(records: Sequence[Dict[str, object]], field: str) -> Dict[str, int]:
        return dict(sorted(Counter(str(r[field]) for r in records).items()))

    def cross(records: Sequence[Dict[str, object]]) -> Dict[str, Dict[str, int]]:
        out: Dict[str, Dict[str, int]] = {}
        for s in SHAPES:
            c = Counter(str(r["answerability"]) for r in records if r["shape"] == s)
            out[s] = {a: c.get(a, 0) for a in ANSWERABILITY}
        return out

    def decisions(keys: Iterable[str], labs: Dict[str, Label]) -> Dict[str, int]:
        return dict(sorted(Counter(labs[k][0] for k in keys).items()))

    union = real_records + supp_records
    manifest = {
        "freeze_date": FREEZE_DATE,
        "exclusion_snapshot_frozen_at_utc": snap.get("frozen_at_utc"),
        "files_sha256": digests,
        "sealed_until_the_blinded_read": [
            "T-REAL.jsonl", "T-REAL-SUPPLEMENT.jsonl", "T-CAT.jsonl", "LABELS.json",
        ],
        "open_to_the_v2_developer": [
            "DEV.jsonl", "SPENT_210.jsonl", "HELDOUT_HASHES.txt", "CODEBOOK.md", "MANIFEST.json",
            "build_sets.py", "EXCLUSION_SNAPSHOT.json",
        ],
        "sources_sha256": {
            "classified_corpus.csv": sha256_file(CORPUS_CSV),
            "smart_building_questions.csv": sha256_file(BANK_CSV),
            "catalogue_pdfs": snap.get("catalogue_pdf_sha256"),
        },
        "counts": {
            "T-REAL.jsonl": len(real_records),
            "T-REAL-SUPPLEMENT.jsonl": len(supp_records),
            "T-CAT.jsonl": len(cat_records),
            "DEV.jsonl": len(dev_records),
            "SPENT_210.jsonl": len(spent_records),
            "HELDOUT_HASHES.txt": len(hashes),
        },
        "T-REAL": {
            "role": "pre-registered primary held-out test (pool: MULTI_STEP + AGGREGATION rows)",
            "by_shape": dist(real_records, "shape"),
            "by_answerability": dist(real_records, "answerability"),
            "shape_x_answerability": cross(real_records),
            "distinct_participants": len({r["pid"] for r in real_records}),
            "pool_accounting": rstats,
            "codebook_decisions_over_pool": decisions([r["_key"] for r in pool], labels["real"]),
            "selection": sel_r,
        },
        "T-REAL-SUPPLEMENT": {
            "role": (
                "NOT part of the pre-registered T-REAL. Same freeze, codebook, exclusions and "
                "participant cap, drawn from LOOKUP rows because the specified pool yields far "
                "fewer than 80. The owner decides, before any v2 commit, whether the primary "
                "analysis uses T-REAL alone or T-REAL + supplement; record that decision."
            ),
            "screening_rule": "LOOKUP rows matching SUPPLEMENT_SIGNAL (fixed before reading)",
            "by_shape": dist(supp_records, "shape"),
            "by_answerability": dist(supp_records, "answerability"),
            "shape_x_answerability": cross(supp_records),
            "distinct_participants": len({r["pid"] for r in supp_records}),
            "pool_accounting": sstats,
            "codebook_decisions_over_pool": decisions(
                [r["_key"] for r in supp], labels["supplement"]
            ),
            "selection": sel_s,
        },
        "T-REAL_plus_supplement": {
            "count": len(union),
            "by_shape": dist(union, "shape"),
            "by_answerability": dist(union, "answerability"),
            "distinct_participants": len({r["pid"] for r in union}),
            "max_items_per_participant": max(Counter(r["pid"] for r in union).values() or [0]),
        },
        "T-CAT": {
            "role": "secondary held-out test (catalogue items never asked, quoted or printed)",
            "by_shape": dist(cat_records, "shape"),
            "by_answerability": dist(cat_records, "answerability"),
            "shape_x_answerability": cross(cat_records),
            "distinct_personas": len({r["persona"] for r in cat_records}),
            "pool_accounting": cstats,
            "codebook_decisions_over_pool": decisions(
                [str(it["key"]) for it in cat_eligible], labels["cat"]
            ),
            "selection": sel_c,
        },
        "DEV": {
            "items_removed_because_they_would_show_a_test_item": dev_leak_removed,
            "with_bank_id": sum(1 for d in dev_records if d["bank_id"]),
            "note": (
                "Extraction is the PDF regex pass as specified; items without a bank_id are "
                "two-column merges or header fragments and should be read with that in mind."
            ),
        },
        "seeds": {
            "spent_210_draw": SEED_SPENT_210,
            "parent_peek_reproduction": PARENT_PEEK_SEED,
            "t_real_order": ORDER_SEED_REAL,
            "t_real_supplement_order": ORDER_SEED_SUPP,
            "t_cat_order": ORDER_SEED_CAT,
        },
        "parameters": {
            "target_real": TARGET_REAL,
            "target_cat": TARGET_CAT,
            "max_per_pid_across_t_real_and_supplement": MAX_PER_PID,
            "max_per_persona": MAX_PER_PERSONA,
            "near_dup_jaccard": NEAR_DUP_JACCARD,
            "bulk_threshold": BULK_THRESHOLD,
        },
        "heldout_hashes_rule": (
            "One line per T-REAL, T-REAL-SUPPLEMENT and T-CAT item: sha256 hex of the UTF-8 "
            "bytes of the question text after: lowercase; every run of whitespace collapsed to "
            "one space and leading/trailing whitespace stripped; then all trailing '?' "
            "characters removed and any trailing whitespace left stripped. Lines sorted, "
            "duplicates removed, no question text. Matches exact (normalised) copies only, not "
            "paraphrases or near-duplicates. Anyone who hashes the corpus can recover set "
            "membership from this file, so it protects against accidental exposure only."
        ),
        "statement": (
            "Built on 2026-10-07 by an isolated agent, before any v2 code was committed, from "
            "the real survey corpus (classified_corpus.csv) and the 37-role stakeholder "
            "catalogue PDFs. The 210 catalogue questions asked during development that day were "
            "reproduced from their seeded draw and excluded. Every corpus question that had been "
            "stored as asked, logged by the orchestrator as answered, printed to the developer, "
            "quoted, or present in any development artefact, session transcript or uncompressed "
            "live store - or was a near-duplicate of one, or of any 4,060-bank question - was "
            "removed before the codebook was applied; the scan is frozen in "
            "EXCLUSION_SNAPSHOT.json. Compoundness, shape and FULL/PARTIAL/NONE answerability "
            "for bldg1 were judged under CODEBOOK.md and frozen in LABELS.json, and the sets "
            "were drawn by fixed seeds. The specified T-REAL pool yields far fewer than the "
            "planned 80 items, so a separately filed supplement from LOOKUP rows was frozen at "
            "the same time for the owner to adopt or discard. The v2 developer may use DEV.jsonl "
            "only; the sealed files stay unread until the blinded hand read. Every catalogue "
            "question, test items included, is in the 4,060-question development bank, so T-CAT "
            "is a weaker held-out set than T-REAL."
        ),
        "build": "python eval/compound/build_sets.py [--write]   (--rescan only at freeze time)",
    }
    m_bytes = (json.dumps(manifest, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    emit(HERE / "MANIFEST.json", m_bytes, write, report)
    for line in report:
        print(line)
    return 0 if write or all(not ln.startswith("DIFFERS") for ln in report) else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--rescan", action="store_true", help="freeze time only: rebuild the snapshot")
    ap.add_argument("--write", action="store_true", help="write outputs (default: verify only)")
    ap.add_argument("--pages-cache", default="", help="optional cache file for PDF page texts")
    return build(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())


