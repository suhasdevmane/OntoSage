# -*- coding: utf-8 -*-
"""claim_binder.py — every figure in an answer must point at a row (A2).

**The defect this exists for.** The evidence dossier records what was *fetched*. Nothing has
ever checked that the prose says only what the fetched rows *support*. From the hand read of
147 live answers on 2026-09-17 (``docs/phase0/phase0_rerun_read.md`` §C7, 17 rows):

* *"Each of the 20 records contains a mapped opening and a granted role, so none lack the
  basic evidence of ownership, purpose"* — the question asked which are orphaned; the verdict
  was reasoned from whichever fields happened to be present.
* *"Several assets list probable containment features that would limit damage from a leak"* —
  no field records containment.
* *"Short answer: Yes … all … are available"* beside its own table showing Lift B out of service.

The countermeasure shipped the same evening was a line in a prompt. A prompt rule is the
weakest possible enforcement: it is advice to a generator that has already demonstrated it
will ignore it. This module is the structural one — it reads the answer AFTER it is written
and asks, of every number in it, *which row is this?*

**Why a separate module, and why pure.** ``numeric_guard`` already does a cruder version of
this for two template-driven lanes (register, asset_state): any number not appearing anywhere
in the payload suppresses the WHOLE narration. That is right for a template (a template bug is
total) and wrong for a model narration (one bad figure should not destroy a correct answer),
and it never runs on the lanes where the C7 defects actually live. This module therefore:

* classifies each claim rather than the answer — BOUND / DERIVED / UNBOUND / SKIPPED;
* says WHY, in a report object, for every single decision;
* states its tolerances rather than hiding them in a comparison.

**Nothing here does I/O, and nothing here knows the name of a building.** Every fact comes
from the bus dict it is handed. That makes the whole module unit-testable and lets the same
code run offline over recorded answers, which is how its headline number was measured.

**Three claim families**

``NUMERIC``
    A number with the subject it is attached to. ``20 records``, ``-50.8%``,
    ``a mean of 21.5 °C``, ``18 September 2026``, ``14:00``, ``9 of 21``.

``UNIVERSAL``
    ``all`` / ``every`` / ``each`` / ``none`` / ``no`` + a subject + a predicate. The figures
    are right and the *verdict over* them is invented. Bound only when the property the
    predicate asserts is a field the evidence carries; ``containment`` is not, and that is
    the finding.

``INFERENCE``
    Whatever follows ``so`` / ``therefore`` / ``since`` / ``because``. This is the sharpest of
    the three and the one aimed squarely at C7: *"…, so none lack the basic evidence of
    ownership, purpose"*. The premises are evidenced, the conclusion turns on words no row is
    about.

**Enforcement asymmetry, deliberately.** In ``enforce`` mode an UNBOUND *numeric* claim has
its sentence removed and the answer says plainly that a figure could not be evidenced. An
UNBOUND *universal or inference* is never silently deleted — it is flagged and the answer
carries a plain caveat naming the property no record holds. Deleting a whole verdict sentence
on a lexical test would strip correct answers, and a binder that strips a correct figure is
worse than the defect it was built for.

**Enforcement is conditional on the record being complete (CAVEAT-769).** The flag was
switched on for one probe run on 2026-09-18 and reverted 25 minutes later: it had deleted
five CORRECT figures, among them the number a counting question had asked for. Nothing was
wrong with those answers. What was wrong is that the lanes producing them compute their
figures live and never recorded them, so to this module they were indistinguishable from
inventions. Two things follow, and both are implemented:

* lanes record what they compute (``evidence/computed.py``, read here as the
  ``computed_figures`` bus key) -- a ``COUNT`` is a query's result and therefore evidence;
* and enforcement now runs only when :func:`assess_completeness` says this turn's record
  accounts for the lane that answered. Anything less degrades to record-only **for that
  turn**, with the reason carried in the record. ``absence_guard`` states the principle this
  follows: *a guard that cannot verify has no business rewriting an answer.*

**Flag.** ``CLAIM_BINDING_ENABLED`` (or ``CLAIM_BINDING_MODE=record|enforce|off``) is read
from ``os.environ`` here rather than from ``shared.config``, and the documented default is
``record``: extract, bind, count, log, change nothing. The per-answer counts are the
measurement that justifies enforcing.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

__all__ = [
    "Claim",
    "ClaimBindingReport",
    "Completeness",
    "EV_ABSENT",
    "EV_COMPLETE",
    "EV_PARTIAL",
    "EvidenceIndex",
    "MODE_ENFORCE",
    "MODE_OFF",
    "MODE_RECORD",
    "analyse",
    "assess_completeness",
    "build_evidence_index",
    "current_mode",
    "extract_claims",
    "run",
]


# ── modes ────────────────────────────────────────────────────────────────────

MODE_OFF = "off"
MODE_RECORD = "record"
MODE_ENFORCE = "enforce"

#: The documented default. Record-only: the binder runs, counts and logs, and the answer the
#: reader receives is byte-identical to the one they would have received without it.
DEFAULT_MODE = MODE_RECORD


def current_mode(env: Optional[Dict[str, str]] = None) -> str:
    """The mode this process runs in, from the environment.

    Read here rather than from ``shared.config`` so this module has no settings dependency
    and can be exercised offline. ``CLAIM_BINDING_MODE`` wins when set; otherwise
    ``CLAIM_BINDING_ENABLED`` truthy means enforce. Anything unrecognised falls back to the
    documented default rather than to off — a typo must not silently disable the measurement.
    """
    src = os.environ if env is None else env
    raw = str(src.get("CLAIM_BINDING_MODE", "") or "").strip().lower()
    if raw in (MODE_OFF, MODE_RECORD, MODE_ENFORCE):
        return raw
    flag = str(src.get("CLAIM_BINDING_ENABLED", "") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return MODE_ENFORCE
    if flag in ("0", "false", "no", "off"):
        return MODE_RECORD
    return DEFAULT_MODE


# ── tolerances, stated once and never re-derived at a call site ──────────────

#: Relative tolerance for a DERIVED figure (sum/mean/percentage). 0.5% absorbs the difference
#: between a mean over the rows the lane handed up and the same mean the narrator computed
#: from a rounded rendering of them. It is NOT applied to a direct value lookup: a reading is
#: either in the rows or it is not.
REL_TOL = 0.005

#: Absolute tolerance in percentage points, for the same reason, on percentage claims.
PCT_TOL_PP = 0.05

#: Absolute floor so tiny values are not judged by a relative test ("0.0%" vs "0.004%").
ABS_TOL = 1e-6

#: There is deliberately NO "numbers too small to matter" allowlist here, the way
#: ``numeric_guard.INNOCUOUS`` exempts 0-10, 24, 25 and 100. "9 of 21" is a claim and "1." is
#: not, and the difference is CONTEXT, not magnitude — so the exemptions are made by the
#: masking pass (list markers, headings, code, identifiers, the response node's own trailer)
#: and each one is visible in the report as a SKIPPED claim with its reason.
#:
#: How many individual claims travel in the serialised record. The COUNTS are always complete.
_MAX_RECORDED_CLAIMS = 80


# ── the claim grammar ────────────────────────────────────────────────────────

#: A number, with thousands separators and an optional decimal part. Deliberately greedy on
#: the integer side so "77,088" is one claim and not three.
_NUM_RE = re.compile(r"[-+−]?\d[\d,]*(?:\.\d+)?")

#: Units the building's answers actually use, plus the bare-word units a count can carry.
#: Matched case-sensitively for the symbols (K vs k) and insensitively for the words.
_UNIT_SYMBOLS = (
    "%",
    "°C",
    "°F",
    "℃",
    "ppm",
    "ppb",
    "µg/m³",
    "ug/m3",
    "mg/m³",
    "kWh",
    "MWh",
    "Wh",
    "kW",
    "MW",
    "W",
    "kVA",
    "kg",
    "g",
    "t",
    "m²",
    "m2",
    "m³",
    "m3",
    "m",
    "mm",
    "cm",
    "km",
    "L",
    "l",
    "lx",
    "lux",
    "dB",
    "dBA",
    "Pa",
    "kPa",
    "bar",
    "hPa",
    "V",
    "A",
    "Hz",
    "£",
    "$",
    "€",
)

_UNIT_WORDS = (
    "percent",
    "percentage",
    "degrees",
    "celsius",
    "minutes",
    "minute",
    "hours",
    "hour",
    "days",
    "day",
    "weeks",
    "week",
    "months",
    "month",
    "years",
    "year",
    "seconds",
    "second",
)

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

#: "18 September 2026" / "September 18, 2026" / "2026-09-18" / "18/09/2026"
_DATE_DMY_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(_MONTHS) + r")\.?\s+(\d{4})\b", re.I
)
_DATE_MDY_RE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I
)
#: ``\b`` after the day would FAIL inside a timestamp ("2026-08-03T11:31:24"), because T is a
#: word character — so no stored timestamp was ever recognised as carrying a date, and its
#: loose digits were then offered as evidence for any small number.
_DATE_ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_DATE_SLASH_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")

#: A clock time. Kept separate from plain numbers so "14:00" is one claim, not two.
_TIME_RE = re.compile(r"(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?(?![\d:])")

#: Record identifiers ("APG-001", "REG-004", "CT-065"). These are names, not quantities.
_IDENT_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}[-_]\d{1,6}\b")

#: A hyphenated code: at least one segment with a letter and at least one with a digit —
#: "MCC-0-way-3", "LI-AHU-00", "RI-CT-01", "LMR-1", "Room-2.14". Measured on the recorded
#: bank: without this, an equipment tag contributed FOUR separate "claims" ("0", "3", "00",
#: "01") and the binder then reported an asset name as four unevidenced figures.
#: It must START with a letter, so an ISO timestamp ("2026-06-16T11:31:24") is not mistaken
#: for a code and masked away — that would delete the date claims this module is meant to test.
#: The lookahead has to be able to cross the separators, or it can never see the digit that
#: makes the token a code: written as ``[\w.]*\d`` it matched nothing at all, and the mask it
#: was added for silently did nothing.
_CODE_RE = re.compile(r"\b(?=[-\w./]*\d)[A-Za-z][A-Za-z0-9.]*(?:[-_/][A-Za-z0-9.]+)+")

#: A digit run GLUED to the letters before it is part of a name, not a quantity: the 2 of
#: ``CO2``, the 2.5 of ``PM2.5``, the 2 of ``NO2``. Measured 2026-09-18 on the census answer
#: this building actually renders: those three were extracted as the claims "2", "2.5" and
#: "2", none of which any row records, and enforcement then deleted the bullets carrying
#: **280**, **274** and **245** — three correct counts destroyed by the digits inside the
#: names of the things being counted. ``_CODE_RE`` did not cover it because a measurand name
#: has no separator in it.
#:
#: A quantity in these answers is always separated from the word before it (a space, a colon,
#: a currency symbol, an opening bracket), so requiring a letter IMMEDIATELY before the digit
#: costs nothing and closes the whole family at once.
_NAME_DIGIT_RE = re.compile(r"(?<=[A-Za-z])\d[\d.]*")

#: The system's OWN disclosure about how to read a figure ("_Note: in Brick, … the total is
#: broader than the name suggests._"). It is template text explaining the count, not a claim
#: about the building, and it is written precisely to stop a reader over-reading. Treating it
#: as an unsupported inference caveats a caveat, which is circular and reads as the system
#: doubting its own honesty note.
_NOTE_BLOCK_RE = re.compile(r"(?m)^[ \t]*(?:_|\*)*\s*Note\s*:.*$")

#: Typographic dashes and minus signs. Markdown from the model is full of U+2011 (a
#: non-breaking hyphen), and every date and identifier written with one fell straight through
#: the date and identifier patterns: "2026‑06‑16" became the three separate claims 2026, 06
#: and 16, all unbound, all nonsense. Same-length replacement, so every offset survives.
_DASHES = {
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    "­": "-",
}
#: Spaces that are not the space character. The model writes "115 minutes" with U+202F (a
#: narrow no-break space) between the figure and its unit, and every one of those units was
#: invisible: ``_unit_at`` tests for ``" "`` and then for ``[A-Za-z]+`` at the next character,
#: and a narrow no-break space satisfies neither. Measured 2026-09-18 on a correct answer --
#: "1 hour 55 minutes" carried no units at all, so the duration rule could not see the pair
#: and enforcement deleted the 55. Same length in, same length out, so every span still
#: indexes the ORIGINAL string and redaction stays exact.
_SPACES = {
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    "　": " ",
}
_NORMALISE_TABLE = {ord(k): v for k, v in {**_DASHES, **_SPACES}.items()}

#: An inferential connective. What follows one is a CONCLUSION, and the C7 defect family is
#: conclusions that rest on properties no field records — "…, so none lack the basic evidence
#: of ownership, purpose". The figures before the connective are usually right; the clause
#: after it is the invention.
_INFERENCE_RE = re.compile(
    r"(?:,\s*|\.\s+|;\s*)(?:so|therefore|thus|hence|consequently|which\s+means|meaning)\b"
    r"|\b(?:since|because)\b",
    re.I,
)

#: Markdown/structural regions whose numbers are not claims about the building.
_FENCE_RE = re.compile(r"```.*?```", re.S)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+|<[a-z]+:[^>\s]+>", re.I)
_LIST_MARKER_RE = re.compile(r"(?m)^[ \t]*(\d{1,3})[.)]\s")
_HEADING_RE = re.compile(r"(?m)^[ \t]*#{1,6} .*$")
_TABLE_SEP_RE = re.compile(r"(?m)^[ \t]*\|?[-: |]{5,}\|?[ \t]*$")

#: The response node's own trailers: the follow-up suggestions and the sources footer. They
#: are template furniture appended after the answer, and their numbers ("Which of these are
#: on floor 3?") are QUESTIONS, not assertions. Counting them as claims made the binder
#: measure its own scaffolding.
_TRAILER_RE = re.compile(
    r"(?ms)^(?:---+\s*)?(?:\*?\*?(?:You might also ask|Sources?|Follow-?ups?|"
    r"Suggested (?:questions|follow-ups))\b.*)\Z"
)

_QUANTIFIERS = ("all", "every", "each", "none", "no", "any", "both", "neither")

#: Words that make an aggregate claim explicit. DERIVED only tries an operation the prose
#: itself names (or whose column the subject names) — otherwise a mean over some unrelated
#: column would "explain" an invented number, which is the failure mode this guards against.
_SUM_WORDS = ("total", "sum", "combined", "altogether", "overall", "aggregate", "across")
_MEAN_WORDS = ("average", "mean", "typical", "avg", "per day", "per hour")
_MIN_WORDS = ("lowest", "minimum", "min", "coolest", "quietest", "least", "smallest")
_MAX_WORDS = ("highest", "maximum", "max", "peak", "warmest", "loudest", "most", "largest")
_COUNT_WORDS = (
    "records",
    "record",
    "rows",
    "entries",
    "entry",
    "items",
    "sensors",
    "readings",
    "of the",
    "out of",
    "there are",
    "there is",
    "found",
    "listed",
    "returned",
    "total of",
)
_CHANGE_WORDS = (
    "change",
    "increase",
    "decrease",
    "higher",
    "lower",
    "down",
    "up",
    "from",
    "versus",
    "vs",
    "compared",
    "difference",
    "more",
    "less",
    "fewer",
)

#: An absence statement. Measured on the recorded bank: without this guard the binder flagged
#: honest declines ("the records do not contain any information about vehicle usage") as
#: unsupported universals — condemning the one behaviour the lanes were hardest to teach.
#:
#: ``lack``/``without``/``absent`` are deliberately NOT here. "so none lack the basic evidence
#: of ownership" is a POSITIVE verdict phrased with a negative word, and treating it as an
#: absence statement skipped the single worst answer in the C7 set — the one this whole
#: workstream was opened for.
_NEGATION_RE = re.compile(
    r"\b(?:do(?:es)?\s+not|did\s+not|don'?t|doesn'?t|isn'?t|aren'?t|wasn'?t|weren'?t|"
    r"cannot|can'?t|could\s+not|couldn'?t|no\s+record|not\s+recorded|not\s+contain|"
    r"not\s+(?:show|include|indicate|provide|hold|state)|there\s+(?:is|are)\s+no|"
    r"i\s+(?:could|can)\s*n[o']t|unable|nothing|"
    # "no explicit ready-before-arrival INSTRUCTIONS are recorded" — the head noun can sit two
    # modifiers away from the "no", and an absence stated that way is still an absence.
    r"no\s+(?:\w+[- ]){0,3}(?:record|records|field|fields|data|information|entry|entries|"
    r"instruction|instructions|detail|details|mention|evidence|note|notes))\b"
)

#: Words that never make a useful subject.
_STOPWORDS = frozenset(
    """a an the of in on at to for by with and or is are was were be been being
    this that these those it its their there here as from into over under about
    which who whom whose has have had do does did not no than then so but if""".split()
)


@dataclass
class Claim:
    """One thing the answer asserts that the evidence must support.

    Every field is filled from the answer text alone — binding happens later and separately,
    so a claim can be inspected (and a extraction bug found) without any evidence at hand.
    """

    kind: str  # "numeric" | "universal"
    raw: str  # exactly as written, for the report and for redaction
    start: int
    end: int
    sentence: str
    subject: str = ""
    unit: str = ""
    value: Optional[float] = None
    iso_date: str = ""
    quantifier: str = ""
    predicate: Tuple[str, ...] = ()
    decimals: int = 0

    # filled by binding
    binding: str = "unbound"  # "bound" | "derived" | "unbound" | "skipped"
    reason: str = ""
    operation: str = ""
    inputs: Tuple[str, ...] = ()
    evidence_path: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "raw": self.raw,
            "subject": self.subject,
            "unit": self.unit,
            "value": self.value,
            "iso_date": self.iso_date or None,
            "quantifier": self.quantifier or None,
            "predicate": list(self.predicate) or None,
            "binding": self.binding,
            "reason": self.reason,
            "operation": self.operation or None,
            "inputs": list(self.inputs) or None,
            "evidence_path": self.evidence_path or None,
            "sentence": self.sentence[:240],
        }


@dataclass
class EvidenceIndex:
    """Everything this turn actually fetched, in the shapes a claim can be tested against."""

    available: bool = False
    lanes: Dict[str, int] = field(default_factory=dict)
    #: canonical float -> the path it was read from ("register_result.rows[3].dueDate")
    floats: List[Tuple[float, str]] = field(default_factory=list)
    #: numbers that occur INSIDE a text cell — ``valueBand: "100k-250k"`` carries 100 and 250
    #: as facts even though the cell is a string. Kept in a second tier so a report can say
    #: which kind of hit it was, and checked after the structured values so the more precise
    #: provenance always wins. Measured: without this the binder called a correctly quoted
    #: cost band an invention, eight times in one answer.
    cell_numbers: List[Tuple[float, str]] = field(default_factory=list)
    #: every string cell, lowercased, for a literal match ("18 September 2026")
    literals: Set[str] = field(default_factory=set)
    #: ISO dates found anywhere in the evidence
    iso_dates: Set[str] = field(default_factory=set)
    #: field/column names, normalised to words ("controlsOpening" -> {"controls", "opening"})
    field_words: Set[str] = field(default_factory=set)
    #: value words from string cells, for the universal test
    value_words: Set[str] = field(default_factory=set)
    #: numeric column -> its values, for the DERIVED aggregates
    columns: Dict[str, List[float]] = field(default_factory=dict)
    #: string column -> {value: how many rows carry it}. This is what makes "72 completed"
    #: bindable: the rows say ``recordStatus`` 72 times with the value ``done``, and the
    #: narrator counted them. Without it a correct group count reads as an invention.
    categories: Dict[str, Dict[str, int]] = field(default_factory=dict)
    #: named counts the evidence supports directly ("register_result.rows" -> 20)
    counts: Dict[str, int] = field(default_factory=dict)

    def summary(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "lanes": dict(self.lanes),
            "distinct_values": len(self.floats),
            "cell_numbers": len(self.cell_numbers),
            "columns": len(self.columns),
            "counts": len(self.counts),
            "field_words": len(self.field_words),
        }


@dataclass
class ClaimBindingReport:
    """What was claimed, what was supported, and what the binder did about it."""

    mode: str
    lane: str
    evidence_available: bool
    claims: List[Claim] = field(default_factory=list)
    answer: str = ""
    original_answer: str = ""
    changed: bool = False
    notes: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    #: Whether the record was complete enough to rewrite the answer against, and why. In
    #: ``enforce`` mode a turn that is not COMPLETE degrades to record-only -- the counts are
    #: still taken, the answer is untouched, and the reason travels with the record.
    completeness: Optional["Completeness"] = None
    enforced: bool = False

    # ---- counts, derived so they can never disagree with the claim list ----
    def counts(self) -> Dict[str, int]:
        out = {"total": 0, "bound": 0, "derived": 0, "unbound": 0, "skipped": 0}
        for c in self.claims:
            out["total"] += 1
            out[c.binding] = out.get(c.binding, 0) + 1
        for kind in ("numeric", "universal", "inference"):
            out[kind] = sum(1 for c in self.claims if c.kind == kind)
            out[f"unbound_{kind}"] = sum(
                1 for c in self.claims if c.kind == kind and c.binding == "unbound"
            )
        return out

    def unbound_rate(self) -> Optional[float]:
        """Unbound share of ASSESSED claims (skipped ones are not assessed)."""
        assessed = [c for c in self.claims if c.binding != "skipped"]
        if not assessed:
            return None
        return sum(1 for c in assessed if c.binding == "unbound") / len(assessed)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "lane": self.lane,
            "evidence_available": self.evidence_available,
            "counts": self.counts(),
            "unbound_rate": self.unbound_rate(),
            "changed": self.changed,
            "enforced": self.enforced,
            "completeness": (
                self.completeness.as_dict()
                if self.completeness is not None
                else {"status": EV_ABSENT, "reason": "not assessed", "enforceable": False}
            ),
            "notes": list(self.notes),
            "evidence": dict(self.evidence),
            # Unbound claims first, then the rest, and capped: this record rides in the
            # conversation state and the response cache, and a table-heavy answer can carry
            # two hundred claims. The counts above are complete whatever is dropped here.
            "claims": [c.as_dict() for c in self._claims_for_record()],
            "claims_recorded": min(len(self.claims), _MAX_RECORDED_CLAIMS),
        }

    def _claims_for_record(self) -> List[Claim]:
        ranked = sorted(self.claims, key=lambda c: (c.binding != "unbound", c.start))
        return ranked[:_MAX_RECORDED_CLAIMS]


# ── extraction ───────────────────────────────────────────────────────────────


def _mask(text: str) -> str:
    """Blank out regions whose numbers are not claims, preserving every offset.

    Offsets must survive because redaction works on spans of the ORIGINAL string. Replacing
    a region with spaces of equal length is the only way to do both.
    """

    text = text.translate(_NORMALISE_TABLE)  # same length, so every offset survives
    out = list(text)

    def blank(match: "re.Match[str]", group: int = 0) -> None:
        for i in range(match.start(group), match.end(group)):
            if out[i] != "\n":
                out[i] = " "

    for rx in (
        _FENCE_RE,
        _INLINE_CODE_RE,
        _URL_RE,
        _HEADING_RE,
        _TABLE_SEP_RE,
        _IDENT_RE,
        _CODE_RE,
        _NAME_DIGIT_RE,
        _NOTE_BLOCK_RE,
        _TRAILER_RE,
    ):
        for m in rx.finditer(text):
            blank(m)
    for m in _LIST_MARKER_RE.finditer(text):
        blank(m, 1)
    return "".join(out)


def _sentence_bounds(text: str, pos: int) -> Tuple[int, int]:
    """The sentence containing ``pos``. Newlines and bullets end a sentence too.

    A markdown answer is mostly not sentences — it is table rows and bullets — so a naive
    split on '.' would join a whole table into one 'sentence' and a redaction would delete
    the evidence along with the claim.
    """
    start = 0
    for i in range(pos - 1, -1, -1):
        ch = text[i]
        if ch == "\n":
            start = i + 1
            break
        if ch in ".!?" and i + 1 < len(text) and text[i + 1] in " \n":
            start = i + 1
            break
    end = len(text)
    for i in range(pos, len(text)):
        ch = text[i]
        if ch == "\n":
            end = i
            break
        if ch in ".!?" and (i + 1 >= len(text) or text[i + 1] in " \n"):
            end = i + 1
            break
    return start, end


def _words(s: str) -> List[str]:
    return [w for w in re.split(r"[^\w°%£$€.²³/-]+", s.lower()) if w]


def _content_words(s: str) -> List[str]:
    return [w for w in _words(s) if w not in _STOPWORDS and not w.isdigit() and len(w) > 2]


def _unit_at(text: str, pos: int) -> Tuple[str, int]:
    """The unit immediately after ``pos``, and where it ends."""
    i = pos
    if i < len(text) and text[i] == " ":
        i += 1
    for sym in sorted(_UNIT_SYMBOLS, key=len, reverse=True):
        if text.startswith(sym, i):
            # 'm' must not swallow the 'm' of 'meeting rooms'
            nxt = i + len(sym)
            if sym.isalpha() and nxt < len(text) and (text[nxt].isalnum() or text[nxt] == "-"):
                continue
            return sym, nxt
    m = re.match(r"([A-Za-z]+)", text[i:])
    if m and m.group(1).lower() in _UNIT_WORDS:
        return m.group(1).lower(), i + m.end(1)
    return "", pos


def _subject_for(text: str, num_start: int, num_end: int) -> str:
    """The noun the number is attached to, read the way English attaches it.

    Two attachments, in this order:

    1. *after* — ``20 records``, ``3 sensors``: the head noun that follows.
    2. *before* — ``the average temperature is 21.5``, ``a mean of 900 ppm``: the noun phrase
       that precedes a copula or ``of``.

    Both are returned as plain lowercase words. This is a heuristic and is treated as one:
    the subject is used to CHOOSE which derived operations to try and to explain a decision.
    It never, on its own, makes a claim unbound.
    """
    tail = text[num_end : num_end + 60]
    tail = re.sub(r"^\s*(?:%|°[CF]|[A-Za-z²³/µ]{1,6})?\s*", " ", tail, count=1)
    after = [w for w in _words(tail)[:5] if w not in _STOPWORDS and not w.isdigit()]
    if after:
        head = after[0]
        if len(after) > 1 and head in ("of", "out"):
            head = after[1]
        if len(head) > 2:
            return " ".join(after[:2])
    head_text = text[max(0, num_start - 90) : num_start]
    head_text = re.split(r"[.;:!?\n]", head_text)[-1]
    before = [w for w in _content_words(head_text)]
    if before:
        return " ".join(before[-2:])
    return ""


def _decimals_of(raw: str) -> int:
    return len(raw.split(".", 1)[1]) if "." in raw else 0


def _to_float(raw: str) -> Optional[float]:
    try:
        return float(raw.replace(",", "").replace("−", "-").replace("+", ""))
    except ValueError:
        return None


def _iso_from_match(kind: str, m: "re.Match[str]") -> str:
    try:
        if kind == "dmy":
            d, mon, y = int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
        elif kind == "mdy":
            mon, d, y = _MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
        elif kind == "iso":
            y, mon, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:  # dd/mm/yyyy — the building states dates day-first
            d, mon, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= mon <= 12 and 1 <= d <= 31):
            return ""
        return "%04d-%02d-%02d" % (y, mon, d)
    except Exception:
        return ""


def extract_claims(answer: str) -> List[Claim]:
    """Every quantitative and universal claim in an answer, with its span and subject.

    Order is by position, and spans never overlap: a date consumes its own digits so
    "18 September 2026" is one claim rather than three numbers with nonsense subjects.
    """
    if not answer:
        return []
    # Typographic dashes normalised once, for the whole pass. Same length in, same length
    # out, so every span below still indexes the ORIGINAL string and redaction is exact.
    answer = answer.translate(_NORMALISE_TABLE)
    masked = _mask(answer)
    claims: List[Claim] = []
    taken: List[Tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= s or a >= e for s, e in taken)

    # 1. dates first — they own their digits
    for kind, rx in (
        ("dmy", _DATE_DMY_RE),
        ("mdy", _DATE_MDY_RE),
        ("iso", _DATE_ISO_RE),
        ("slash", _DATE_SLASH_RE),
    ):
        for m in rx.finditer(masked):
            if not free(m.start(), m.end()):
                continue
            iso = _iso_from_match(kind, m)
            if not iso:
                continue
            s, e = _sentence_bounds(answer, m.start())
            taken.append((m.start(), m.end()))
            claims.append(
                Claim(
                    kind="numeric",
                    raw=answer[m.start() : m.end()],
                    start=m.start(),
                    end=m.end(),
                    sentence=answer[s:e].strip(),
                    subject=_subject_for(answer, m.start(), m.end()) or "date",
                    unit="date",
                    iso_date=iso,
                )
            )

    # 2. clock times
    for m in _TIME_RE.finditer(masked):
        if not free(m.start(), m.end()):
            continue
        s, e = _sentence_bounds(answer, m.start())
        taken.append((m.start(), m.end()))
        claims.append(
            Claim(
                kind="numeric",
                raw=answer[m.start() : m.end()],
                start=m.start(),
                end=m.end(),
                sentence=answer[s:e].strip(),
                subject=_subject_for(answer, m.start(), m.end()) or "time",
                unit="time",
            )
        )

    # 3. plain numbers, with whatever unit follows
    for m in _NUM_RE.finditer(masked):
        if not free(m.start(), m.end()):
            continue
        raw = m.group(0).rstrip(",.")
        if not raw or not any(ch.isdigit() for ch in raw):
            continue
        end = m.start() + len(raw)
        unit, unit_end = _unit_at(masked, end)
        s, e = _sentence_bounds(answer, m.start())
        taken.append((m.start(), unit_end))
        value = _to_float(raw)
        claims.append(
            Claim(
                kind="numeric",
                raw=answer[m.start() : unit_end],
                start=m.start(),
                end=unit_end,
                sentence=answer[s:e].strip(),
                subject=_subject_for(answer, m.start(), end),
                unit=unit,
                value=value,
                decimals=_decimals_of(raw),
            )
        )

    # 4. universals — the C7 shape
    for m in re.finditer(
        r"\b(" + "|".join(_QUANTIFIERS) + r")\b(?!\s+(?:of\s+)?(?:which|whom|these|those)\b)",
        masked,
        re.I,
    ):
        s, e = _sentence_bounds(answer, m.start())
        clause = answer[m.start() : e]
        if len(clause.split()) < 3:
            continue
        words = _content_words(clause)
        if not words:
            continue
        claims.append(
            Claim(
                kind="universal",
                raw=clause.strip()[:160],
                start=m.start(),
                end=e,
                sentence=answer[s:e].strip(),
                quantifier=m.group(1).lower(),
                subject=" ".join(words[:2]),
                predicate=tuple(words[:10]),
            )
        )

    # 5. inferences — the C7 shape in its purest form. The figures before "so" are usually
    #    right; the verdict after it is the invention.
    for m in _INFERENCE_RE.finditer(masked):
        s, e = _sentence_bounds(answer, m.start())
        conclusion = answer[m.end() : e].strip()
        if len(conclusion.split()) < 3:
            continue
        words = _content_words(conclusion)
        if not words:
            continue
        claims.append(
            Claim(
                kind="inference",
                raw=conclusion[:180],
                start=m.end(),
                end=e,
                sentence=answer[s:e].strip(),
                subject=" ".join(words[:2]),
                predicate=tuple(words[:12]),
            )
        )

    claims.sort(key=lambda c: (c.start, c.kind))
    return claims


# ── the evidence side ────────────────────────────────────────────────────────

#: Bus keys whose value is (or contains) the rows this turn fetched. Kept in step with
#: ``evidence.assemble.T02_LANES`` by a test, not by hope: a lane added there and missed here
#: would make every figure it produced look unbound.
_EVIDENCE_KEYS = (
    "sql_result",
    "sparql_result",
    "analytics_result",
    "forecast_result",
    "deliberate_result",
    "events_result",
    "register_result",
    "capability_result",
    "spatial_result",
    "floor_plan_result",
    "asset_state_result",
    "compliance_context",
    "sensor_metadata",
    "dossier",
    "recipe_hints",
    "report_intake_result",
    "goal_plan",
    # Figures a lane COMPUTED rather than fetched -- a live COUNT over the building's model,
    # a census, a ranking score. They were invisible here until 2026-09-18, and enforcement
    # therefore deleted correct numbers on its single live run (CAVEAT-769). A count is a
    # query's result; it is evidence, and this is where it arrives.
    "computed_figures",
)

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _split_field(name: str) -> List[str]:
    return [w for w in re.split(r"[^a-z0-9]+", _CAMEL_RE.sub(" ", str(name)).lower()) if w]


def _walk(
    node: Any,
    path: str,
    idx: EvidenceIndex,
    column: str = "",
    depth: int = 0,
) -> None:
    """One recursive pass that fills every index at once.

    A single walk matters: two passes over the same structure is how ``assemble.py``'s own
    docstring says BUG-210 happened. Depth-capped because a bus payload can carry a cyclic
    proxy and a binder must never hang the response node.
    """
    if depth > 9:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("formatted_response", "response", "message", "narration", "prompt"):
                continue  # the text under test must not vouch for itself
            idx.field_words.update(_split_field(k))
            _walk(v, f"{path}.{k}", idx, column=str(k), depth=depth + 1)
    elif isinstance(node, (list, tuple)):
        if node and all(isinstance(r, dict) for r in node):
            idx.counts[path] = len(node)
        for i, v in enumerate(node[:400]):
            _walk(v, f"{path}[{i}]", idx, column=column, depth=depth + 1)
    elif isinstance(node, bool):
        idx.value_words.add("true" if node else "false")
    elif isinstance(node, (int, float)):
        if not (isinstance(node, float) and (math.isnan(node) or math.isinf(node))):
            idx.floats.append((float(node), path))
            if column:
                idx.columns.setdefault(column, []).append(float(node))
    elif isinstance(node, str):
        s = node.strip()
        if not s or len(s) > 4000:
            return
        low = s.lower()
        idx.literals.add(low)
        idx.value_words.update(_content_words(low))
        if column and len(low) <= 120:
            bucket = idx.categories.setdefault(column, {})
            bucket[low] = bucket.get(low, 0) + 1
        for m in _DATE_ISO_RE.finditer(s):
            idx.iso_dates.add(_iso_from_match("iso", m))
        for m in _DATE_DMY_RE.finditer(s):
            idx.iso_dates.add(_iso_from_match("dmy", m))
        # a numeric string cell is still a number ("21.5", "1,316")
        if len(s) <= 40:
            m = _NUM_RE.fullmatch(s)
            if m:
                v = _to_float(s)
                if v is not None:
                    idx.floats.append((v, path))
                    if column:
                        idx.columns.setdefault(column, []).append(v)
                    return
        # Numbers inside a free-text cell, MINUS the structured tokens that are already
        # indexed elsewhere. Without stripping dates and clock times first, "03" out of
        # "2026-08-03T11:31:24" evidenced a claim of "3 outstanding" — a guard that accepts
        # any digit occurring anywhere is not a guard. Single digits go the same way: "m3/s"
        # is a unit, not a quantity.
        residue = _TIME_RE.sub(" ", _DATE_ISO_RE.sub(" ", s))
        for tok in _NUM_RE.findall(residue)[:40]:
            body = tok.lstrip("+-")
            if "." not in body and len(body.replace(",", "")) < 2:
                continue
            v = _to_float(tok)
            if v is not None:
                idx.cell_numbers.append((v, path))
    else:
        idx.literals.add(str(node).lower()[:200])


def _with_computed_figures(results: Dict[str, Any]) -> Dict[str, Any]:
    """Add this turn's computed figures to the bus view, if the bus does not carry them.

    Lanes that compute a figure file it with ``evidence.computed`` at the moment they compute
    it, because the value never becomes a row on the bus -- it becomes a sentence. Collecting
    it here, rather than asking ten agents to remember to put it on the bus, is the same
    reasoning that put the binder itself at one chokepoint.

    A bus that already carries the key wins: that is how the offline replay hands recorded
    figures to this exact code path, so what is measured offline is what runs live.
    """
    if results.get("computed_figures"):
        return results
    try:
        from orchestrator.services.evidence.computed import as_payload

        payload = as_payload(consume=True)
    except Exception:  # pragma: no cover - import guard only
        payload = None
    if not payload:
        return results
    merged = dict(results)
    merged["computed_figures"] = payload
    return merged


def build_evidence_index(results: Dict[str, Any]) -> EvidenceIndex:
    """Index everything this turn fetched. Never raises; an index it could not build is an
    index that says it is empty, which then SKIPS every claim rather than condemning it."""
    idx = EvidenceIndex()
    if not isinstance(results, dict):
        return idx
    results = _with_computed_figures(results)
    for key in _EVIDENCE_KEYS:
        val = results.get(key)
        if val in (None, {}, [], ""):
            continue
        try:
            before = len(idx.floats) + len(idx.literals)
            _walk(val, key, idx)
            rows = _rows_in(val)
            if rows:
                idx.counts.setdefault(f"{key}.rows", len(rows))
            idx.lanes[key] = len(rows)
            if len(idx.floats) + len(idx.literals) > before:
                idx.available = True
        except Exception as exc:  # one malformed lane must not void the whole index
            logger.debug(f"[claim_binder] lane {key} skipped: {type(exc).__name__}: {exc}")
    # the counts a narrator most often quotes
    for key, n in list(idx.lanes.items()):
        if n:
            idx.counts[f"{key}.count"] = n
    return idx


def _rows_in(payload: Any) -> List[Dict[str, Any]]:
    """The row list, whichever shape a lane used. Mirrors ``assemble._rows_of`` deliberately
    at the call boundary only — the shapes are the lanes' contract, not this module's."""
    try:
        from orchestrator.services.evidence.assemble import _rows_of

        return _rows_of(payload)
    except Exception:
        if isinstance(payload, list):
            return [r for r in payload if isinstance(r, dict)]
        return []


# ── binding ──────────────────────────────────────────────────────────────────


def _close(a: float, b: float, decimals: int, *, rel: float = 0.0) -> bool:
    """Is ``b`` the same figure as ``a``, given how ``a`` was WRITTEN?

    Rounding is explicit: a claim written "21.5" is compared at one decimal place, so a stored
    21.4979 binds and a stored 22.1 does not. ``rel`` is added only for DERIVED figures.
    """
    if a is None or b is None:
        return False
    if round(b, decimals) == round(a, decimals):
        return True
    if abs(a - b) <= ABS_TOL:
        return True
    if rel and abs(a - b) <= max(abs(a), abs(b)) * rel:
        return True
    return False


def _lookup(value: float, decimals: int, idx: EvidenceIndex) -> Optional[str]:
    for v, path in idx.floats:
        if _close(value, v, decimals):
            return path
    return None


def _sentence_mentions(sentence: str, words: Sequence[str]) -> bool:
    low = sentence.lower()
    return any(w in low for w in words)


def _columns_for(claim: Claim, idx: EvidenceIndex) -> List[Tuple[str, List[float]]]:
    """Columns worth aggregating for this claim: the ones the subject names, else all.

    Restricting by subject first is what keeps DERIVED honest. Trying a mean over every
    column until one matches would "explain" an invented number roughly as often as a real
    one, and the explanation would be a coincidence dressed as provenance.
    """
    subj = set(_content_words(claim.subject)) | set(_content_words(claim.unit))
    named = [(c, vs) for c, vs in idx.columns.items() if subj & set(_split_field(c))]
    return named or list(idx.columns.items())


def _try_derive(claim: Claim, idx: EvidenceIndex) -> bool:
    """Attempt each licensed operation. Returns True and stamps the claim when one fits."""
    v = claim.value
    if v is None:
        return False
    dec = claim.decimals

    # counts — the single most common quoted figure ("20 records", "9 of 21")
    if v == int(v) and 0 <= v <= 100000:
        target = int(v)
        for name, n in idx.counts.items():
            if n == target:
                claim.binding = "derived"
                claim.operation = "count"
                claim.inputs = (name,)
                claim.evidence_path = name
                claim.reason = f"equals the number of rows in {name}"
                return True
        # a filtered count: rows whose cells carry a status word the sentence also uses.
        # "72 completed (done) records" out of 82 rows is a COUNT OVER A GROUP, and until
        # this existed every correct group count in a register answer read as an invention.
        sent_low = claim.sentence.lower()
        sent_words = set(_content_words(claim.sentence))
        for col, buckets in idx.categories.items():
            for val, n in buckets.items():
                if n != target:
                    continue
                if val in sent_low or (set(_content_words(val)) & sent_words):
                    claim.binding = "derived"
                    claim.operation = "count_where"
                    claim.inputs = (col, val)
                    claim.evidence_path = col
                    claim.reason = f"{n} rows carry {col} = '{val}'"
                    return True
        for col, vals in idx.columns.items():
            if len(vals) == target and (set(_split_field(col)) & sent_words):
                claim.binding = "derived"
                claim.operation = "count"
                claim.inputs = (col,)
                claim.evidence_path = col
                claim.reason = f"equals the number of values recorded for {col}"
                return True
        # a complement: "10 open" where 82 rows hold 72 of something else
        for col, buckets in idx.categories.items():
            total = sum(buckets.values())
            for val, n in buckets.items():
                if total - n == target and (
                    val in sent_low or set(_content_words(val)) & sent_words
                ):
                    claim.binding = "derived"
                    claim.operation = "count_complement"
                    claim.inputs = (col, val, f"total={total}")
                    claim.evidence_path = col
                    claim.reason = f"{total} rows minus the {n} whose {col} is '{val}'"
                    return True

    cols = _columns_for(claim, idx)
    ops: List[Tuple[str, Any, Tuple[str, ...]]] = []
    if _sentence_mentions(claim.sentence, _SUM_WORDS):
        ops.append(("sum", lambda xs: math.fsum(xs), _SUM_WORDS))
    if _sentence_mentions(claim.sentence, _MEAN_WORDS):
        ops.append(("mean", lambda xs: math.fsum(xs) / len(xs), _MEAN_WORDS))
    if _sentence_mentions(claim.sentence, _MIN_WORDS):
        ops.append(("min", min, _MIN_WORDS))
    if _sentence_mentions(claim.sentence, _MAX_WORDS):
        ops.append(("max", max, _MAX_WORDS))
    for op_name, fn, _w in ops:
        for col, vals in cols:
            if not vals:
                continue
            try:
                got = fn(vals)
            except Exception:
                continue
            if _close(v, got, dec, rel=REL_TOL):
                claim.binding = "derived"
                claim.operation = op_name
                claim.inputs = (col, f"n={len(vals)}")
                claim.evidence_path = col
                claim.reason = f"{op_name} of {len(vals)} values in {col} = {got:.6g}"
                return True

    # percentages and changes, only where the prose says so
    is_pct = claim.unit in ("%", "percent", "percentage")
    if is_pct or _sentence_mentions(claim.sentence, _CHANGE_WORDS):
        pool = [(x, p) for x, p in idx.floats if x is not None][:120]
        pool += [(float(n), name) for name, n in list(idx.counts.items())[:60]]
        for a, pa in pool:
            for b, pb in pool:
                if pa == pb or b == 0:
                    continue
                if is_pct:
                    share = 100.0 * a / b
                    if _close(v, share, dec, rel=REL_TOL) or abs(v - share) <= PCT_TOL_PP:
                        claim.binding = "derived"
                        claim.operation = "percentage"
                        claim.inputs = (pa, pb)
                        claim.evidence_path = pa
                        claim.reason = f"100 x {pa} / {pb} = {share:.4g}%"
                        return True
                    change = 100.0 * (a - b) / abs(b)
                    if _close(v, change, dec, rel=REL_TOL) or abs(v - change) <= PCT_TOL_PP:
                        claim.binding = "derived"
                        claim.operation = "percent_change"
                        claim.inputs = (pa, pb)
                        claim.evidence_path = pa
                        claim.reason = f"100 x ({pa} - {pb}) / {pb} = {change:.4g}%"
                        return True
                else:
                    if _close(v, a - b, dec, rel=REL_TOL):
                        claim.binding = "derived"
                        claim.operation = "difference"
                        claim.inputs = (pa, pb)
                        claim.evidence_path = pa
                        claim.reason = f"{pa} - {pb} = {a - b:.6g}"
                        return True
    return False


def _literal_hit(raw: str, idx: EvidenceIndex, *, loose: bool = False) -> bool:
    """Does the evidence carry this token as a token, not as a coincidence of digits?

    Measured on the recorded bank: a plain substring test bound "10" and "3" against
    ``…test_01`` and ``…2026-08-03T11:31:24`` and declared them evidenced. A guard that
    accepts any short number because its digits occur somewhere in a timestamp is not a
    guard. The match is therefore word-bounded, and a token shorter than three characters
    must be separated by whitespace or punctuation that is not part of a number or a date.
    """
    raw = raw.strip().lower()
    if not raw:
        return False
    if loose:
        # A time or a date is ALREADY a structured token; it may sit inside a compound cell
        # ("Mon-Sun 07:00-22:00") and is still exactly the fact the answer quoted. Measured:
        # the strict boundary rejected every opening hour in the workspace register and
        # reported a correct answer as 22 unevidenced figures.
        pat = re.compile(r"(?<!\d)" + re.escape(raw) + r"(?!\d)")
    else:
        pat = re.compile(r"(?<![\w.:/-])" + re.escape(raw) + r"(?![\w.:/-])")
    for lit in idx.literals:
        if raw in lit and pat.search(lit):
            return True
    return False


#: Clause boundaries. A sentence in these answers routinely carries a positive verdict and an
#: absence side by side -- *"All remaining 16 plant items are operating at or near duty, or no
#: operating data are currently recorded"* -- and testing the WHOLE sentence for a negation
#: let the second half excuse the first. That cost a real finding on the recorded bank
#: (2026-09-18): the 16 was a count no row supported, and it stopped being reported.
_CLAUSE_SPLIT_RE = re.compile(r"[;,]|\s\bor\b\s")


def _in_absence_clause(claim: Claim) -> bool:
    """Is the claim's OWN clause a statement about what the records do not hold?

    Clause, not sentence. The numbers inside an honest decline are the referent the decline
    is about ("no asset reports a filter size for the units on floor 4"), and deleting them
    guts the one behaviour the lanes were hardest to teach -- but a negation two clauses away
    says nothing about this figure.
    """
    sentence = claim.sentence
    raw = claim.raw.strip()
    clauses = [c for c in _CLAUSE_SPLIT_RE.split(sentence) if raw and raw in c]
    if not clauses:
        clauses = [sentence]
    return all(_NEGATION_RE.search(c.lower()) for c in clauses)


def _bind_numeric(claim: Claim, idx: EvidenceIndex) -> None:
    # a literal the evidence carries verbatim (identifiers, dates written out, room numbers)
    if len(claim.raw.strip()) >= 3 and _literal_hit(claim.raw, idx):
        claim.binding = "bound"
        claim.reason = "the figure appears verbatim in a fetched cell"
        claim.evidence_path = "literal"
        return
    if claim.iso_date:
        if claim.iso_date in idx.iso_dates:
            claim.binding = "bound"
            claim.reason = f"date {claim.iso_date} is recorded in the evidence"
            claim.evidence_path = "iso_date"
        else:
            claim.binding = "unbound"
            claim.reason = f"no fetched row records the date {claim.iso_date}"
        return
    if claim.unit == "time":
        if _literal_hit(claim.raw, idx, loose=True):
            claim.binding = "bound"
            claim.reason = "the time appears in a fetched cell"
        else:
            claim.binding = "unbound"
            claim.reason = "no fetched row records this time"
        return
    if claim.value is None:
        claim.binding = "skipped"
        claim.reason = "not a parseable quantity"
        return
    # A figure inside an ABSENCE sentence is not a figure the answer asserts. "The records do
    # not contain any asset that reports a filter size for the units on floor 4" states the 4
    # to say WHICH units it looked for; it claims nothing about a measurement. The universal
    # and inference tests have skipped absence statements since they were written, for the
    # same reason -- this extends the rule to the numbers inside them. Measured 2026-09-18:
    # without it, enforcement deleted the referent out of an honest decline, which turns the
    # one behaviour the lanes were hardest to teach into a defect.
    if _in_absence_clause(claim):
        claim.binding = "skipped"
        claim.reason = "stated inside a clause about what the records do NOT hold"
        return
    path = _lookup(claim.value, claim.decimals, idx)
    if path is not None:
        claim.binding = "bound"
        claim.evidence_path = path
        claim.reason = f"value present in evidence at {path}"
        return
    # An exact row count is the most precise account available of what a figure IS, so it is
    # tried before the loose "these digits occur somewhere" tier. Otherwise "20 records" over
    # twenty rows would be explained by the digits of a record id, which is true and useless.
    if claim.value == int(claim.value) and 0 <= claim.value <= 100000:
        for name, n in idx.counts.items():
            if n == int(claim.value):
                claim.binding = "derived"
                claim.operation = "count"
                claim.inputs = (name,)
                claim.evidence_path = name
                claim.reason = f"equals the number of rows in {name}"
                return
    for v, p in idx.cell_numbers:
        # Magnitudes, not signs. Inside free text a leading "-" is usually a RANGE separator
        # ("100k-250k", "2026-06-16"), not a minus, on both sides of the comparison; insisting
        # on the sign made the upper end of every quoted band read as an invention. A sign
        # that matters comes from a structured value, and those are matched above with it.
        if _close(claim.value, v, claim.decimals) or _close(
            abs(claim.value), abs(v), claim.decimals
        ):
            claim.binding = "bound"
            claim.evidence_path = p
            claim.reason = f"the figure occurs inside the fetched cell at {p}"
            return
    if _try_derive(claim, idx):
        return
    claim.binding = "unbound"
    claim.reason = "no fetched row, and no stated operation over fetched rows, yields this figure"


def _bind_universal(claim: Claim, idx: EvidenceIndex) -> None:
    """A universal is bound only when the property it asserts is a property the rows carry.

    This is the ``containment`` test. "Several assets list probable containment features"
    fails not because the count is wrong but because nothing in any fetched row is about
    containment — the verdict was reasoned from the absence of a field rather than from it.

    Three guards stand in front of that test, because the first draft of it condemned two
    kinds of perfectly honest sentence when it was measured over the recorded bank:

    1. **An absence statement is not a universal claim.** "The records do not contain any
       information about vehicle usage" asserts nothing about the building; it is the honest
       decline this project spent months getting the lanes to produce. Binding it as a
       fabrication would punish exactly the behaviour that is wanted.
    2. **A clause whose subject is not among the fetched fields is out of scope**, not false.
       "these all refer to the same building" is about the answer's own framing, not rows.
    3. Only the PREDICATE is tested, never the whole clause, so an unremarkable verb or a
       proper noun cannot tip a true sentence into UNBOUND.
    """
    sent = claim.sentence.lower()
    if _NEGATION_RE.search(sent):
        claim.binding = "skipped"
        claim.reason = "absence statement — asserts what the records do NOT hold"
        return
    words = [w for w in claim.predicate if w not in _STOPWORDS]
    if not words:
        claim.binding = "skipped"
        claim.reason = "no testable property in the clause"
        return
    known = idx.field_words | idx.value_words

    def recorded(word: str) -> bool:
        return word in known or any(word in k or k in word for k in known if len(k) > 3)

    subject_words = words[: max(1, len(words) // 2)]
    if not any(recorded(w) for w in subject_words):
        claim.binding = "skipped"
        claim.reason = "the clause is not about any fetched field"
        return
    predicate = [w for w in words if w not in subject_words]
    if not predicate:
        claim.binding = "skipped"
        claim.reason = "no predicate to test"
        return
    missing = [w for w in predicate if not recorded(w)]
    if len(missing) == len(predicate):
        claim.binding = "unbound"
        claim.reason = (
            f"'{claim.quantifier}' asserts a property no fetched field records: "
            + ", ".join(missing[:5])
        )
        return
    claim.binding = "bound"
    claim.reason = "the property this clause asserts is a field the evidence carries"


def _bind_inference(claim: Claim, idx: EvidenceIndex) -> None:
    """A conclusion is bound only when every content word in it is something a row records.

    This is the sharpest of the three tests and the one aimed squarely at C7. *"Each of the
    20 records contains a mapped opening and a granted role, **so none lack the basic
    evidence of ownership, purpose**"* — the counts are right, the fields are right, and the
    verdict is about ``ownership`` and ``purpose``, which no fetched field is about. The
    question asked which are orphaned; the answer reasoned from whichever fields happened to
    be present.

    Deliberately narrow: it fires only after an explicit inferential connective, so ordinary
    description is never touched, and never on a conclusion that states an ABSENCE.
    """
    if _NEGATION_RE.search(claim.sentence.lower()):
        claim.binding = "skipped"
        claim.reason = "conclusion states what the records do NOT hold"
        return
    words = [w for w in claim.predicate if w not in _STOPWORDS and len(w) > 3]
    if not words:
        claim.binding = "skipped"
        claim.reason = "no testable content in the conclusion"
        return
    known = idx.field_words | idx.value_words
    missing = [w for w in words if w not in known and not any(w in k or k in w for k in known)]
    if not missing:
        claim.binding = "bound"
        claim.reason = "every term in this conclusion is something the fetched rows record"
        return
    claim.binding = "unbound"
    claim.reason = "the conclusion turns on terms no fetched field records: " + ", ".join(
        missing[:5]
    )


#: Units that mean "minutes" and "hours" to the composite-duration rule below.
_MINUTE_UNITS = ("minutes", "minute", "min", "mins")
_HOUR_UNITS = ("hours", "hour", "hr", "hrs", "h")


def _supported(claim: Claim) -> bool:
    return claim.binding in ("bound", "derived")


def _derive_from_stated(claim: Claim, claims: Sequence[Claim], idx: EvidenceIndex) -> bool:
    """Arithmetic the answer performs IN FRONT OF THE READER, over figures already evidenced.

    Two shapes, both measured on the recorded bank rather than imagined:

    1. **A total of figures stated in the same sentence.** *"Total time required: 45 + 40 + 30
       = 115 minutes"*. The three addends each bind to a row; the total binds to nothing,
       because no row holds it -- the narrator added up. Deleting it deletes the answer to the
       question that was asked, and the arithmetic is right there to check.
    2. **The same duration restated in hours and minutes.** *"115 minutes ... roughly 1 hour
       55 minutes"*. Two claims, one quantity, and the quantity is already supported.

    Both are deliberately narrow: every input must ALREADY be bound or derived, so this can
    only license arithmetic over evidence, never conjure a premise. A figure with no
    supported inputs stays unbound.
    """
    v = claim.value
    if v is None or claim.binding != "unbound":
        return False

    # 1. a total over supported figures in the same sentence
    same = [
        c.value
        for c in claims
        if c is not claim
        and c.kind == "numeric"
        and c.sentence == claim.sentence
        and _supported(c)
        and c.value is not None
    ][:8]
    for size in (2, 3, 4):
        if len(same) < size:
            break
        for combo in _combinations(same, size):
            if _close(v, math.fsum(combo), claim.decimals, rel=REL_TOL):
                claim.binding = "derived"
                claim.operation = "sum_of_stated"
                claim.inputs = tuple(f"{x:g}" for x in combo)
                claim.evidence_path = "stated figures in the same sentence"
                claim.reason = (
                    "equals the sum of figures stated beside it, each of which is evidenced"
                )
                return True

    # 2. an hours-and-minutes restatement of a supported duration
    unit = claim.unit.lower()
    partner: Optional[Claim] = None
    if unit in _MINUTE_UNITS:
        partner = _nearest(claims, claim, _HOUR_UNITS)
        total = (partner.value or 0) * 60 + v if partner else None
    elif unit in _HOUR_UNITS:
        partner = _nearest(claims, claim, _MINUTE_UNITS)
        total = v * 60 + (partner.value or 0) if partner else None
    else:
        total = None
    if total is not None:
        supported_totals = [c.value for c in claims if _supported(c) and c.value is not None]
        supported_totals += [x for x, _p in idx.floats]
        for other in supported_totals:
            if _close(total, other, 0, rel=REL_TOL):
                claim.binding = "derived"
                claim.operation = "duration_restated"
                claim.inputs = (f"{total:g} minutes",)
                claim.evidence_path = "restated duration"
                claim.reason = f"the same duration as the evidenced {total:g} minutes"
                return True
    return False


def _nearest(claims: Sequence[Claim], claim: Claim, units: Sequence[str]) -> Optional[Claim]:
    """The closest claim before or after ``claim`` carrying one of ``units``, within a clause."""
    best: Optional[Claim] = None
    for c in claims:
        if c is claim or c.kind != "numeric" or c.unit.lower() not in units:
            continue
        if abs(c.start - claim.start) > 40:
            continue
        if best is None or abs(c.start - claim.start) < abs(best.start - claim.start):
            best = c
    return best


def _combinations(values: Sequence[float], size: int):
    from itertools import combinations

    return combinations(values, size)


def _question_figures(question: str) -> Set[str]:
    """The figures the ASKER stated, as written.

    A number the question supplies and the answer repeats back is not a claim the building's
    records have to support: it is the referent. Measured 2026-09-18 on the recorded bank,
    enforcement deleted *"your 9 a.m. lecture"* and *"the units on floor 4"* out of two honest
    answers, because neither 9 nor 4 was in any row -- they were in the question.
    """
    if not question:
        return set()
    masked = question.translate(_NORMALISE_TABLE)
    return {m.group(0).rstrip(",.") for m in _NUM_RE.finditer(masked)}


def _mark_structural(claim: Claim, answer: str, question_figures: Set[str]) -> bool:
    """Numbers that are page furniture, not assertions about the building."""
    if claim.kind != "numeric":
        return False
    if question_figures and claim.raw.strip().rstrip(",.") in question_figures:
        claim.binding = "skipped"
        claim.reason = "the question states this figure"
        return True
    line_start = answer.rfind("\n", 0, claim.start) + 1
    prefix = answer[line_start : claim.start]
    if re.fullmatch(r"[ \t>*+\-]*", prefix) and claim.value is not None:
        # a bare bullet number at the head of a line, with a delimiter after it
        after = answer[claim.end : claim.end + 2]
        if after[:1] in (".", ")") and claim.value == int(claim.value):
            claim.binding = "skipped"
            claim.reason = "list marker"
            return True
    return False


def bind_claims(
    claims: Sequence[Claim], idx: EvidenceIndex, answer: str, question: str = ""
) -> None:
    """Classify every claim in place."""
    qfigs = _question_figures(question)
    for claim in claims:
        if _mark_structural(claim, answer, qfigs):
            continue
        if not idx.available:
            claim.binding = "skipped"
            claim.reason = "this turn recorded no fetched rows to bind against"
            continue
        try:
            if claim.kind == "universal":
                _bind_universal(claim, idx)
            elif claim.kind == "inference":
                _bind_inference(claim, idx)
            else:
                _bind_numeric(claim, idx)
        except Exception as exc:  # a binder that raises must not condemn the claim
            claim.binding = "skipped"
            claim.reason = f"binding failed: {type(exc).__name__}"
            logger.debug(f"[claim_binder] bind failed on {claim.raw!r}: {exc}")

    # SECOND PASS, and it has to be second: arithmetic over evidenced figures can only be
    # judged once it is known which figures are evidenced. One pass would have to guess, and
    # the first version of the rule that guessed licensed a total from its own addends
    # whether or not any of them was a row.
    if not idx.available:
        return
    for claim in claims:
        if claim.kind != "numeric" or claim.binding != "unbound":
            continue
        try:
            _derive_from_stated(claim, claims, idx)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(f"[claim_binder] stated-arithmetic pass failed: {exc}")


# ── is this turn's record complete enough to enforce over? ───────────────────

#: The three states of a turn's evidence record.
EV_COMPLETE = "complete"
EV_PARTIAL = "partial"
EV_ABSENT = "absent"

#: Lanes whose evidence is a PASSAGE, not rows. A figure in one of their answers is either a
#: number the lane computed (and, since CAVEAT-769, recorded) or a number quoted out of prose
#: that this module deliberately refuses to read. Neither is a row, so enforcement over one of
#: these is only defensible when the lane filed computed figures for the turn.
_PROSE_LANES = frozenset({"capability_result", "document_result", "goal_plan"})

#: Field words that mean "a stored series was referenced here". If one is present and no
#: store lane produced rows, the turn read a store this record cannot see, and figures drawn
#: from it will look invented. Same test as ``scripts/measure_claim_binding._STORE_VARS``,
#: which is where the shape was first measured.
_STORE_REFERENCE_WORDS = frozenset({"uuid", "timeseries"})

#: Lanes that answer FROM a store read.
_STORE_LANES = ("sql_result", "analytics_result", "forecast_result")

#: Above this share of unaccounted-for numerics, the likeliest explanation is that the binder
#: cannot see the evidence -- not that the lane invented most of its answer. Measured on the
#: one live enforcement run: the lanes that broke logged 17/19, 99/123 and 9/16 unbound, all
#: with correct answers, while the recorded 147-question bank's complete-evidence turns sit at
#: 8.2%. A guard 50% of whose findings would have to be fabrications is not reading the turn.
_BLINDNESS_SHARE = 0.5

#: Below this many assessed numeric claims a share is noise ("1 of 2 unbound" is 50%).
_BLINDNESS_MIN_NUMERIC = 4


@dataclass
class Completeness:
    """Whether this turn's record is good enough to REWRITE an answer against.

    The principle is already written down in ``absence_guard``: *a guard that cannot verify
    has no business rewriting an answer.* It was not applied here, and the one live
    enforcement run deleted five correct figures in 25 minutes. So enforcement is now
    conditional, the condition is stated, and a turn that fails it degrades to record-only
    with the reason attached rather than silently doing nothing or silently doing damage.
    """

    status: str
    reason: str = ""

    @property
    def enforceable(self) -> bool:
        return self.status == EV_COMPLETE

    def as_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "reason": self.reason, "enforceable": self.enforceable}


def _lane_has_rows(results: Dict[str, Any], key: str) -> bool:
    try:
        from orchestrator.services.evidence.assemble import lane_produced_evidence

        return bool(lane_produced_evidence(key, results.get(key)))
    except Exception:
        return bool(results.get(key))


def assess_completeness(
    results: Dict[str, Any],
    idx: EvidenceIndex,
    lane: str,
    claims: Sequence[Claim],
) -> Completeness:
    """Is the turn's evidence complete FOR THE LANE THAT ANSWERED?

    Four ways it is not, each one measured rather than supposed:

    1. **Nothing was recorded.** Every claim is already SKIPPED; there is nothing to enforce
       and no basis on which to.
    2. **No lane declared evidence.** Then this module does not know what the answer rests
       on, and an answer whose source is unknown is not one to start deleting sentences from.
    3. **A stored series was referenced and its rows are not here.** The projection names a
       timeseries, no store lane produced rows, and every figure read out of that store would
       look invented. This is the PARTIAL bucket the offline measurement already reports
       separately; it now also withholds enforcement rather than merely footnoting it.
    4. **The binder accounted for almost nothing.** Most of the figures unbound is far more
       likely to mean the record is missing than that the lane fabricated its answer -- and
       on the single live enforcement run, it meant exactly that, three times.

    Returns COMPLETE only when none of the four applies.
    """
    if not idx.available:
        return Completeness(EV_ABSENT, "this turn recorded no fetched rows or computed figures")
    if not lane or lane == "unknown":
        return Completeness(EV_ABSENT, "no lane recorded evidence for this turn")

    has_computed = bool((results.get("computed_figures") or {}).get("sources"))
    if lane in _PROSE_LANES and not has_computed:
        return Completeness(
            EV_PARTIAL,
            f"the {lane} lane answers from a passage, and no figure it computed was recorded",
        )

    if idx.field_words & _STORE_REFERENCE_WORDS and not any(
        _lane_has_rows(results, k) for k in _STORE_LANES
    ):
        return Completeness(
            EV_PARTIAL,
            "a stored series is referenced but its readings are not in this turn's record",
        )

    numerics = [c for c in claims if c.kind == "numeric" and c.binding != "skipped"]
    unbound = [c for c in numerics if c.binding == "unbound"]
    if len(numerics) >= _BLINDNESS_MIN_NUMERIC and len(unbound) / len(numerics) >= _BLINDNESS_SHARE:
        return Completeness(
            EV_PARTIAL,
            f"{len(unbound)} of {len(numerics)} figures could not be accounted for, which "
            "indicates a missing record rather than an invented answer",
        )
    return Completeness(EV_COMPLETE, "the lane that answered recorded what its figures rest on")


# ── enforcement ──────────────────────────────────────────────────────────────

#: Said in the reader's terms. No jargon, no lane names, and nothing about how the data was
#: produced — the owner's standing rule keeps provenance words out of user-visible text.
_REMOVED_ONE = (
    "\n\n_One figure has been left out of this answer: the records behind it do not "
    "support it, so I would rather not state it._"
)
_REMOVED_MANY = (
    "\n\n_{n} figures have been left out of this answer: the records behind them do not "
    "support them, so I would rather not state them._"
)
_CAVEAT_UNIVERSAL = (
    "\n\n_One statement above goes further than the records do — nothing recorded covers "
    "{what}, so treat that part as unconfirmed._"
)
_NOTHING_LEFT = (
    "I found records for this, but I could not evidence the figures I was about to give you, "
    "so I am not going to state them. Ask for the underlying records and I will show those "
    "instead."
)


def _redact(answer: str, claims: Sequence[Claim]) -> Tuple[str, List[str]]:
    """Remove the sentence carrying each unbound numeric claim.

    The SENTENCE, not the number. An answer with a number cut out of it reads as a fabrication
    with a hole in it, and the surrounding clause ("so none lack the basic evidence") is
    exactly the part that was invented.
    """
    bad = [c for c in claims if c.kind == "numeric" and c.binding == "unbound"]
    if not bad:
        return answer, []
    spans: List[Tuple[int, int]] = []
    notes: List[str] = []
    for c in bad:
        s, e = _sentence_bounds(answer, c.start)
        spans.append((s, e))
        notes.append(f"removed {c.raw!r} ({c.reason})")
    spans.sort()
    merged: List[Tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    out = []
    prev = 0
    for s, e in merged:
        out.append(answer[prev:s])
        prev = e
    out.append(answer[prev:])
    text = re.sub(r"[ \t]{2,}", " ", "".join(out))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, notes


def _apply_enforcement(report: ClaimBindingReport) -> None:
    text, notes = _redact(report.original_answer, report.claims)
    n = len(notes)
    if n:
        report.notes.extend(notes)
        if not re.search(r"[A-Za-z]{3}", text):
            text = _NOTHING_LEFT
        else:
            text += _REMOVED_ONE if n == 1 else _REMOVED_MANY.format(n=n)
    unsupported = [
        c for c in report.claims if c.kind in ("universal", "inference") and c.binding == "unbound"
    ]
    if unsupported:
        what = ", ".join(
            sorted({w for c in unsupported for w in c.reason.split(": ")[-1].split(", ")})[:3]
        )
        if what:
            text += _CAVEAT_UNIVERSAL.format(what=what)
            report.notes.append(f"caveat added for unsupported property: {what}")
    report.answer = text
    report.changed = text != report.original_answer


# ── the one entry point ──────────────────────────────────────────────────────


#: Bus keys that may carry the question, best first. The response node does not currently put
#: the user's message on the bus; ``run(..., question=...)`` is the direct route and this is
#: the fallback for the shapes that are already there (a rewritten follow-up keeps both).
_QUESTION_KEYS = ("user_message", "user_query", "question", "standalone_query")


def _question_from(results: Dict[str, Any]) -> str:
    """The question this answer is answering, if the bus happens to carry it."""
    for key in _QUESTION_KEYS:
        val = results.get(key)
        if isinstance(val, str) and val.strip():
            return val
    coref = results.get("coref_rewrite")
    if isinstance(coref, dict):
        parts = [str(coref.get(k) or "") for k in ("original", "rewritten")]
        joined = " ".join(p for p in parts if p)
        if joined.strip():
            return joined
    return ""


def analyse(
    answer: str,
    results: Optional[Dict[str, Any]] = None,
    *,
    mode: Optional[str] = None,
    lane: str = "",
    question: str = "",
    require_complete_evidence: bool = True,
) -> ClaimBindingReport:
    """Extract, bind and (in enforce mode) rewrite. Pure: no I/O, no clock, no settings.

    ``require_complete_evidence=False`` reproduces the behaviour that ran live for 25 minutes
    on 2026-09-18 -- enforce whatever the record looks like. It exists so the offline replay
    can measure the two side by side rather than describing the old one from memory, and
    nothing in the running system passes it.
    """
    mode = mode or current_mode()
    results = results if isinstance(results, dict) else {}
    results = _with_computed_figures(results)
    idx = build_evidence_index(results)
    if not lane:
        try:
            from orchestrator.services.evidence.assemble import infer_lane

            lane = infer_lane(results) or ""
        except Exception:
            lane = ""
    report = ClaimBindingReport(
        mode=mode,
        lane=lane or "unknown",
        evidence_available=idx.available,
        answer=answer,
        original_answer=answer,
        evidence=idx.summary(),
    )
    if mode == MODE_OFF:
        return report
    report.claims = extract_claims(answer)
    bind_claims(report.claims, idx, answer, question or _question_from(results))
    report.completeness = assess_completeness(results, idx, report.lane, report.claims)
    if mode == MODE_ENFORCE:
        if report.completeness.enforceable or not require_complete_evidence:
            report.enforced = True
            _apply_enforcement(report)
        else:
            # RECORD-ONLY FOR THIS TURN, and the record says why. Enforcing over a record
            # that cannot account for the answer is how five correct figures were deleted in
            # 25 minutes (CAVEAT-769); leaving an unbound figure standing is the cheaper
            # error, and this module's whole trade is precision over coverage.
            report.notes.append(
                f"enforcement withheld ({report.completeness.status}): "
                f"{report.completeness.reason}"
            )
    return report


def run(
    answer: str,
    results: Optional[Dict[str, Any]] = None,
    *,
    mode: Optional[str] = None,
    question: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """What the response node calls: ``(text_to_send, record_to_store)``.

    Never raises and never returns an empty answer. A binder that could take the answer down
    with it would turn an honesty check into an outage, which is a strictly worse trade than
    the defect it guards.
    """
    try:
        report = analyse(answer, results, mode=mode, question=question)
    except Exception as exc:
        logger.warning(f"[claim_binder] skipped: {type(exc).__name__}: {exc}", exc_info=True)
        return answer, {"mode": "error", "error": f"{type(exc).__name__}: {exc}"}
    # `enforced`, not `mode`: a turn in enforce mode whose record was incomplete was never
    # rewritten, and reading the mode instead of what actually happened is how a flag comes
    # to be believed rather than measured.
    text = report.answer if report.enforced else answer
    if not str(text or "").strip():
        text = answer
    counts = report.counts()
    if counts.get("unbound"):
        # WARNING: an unevidenced figure reaching a reader is the defect this project's
        # largest family is made of. At DEBUG it would be measured by nobody.
        logger.warning(
            "[claim_binder] mode=%s lane=%s evidence=%s unbound=%d/%d "
            "(numeric=%d universal=%d) enforced=%s changed=%s%s",
            report.mode,
            report.lane,
            report.completeness.status if report.completeness else "unassessed",
            counts["unbound"],
            counts["total"],
            counts["unbound_numeric"],
            counts["unbound_universal"],
            report.enforced,
            report.changed,
            (
                ""
                if report.enforced or report.mode != MODE_ENFORCE
                else f" withheld: {report.completeness.reason if report.completeness else ''}"
            ),
        )
    else:
        logger.info(
            "[claim_binder] mode=%s lane=%s evidence=%s claims=%d bound=%d derived=%d "
            "skipped=%d",
            report.mode,
            report.lane,
            report.completeness.status if report.completeness else "unassessed",
            counts["total"],
            counts["bound"],
            counts["derived"],
            counts["skipped"],
        )
    return text, report.as_dict()
