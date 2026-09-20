#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Register oracle: questions whose true answers are COMPUTED from the register tables, and a
checker that scores a live run against them without a judge.

WHY THIS EXISTS
---------------
The hand read is the measurement bottleneck (200 answers is hours) and the automatic grader
agrees with the hand labels only at kappa 0.31 on material it was not tuned on. But a register
question has a single true answer that sits in a markdown table: a count, a set of ids, an
owner, a date. So this tool

1. parses every register table under ``input/documents/*.md``,
2. writes natural questions (five wordings: facility manager, occupant, auditor, executive,
   student) whose expected facts are read off the rows, and
3. scores a run file (``scripts/ask_questions.py --out PREFIX`` -> ``PREFIX.jsonl``) against
   those facts: fact recall, FALSE ABSENCE, INVENTED IDS, and a decline where the facts exist.

FALSE ABSENCE is the defect that matters most: the answer says the register "does not record"
a property that is in the table (38 of 96 weird answers in the first hand read). It is checked
against the table's own header, not against a phrase list alone: an absence claim is false
only if the thing it says is missing is a column (or a value, or the register itself) that the
table holds.

    python scripts/register_oracle.py --list
    python scripts/register_oracle.py --n 250 --seed 1 --out scripts/outputs/register_oracle
    #   optional: --register fire_safety (repeatable)  --weights FILE.json  (a demand tilt)
    python scripts/ask_questions.py --v1 --stream --file scripts/outputs/register_oracle.txt \\
        --out scripts/outputs/register_run
    python scripts/register_oracle.py --score scripts/outputs/register_run.jsonl \\
        --oracle scripts/outputs/register_oracle.jsonl
    python scripts/register_oracle.py --selfcheck

The oracle JSONL also works as ``ask_questions.py --jsonl`` (it has a ``question`` field).
Stdlib only. Deterministic: same documents + same seed -> same questions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "scripts" / "outputs" / "register_oracle"


def default_doc_dir() -> Path:
    """The active building's documents, else the first parked building's.

    The committed tree has NO active building (Workflow rule 8): ``input/`` exists only while a
    building is running, and a fresh clone holds the same files under ``bldg<N>/documents``.
    """
    active = REPO / "input" / "documents"
    if active.is_dir():
        return active
    for parked in sorted(REPO.glob("bldg*/documents")):
        if parked.is_dir():
            return parked
    return active


DOC_DIR = default_doc_dir()

PERSONAS: Tuple[str, ...] = ("facility_manager", "occupant", "auditor", "executive", "student")

# A list question is only asked when the answer is a list a person could actually read.
MAX_LIST_IDS = 12
MAX_OWNER_VALUES = 6
MAX_VALUE_CHARS = 90

# ---------------------------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------------------------

# Every dash-like character an LLM or a markdown renderer might emit. The first live answers
# printed "WO-008" with U+2011 (non-breaking hyphen), which a plain substring test misses.
NB_HYPHEN = chr(0x2011)  # the one live answers print in 'WO-008'
_DASH_TABLE = {
    c: "-"
    for c in (
        0x2010,
        0x2011,
        0x2012,
        0x2013,
        0x2014,
        0x2015,
        0x2212,
        0x2043,
        0xFE58,
        0xFE63,
        0xFF0D,
    )
}
_SPACE_TABLE = {c: " " for c in (0xA0, 0x2002, 0x2003, 0x2007, 0x2008, 0x2009, 0x200A, 0x202F)}
_QUOTE_TABLE: Dict[int, Optional[str]] = {
    0x2018: "'",
    0x2019: "'",
    0x201C: '"',
    0x201D: '"',
    # soft hyphen, zero-width space / non-joiner / joiner, byte-order mark: dropped
    0xAD: None,
    0x200B: None,
    0x200C: None,
    0x200D: None,
    0xFEFF: None,
}


def normalise(text: str) -> str:
    """Dashes, spaces and quotes folded to ASCII; markdown emphasis removed; case kept."""
    out = str(text or "").translate(_DASH_TABLE).translate(_SPACE_TABLE).translate(_QUOTE_TABLE)
    out = out.replace("**", "").replace("__", "").replace("`", "")
    return out


def norm_lower(text: str) -> str:
    """``normalise`` + lowercase + collapsed whitespace, for substring comparison."""
    return re.sub(r"\s+", " ", normalise(text).lower().replace("&", " and ")).strip()


def words_of(text: str) -> List[str]:
    """Lowercase alphanumeric word tokens of ``text`` (dashes and punctuation are separators)."""
    return re.findall(r"[a-z0-9]+", norm_lower(text).replace("-", " "))


def plain(text: str) -> str:
    """One space-joined run of the alphanumeric tokens, for punctuation-blind comparison."""
    return " ".join(words_of(text))


# ---------------------------------------------------------------------------------------------
# Parsing: markdown tables -> registers
# ---------------------------------------------------------------------------------------------

_ID_HEADERS = {
    "code",
    "id",
    "ref",
    "reference",
    "group",
    "route",
    "approval",
    "task",
    "activity",
    "checkpoint",
    "opening",
    "component",
    "provision",
    "function",
    "line",
    "event",
    "permit",
    "point",
    "asset",
    "record",
    "number",
    "no",
}
_STATUS_EXACT = ("status", "state", "grade", "decision")
_CODE_VALUE = re.compile(r"^[A-Za-z]{1,8}[-_ ]?\d[\w.\-]*$")
_NAME_HEADERS = ("name", "title", "description", "summary", "hazard")
_OWNER_HEADERS = ("owner", "owner_role", "accountable_role")
# The columns a person would slice a register by. A whitelist, not "any short column": a column
# of times, evidence references or near-unique locations makes a question nobody would ask.
_FACET_HEADERS = (
    "kind",
    "category",
    "type",
    "session_kind",
    "document_kind",
    "subject_kind",
    "evidence_type",
    "stream_label",
    "engineering_system",
    "utility",
    "trade",
    "zone",
    "circuit",
    "system",
    "floor",
    "priority",
    "severity",
    "criticality",
    "shift",
    "frequency",
    "provider",
    "venue",
    "authority",
    "cost_centre",
    "weekday",
    "role_template",
    "time_profile",
    "access_tier",
    "standard",
    "event",
    "room",
    "decision",
)
_NOTE_HEADERS = {"note", "notes", "comment", "comments", "conditions", "condition", "remarks"}
_BOOLEAN_VALUES = {"yes", "no", "true", "false", "y", "n"}
# A status value that reads as "no status" makes an unnatural question ("are any none?").
_NONE_LIKE = {"none", "n/a", "na", "-", "unknown"}

_NOUN_OVERRIDES = {
    "surveys": "condition surveys",
    "targets": "sustainability targets",
    "handover": "handover records",
    "door hardware": "door hardware items",
    "continuity provision": "continuity provisions",
    "waste points": "waste collection points",
    "risks": "risk assessments",
    "av components": "AV components",
    "approvals": "approvals",
}


@dataclass
class Register:
    """One register table: its rows and what the columns are for."""

    key: str  # file stem, "#2" appended when a file holds several registers
    file: str
    title: str  # front-matter table name, else the nearest heading
    noun: str  # plural noun a person would use: "fire safety assets"
    headers: List[str]
    rows: List[Dict[str, str]]
    id_col: str = ""
    status_col: str = ""
    name_col: str = ""
    owner_col: str = ""
    kind_cols: List[str] = field(default_factory=list)
    date_cols: List[str] = field(default_factory=list)
    numeric_cols: List[str] = field(default_factory=list)
    id_prefixes: Set[str] = field(default_factory=set)
    anomalies: List[str] = field(default_factory=list)
    sha1: str = ""  # of the source file: a run scored against a changed file is stale

    @property
    def ids(self) -> List[str]:
        """Record ids in table order."""
        return [r[self.id_col] for r in self.rows]


def _is_separator(line: str) -> bool:
    s = line.strip()
    if not s.startswith("|"):
        return False
    body = s.replace("|", "").replace(":", "").replace(" ", "")
    return bool(body) and set(body) <= {"-"}


def _split_row(line: str) -> List[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def clean_cell(cell: str) -> str:
    """A cell's value: markdown emphasis and code ticks dropped, whitespace collapsed."""
    return re.sub(r"\s+", " ", normalise(cell)).strip()


def _front_matter(lines: Sequence[str]) -> Tuple[Dict[str, str], List[Dict[str, str]], int]:
    """(top-level scalars, the ``tables:`` entries, index of the first body line)."""
    if not lines or lines[0].strip() != "---":
        return {}, [], 0
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, [], 0
    meta: Dict[str, str] = {}
    tables: List[Dict[str, str]] = []
    in_tables = False
    for raw in lines[1:end]:
        if re.match(r"^tables\s*:", raw):
            in_tables = True
            continue
        if in_tables and re.match(r"^\s+-\s+\w+\s*:", raw):
            k, _, v = raw.strip()[1:].strip().partition(":")
            tables.append({k.strip(): v.strip().strip('"')})
            continue
        if in_tables and re.match(r"^\s+\w+\s*:", raw) and tables:
            k, _, v = raw.strip().partition(":")
            tables[-1][k.strip()] = v.strip().strip('"')
            continue
        if re.match(r"^\w[\w_]*\s*:", raw):
            in_tables = False
            k, _, v = raw.partition(":")
            meta[k.strip()] = v.strip().strip('"')
    return meta, tables, end + 1


def _looks_like_id_column(header: str, values: List[str]) -> bool:
    if header.strip().lower() in _ID_HEADERS:
        return True
    vals = [v for v in values if v]
    return bool(vals) and sum(1 for v in vals if _CODE_VALUE.match(v)) / len(vals) >= 0.9


def _status_column(headers: List[str]) -> str:
    low = [h.strip().lower() for h in headers]
    for want in _STATUS_EXACT:
        if want in low:
            return headers[low.index(want)]
    for h, lh in zip(headers, low):
        if lh.endswith("_status"):
            return h
    return ""


_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")


def _parse_iso(value: str) -> Optional[date]:
    if not _ISO.match(value or ""):
        return None
    try:
        return date(int(value[:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def _noun_from(meta: Dict[str, str], tab: Dict[str, str], stem: str) -> str:
    raw = (tab.get("maps_to") or meta.get("record_type") or stem).replace("_", " ").strip()
    if raw in _NOUN_OVERRIDES:
        return _NOUN_OVERRIDES[raw]
    return raw


def _classify(reg: Register) -> None:
    """Fill the column roles of a register from its header and its values."""
    hdrs = reg.headers
    low = {h: h.strip().lower() for h in hdrs}
    reg.id_col = hdrs[0]
    reg.status_col = _status_column(hdrs)
    n = len(reg.rows)

    def col(h: str) -> List[str]:
        return [r[h] for r in reg.rows]

    for want in _NAME_HEADERS:
        for h in hdrs:
            if low[h] == want and h != reg.id_col:
                vals = col(h)
                if all(vals) and len(set(v.lower() for v in vals)) == n:
                    reg.name_col = h
                    break
        if reg.name_col:
            break
    for want in _OWNER_HEADERS:
        for h in hdrs:
            if low[h] == want and any(col(h)):
                reg.owner_col = h
                break
        if reg.owner_col:
            break
    for h in hdrs:
        vals = [v for v in col(h) if v]
        if not vals or h == reg.id_col:
            continue
        if sum(1 for v in vals if _parse_iso(v)) / len(vals) >= 0.8:
            reg.date_cols.append(h)
        elif sum(1 for v in vals if _NUM.match(v)) / len(vals) >= 0.8:
            reg.numeric_cols.append(h)
    # Facets: whitelisted slicing columns whose values group the rows usefully (2..15 distinct
    # values, no more than half as many distinct values as rows, short, not yes/no flags).
    for h in hdrs:
        if h in (reg.id_col, reg.status_col, reg.owner_col, reg.name_col):
            continue
        if not (low[h] in _FACET_HEADERS or low[h].endswith("_kind")):
            continue
        vals = [v for v in col(h) if v]
        distinct = set(vals)
        if len(vals) < 2 or not 2 <= len(distinct) <= 15:
            continue
        if len(distinct) * 2 > n and len(distinct) > 3:
            continue
        if any(len(v) > 40 for v in distinct) or {v.lower() for v in distinct} <= _BOOLEAN_VALUES:
            continue
        reg.kind_cols.append(h)
    reg.id_prefixes = {
        m.group(1).upper() for i in reg.ids for m in [re.match(r"^([A-Za-z]+)", i)] if m
    }


def parse_registers(path: Path) -> List[Register]:
    """Every register table in one markdown file (usually one; some files hold lookup tables)."""
    raw = path.read_bytes()
    digest = hashlib.sha1(raw, usedforsecurity=False).hexdigest()[:12]  # change detector only
    lines = raw.decode("utf-8").splitlines()
    meta, tab_meta, body = _front_matter(lines)
    found: List[Register] = []
    heading = ""
    i = body
    while i < len(lines):
        line = lines[i]
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        if (
            line.strip().startswith("|")
            and i + 1 < len(lines)
            and _is_separator(lines[i + 1])
            and not _is_separator(line)
        ):
            headers = [clean_cell(c) for c in _split_row(line)]
            j = i + 2
            rows: List[Dict[str, str]] = []
            anomalies: List[str] = []
            while j < len(lines) and lines[j].strip().startswith("|"):
                cells = [clean_cell(c) for c in _split_row(lines[j])]
                if len(cells) != len(headers):
                    anomalies.append(f"line {j + 1}: {len(cells)} cells for {len(headers)} headers")
                    cells = (cells + [""] * len(headers))[: len(headers)]
                rows.append(dict(zip(headers, cells)))
                j += 1
            idx = len(found)
            tab = tab_meta[idx] if idx < len(tab_meta) else (tab_meta[0] if tab_meta else {})
            reg = Register(
                key=path.stem,
                file=path.name,
                title=tab.get("name") or heading,
                noun=_noun_from(meta, tab, path.stem),
                headers=headers,
                rows=rows,
                anomalies=anomalies,
                sha1=digest,
            )
            first_vals = [r[headers[0]] for r in rows]
            qualifies = (
                len(rows) >= 3
                and len(headers) >= 3
                and _looks_like_id_column(headers[0], first_vals)
                and bool(_status_column(headers))
                and len(set(first_vals)) == len(first_vals)
                and all(first_vals)
            )
            if qualifies:
                _classify(reg)
                found.append(reg)
            i = j
        else:
            i += 1
    if len(found) > 1:
        for n, reg in enumerate(found):
            if n:
                reg.key = f"{path.stem}#{n + 1}"
    return found


def load_registers(doc_dir: Optional[Path] = None) -> "OrderedDict[str, Register]":
    """Every register under ``doc_dir``, keyed by file stem (sorted, deterministic)."""
    out: "OrderedDict[str, Register]" = OrderedDict()
    for path in sorted(Path(doc_dir or default_doc_dir()).glob("*.md")):
        for reg in parse_registers(path):
            out[reg.key] = reg
    return out


# ---------------------------------------------------------------------------------------------
# Reading an answer: ids, dates, numbers
# ---------------------------------------------------------------------------------------------

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_MONTH_NUM = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_DATE_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("iso", re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")),
    ("ymd_slash", re.compile(r"(?<!\d)(\d{4})/(\d{1,2})/(\d{1,2})(?!\d)")),
    (
        "dmy_text",
        re.compile(
            rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH})\b\.?,?\s+(\d{{4}})(?!\d)",
            re.I,
        ),
    ),
    (
        "mdy_text",
        re.compile(rf"\b({_MONTH})\b\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})(?!\d)", re.I),
    ),
    ("slash", re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")),
    ("dot", re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)")),
]


def _mk_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def dates_in(text: str) -> Set[date]:
    """Every calendar date written in ``text``: ISO, '18 Sep 2026', 'September 18, 2026', 18/09/2026."""
    t = normalise(text)
    found: Set[date] = set()
    for kind, pat in _DATE_PATTERNS:
        for m in pat.finditer(t):
            g = m.groups()
            cands: List[Optional[date]] = []
            if kind in ("iso", "ymd_slash"):
                cands.append(_mk_date(int(g[0]), int(g[1]), int(g[2])))
            elif kind == "dmy_text":
                cands.append(_mk_date(int(g[2]), _MONTH_NUM[g[1][:3].lower()], int(g[0])))
            elif kind == "mdy_text":
                cands.append(_mk_date(int(g[2]), _MONTH_NUM[g[0][:3].lower()], int(g[1])))
            else:  # slash / dot: UK day-first, and month-first when that is also a date
                cands.append(_mk_date(int(g[2]), int(g[1]), int(g[0])))
                cands.append(_mk_date(int(g[2]), int(g[0]), int(g[1])))
            found.update(c for c in cands if c)
    return found


def strip_dates(text: str) -> str:
    """``text`` with every date replaced by a space (so its digits are not read as counts)."""
    t = normalise(text)
    for _kind, pat in _DATE_PATTERNS:
        t = pat.sub(" ", t)
    return t


_SEP = r"[-\s_]?"


def id_tokens(value: str) -> Tuple[Any, ...]:
    """Canonical form of an id: alpha runs upper-cased, digit runs as ints ('FSA-027' -> ('FSA', 27))."""
    return tuple(
        m.group(1).upper() if m.group(1) else int(m.group(2))
        for m in re.finditer(r"([A-Za-z]+)|(\d+)", value)
    )


def id_regex(ids: Iterable[str]) -> "re.Pattern[str]":
    """One pattern matching anything shaped like the given ids ('FSA-027' -> FSA-<digits>).

    Alpha runs are literal, digit runs are ``\\d+`` and the separators are optional, so a
    non-breaking hyphen, a space or no separator all match; an id that is NOT in the table but
    has its shape ('FSA-999') matches too, which is how an invented one is found.
    """
    shapes: List[str] = []
    for value in ids:
        runs = re.findall(r"[A-Za-z]+|\d+", value)
        if not runs:
            continue
        rx = _SEP.join(r"\d+" if r[0].isdigit() else re.escape(r) for r in runs)
        if rx not in shapes:
            shapes.append(rx)
    if not shapes:
        return re.compile(r"(?!x)x")
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(shapes) + r")(?![A-Za-z0-9])", re.I)


_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_WORD_RE = re.compile(
    r"\b(?:("
    + "|".join(_TENS)
    + r")(?:[-\s]+("
    + "|".join(k for k in _NUMBER_WORDS if 0 < _NUMBER_WORDS[k] < 10)
    + r"))?"
    r"|(" + "|".join(_NUMBER_WORDS) + r"))\b",
    re.I,
)


def number_word(n: int) -> str:
    """0..99 in words ('twenty-one'), or the digits when larger."""
    inv = {v: k for k, v in _NUMBER_WORDS.items()}
    if n in inv:
        return inv[n]
    if 20 <= n <= 99:
        tens, unit = (n // 10) * 10, n % 10
        base = next(k for k, v in _TENS.items() if v == tens)
        return base if not unit else f"{base}-{inv[unit]}"
    return str(n)


def _drop_noise(text: str, ids: Optional["re.Pattern[str]"]) -> str:
    """Dates, record ids, times and list numbering removed, so what is left holds only counts."""
    t = strip_dates(text)
    if ids is not None:
        t = ids.sub(" ", t)
    t = re.sub(r"(?<!\d)\d{1,2}:\d{2}(?::\d{2})?(?!\d)", " ", t)
    t = re.sub(r"(?m)^\s*(?:[-*•]\s*)?\d{1,3}[.)]\s+", " ", t)
    return t


_NUM_TOKEN = re.compile(r"(?<![\w.,])(-?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![\w])")
# "floor 1", "Level 3", "room 5.04", "2nd": a place or an ordinal, never the count asked for.
_LABELLED_NUMBER = re.compile(
    r"\b(?:floors?|levels?|storeys?|rooms?|zones?|blocks?|bays?|stair(?:s|well)?|lifts?|units?)"
    r"\s*(?:no\.?\s*)?[A-Za-z]?\d+(?:\.\d+)?\b|\b\d+(?:st|nd|rd|th)\b",
    re.I,
)


def numbers_in(
    text: str,
    ids: Optional["re.Pattern[str]"] = None,
    mask_labels: bool = False,
    echo: Sequence[str] = (),
) -> Tuple[Set[int], Set[Decimal]]:
    """(whole numbers incl. number words, every numeric token incl. decimals) in ``text``.

    ``mask_labels`` drops 'floor 1' / 'Level 3' / '2nd', and ``echo`` drops phrases that repeat
    the question ('4-hourly'); both are for reading a COUNT, where the number in the place the
    question named ('8 items on floor 1') must not pass for the number asked ('1').
    """
    t = _drop_noise(text, ids)
    for phrase in echo:
        t = re.sub(re.escape(normalise(phrase)), " ", t, flags=re.I)
    if mask_labels:
        t = _LABELLED_NUMBER.sub(" ", t)
    ints: Set[int] = set()
    decs: Set[Decimal] = set()
    for m in _NUM_TOKEN.finditer(t):
        whole = m.group(2).replace(",", "")
        try:
            decs.add(Decimal(m.group(1) + whole + (m.group(3) or "")))
        except InvalidOperation:
            continue
        if not m.group(3) and not m.group(1):
            ints.add(int(whole))
    for m in _WORD_RE.finditer(t.lower()):
        if m.group(3) is not None:
            ints.add(_NUMBER_WORDS[m.group(3).lower()])
        else:
            ints.add(
                _TENS[m.group(1).lower()] + (_NUMBER_WORDS[m.group(2).lower()] if m.group(2) else 0)
            )
    decs.update(Decimal(i) for i in ints)
    return ints, decs


def value_present(
    value: str,
    answer: str,
    ids: Optional["re.Pattern[str]"] = None,
    exclude: Sequence[str] = (),
) -> bool:
    """Is the cell ``value`` in ``answer``? Dates in any format, numbers as tokens, text loosely.

    ``exclude`` lists phrases that only echo the question (the record's name or id): a value
    that appears solely inside them ('pump' inside 'Zeta pump') is not an answer.
    """
    v = value.strip()
    if not v:
        return True
    echoes = [normalise(p) for p in exclude if plain(p)]
    bare = normalise(answer)
    for phrase in echoes:
        bare = re.sub(re.escape(phrase), " ", bare, flags=re.I)
    iso = _parse_iso(v)
    if iso is not None:
        return iso in dates_in(bare)
    if _NUM.match(v):
        # 'Level 1 Atrium' in the question must not answer "how many seated rests: 1".
        return Decimal(v) in numbers_in(bare, ids)[1]
    pa = f" {plain(answer)} "
    pv = plain(v)
    for phrase in exclude:
        p = plain(phrase)
        # Only a phrase that CONTAINS the value can hide it ('pump' inside 'Zeta pump'). One the
        # value contains ('Emergency Planning' inside 'Emergency Planning Officer') is left alone.
        if p and pv and pv != p and f" {pv} " in f" {p} ":
            pa = pa.replace(f" {p} ", " ")
        elif p and pv == p:  # the value IS the record's name: it must appear beyond the echo
            pa = pa.replace(f" {p} ", " ", 1)
    if not pv:
        return True
    if f" {pv} " in pa:
        return True
    parts = [p for p in re.split(r"[,;/]", v) if plain(p)]
    if 1 < len(parts) <= 6 and all(f" {plain(p)} " in pa for p in parts):
        return True
    toks = [t for t in pv.split() if t not in _STOP]
    if len(toks) >= 3:
        # the loose match must not be satisfied by the question's own words either
        have = set(plain(bare).split())
        return sum(1 for t in toks if t in have) / len(toks) >= 0.8
    return False


_STOP = {"the", "a", "an", "of", "and", "in", "on", "at", "to", "for", "by", "or", "is"}


# ---------------------------------------------------------------------------------------------
# Reading an answer: absence claims and declines
# ---------------------------------------------------------------------------------------------

_VERBS = (  # after "does not" / "do not" / "did not"
    r"record|contain|hold|store|include|carry|track|list|capture|specify|provide|have|show|give|"
    r"state|mention|keep|expose|cover|capture|describe"
)
_PARTICIPLES = (  # after "is not" / "are not" / "has not been" ...
    r"recorded|contained|held|stored|included|carried|tracked|listed|captured|specified|provided|"
    r"shown|given|stated|mentioned|kept|exposed|covered|described|available|present|found"
)
# An ABSENCE is a claim about the data: "the register does not record X", "there is no X field".
# A refusal ("I cannot say", "I couldn't find") is a different thing and lives in _DECLINE.
_ABSENCE = re.compile(
    "|".join(
        [
            rf"\b(?:does|do|did)(?:\s+not|n't)\s+(?:\w+\s+){{0,2}}?(?:{_VERBS})\b",
            rf"\b(?:is|are|was|were|has|have|had)(?:\s+not|n't)\s+(?:been\s+)?(?:{_PARTICIPLES})\b",
            r"\b(?:there\s+(?:is|are)|has|have|had|with)\s+no\b",
            r"\bno\s+(?:\w+\s+){0,3}?(?:field|column|property|attribute|data|information|details)\b",
            r"\bnot\s+(?:been\s+)?(?:recorded|stored|held|tracked|captured|listed|available|provided|specified|included|given)\b",
            r"\bonly\s+(?:records?|holds?|contains?|stores?|tracks?|lists?)\b",
            r"\bnone\s+(?:is\s+|are\s+)?recorded\b",
            r"\bno\s+(?:\w+\s+){0,3}?recorded\b",
            r"\blacks?\b",
        ]
    ),
    re.I,
)
_STRUCTURAL = re.compile(r"\b(?:fields?|columns?|propert(?:y|ies)|attributes?)\b", re.I)
_ROW_LEVEL = re.compile(r"(?:with|has|have|had)\s+no\b", re.I)
# "no OTHER assets are overdue", "no evidence FOR IT", "an EMPTY evidence field": true statements
# that follow the right facts, not a claim that the register lacks the column or the records.
_BEYOND = re.compile(
    r"\b(?:other|others|else|remaining|further|additional|besides|apart|rest|otherwise)\b", re.I
)
_SCOPED = re.compile(
    r"\bfor\s+(?:it|this|that|them|these|those|its)\b|\b(?:empty|blank)\s+(?:\w+\s+){0,3}(?:field|column)\b",
    re.I,
)
_REGISTER_SUBJECT = re.compile(
    r"\b(?:register|registers|building|system|data|dataset|model|ontology|documents?|table|"
    r"catalogue|information)\b",
    re.I,
)
# Quoted phrases: double quotes, and single quotes that are not apostrophes in a contraction.
_QUOTED = re.compile(r"\"([^\"]{2,40})\"|(?<!\w)'([^']{2,40})'(?!\w)")
_DECLINE = re.compile(
    "|".join(
        [
            r"\bi\s+(?:could\s*n[o']?t|can\s*n[o']?t|cannot|was\s+not\s+able\s+to|am\s+unable\s+to|do\s*n[o']?t\s+have|did\s*n[o']?t\s+find|did\s+not\s+find)\b",
            r"\b(?:cannot|can\s+not|can't|unable\s+to|not\s+able\s+to)\s+(?:\w+\s+){0,2}?(?:determine|say|tell|find|identify|confirm|establish|answer|see|locate|provide|work\s+out|list)\b",
            r"\bno\s+(?:relevant\s+|matching\s+|such\s+)?(?:information|data|records?|entries|results?|matches)\s+(?:found|available|recorded|were|was|in|for|about)\b",
            r"\b(?:not\s+enough|insufficient)\s+(?:information|data)\b",
            r"\bunable\s+to\s+(?:find|answer|determine|provide|locate)\b",
            r"\bnot\s+(?:able|possible)\s+to\b",
            r"\bi\s+understood\s+the\s+question\b",
            r"\bdocuments?\s+(?:do|does)\s*(?:n[o']?t|not)\s+(?:answer|contain|cover)\b",
            r"\bnothing\s+(?:relevant|about|matching)\b",
        ]
    ),
    re.I,
)
_NONE_LEAD = re.compile(
    r"^[\W_]*(?:no|none|nope|zero|nothing|not\s+any)\b|"
    r"\bthere\s+(?:are|is)\s+(?:no|none|zero)\b|\b(?:are|is)\s+none\b|\bnone\s+of\b|"
    r"\bnot\s+any\b|\bzero\b|(?<![\w.])0(?![\w.])",
    re.I,
)
_YES_LEAD = re.compile(r"^[\W_]*(?:yes|yep|yeah|correct|indeed)\b", re.I)
# For a question whose true answer is "none": any way of saying it, judged next to the asked value.
_NONE_SIGNAL = re.compile(
    r"\bno\b|\bnone\b|\bzero\b|\bnothing\b|\bneither\b|\bnil\b|(?<![\w.])0(?![\w.])|"
    r"\bnot\s+(?:\w+\s+){0,2}?(?:any|a)\b",
    re.I,
)


def split_sentences(text: str) -> List[str]:
    """Sentence-ish units: split on line breaks, ';' and sentence-final punctuation."""
    out: List[str] = []
    for line in normalise(text).splitlines():
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9*\-•])|;", line):
            if part.strip():
                out.append(part.strip())
    return out


_TERM_STOP = {
    "on",
    "of",
    "the",
    "ref",
    "id",
    "by",
    "at",
    "for",
    "to",
    "from",
    "is",
    "in",
    "last",
    "next",
    "test",
}
_TERM_GENERIC = {"name", "note", "notes", "date", "dates", "type", "kind", "code", "value", "role"}
_SYNONYMS: Dict[str, Tuple[str, ...]] = {
    "owner": (
        "owner",
        "owners",
        "ownership",
        "owned",
        "owns",
        "who owns",
        "responsible",
        "accountable",
    ),
    "accountable": (
        "accountable",
        "accountability",
        "responsible",
        "owner",
        "ownership",
        "who owns",
    ),
    "status": ("status", "state"),
    "state": ("status", "state"),
    "grade": ("grade",),
    "due": ("due", "due date", "deadline"),
    "tested": ("tested", "test date", "testing date"),
    "checked": ("checked", "check date"),
    "review": ("review", "reviewed", "review date"),
    "evidence": ("evidence", "evidenced", "evidence reference"),
    "floor": ("floor", "level", "storey"),
    "location": ("location", "where", "located"),
    "completed": ("completed", "completion"),
    "raised": ("raised",),
    "expires": ("expires", "expiry", "expiration"),
    "priority": ("priority",),
}


def property_terms(col: str, generic: bool = True, synonyms: bool = True) -> Set[str]:
    """Words and phrases by which an answer would refer to the column ``col``.

    With ``generic=False`` the very common column words ('name', 'date', 'type', 'kind', ...)
    are left out, so that an unrelated 'no date' in a sentence does not match every register;
    with ``synonyms=False`` only the column's own words count (the asked column gets synonyms,
    a column nobody asked about does not, or 'state' would match every 'status' column).
    """
    low = re.sub(r"[_\s]+", " ", str(col).lower()).strip()
    terms: Set[str] = {low, low.replace(" ref", " reference")}
    for tok in low.split():
        if tok in _TERM_STOP:
            continue
        if not generic and tok in _TERM_GENERIC:
            continue
        terms.add(tok)
        if synonyms:
            terms.update(_SYNONYMS.get(tok, ()))
    return {t for t in terms if t}


def _has(win_plain: str, terms: Iterable[str]) -> bool:
    hay = f" {win_plain} "
    for t in terms:
        p = plain(t)
        if p and (f" {p} " in hay or f" {p}s " in hay):
            return True
    return False


def noun_terms(noun: str) -> Set[str]:
    """The register noun in plural and a naive singular ('fire safety assets' -> ... 'asset')."""
    n = plain(noun)
    out = {n}
    if n.endswith("ies"):
        out.add(n[:-3] + "y")
    elif n.endswith("s"):
        out.add(n[:-1])
    return out


def _entry_value_terms(entry: Dict[str, Any]) -> Set[str]:
    terms: Set[str] = set()
    for v in (entry.get("filters") or {}).values():
        if v and str(v).lower() not in _NONE_LIKE:
            terms.add(str(v))
    return terms


#: A sentence that opens with a count of the register's rows ("6 of the 16 records ...").
_COUNT_OF_ROWS = re.compile(r"\W*\d+\s+of\s+the\s+\d+\s+(?:records|rows|entries)\b", re.IGNORECASE)


def false_absence_hits(
    entry: Dict[str, Any], reg: Optional[Register], text: str, facts_any: bool = False
) -> List[str]:
    """Sentences that claim something absent which the table holds (the evidence, verbatim).

    A claim counts only if what it says is missing is (a) a field or column the register has,
    (b) the very property the question asked about, (c) the asked status/kind value while
    records of that value exist, (d) the register's own records, or (e) 'the data' at large
    while the answer gives none of the facts. A per-record 'none recorded' inside a table row,
    a count of rows that lack something ('2 have no evidence'), a quoted value the register does
    not hold, or a column the question did not ask about, is not a claim about the register.
    """
    ex = entry.get("expected") or {}
    zero = ex.get("mode") == "none"
    tpl = entry.get("template", "")
    blank = tpl == "blank_field"  # "which have no X": saying that some rows lack X is the answer
    prop = ex.get("property") or ""
    asked = property_terms(prop) if prop else set()
    other: Set[str] = set()
    nouns: Set[str] = set()
    known: Set[str] = set()
    header_plain: Set[str] = set()
    idre: Optional["re.Pattern[str]"] = None
    if reg is not None:
        for h in reg.headers:
            other |= property_terms(h, generic=False, synonyms=False)
        nouns = noun_terms(reg.noun)
        known |= {plain(v) for v in _groups(reg, reg.status_col)}
        header_plain = {plain(h) for h in reg.headers}
        idre = id_regex(reg.ids)
    values = _entry_value_terms(entry)
    known |= {plain(v) for v in values}
    # A category called "property damage" is a value, not the word "property" used as a noun.
    words_in_values = set(values)
    if reg is not None:
        for col in [*reg.kind_cols, reg.status_col]:
            words_in_values |= set(_groups(reg, col))
    struct_values = sorted(
        (v for v in words_in_values if _STRUCTURAL.search(v)), key=len, reverse=True
    )
    struct_mask = (
        re.compile("|".join(re.escape(normalise(v)) for v in struct_values), re.I)
        if struct_values
        else None
    )
    header_words = sorted(
        {re.sub(r"[_\s]+", " ", h).strip() for h in (reg.headers if reg else [])},
        key=len,
        reverse=True,
    )
    header_mask = (
        re.compile("|".join(re.escape(h) for h in header_words if h), re.I)
        if header_words
        else None
    )
    hits: List[str] = []
    for sent in split_sentences(text):
        if sent.startswith("|"):
            continue
        for m in _ABSENCE.finditer(sent):
            pre, post = sent[max(0, m.start() - 40) : m.start()], sent[m.end() : m.end() + 80]
            around = pre + m.group(0) + post
            win = plain(around)
            # 'no "overdue" state' is about a QUOTED value the register does not hold: a true
            # absence, and not the property the question asked about.
            quoted = [plain(a or b) for a, b in _QUOTED.findall(around)]
            if any(q and q not in known and q not in header_plain for q in quoted):
                continue
            structural = bool(
                _STRUCTURAL.search(struct_mask.sub(" ", around) if struct_mask else around)
            )
            row_level = bool(_ROW_LEVEL.match(m.group(0))) and not _REGISTER_SUBJECT.search(around)
            near_value = _has(plain(pre[-25:] + m.group(0) + post), values)
            # "No OTHER records are overdue" / "...for it" / "an empty evidence field" are true
            # statements made after the right facts, and a sentence naming a record or a date is
            # about that record: none of them says the register lacks something.
            # (column names are masked first: "remaining life years" is a column, not "the remaining")
            beyond = bool(_BEYOND.search(header_mask.sub(" ", sent) if header_mask else sent))
            scoped = bool(_SCOPED.search(around))
            about_a_record = bool(dates_in(sent)) or bool(idre is not None and idre.search(sent))
            # "It only records X" asserts X is there: only its blanket form (nothing answered,
            # and the data is said to hold something else) can be a false absence.
            only = m.group(0).lower().startswith("only")
            if beyond:
                continue
            # "6 of the 16 records in the Accessible route register have no lift status - the field
            # is empty on each of them:" IS the answer to "which have no lift status", and the
            # colon introduces the list. The grader read its "field is empty" as the register
            # lacking the field (four correct answers scored FALSE_ABSENCE on 2026-09-20).
            if blank and _COUNT_OF_ROWS.match(sent):
                continue
            if only:
                if not facts_any:
                    hits.append(sent)
                    break
                continue
            if structural and not scoped and _has(win, other | asked):
                hits.append(sent)
            elif row_level:
                continue
            elif not zero and not blank and asked and not scoped and _has(win, asked):
                hits.append(sent)
            elif about_a_record:
                continue
            elif not zero and not blank and near_value:
                hits.append(sent)
            elif not blank and _has(plain(post[:45]), nouns) and not (zero and near_value):
                hits.append(sent)
            elif not facts_any and _REGISTER_SUBJECT.search(around) and not (zero and near_value):
                hits.append(sent)
            else:
                continue
            break
    return hits


# ---------------------------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------------------------

REASON_ORDER = (
    "NO_ANSWER",
    "FALSE_ABSENCE",
    "DECLINED",
    "WRONG_NONE",
    "WRONG_COUNT",
    "MISSING_IDS",
    "MISSING_VALUES",
    "MISSING_NONE",
    "INVENTED_IDS",
    "EXTRA_IDS",
)


def _canon_map(reg: Optional[Register]) -> Dict[Tuple[Any, ...], str]:
    return {id_tokens(i): i for i in reg.ids} if reg else {}


def score_answer(
    entry: Dict[str, Any],
    answer: str,
    reg: Optional[Register],
    status: str = "OK",
    strict_extra: bool = False,
) -> Dict[str, Any]:
    """Score one answer against one oracle entry: pass/fail, the reasons, and the evidence."""
    ex = entry.get("expected") or {}
    mode = ex.get("mode", "count")
    out: Dict[str, Any] = {"pass": False, "reasons": [], "warnings": [], "evidence": {}}
    text = normalise(answer or "")
    if not text.strip() or (status and status not in ("OK", "EMPTY_OK")):
        out["reasons"] = ["NO_ANSWER"]
        out["evidence"]["status"] = status
        return out
    canon = _canon_map(reg)
    idre = id_regex(reg.ids) if reg else None
    echoed = [
        str(v)
        for v in (entry.get("filters") or {}).values()
        if len(str(v)) >= 2 and any(ch.isdigit() for ch in str(v))
    ]
    ints, _decs = numbers_in(text, idre, mask_labels=True, echo=echoed)
    raw_ids = [m.group(0) for m in idre.finditer(text)] if idre else []
    mentioned: Set[str] = {canon[c] for c in map(id_tokens, raw_ids) if c in canon}
    invented = sorted({r for r in raw_ids if id_tokens(r) not in canon})
    if reg is not None and reg.name_col:
        plain_text = f" {plain(text)} "
        for row in reg.rows:
            nm = plain(row[reg.name_col])
            if nm and (len(nm.split()) >= 2 or len(nm) >= 8) and f" {nm} " in plain_text:
                mentioned.add(row[reg.id_col])
    exp_ids: List[str] = list(ex.get("ids") or [])
    exp_count = ex.get("count")
    count_found = exp_count is not None and int(exp_count) in ints
    ids_found = [i for i in exp_ids if i in mentioned]
    missing_ids = [i for i in exp_ids if i not in mentioned]
    values = [str(v) for v in (ex.get("values") or [])]
    slots = entry.get("slots") or {}
    echo = [
        re.sub(r"^the\s+", "", str(slots.get("rec") or ""), flags=re.I),
        str(slots.get("rec_id") or ""),
    ]
    missing_values = [v for v in values if not value_present(v, text, idre, echo)]
    lead_none = bool(_NONE_LEAD.search(split_sentences(text)[0] if split_sentences(text) else ""))
    facts_any = False
    reasons: List[str] = []

    if mode == "count":
        facts_any = count_found or bool(ids_found)
        # Listing exactly the right records without saying the number still answers "how many":
        # the count is there to be read off, so it passes with a warning rather than failing.
        implicit = bool(exp_ids) and mentioned == set(exp_ids)
        if implicit and not count_found:
            out["warnings"].append("COUNT_IMPLICIT")
        elif not count_found:
            reasons.append("WRONG_COUNT")
    elif mode == "ids":
        facts_any = bool(ids_found)
        if missing_ids:
            reasons.append("MISSING_IDS")
    elif mode == "values":
        facts_any = len(missing_values) < len(values)
        if missing_values:
            reasons.append("MISSING_VALUES")
    elif mode == "yes":
        supported = count_found or bool(ids_found) or bool(_YES_LEAD.search(text))
        facts_any = supported
        if not supported:
            reasons.append("MISSING_IDS")
    elif mode == "none":
        terms = {plain(v) for v in _entry_value_terms(entry)}
        near = any(
            _NONE_SIGNAL.search(s)
            and not _DECLINE.search(s)
            and (not terms or _has(plain(s), terms))
            for s in split_sentences(text)
        )
        facts_any = near or lead_none
        if not (near or (lead_none and not _DECLINE.search(text))):
            reasons.append("MISSING_NONE")

    absence = false_absence_hits(entry, reg, text, facts_any)
    if absence:
        reasons.insert(0, "FALSE_ABSENCE")
        out["evidence"]["false_absence"] = absence[:3]
    # A decline is an answer that refuses the whole question: an explicit refusal, or a short
    # answer that is nothing but an absence claim and names no record.
    blanket = bool(_ABSENCE.search(text)) and not mentioned and len(words_of(text)) < 60
    declined = bool(_DECLINE.search(text)) or blanket
    if mode in ("count", "ids", "yes") and lead_none and not facts_any:
        reasons.append("WRONG_NONE")  # "There are none", when records of that value exist
    elif declined and not facts_any:
        reasons.append("DECLINED")  # includes a decline where the true answer is "none"
    if invented:
        reasons.append("INVENTED_IDS")
        out["evidence"]["invented_ids"] = invented
    extra = sorted(mentioned - set(exp_ids)) if exp_ids and mode in ("count", "ids", "yes") else []
    if extra:
        (reasons if strict_extra else out["warnings"]).append("EXTRA_IDS")
        out["evidence"]["extra_ids"] = extra[:10]
    if missing_ids and (mode in ("ids", "yes") or "WRONG_COUNT" in reasons):
        out["evidence"]["missing_ids"] = missing_ids[:20]
    if missing_values:
        out["evidence"]["missing_values"] = missing_values[:10]
    if mode == "count" and not count_found:
        out["evidence"]["expected_count"] = exp_count
    out["reasons"] = sorted(set(reasons), key=REASON_ORDER.index)
    out["pass"] = not out["reasons"]
    return out


# ---------------------------------------------------------------------------------------------
# Generation: questions and their expected facts
# ---------------------------------------------------------------------------------------------

_DATE_STEMS: Dict[str, Tuple[str, str]] = {
    "next_test_due": ("when_next_due", "When is {rec} next due for testing?"),
    "next_due": ("when_next_due", "When is {rec} next due?"),
    "next_collection": ("when_next_due", "When is {rec} next collected?"),
    "review_due": ("when_review", "When is {rec} due for review?"),
    "last_tested_on": ("when_last_done", "When was {rec} last tested?"),
    "last_tested": ("when_last_done", "When was {rec} last tested?"),
    "last_checked": ("when_last_done", "When was {rec} last checked?"),
    "last_done": ("when_last_done", "When was {rec} last done?"),
    "last_completed": ("when_last_done", "When was {rec} last completed?"),
    "last_proved_on": ("when_last_done", "When was {rec} last proved?"),
    "last_visited": ("when_last_done", "When was {rec} last visited?"),
    "last_verified": ("when_last_done", "When was {rec} last verified?"),
}
_OTHER_DATE_STEMS: Dict[str, str] = {
    "raised_on": "When was {rec} raised?",
    "completed_on": "When was {rec} completed?",
    "approved_on": "When was {rec} approved?",
    "occurred_on": "When did {rec} occur?",
    "closed_on": "When was {rec} closed?",
    "surveyed_on": "When was {rec} surveyed?",
    "surveyed": "When was {rec} surveyed?",
    "assessed": "When was {rec} assessed?",
    "issued": "When was {rec} issued?",
    "expires": "When does {rec} expire?",
    "valid_until": "Until when is {rec} valid?",
    "valid_from": "From when is {rec} valid?",
    "start": "When does {rec} start?",
    "end": "When does {rec} end?",
    "session_date": "On what date is {rec}?",
}
_ADJECTIVE = re.compile(r"(ed|ing|ent|able|ible|ive|al|due|full|open|ready|void|wn|held)$")
_PLACE_FACETS = {"room", "zone", "venue", "location"}
_TEMPLATES = (
    "count_status",
    "list_status",
    "count_facet_status",
    "list_facet_status",
    "owner_facet",
    "owner_record",
    "when_next_due",
    "when_last_done",
    "when_review",
    "blank_field",
    "field_of_record",
    "any_exists",
    "count_facet",
    "count_total",
)
_MAX_PER_BUCKET = 40


def human_label(col: str) -> str:
    """'evidence_ref' -> 'evidence reference'; 'last_tested_on' -> 'last tested'."""
    low = re.sub(r"[_\s]+", " ", str(col).strip().lower())
    low = re.sub(r"\bref\b", "reference", low)
    return re.sub(r"\s+on$", "", low)


def date_label(col: str) -> str:
    """A column of dates as a noun: 'valid_from' -> 'valid from date'."""
    label = human_label(col)
    return label if label.endswith("date") else f"{label} date"


def facet_phrase(col: str, value: str) -> str:
    """How a facet reads inside a noun phrase: 'on floor 3', 'of kind alarm', 'with trade X'."""
    low = col.strip().lower()
    if low == "floor":
        return f"on floor {value}"
    if low in ("kind", "type", "category") or low.endswith("_kind"):
        return f"of {human_label(col)} {value}"
    if low in _PLACE_FACETS:
        return f"in {value}"
    return f"with {human_label(col)} {value}"


def status_phrase(reg: Register, value: str) -> Dict[str, str]:
    """The predicate for a status: {'pl': 'are overdue', 'any': 'Are any {np} overdue?'}."""
    label = human_label(reg.status_col)
    low = value.lower()
    if label == "grade":
        return {"pl": f"have grade {value}", "any": f"Do any {{np}} have grade {value}?"}
    if re.fullmatch(r"[A-Za-z ]+", value) and _ADJECTIVE.search(low):
        return {"pl": f"are {low}", "any": f"Are any {{np}} {low}?"}
    return {
        "pl": f"have the {label} '{value}'",
        "any": f"Do any {{np}} have the {label} '{value}'?",
    }


@dataclass
class Cand:
    """One question waiting to be worded: what it asks and what the table says."""

    register: str
    template: str
    slots: Dict[str, Any]
    expected: Dict[str, Any]
    filters: Dict[str, str] = field(default_factory=dict)


def _groups(reg: Register, col: str) -> "OrderedDict[str, List[int]]":
    out: "OrderedDict[str, List[int]]" = OrderedDict()
    for i, row in enumerate(reg.rows):
        v = row[col]
        if v:
            out.setdefault(v, []).append(i)
    return out


def _ids(reg: Register, idx: Iterable[int]) -> List[str]:
    return [reg.rows[i][reg.id_col] for i in idx]


def _status_groups(reg: Register) -> "OrderedDict[str, List[int]]":
    g = _groups(reg, reg.status_col)
    return OrderedDict((k, v) for k, v in g.items() if k.lower() not in _NONE_LIKE)


def _facets(reg: Register) -> List[Tuple[str, str, List[int]]]:
    out: List[Tuple[str, str, List[int]]] = []
    for col in reg.kind_cols:
        for val, idx in _groups(reg, col).items():
            out.append((col, val, idx))
    return out


def _np(reg: Register, col: Optional[str] = None, val: Optional[str] = None) -> str:
    return reg.noun if col is None else f"{reg.noun} {facet_phrase(col, str(val))}"


def _rec_ref(reg: Register, i: int, rng: random.Random) -> Tuple[str, str]:
    """(how the question names the record, 'id' or 'name')."""
    row = reg.rows[i]
    # A summary is a sentence ("Delivery vehicle blocked the route"), not a name to put after "the".
    if reg.name_col and reg.name_col.lower() != "summary" and rng.random() < 0.5:
        name = row[reg.name_col]
        if 0 < len(name) <= 60:
            return f"the {name}", "name"
    return row[reg.id_col], "id"


def _expected(
    mode: str,
    count: Optional[int] = None,
    ids: Optional[List[str]] = None,
    values: Optional[List[str]] = None,
    prop: Optional[str] = None,
) -> Dict[str, Any]:
    return {"mode": mode, "count": count, "ids": ids, "values": values or [], "property": prop}


def enumerate_candidates(reg: Register, seed: int) -> Dict[str, List[Cand]]:
    """Every question the register supports, by template, in a seeded (stable) order."""
    rng = random.Random(f"{seed}:{reg.key}")
    out: Dict[str, List[Cand]] = {t: [] for t in _TEMPLATES}
    n = len(reg.rows)
    statuses = _status_groups(reg)
    facets = _facets(reg)

    def cand(tpl: str, slots: Dict[str, Any], exp: Dict[str, Any], flt: Dict[str, str]) -> None:
        out[tpl].append(Cand(reg.key, tpl, slots, exp, flt))

    for s, idx in statuses.items():
        ph = status_phrase(reg, s)
        slots = {"np": _np(reg), "pred": ph["pl"], "any_q": ph["any"], "status": s}
        ids = _ids(reg, idx) if len(idx) <= 40 else None
        cand(
            "count_status",
            slots,
            _expected("count", len(idx), ids, None, reg.status_col),
            {"status": s},
        )
        if 1 <= len(idx) <= MAX_LIST_IDS:
            cand(
                "list_status",
                slots,
                _expected("ids", len(idx), ids, None, reg.status_col),
                {"status": s},
            )
    for col, val, fidx in facets:
        np_ = _np(reg, col, val)
        for s, sidx in statuses.items():
            sset = set(sidx)
            both = [i for i in fidx if i in sset]
            ph = status_phrase(reg, s)
            slots = {
                "np": np_,
                "pred": ph["pl"],
                "any_q": ph["any"],
                "status": s,
                "facet": {"col": col, "value": val},
            }
            flt = {"status": s, col: val}
            if both:
                ids = _ids(reg, both)
                cand(
                    "count_facet_status",
                    slots,
                    _expected(
                        "count", len(both), ids if len(both) <= 40 else None, None, reg.status_col
                    ),
                    flt,
                )
                if len(both) <= MAX_LIST_IDS:
                    cand(
                        "list_facet_status",
                        slots,
                        _expected("ids", len(both), ids, None, reg.status_col),
                        flt,
                    )
                cand(
                    "any_exists",
                    slots,
                    _expected(
                        "yes", len(both), ids if len(both) <= 40 else None, None, reg.status_col
                    ),
                    flt,
                )
            else:
                cand("any_exists", slots, _expected("none", 0, [], None, reg.status_col), flt)
        slots = {"np": np_, "facet": {"col": col, "value": val}}
        cand(
            "count_facet",
            slots,
            _expected("count", len(fidx), _ids(reg, fidx) if len(fidx) <= 40 else None, None, col),
            {col: val},
        )
        if reg.owner_col:
            owners = list(
                OrderedDict.fromkeys(
                    reg.rows[i][reg.owner_col] for i in fidx if reg.rows[i][reg.owner_col]
                )
            )
            if 1 <= len(owners) <= MAX_OWNER_VALUES:
                cand(
                    "owner_facet",
                    slots,
                    _expected("values", None, _ids(reg, fidx), owners, reg.owner_col),
                    {col: val},
                )
    for s, sidx in statuses.items():  # status-level "are any": the yes case
        ph = status_phrase(reg, s)
        if not facets:
            slots = {"np": _np(reg), "pred": ph["pl"], "any_q": ph["any"], "status": s}
            cand(
                "any_exists",
                slots,
                _expected(
                    "yes",
                    len(sidx),
                    _ids(reg, sidx) if len(sidx) <= 40 else None,
                    None,
                    reg.status_col,
                ),
                {"status": s},
            )
    for i, row in enumerate(reg.rows):
        rec, how = _rec_ref(reg, i, rng)
        base = {"rec": rec, "rec_how": how, "rec_id": row[reg.id_col]}
        if reg.owner_col and row[reg.owner_col]:
            cand(
                "owner_record",
                dict(base),
                _expected("values", None, [row[reg.id_col]], [row[reg.owner_col]], reg.owner_col),
                {},
            )
        for col in reg.date_cols:
            if not row[col]:
                continue
            if col in _DATE_STEMS:
                tpl, stem = _DATE_STEMS[col]
                cand(
                    tpl,
                    dict(base, stem=stem, col=col),
                    _expected("values", None, [row[reg.id_col]], [row[col]], col),
                    {},
                )
        # A generic "what is the <field> of <record>": one random column per record, so a
        # 675-row register does not swamp the pool.
        cols = [
            h
            for h in reg.headers
            if h != reg.id_col
            and row[h]
            and len(row[h]) <= MAX_VALUE_CHARS
            and h.strip().lower() not in _NOTE_HEADERS
            and row[h].lower() not in _BOOLEAN_VALUES
            and not (how == "name" and h == reg.name_col)
        ]
        if cols:
            col = rng.choice(cols)
            if col in _DATE_STEMS:
                stem = _DATE_STEMS[col][1]
            elif col in _OTHER_DATE_STEMS:
                stem = _OTHER_DATE_STEMS[col]
            elif col in reg.date_cols:
                stem = "What is the " + date_label(col) + " of {rec}?"
            elif re.search(r"(minutes|hours|years|litres|days)$", human_label(col)):
                stem = "What are the " + human_label(col) + " for {rec}?"
            elif human_label(col).endswith("seats"):
                stem = "How many seats does {rec} have?"
            else:
                stem = "What is the " + human_label(col) + " of {rec}?"
            cand(
                "field_of_record",
                dict(base, stem=stem, col=col),
                _expected("values", None, [row[reg.id_col]], [row[col]], col),
                {},
            )
    for col in reg.headers:
        low = col.strip().lower()
        if col in (reg.id_col, reg.status_col) or low in _NOTE_HEADERS:
            continue
        blanks = [i for i, r in enumerate(reg.rows) if not r[col]]
        # Blank in at most half the rows: a column that is empty nearly everywhere records
        # "not applicable", and "which have no X" is then not a question anyone asks.
        if 1 <= len(blanks) <= MAX_LIST_IDS and len(blanks) * 2 <= n:
            slots = {"np": _np(reg), "label": human_label(col), "col": col}
            cand(
                "blank_field",
                slots,
                _expected("ids", len(blanks), _ids(reg, blanks), None, col),
                {},
            )
    cand(
        "count_total",
        {"np": _np(reg)},
        _expected("count", n, _ids(reg, range(n)) if n <= 40 else None, None, None),
        {},
    )
    for tpl in out:
        rng.shuffle(out[tpl])
        del out[tpl][_MAX_PER_BUCKET:]
    return out


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text and not text[:2].isupper() else text


def _wrap(persona: str, q: str) -> str:
    if persona == "occupant":
        return "Could you tell me: " + _lower_first(q)
    if persona == "auditor":
        return "For the audit record: " + q
    if persona == "executive":
        return "Briefly: " + q
    if persona == "student":
        return "For my notes: " + q
    return q


_WORDING: Dict[str, Dict[str, str]] = {
    "count": {
        "facility_manager": "How many {np} {pred}?",
        "occupant": "Can you tell me how many {np} {pred}?",
        "auditor": "For the audit record, how many {np} {pred}?",
        "executive": "Give me the headline number: how many {np} {pred}?",
        "student": "I'm writing a report on this building. How many {np} {pred}?",
    },
    "list": {
        "facility_manager": "Which {np} {pred}?",
        "occupant": "Could you list the {np} that {pred}?",
        "auditor": "List every one of the {np} that {pred}, giving each reference.",
        "executive": "Which {np} {pred}? Just the references, please.",
        "student": "For my notes, which {np} {pred}? Please give the ids.",
    },
    "owner_group": {
        "facility_manager": "Who owns the {np}?",
        "occupant": "Who is in charge of the {np}?",
        "auditor": "Who is the recorded owner of the {np}?",
        "executive": "Who is accountable for the {np}?",
        "student": "Which role owns the {np}?",
    },
    "owner_rec": {
        "facility_manager": "Who owns {rec}?",
        "occupant": "Who is in charge of {rec}?",
        "auditor": "Who is the recorded owner of {rec}?",
        "executive": "Who is accountable for {rec}?",
        "student": "Which role owns {rec}?",
    },
}


def render_question(c: Cand, persona: str) -> str:
    """Word ``c`` for one persona. The five wordings ask for the same facts."""
    s, t = c.slots, c.template
    if t in ("count_status", "count_facet_status"):
        return _WORDING["count"][persona].format(np=s["np"], pred=s["pred"])
    if t in ("list_status", "list_facet_status"):
        return _WORDING["list"][persona].format(np=s["np"], pred=s["pred"])
    if t == "owner_facet":
        return _WORDING["owner_group"][persona].format(np=s["np"])
    if t == "owner_record":
        return _WORDING["owner_rec"][persona].format(rec=s["rec"])
    if t in ("when_next_due", "when_last_done", "when_review", "field_of_record"):
        return _wrap(persona, s["stem"].format(rec=s["rec"]))
    if t == "blank_field":
        return _wrap(persona, f"Which {s['np']} have no {s['label']} recorded?")
    if t == "any_exists":
        return _wrap(persona, s["any_q"].format(np=s["np"]))
    if t == "count_facet":
        return _wrap(persona, f"How many {s['np']} are there in total?")
    if t == "count_total":
        return _wrap(persona, f"How many {s['np']} are recorded in total?")
    raise ValueError(f"no wording for template {t}")


def generate(
    regs: "OrderedDict[str, Register]",
    n: int = 250,
    seed: int = 1,
    only: Optional[Sequence[str]] = None,
    weights: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """``n`` oracle entries, balanced across registers, then templates, then personas.

    ``weights`` (register key or noun -> number) tilts the register balance towards the
    registers people ask about most; the default is an even share for every register.
    """
    chosen = [k for k in regs if not only or any(k == o or k.startswith(o) for o in only)]

    def weight(k: str) -> float:
        w = weights or {}
        w = w.get(k) or w.get(regs[k].noun) or w.get("_default") or 1.0
        return max(float(w), 1e-9)

    pools: Dict[str, Dict[str, List[Cand]]] = {
        k: enumerate_candidates(regs[k], seed) for k in chosen
    }
    rng = random.Random(f"{seed}:sample")
    use_reg: Counter = Counter()
    use_tpl: Counter = Counter()
    use_reg_tpl: Counter = Counter()
    use_persona: Counter = Counter()
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    while len(out) < n:
        live = [k for k in chosen if any(pools[k].values())]
        if not live:
            break
        key = min(live, key=lambda k: (use_reg[k] / weight(k), rng.random()))
        tpls = [t for t, lst in pools[key].items() if lst]
        tpl = min(tpls, key=lambda t: (use_tpl[t], use_reg_tpl[(key, t)], rng.random()))
        c = pools[key][tpl].pop(0)
        persona = min(PERSONAS, key=lambda p: (use_persona[p], rng.random()))
        q = render_question(c, persona)
        if q in seen:
            continue
        seen.add(q)
        use_reg[key] += 1
        use_tpl[tpl] += 1
        use_reg_tpl[(key, tpl)] += 1
        use_persona[persona] += 1
        out.append(
            {
                "id": f"RO-{len(out) + 1:04d}",
                "question": q,
                "register": key,
                "template": tpl,
                "persona": persona,
                "expected": c.expected,
                "filters": c.filters,
                "slots": c.slots,
                "source": {"file": regs[key].file, "sha1": regs[key].sha1},
            }
        )
    return out


def write_oracle(rows: List[Dict[str, Any]], prefix: Path) -> Tuple[Path, Path]:
    """``prefix``.jsonl (the oracle) and ``prefix``.txt (one question per line)."""
    prefix.parent.mkdir(parents=True, exist_ok=True)
    jl, tx = Path(f"{prefix}.jsonl"), Path(f"{prefix}.txt")
    jl.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tx.write_text("".join(r["question"] + "\n" for r in rows), encoding="utf-8")
    return jl, tx


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Every JSON object in a .jsonl file (blank and unparseable lines skipped)."""
    rows: List[Dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


# ---------------------------------------------------------------------------------------------
# The checker's own test: ground-truth phrasing must pass, each corruption must fail rightly
# ---------------------------------------------------------------------------------------------

_MONTH_NAMES = (
    "January February March April May June July August September October November December"
).split()


def fmt_date(iso: str, style: int) -> str:
    """An ISO date written one of five ways, as answers write them."""
    d = _parse_iso(iso)
    if d is None:
        return iso
    mon = _MONTH_NAMES[d.month - 1]
    forms = [
        iso,
        f"{d.day} {mon[:3]} {d.year}",
        f"{mon} {d.day}, {d.year}",
        f"{d.day:02d} {mon} {d.year}",
        f"{d.day:02d}/{d.month:02d}/{d.year}",
    ]
    return forms[style % len(forms)]


def render_truth(entry: Dict[str, Any], i: int = 0) -> str:
    """The answer a correct system would give, varied by ``i`` (dashes, dates, number words)."""
    ex, s = entry["expected"], entry["slots"]
    mode = ex["mode"]
    dash = NB_HYPHEN if i % 2 else "-"
    ids = [x.replace("-", dash) for x in (ex.get("ids") or [])]
    np_, pred = s.get("np", "records"), s.get("pred", "")
    if mode == "count":
        n = int(ex["count"])
        num = number_word(n) if (i % 3 == 1 and n < 100) else str(n)
        tail = f" that {pred}" if pred else " in the register"
        text = f"There are **{num}** {np_}{tail}."
        if ids and len(ids) <= MAX_LIST_IDS:
            text += " These are " + ", ".join(ids) + "."
        return text
    if mode == "ids":
        head = (
            f"The {np_} that {pred}"
            if pred
            else f"The {np_} with no {s.get('label', 'value')} recorded"
        )
        text = head + " are:\n" + "\n".join(f"- **{x}**" for x in ids)
        if i % 2:
            text += f"\n\n{ex['count']} in total."
        return text
    if mode == "values":
        vals = [fmt_date(v, i) if _parse_iso(str(v)) else str(v) for v in ex["values"]]
        subject = s.get("rec") or f"the {np_}"
        return f"The recorded value for {subject} is " + "; ".join(vals) + "."
    if mode == "yes":
        return f"Yes. There are {ex['count']} {np_} that {pred}: " + ", ".join(ids[:12]) + "."
    return f"No. There are no {np_} that {pred}."


def mint_invented_id(reg: Register) -> str:
    """An id shaped like the register's own that the table does not contain."""
    have = {id_tokens(i) for i in reg.ids}
    base = reg.ids[0]
    runs = list(re.finditer(r"\d+", base))
    if not runs:
        return base + "-999"
    m = runs[-1]
    for value in range(9999, 0, -1):
        cand = base[: m.start()] + str(value).zfill(len(m.group(0))) + base[m.end() :]
        if id_tokens(cand) not in have:
            return cand
    return base + "-999"


CORRUPTIONS = (
    "wrong_count",
    "missing_id",
    "false_absence",
    "invented_id",
    "decline",
    "wrong_value",
    "wrong_none",
    "wrong_yes",
)


def corrupt(entry: Dict[str, Any], kind: str, reg: Register) -> Optional[Tuple[str, str]]:
    """(a wrong answer, the reason the checker must give) - or None when it does not apply."""
    ex, s = entry["expected"], entry["slots"]
    mode = ex["mode"]
    np_, pred = s.get("np", "records"), s.get("pred", "")
    tail = f" that {pred}" if pred else ""
    if kind == "wrong_count" and mode == "count":
        return f"There are {int(ex['count']) + 7} {np_}{tail}.", "WRONG_COUNT"
    if kind == "missing_id" and mode == "ids":
        keep = (ex.get("ids") or [])[:-1]
        body = ", ".join(keep) if keep else "some of them"
        return f"The {np_}{tail} include {body}.", "MISSING_IDS"
    if kind == "false_absence":
        prop = ex.get("property")
        if prop:
            return (
                f"The {reg.noun} register has no {human_label(prop)} field, so this cannot be said.",
                "FALSE_ABSENCE",
            )
        return f"The register does not contain any {np_}.", "FALSE_ABSENCE"
    if kind == "invented_id" and mode != "none":
        return render_truth(entry, 0) + f" It also lists {mint_invented_id(reg)}.", "INVENTED_IDS"
    if kind == "decline":
        want = "MISSING_NONE" if mode == "none" else "DECLINED"
        return "I couldn't find that in the building's records.", want
    if kind == "wrong_value" and mode == "values":
        return (
            f"The recorded value is Nobody Special 12345 for {s.get('rec') or np_}.",
            "MISSING_VALUES",
        )
    if kind == "wrong_none" and mode in ("yes", "ids", "count"):
        return "None.", "WRONG_NONE"
    if kind == "wrong_yes" and mode == "none":
        return "Yes, there are two such records.", "MISSING_NONE"
    return None


def selfcheck(
    regs: "OrderedDict[str, Register]", n: int = 250, seed: int = 1
) -> Tuple[bool, List[str]]:
    """Run the checker on ground truth (must be 100%) and on each corruption (must fail rightly)."""
    rows = generate(regs, n=n, seed=seed)
    lines: List[str] = [f"selfcheck: {len(rows)} oracle questions, seed {seed}"]
    ok = True
    total = good = 0
    bad_truth: List[str] = []
    for k, e in enumerate(rows):
        for style in range(3):
            ans = render_truth(e, k + style)
            sc = score_answer(e, ans, regs[e["register"]])
            total += 1
            if sc["pass"]:
                good += 1
            else:
                bad_truth.append(
                    f"  TRUTH FAILED {e['id']} {e['template']}: {sc['reasons']} :: {ans[:120]!r}"
                )
    lines.append(f"ground truth: {good}/{total} pass ({100.0 * good / max(total, 1):.1f}%)")
    ok &= good == total
    lines.extend(bad_truth[:10])
    for kind in CORRUPTIONS:
        applicable = caught = 0
        wrong: List[str] = []
        for e in rows:
            made = corrupt(e, kind, regs[e["register"]])
            if made is None:
                continue
            applicable += 1
            ans, want = made
            sc = score_answer(e, ans, regs[e["register"]])
            if not sc["pass"] and want in sc["reasons"]:
                caught += 1
            else:
                wrong.append(
                    f"  MISSED {e['id']} {e['template']} want {want} got {sc['reasons']} :: {ans[:100]!r}"
                )
        lines.append(f"corruption {kind:<14} caught {caught}/{applicable}")
        ok &= caught == applicable
        lines.extend(wrong[:6])
    lines.append("selfcheck " + ("PASSED" if ok else "FAILED"))
    return ok, lines


# ---------------------------------------------------------------------------------------------
# Scoring a run file
# ---------------------------------------------------------------------------------------------


def wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """95% Wilson score interval for k successes in n trials (0..1)."""
    if n <= 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def _qkey(q: str) -> str:
    return re.sub(r"\s+", " ", str(q or "").strip())


def score_run(
    oracle: List[Dict[str, Any]],
    run: List[Dict[str, Any]],
    regs: "OrderedDict[str, Register]",
    strict_extra: bool = False,
) -> Dict[str, Any]:
    """Join a run file to the oracle on the question text and score every answer."""
    by_q: Dict[str, Dict[str, Any]] = {_qkey(e["question"]): e for e in oracle}
    results: List[Dict[str, Any]] = []
    unmatched = 0
    asked: Set[str] = set()
    for r in run:
        e = by_q.get(_qkey(r.get("q") or r.get("question")))
        if e is None:
            unmatched += 1
            continue
        asked.add(e["id"])
        sc = score_answer(
            e,
            str(r.get("answer") or ""),
            regs.get(e["register"]),
            status=str(r.get("status") or "OK"),
            strict_extra=strict_extra,
        )
        results.append(
            {
                "entry": e,
                "run": r.get("run"),
                "secs": r.get("secs"),
                "score": sc,
                "answer": str(r.get("answer") or ""),
            }
        )
    # The expected facts were read off the register files at generation time. If a file has
    # changed since, its rows are scored against a different table than the one they came from.
    stale = sorted(
        {
            e["register"]
            for e in oracle
            if e.get("source")
            and e["register"] in regs
            and regs[e["register"]].sha1 != e["source"].get("sha1")
        }
    )
    return {
        "results": results,
        "unmatched_run_rows": unmatched,
        "not_asked": [e["id"] for e in oracle if e["id"] not in asked],
        "stale_registers": stale,
    }


def _rate_table(results: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in results:
        groups[r["entry"][key]].append(r)
    rows = []
    for name in sorted(groups):
        rs = groups[name]
        n = len(rs)
        passed = sum(1 for r in rs if r["score"]["pass"])
        rows.append(
            {
                key: name,
                "n": n,
                "pass": passed,
                "pass_rate": passed / n,
                "false_absence": sum("FALSE_ABSENCE" in r["score"]["reasons"] for r in rs),
                "declined": sum("DECLINED" in r["score"]["reasons"] for r in rs),
                "invented": sum("INVENTED_IDS" in r["score"]["reasons"] for r in rs),
            }
        )
    return rows


def summarise(scored: Dict[str, Any]) -> Dict[str, Any]:
    """Overall, per-register, per-template and per-persona rates plus defect-class rates."""
    res = scored["results"]
    n = len(res)
    passed = sum(1 for r in res if r["score"]["pass"])
    lo, hi = wilson(passed, n)
    answered = [r for r in res if "NO_ANSWER" not in r["score"]["reasons"]]
    ans_pass = sum(1 for r in answered if r["score"]["pass"])
    defects = {
        reason: sum(1 for r in res if reason in r["score"]["reasons"]) for reason in REASON_ORDER
    }
    defects["EXTRA_IDS(warning)"] = sum(1 for r in res if "EXTRA_IDS" in r["score"]["warnings"])
    return {
        "scored": n,
        "passed": passed,
        "pass_rate": passed / n if n else 0.0,
        "pass_ci95": [lo, hi],
        "answered": len(answered),
        "answered_pass_rate": ans_pass / len(answered) if answered else 0.0,
        "defects": defects,
        "defect_rates": {k: (v / n if n else 0.0) for k, v in defects.items()},
        "by_register": _rate_table(res, "register"),
        "by_template": _rate_table(res, "template"),
        "by_persona": _rate_table(res, "persona"),
        "unmatched_run_rows": scored["unmatched_run_rows"],
        "not_asked": len(scored["not_asked"]),
        "stale_registers": scored.get("stale_registers", []),
    }


def format_report(scored: Dict[str, Any], max_fails: int = 0) -> str:
    """The text report: rates first, then every failing question with its reasons."""
    sm = summarise(scored)
    L: List[str] = []
    L.append(
        f"REGISTER ORACLE  scored {sm['scored']} answers "
        f"(oracle questions not asked: {sm['not_asked']}, run rows not in the oracle: "
        f"{sm['unmatched_run_rows']})"
    )
    if sm["stale_registers"]:
        L.append(
            "WARNING: these register files changed after the oracle was generated, so their rows "
            f"may score wrongly (regenerate and re-ask): {', '.join(sm['stale_registers'])}"
        )
    lo, hi = sm["pass_ci95"]
    L.append(
        f"PASS {sm['passed']}/{sm['scored']} = {100 * sm['pass_rate']:.1f}%  "
        f"(95% CI {100 * lo:.1f}-{100 * hi:.1f}%);  of answers that arrived: "
        f"{100 * sm['answered_pass_rate']:.1f}%"
    )
    L.append("DEFECT CLASSES (share of scored answers; one answer can carry several)")
    for k, v in sm["defects"].items():
        if v or k in ("FALSE_ABSENCE", "DECLINED", "INVENTED_IDS"):
            L.append(f"  {k:<20} {v:>4}  {100 * sm['defect_rates'][k]:5.1f}%")
    for title, key in (
        ("BY REGISTER", "by_register"),
        ("BY TEMPLATE", "by_template"),
        ("BY PERSONA", "by_persona"),
    ):
        L.append(title)
        name_key = key[3:]
        L.append(
            f"  {'':<34} {'n':>4} {'pass':>5} {'pass%':>6} {'falseabs':>8} {'declined':>8} {'invented':>8}"
        )
        for r in sm[key]:
            L.append(
                f"  {r[name_key]:<34} {r['n']:>4} {r['pass']:>5} {100 * r['pass_rate']:>5.0f}% "
                f"{r['false_absence']:>8} {r['declined']:>8} {r['invented']:>8}"
            )
    fails = [r for r in scored["results"] if not r["score"]["pass"]]
    L.append(f"FAILING QUESTIONS ({len(fails)})")
    for r in fails[: max_fails or None]:
        e, sc = r["entry"], r["score"]
        L.append(f"  {e['id']} {e['register']}/{e['template']}  {','.join(sc['reasons'])}")
        L.append(f"      Q: {e['question']}")
        ev = sc["evidence"]
        if "expected_count" in ev:
            L.append(f"      expected count {ev['expected_count']}")
        for k in ("missing_ids", "missing_values", "invented_ids", "extra_ids"):
            if ev.get(k):
                L.append(f"      {k}: {ev[k]}")
        for s in ev.get("false_absence", [])[:2]:
            L.append(f"      absence claim: {s[:200]}")
        L.append(f"      A: {r['answer'][:160].replace(chr(10), ' ')}")
    return "\n".join(L)


def list_registers(regs: "OrderedDict[str, Register]", seed: int = 1) -> List[str]:
    """One line per register: rows, columns used, and how many questions each template yields."""
    lines = [f"{len(regs)} registers under {default_doc_dir()}"]
    for key, r in regs.items():
        per = {t: len(v) for t, v in enumerate_candidates(r, seed).items() if v}
        lines.append(
            f"  {key:<34} rows={len(r.rows):<4} noun={r.noun!r} id={r.id_col} "
            f"status={r.status_col} owner={r.owner_col or '-'} facets={r.kind_cols} "
            f"questions={sum(per.values())}"
        )
    return lines


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--docs",
        default=str(default_doc_dir()),
        help="directory of register .md files (default: input/documents, else bldg*/)",
    )
    ap.add_argument(
        "--register", action="append", help="only this register (file stem); repeatable"
    )
    ap.add_argument("--n", type=int, default=250, help="how many questions to generate")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument(
        "--weights",
        metavar="FILE.json",
        help="JSON {register key or noun: weight} to tilt the register balance",
    )
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="prefix for .jsonl (oracle) and .txt")
    ap.add_argument("--list", action="store_true", help="list the registers found and exit")
    ap.add_argument("--score", metavar="RUN.jsonl", help="score a run file against the oracle")
    ap.add_argument("--oracle", help="oracle .jsonl to score against (default: <out>.jsonl)")
    ap.add_argument(
        "--strict-extra",
        action="store_true",
        help="count real ids outside the expected set as a failure, not a warning",
    )
    ap.add_argument("--fails", type=int, default=0, help="print at most this many failures (0=all)")
    ap.add_argument("--json", metavar="PATH", help="also write the summary and per-answer scores")
    ap.add_argument("--selfcheck", action="store_true", help="test the checker itself and exit")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    regs = load_registers(Path(args.docs))
    if not regs:
        print(f"no register tables found under {args.docs}")
        return 2
    weights = json.loads(Path(args.weights).read_text(encoding="utf-8")) if args.weights else None
    if args.list:
        print("\n".join(list_registers(regs, args.seed)))
        return 0
    if args.selfcheck:
        ok, lines = selfcheck(regs, n=args.n, seed=args.seed)
        print("\n".join(lines))
        return 0 if ok else 1
    if args.score:
        oracle_path = Path(args.oracle or f"{args.out}.jsonl")
        if oracle_path.is_file():
            oracle = read_jsonl(oracle_path)
        else:
            print(f"[oracle] {oracle_path} not found; regenerating n={args.n} seed={args.seed}")
            oracle = generate(regs, n=args.n, seed=args.seed, only=args.register, weights=weights)
        scored = score_run(oracle, read_jsonl(Path(args.score)), regs, args.strict_extra)
        print(format_report(scored, args.fails))
        if args.json:
            payload = {
                "summary": summarise(scored),
                "rows": [
                    {
                        "id": r["entry"]["id"],
                        "register": r["entry"]["register"],
                        "template": r["entry"]["template"],
                        "question": r["entry"]["question"],
                        "pass": r["score"]["pass"],
                        "reasons": r["score"]["reasons"],
                        "warnings": r["score"]["warnings"],
                        "evidence": r["score"]["evidence"],
                    }
                    for r in scored["results"]
                ],
            }
            Path(args.json).write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            print(f"[written] {args.json}")
        return 0
    rows = generate(regs, n=args.n, seed=args.seed, only=args.register, weights=weights)
    if not rows:
        print("no questions generated (unknown --register?)")
        return 2
    jl, tx = write_oracle(rows, Path(args.out))
    per_reg = Counter(r["register"] for r in rows)
    per_tpl = Counter(r["template"] for r in rows)
    print(f"[written] {len(rows)} questions across {len(per_reg)} registers")
    print(f"  oracle   {jl}")
    print(f"  questions {tx}   (feed to: scripts/ask_questions.py --file)")
    print("  templates:", dict(sorted(per_tpl.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
