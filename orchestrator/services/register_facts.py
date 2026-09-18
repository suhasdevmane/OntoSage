"""Facts about a register, counted in code, handed to the narration verbatim (BUG-581).

The whole-register handover gives the model every row and tells it not to re-derive a status
from dates. Rehearsed three times through Open WebUI on 2026-09-15, the same question over the
same 24 work orders produced three answers — "9 open, all 9 overdue" (the register records no
due date at all), "the records do not say", and "3 open" — and a refuge-point question listed
an evacuation CHAIR as a defective refuge point one run in three. The rows were right each
time; the counting and the filtering were the model's, and an instruction does not make a
language model count.

So the bookkeeping is done here, from every row, and the narration is told to use it:
  * how many records hold each recorded status;
  * for every ``…Kind`` column, the same split within each kind, with record ids — so
    "which refuge points are defective" is a lookup, not a filter the model performs;
  * when the question asks what is OVERDUE: either the dates a ``…Due`` column holds that have
    passed, or a plain statement that nothing in the register records a due date.

Nothing here knows a register, a class or a building: columns are recognised by the shape of
their names (``recordStatus``, a ``Kind`` suffix, a ``Due`` suffix or ``deadline``), which is
how the record-document lifter names them for every register it lifts.

THE SECOND ROUND (BUG-709) follows the same argument one step further. In the 2026-09-17 hand
read of 147 live answers, 20 were this shape: the right records, and a conclusion the fields do
not hold — an orphan verdict reasoned from the fields that happened to be present, containment
features "listed" by a register with no containment field, a due date computed two different
wrong ways in one answer, a fill threshold read as an instruction to fill a clinical sharps
bin, two rooms filed under a floor neither their floor field nor their own room number gives.
Each of those is an OPERATION performed in prose. So each is performed here instead — which of
the things the question names the register records at all, which records lack a field, what
values a field actually holds, what a last-seen date plus an interval comes to, where the
register contradicts itself, which floor a record is on, and that no record says who the reader
is. The narration is handed the result; it is not asked to derive it.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

STATUS = "recordStatus"
ID_FIELDS = ("recordId", "label")
MAX_KIND_VALUES = 12
MAX_IDS_LISTED = 15

_OVERDUE_RE = re.compile(
    r"\b(overdue|past\s+due|late|behind\s+schedule|out\s+of\s+date|lapsed)\b", re.I
)
_DUE_COLUMN_RE = re.compile(r"(due|deadline)$", re.I)
_CLOSED_STATUSES = {"completed", "closed", "void", "cancelled", "canceled", "withdrawn", "retired"}

#: Fields the lifter stamps on every record — provenance, not content anyone asks about.
_PROVENANCE_FIELDS = frozenset(
    {
        "recordId",
        "recordOwner",
        "recordVersion",
        "owningAuthority",
        "retrievedAt",
        "derivedFromDocument",
        "liftedByMapping",
        "isSimulated",
        "effectiveFrom",
        "label",
        "comment",
        "type",
    }
)


#: `effectiveFrom` is the ONE ambiguous column. The lifter stamps it from a register's front
#: matter ONLY when the row has no mapped column of its own (record_documents.py), so in ten
#: registers — permits, bookings, condition surveys, contracts, handovers — it holds the
#: record's REAL date, and everywhere else it is one date repeated on every row.
#:
#: Treating it as provenance in both cases cost real answers: "when was the last project
#: handover?" was answered "the records do not contain dates for handovers" while the register
#: carried an `issued` date for every row (BUG-639).
#:
#: The test is the data, not a mapping lookup: a column whose value is the SAME on every
#: record carries no per-record fact and is a stamp; one that varies is content.
_AMBIGUOUS_STAMPS = frozenset({"effectiveFrom"})


def carries_per_record_content(rows: List[Dict], column: str) -> bool:
    """True when this column's values differ between records."""
    seen = set()
    for row in rows or []:
        v = _value(row, column)
        if v:
            seen.add(v)
            if len(seen) > 1:
                return True
    return False


def provenance_fields(rows: List[Dict]) -> frozenset:
    """The stamp columns FOR THESE ROWS — ambiguous ones judged by whether they vary."""
    content = {c for c in _AMBIGUOUS_STAMPS if carries_per_record_content(rows, c)}
    return frozenset(_PROVENANCE_FIELDS - content) if content else _PROVENANCE_FIELDS


def _value(row: Dict, field: str) -> str:
    cell = row.get(field)
    if isinstance(cell, dict):
        cell = cell.get("value")
    return str(cell).strip() if cell not in (None, "") else ""


def _ident(row: Dict) -> str:
    for field in ID_FIELDS:
        v = _value(row, field)
        if v:
            return v
    return "?"


#: EVERY group is named, not just the small ones (run 5, 2026-09-18). The largest group used
#: to be given as a bare count, so the narration had to work out for itself which records were
#: in it — and it got that wrong in four measured answers: a funding list headed "high — 9
#: assets" over a table of 8 with AEP-009 and AEP-014 in no table at all, and a workspace table
#: placing WS-15, WS-16 and WS-01 under two kinds each, 31 placements for 28 records. A count
#: the writer cannot check against a list is a count the writer will contradict.
MAX_IDS_IN_GROUP = 20


def _named(rows: List[Dict]) -> str:
    """ "(A, B, C)" while the group is small enough to name every member of it."""
    ids = sorted(_ident(r) for r in rows)
    if not ids or len(ids) > MAX_IDS_IN_GROUP:
        return ""
    return f" ({', '.join(ids)})"


def _split(rows: List[Dict]) -> str:
    counts = Counter(_value(r, STATUS) or "(no status)" for r in rows)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    parts = []
    for status, n in ordered:
        members = [r for r in rows if (_value(r, STATUS) or "(no status)") == status]
        parts.append(f"{status} {n}{_named(members)}")
    return ", ".join(parts)


#: A question about the ABSENCE of something: "which have no X", "without X", "lack X".
_ASKS_ABSENCE_RE = re.compile(
    r"\b(?:no|without|lack|lacks|lacking|missing|absent|none|not\s+(?:have|covered|provided))\b",
    re.IGNORECASE,
)

#: A recorded value that SAYS the thing is absent. "No cover, next working day" is a real
#: answer to "what happens out of hours", and it means there is none.
_NONE_LIKE_RE = re.compile(
    r"^\s*(?:no\b|none\b|nil\b|n/?a\b|not\s+(?:available|provided|recorded|applicable)"
    r"|without\b|-{1,2}$)",
    re.IGNORECASE,
)


def _absence_lines(rows, col, question):
    """Records whose value for ``col`` SAYS there is none, when the question asks for those."""
    if not _ASKS_ABSENCE_RE.search(question or ""):
        return []
    absent = [r for r in rows if _NONE_LIKE_RE.match(_value(r, col))]
    if not absent:
        return []
    ids = sorted(_ident(r) for r in absent)
    shown = ", ".join(ids[:MAX_IDS_LISTED])
    return [
        f"  - of those, {len(absent)} record(s) state that there is NONE (a value such as "
        f'"{_value(absent[0], col)[:40]}"): {shown}. A recorded value can say the thing is '
        f"absent; those records are the answer to a question asking which have no {col}."
    ]


#: "how long since", "longest blind interval", "rarely visited", "overdue for a visit".
_ELAPSED_RE = re.compile(
    r"\b(?:longest|rarely|seldom|blind|how\s+long\s+since|since\s+(?:it|they)\s+(?:was|were)"
    r"|not\s+been\s+(?:visited|inspected|checked)|unvisited|uninspected)\b",
    re.IGNORECASE,
)

#: A date column recording when something last happened, and an interval column saying how
#: often it should. Registers record the pair instead of a due date about as often as not.
_LAST_COLUMN_RE = re.compile(r"^last[A-Z_]|lastvisited|lastcompleted|lasttested", re.IGNORECASE)
_INTERVAL_COLUMN_RE = re.compile(r"interval", re.IGNORECASE)


#: "slower than", "longer than" — a question asking the system to compare two recorded numbers
#: across every row. The word says which way round: a step-free route that is SLOWER has the
#: larger number, one that is FASTER has the smaller.
_GREATER_RE = re.compile(
    r"\b(slower|longer|greater|larger|higher|more|worse|bigger)\s+than\b", re.IGNORECASE
)
_SMALLER_RE = re.compile(
    r"\b(faster|shorter|lower|less|better|smaller|quicker)\s+than\b", re.IGNORECASE
)


def _as_number(value: str) -> Optional[float]:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _endpoint_columns(rows, columns):
    """Two columns describing the ends of one journey — from/to, origin/destination.

    Found by their VALUES, not their names: a pair of columns drawn from the same small
    vocabulary (the building's floors) is a pair of endpoints whatever a register calls them.
    """
    vocab = {}
    _prov = provenance_fields(rows)
    for col in columns:
        if col in _prov or col == STATUS or col == "record":
            continue
        values = [_value(r, col) for r in rows if _value(r, col)]
        distinct = set(values)
        # Short and REPEATED: the shape of a place name. A floor is as often recorded as `3`
        # as "Level 3", so numbers are not excluded — the first version of this excluded them
        # and missed the only register in the building that has endpoints (BUG-624). Values
        # unique to each row are identifiers or free text, and are excluded by the repetition
        # test; unrelated columns are excluded by the overlap test below.
        if (
            len(distinct) >= 2
            and len(distinct) < len(values)
            and all(len(v) <= 40 for v in distinct)
        ):
            vocab[col] = distinct
    names = sorted(vocab)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            shared = vocab[a] & vocab[b]
            if shared and len(shared) >= 0.6 * min(len(vocab[a]), len(vocab[b])):
                return a, b
    return None


def _comparison_lines(rows, columns, question):
    """Count a comparison the question asks for, instead of leaving it to the narration.

    "On which floor pairs is the step-free route slower than the stair route?" was answered
    "15 of 21" — true of the ROWS and false of the question, because six of those fifteen are
    same-floor routes, which have no stair alternative to be slower than (BUG-624). The same
    register answered "nine" the day before: an arithmetic question settled by whichever way
    the narration read it is not settled at all (BUG-581).
    """
    wants_greater = bool(_GREATER_RE.search(question or ""))
    if not wants_greater and not _SMALLER_RE.search(question or ""):
        return []
    # The endpoints come out FIRST: a floor recorded as `3` is a place, not a measurement, and
    # counting it among the numbers made this bail out on the one register it was written for.
    ends = _endpoint_columns(rows, columns)
    _prov = provenance_fields(rows)
    numeric = [
        c
        for c in columns
        if c not in _prov
        and (not ends or c not in ends)
        and sum(1 for r in rows if _as_number(_value(r, c)) is not None) >= max(2, len(rows) // 2)
    ]
    if len(numeric) != 2:
        # Two is the case a comparative names unambiguously. More, and picking a pair would be
        # guessing which two the question meant.
        return []
    asked = set(re.findall(r"[a-z]+", (question or "").lower()))
    named = [c for c in numeric if asked & {w.lower() for w in re.findall(r"[A-Za-z][a-z]+", c)}]
    if len(named) != 1:
        return []
    subject = named[0]
    other = numeric[0] if numeric[1] == subject else numeric[1]

    lines = []
    same_place = []
    if ends:
        a, b = ends
        same_place = [r for r in rows if _value(r, a) and _value(r, a) == _value(r, b)]

    def _holds(row):
        x, y = _as_number(_value(row, subject)), _as_number(_value(row, other))
        if x is None or y is None:
            return False
        return x > y if wants_greater else x < y

    eligible = [r for r in rows if r not in same_place]
    matching = [r for r in eligible if _holds(r)]
    word = "greater than" if wants_greater else "less than"
    ids = sorted(_ident(r) for r in matching)
    line = (
        f"- {subject} is {word} {other} on {len(matching)} of the {len(eligible)} records "
        f"that compare two different places"
    )
    if ids and len(ids) <= MAX_IDS_LISTED:
        line += f": {', '.join(ids)}"
    lines.append(line + ". State that count; do not recount from the rows.")
    if same_place:
        a, b = ends  # type: ignore[misc]
        lines.append(
            f"- {len(same_place)} further records have the same {a} and {b}, so they are not a "
            f"pair of places and have no alternative route to be compared with. They are "
            f"EXCLUDED from the count above and must not be listed as an answer."
        )
    return lines


def _elapsed_lines(rows, columns, question, today):
    """How long since each record was last seen, and by how far that passes its interval.

    A register that records `last_visited` + `inspection_interval_days` states the answer to
    "which rarely visited areas have the longest blind interval" only after a subtraction, and
    the narration did the wrong one: it ranked by the interval VALUE (365 days) and named a
    meter that is not yet due, over an exhaust fan 369 days unseen against a 180-day interval.
    """
    if today is None or not _ELAPSED_RE.search(question or ""):
        return []
    last_cols = [c for c in columns if _LAST_COLUMN_RE.search(c)]
    interval_cols = [c for c in columns if _INTERVAL_COLUMN_RE.search(c)]
    if not last_cols:
        return []
    col = last_cols[0]
    interval_col = interval_cols[0] if interval_cols else ""
    scored = []
    for r in rows:
        raw = _value(r, col)[:10]
        try:
            elapsed = (today - date.fromisoformat(raw)).days
        except ValueError:
            continue
        over = None
        if interval_col:
            try:
                over = elapsed - int(float(_value(r, interval_col)))
            except (TypeError, ValueError):
                over = None
        scored.append((elapsed, over, _ident(r), raw))
    if not scored:
        return []
    scored.sort(key=lambda t: -t[0])
    out = [
        f"- Days since {col} on {today.isoformat()} (computed by the system; longest first): "
        + "; ".join(
            f"{ident} {elapsed}d"
            + (f" ({over:+d}d against its {interval_col})" if over is not None else "")
            for elapsed, over, ident, _raw in scored[:8]
        )
        + "."
    ]
    if interval_col:
        beyond = sorted((t for t in scored if t[1] is not None and t[1] > 0), key=lambda t: -t[1])
        if beyond:
            out.append(
                f"- PAST its {interval_col}: "
                + "; ".join(f"{ident} by {over}d" for _e, over, ident, _r in beyond[:8])
                + ". 'Longest unseen' means this, not the largest interval VALUE: a record with a "
                "long interval that is still within it is not overdue."
            )
    return out


# --------------------------------------------------------------------------------------
# WHAT THE QUESTION NAMES, AGAINST WHAT THE REGISTER RECORDS (BUG-709).
#
# The largest defect class in the 2026-09-17 hand read of 147 live answers: 20 rows where the
# lane fetched the RIGHT records and the narration reasoned its way to a conclusion the fields
# do not hold. "Each of the 20 records contains a mapped opening and a granted role, SO NONE
# LACK the basic evidence of ownership, purpose" — for a question asking which permission
# groups are orphaned for want of an owner and a purpose, neither of which any column records.
# "Assets list PROBABLE CONTAINMENT FEATURES that would limit damage from a leak" — where the
# word containment appears only inside a note about which services run through a ceiling void.
# A one-off lab permit read as a "verified starter" package; an inspection interval offered to
# an engineer as a trend sampling rate; `recordStatus` relabelled "Condition" and a capital
# value band "Whole-life cost".
#
# Every one of those is the same operation done in prose: deciding whether the register holds
# the thing the question names. So it is done here instead — each content word of the question
# is matched against the column names, and then against the recorded text, and the narration is
# handed three lists it cannot argue with: recorded as a field, present only as free text, and
# not recorded at all.
# --------------------------------------------------------------------------------------

#: Words that carry no concept to look for. Question words, modals, and the register-speak
#: every one of these questions is phrased in.
_STOPWORDS = frozenset(
    """
    about above after again against also always another anything appear are around asked
    available back because been before being below best better both building buildings call
    called can cannot come complete could current currently data date dates day days describe
    detail details did does doing done down during each either else enough etc even ever every
    everything except explain field fields first following from full further get give given
    goes going good got had has have having help her here him his hold holds how however
    information into its itself just keep kept know known last least less let like likely list
    lists look made make makes many may mean means might more most much must name named names
    need needed needs never new next nor not note now number numbers off often once one only
    other others our out over own particular per place places please provide provided put
    quite rather really record recorded records register registers relevant report reported
    reports right said same say says see seem seen set several shall she should show shows
    side since some something soon still such sure take taken tell than that the their them
    then there these they thing things this those three through time times today too took
    total two under until upon use used using usually very via want was way ways well were
    what whatever when where whether which while who whom whose why will with within without
    work working would yes yet you your yours
    """.split()
)

_WORD_RE = re.compile(r"[a-z][a-z]*(?:-[a-z]+)*")

MAX_TERMS_LISTED = 10
MAX_VALUES_SPLIT = 8
MAX_SPLIT_LINES = 4


def _content_columns(rows: List[Dict], columns: List[str]) -> List[str]:
    """The columns that say something ABOUT the records, not where the rows came from."""
    prov = provenance_fields(rows)
    return [c for c in columns if c not in prov and c not in {"record", STATUS}]


def _col_tokens(col: str) -> set:
    return {t.lower() for t in re.findall(r"[A-Za-z][a-z]*", col)}


def _col_flat(col: str) -> str:
    return re.sub(r"[^a-z]", "", col.lower())


def _shared_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _term_matches_column(term: str, col: str) -> bool:
    """Does this question word name this column? Matched on stems, so 'dependencies' finds
    ``dependsOnSpace`` and 'commissioning' finds ``commissionedDuty``."""
    flat = term.replace("-", "")
    if len(flat) >= 5 and flat in _col_flat(col):
        return True
    for tok in _col_tokens(col):
        if tok == flat or _shared_prefix(tok, flat) >= 5:
            return True
    return False


def _term_pattern(term: str) -> "re.Pattern":
    """A stem match: the first six letters, on a word boundary."""
    return re.compile(r"\b" + re.escape(term.replace("-", " ")[:6]), re.IGNORECASE)


def _term_in_text(rows: List[Dict], columns: List[str], term: str) -> List[str]:
    """WHICH records carry this word inside recorded text, with no column named for it.

    A COUNT WAS NOT ENOUGH, measured 2026-09-18. "Who do I contact about a broken door closer"
    was told, correctly, that no field is named for a door and that the word occurs on 2
    records — and then declined, because the two records were never named and so could not be
    used. The records these questions want are exactly these; naming them is what turns the
    census from a limit into the way in.
    """
    pattern = _term_pattern(term)
    return [r for r in rows if any(pattern.search(_value(r, c)) for c in columns)]


def _plain(col: str) -> str:
    """A field's name in ordinary words: ``respondsWithinHours`` -> "responds within hours".

    The handover table's own headers are the internal names, so the answer can read one off
    and print it at a stakeholder, which it did. Every line the system writes gives the plain
    wording alongside, so there is always a form to copy that is not an identifier.
    """
    words = [w.lower() for w in re.findall(r"[A-Za-z][a-z]*|\d+", col)]
    if words and words[0] in ("is", "has", "on", "in", "of"):
        words = words[1:] or words
    return " ".join(words)


def _term_is_a_status_value(rows: List[Dict], term: str) -> bool:
    """'overdue' is not an unrecorded concept in a register that records it as a status."""
    pattern = _term_pattern(term)
    return any(pattern.search(_value(r, STATUS)) for r in rows)


def _question_terms(question: str, register_label: str) -> List[Tuple[str, Optional[str]]]:
    """Content words of the question, each with the compound it came out of, if any.

    A hyphenated compound is kept WHOLE and also split, because "step-free" finds
    ``isStepFree`` only unsplit and "water-supply" finds nothing either way. But a half of a
    compound is never reported as missing on its own: "whole-life cost" is one idea, and
    announcing that "whole" and "life" are not recorded is noise, not a finding.
    """
    label_words = {w.lower() for w in re.findall(r"[A-Za-z]+", register_label or "")}
    out: List[Tuple[str, Optional[str]]] = []
    seen = set()
    for raw in _WORD_RE.findall((question or "").lower()):
        parts = raw.split("-") if "-" in raw else []
        for term in [raw] + parts:
            flat = term.replace("-", "")
            if len(term) < 4 or flat in _STOPWORDS or term in seen:
                continue
            # A word the register is NAMED for says nothing about which fields it holds.
            if any(w == flat or _shared_prefix(w, flat) >= 5 for w in label_words):
                continue
            seen.add(term)
            out.append((term, raw if term in parts else None))
    return out


def _term_census_lines(rows, columns, question, register_label):
    """Which of the things the question names the register records, and which it does not.

    IT BOUNDS WHAT MAY BE CLAIMED; IT IS NOT A VETO, and the first version read as one.
    Measured live 2026-09-18: "Who do I contact about a broken door closer, and how quickly
    should they respond?" produced, in full, "The records do not record a specific department
    responsible for broken door closers; they do record contactEmail, contactPhone, and
    respondsWithinHours for each department." Every word of that is true and the register
    answers the question — Estates Operations owns doors in its scope and responds within 24
    hours. Three faults, all in the wording of this block:

      * the unrecorded word came with three prohibitions and no permission, so the model read
        the census as a reason to decline rather than as the edge of what it could claim;
      * the two records carrying "doors" were COUNTED and not NAMED, so the one path to the
        answer was described and withheld;
      * the recorded fields were listed by their internal names, so that is what was printed.

    So the block now opens with the fields that DO answer, names the records behind a word
    found in recorded text, gives every field in ordinary words as well, and says in terms
    that an unrecorded word is not an unanswerable question.
    """
    terms = _question_terms(question, register_label)
    if not terms:
        return []
    content = _content_columns(rows, columns)
    prov = sorted(provenance_fields(rows))
    # `label` and `comment` are stamped as provenance because nobody asks for them by name,
    # but a register's record NAMES and notes are its own text, and a word that appears there
    # has not gone unrecorded.
    searchable = content + [c for c in ("label", "comment") if c in columns]
    as_field: Dict[str, List[str]] = {}
    as_text: Dict[str, List[Dict]] = {}
    as_stamp: List[str] = []
    absent: List[str] = []
    for term, parent in terms:
        if parent is not None and parent in as_field:
            continue  # the compound already found the field; its halves add nothing
        cols = [c for c in content if _term_matches_column(term, c)]
        if cols:
            as_field[term] = cols
            continue
        if _term_is_a_status_value(rows, term):
            as_field[term] = [f"{STATUS} (as a recorded value)"]
            continue
        if parent is not None:
            continue  # half of a compound: it matched no field, and that is not a finding
        if any(_term_matches_column(term, c) for c in prov) or _term_matches_column(term, STATUS):
            as_stamp.append(term)
            continue
        hit_rows = _term_in_text(rows, searchable, term)
        if len(hit_rows) >= len(rows) > 2:
            continue  # a word on every record distinguishes nothing and is not a finding
        if hit_rows:
            as_text[term] = hit_rows
        else:
            absent.append(term)
    if not (as_field or as_text or as_stamp or absent):
        return []
    lines = [
        "- WHAT THE QUESTION NAMES, CHECKED AGAINST THE FIELDS THESE RECORDS HOLD (matched by "
        "the system, not by reading). THIS BOUNDS WHAT YOU MAY CLAIM; IT IS NOT A REASON TO "
        "DECLINE. Answer from the fields and records named below FIRST, and only then say "
        "which part of the question the register does not reach:"
    ]
    for term, cols in list(as_field.items())[:MAX_TERMS_LISTED]:
        lines.append(
            f'  - "{term}": RECORDED — answer this part from {", ".join(cols[:4])}, which '
            f'holds {", ".join(_plain(c) for c in cols[:4])}.'
        )
    if as_text:
        # The per-term instruction used to be repeated in full on every term — three terms cost
        # 1,086 characters of which 800 were the same sentence three times. Said once.
        lines.append(
            "  - WORDS WITH NO FIELD OF THEIR OWN, and the records whose recorded values carry "
            "them. THOSE RECORDS ARE THE ANSWER to that part of the question: quote what they "
            "say and name the record it is written on. Never call one of these words a "
            "category the register tracks, count records by it, or claim a property no field "
            "records:"
        )
        for term, hit_rows in list(as_text.items())[:4]:
            ids = sorted(_ident(r) for r in hit_rows)
            lines.append(
                f'    - "{term}": {len(ids)} record(s) — {", ".join(ids[:MAX_IDS_LISTED])}'
            )
    if as_stamp:
        lines.append(
            "  - "
            + ", ".join(f'"{t}"' for t in as_stamp[:4])
            + ": matches only the register's own stamp (who keeps the register, and the "
            "state it records), not a property the records describe."
        )
    if absent:
        answers = sorted(as_field) + sorted(as_text)
        lines.append(
            "  - VOCABULARY NOTE, NOT A FINDING: no field name and no recorded value contains "
            + ", ".join(f'"{t}"' for t in absent[:MAX_TERMS_LISTED])
            + ". This exists to stop you CLAIMING these things, and for nothing else. DO NOT "
            "WRITE A SENTENCE ABOUT IT"
            # Measured: "the register does not record whether the building is
            # pushchair-friendly from the car park", printed above the same answer's own "15
            # routes are step-free … RTE-001, RTE-010, RTE-012"; and "the register does not
            # record any open actions" over five records the same run lists as requiring a
            # decision. An absence sentence beside rows that answer the question is the worst
            # output this block can produce.
            #
            # THIS NOTE NEVER AUTHORISES A DECLINE, and an earlier draft of it did: when the
            # question's words happened to match no column it said "say the register does not
            # cover this, and stop" — which is the same veto, reached by a different route,
            # over a block still holding every counted row. A question can be answerable from
            # fields it never names: nobody writing "pushchair" writes "step free".
            + (
                f". THE QUESTION IS ANSWERED ABOVE, from {', '.join(answers[:6])} — answer it "
                f"from there and say nothing about the words in this note."
                if answers
                else ". Answer from the counts and lists above, which stand whatever words the "
                "question used."
            )
            + " Never tell the reader something is not recorded when your own answer shows "
            "records that bear on it."
            + " Never answer one of these from another field, never treat a similar-sounding "
            "field as the same thing, and never reason a verdict about one from the fields "
            "that ARE present."
        )
    lines.append(
        "  - The field names above are internal identifiers. They must not appear in your "
        "answer: write what a field HOLDS, in ordinary words."
    )
    return lines


#: "which is suitable / best / most appropriate" — a question asking the records to be RANKED,
#: not filtered. Filtering is what the register does; ranking needs a field that differs.
_SUITABILITY_RE = re.compile(
    r"\b(?:suitable|suitability|best|most\s+appropriate|ideal|preferable|recommend\w*)\b",
    re.IGNORECASE,
)

#: A ranking field holds a handful of descriptors. More than this and it is a measurement or a
#: name, and a "which is best" answer built on it would be arithmetic the question did not ask.
MAX_RANKING_VALUES = 4
MAX_RANKING_FIELDS = 4

#: A recorded value meaning the record does NOT have the thing.
_FALSE_LIKE = {"false", "no", "0", "none", "n/a", "nil"}


def _scope_from_question(rows, columns, question):
    """The subset a question names by a recorded VALUE — "bookable rooms" of 28 workspaces.

    Uniformity is a property OF A SCOPE. `suitableForCalls` is true on 18 of the register's 28
    records, which looks discriminating; inside the 18 the question asked about, it is true on
    every one and separates nothing. Without the scope the check never fires.
    """
    terms = [t for t, _parent in _question_terms(question, "")]
    best = None
    for col in sorted(_content_columns(rows, columns)):
        counts = Counter(_value(r, col) for r in rows if _value(r, col))
        if not (2 <= len(counts) <= MAX_KIND_VALUES):
            continue
        for value, n in counts.items():
            if n == len(rows) or n < 2:
                continue
            words = [w.lower() for w in re.findall(r"[A-Za-z]+", value)]
            if not any(w == t or _shared_prefix(w, t) >= 5 for w in words for t in terms):
                continue
            if best is None or n < len(best[2]):
                best = (col, value, [r for r in rows if _value(r, col) == value])
    return best


def _suitability_lines(rows, columns, question):
    """A field every record satisfies cannot say which record is best (BUG-783).

    Measured live 2026-09-18: "Which bookable rooms are suitable for a confidential call?" was
    answered "All 18 of those are also marked as suitable for calls (calls_ok = true) …
    Therefore every bookable room in the building is suitable for a call", over a table of 18.
    Nothing was fabricated. But a boolean true on all 18 is a PRECONDITION, and the register
    also records a noise profile on which exactly two of those rooms are `silent`.

    WHICH field to rank on is NOT decided here. Choosing "noise" for "confidential" is a
    concept mapping — the kind of thing the HBCO resolver holds for sensor modalities — and
    hard-coding one would be a building literal wearing a general name. What the system can do
    honestly is say that the matched field ranks nothing, and hand over every field that does
    separate the scope, each with its records named, smallest distinguished group first.
    """
    if not _SUITABILITY_RE.search(question or ""):
        return []
    scope = _scope_from_question(rows, columns, question)
    scope_col, scope_value, subset = scope if scope else ("", "", list(rows))
    if len(subset) < 2:
        return []
    terms = [t for t, _parent in _question_terms(question, "")]
    content = [c for c in _content_columns(rows, columns) if c != scope_col]

    uniform = []
    for col in content:
        if not any(_term_matches_column(t, col) for t in terms):
            continue
        filled = [r for r in subset if _value(r, col)]
        values = {_value(r, col) for r in filled}
        if len(filled) == len(subset) and len(values) == 1:
            uniform.append((col, values.pop()))
    if not uniform:
        return []

    ranking = []
    for col in content:
        if any(col == u for u, _v in uniform):
            continue
        counts = Counter(_value(r, col) for r in subset if _value(r, col))
        if not (2 <= len(counts) <= MAX_RANKING_VALUES):
            continue
        smallest = min(counts.values())
        ranking.append((smallest, col, counts))
    ranking.sort(key=lambda t: (t[0], t[1]))

    where = (
        f'the {len(subset)} records where {scope_col} is "{scope_value}"'
        if scope
        else f"all {len(subset)} records"
    )
    # A UNIFORM FALSE IS NOT A PRECONDITION, IT IS AN ABSENCE. Eight computer labs all record
    # group-friendly as false: "a field satisfied by all of them" is the wrong sentence
    # entirely, and the answer owed is that none of them records it.
    denied = [(c, v) for c, v in uniform if v.strip().lower() in _FALSE_LIKE]
    held = [(c, v) for c, v in uniform if (c, v) not in denied]
    lines = []
    if held:
        lines.append(
            "- THE FIELD THE QUESTION NAMES CANNOT RANK THESE RECORDS. Among "
            + where
            + ", "
            + "; ".join(
                f'{col} ({_plain(col)}) is "{value}" on every one' for col, value in held[:3]
            )
            + ". A value shared by all of them is a PRECONDITION, not an answer to which is "
            "best: never conclude that every record therefore qualifies, and never present "
            "that field as the reason for choosing any of them."
        )
    if denied:
        lines.append(
            "- THE FIELD THE QUESTION NAMES IS NEGATIVE ON EVERY ONE OF THESE RECORDS. Among "
            + where
            + ", "
            + "; ".join(
                f'{col} ({_plain(col)}) is "{value}" on every one' for col, value in denied[:3]
            )
            + ". Say plainly that none of them records it, and never offer one of them as "
            "though it did."
        )
    if not ranking:
        lines.append(
            "- NOTHING ELSE SEPARATES THEM EITHER. Say plainly that the records make no "
            "distinction between these, and name them without ranking them."
        )
        return lines
    detail = []
    for _smallest, col, counts in ranking[:MAX_RANKING_FIELDS]:
        parts = []
        for value, n in sorted(counts.items(), key=lambda kv: (kv[1], kv[0])):
            # Only the DISTINGUISHED groups are named. Listing the sixteen records that are
            # merely ordinary cost a thousand characters a line and told the writer nothing:
            # a "which is best" answer is about the few, and the rest is a count.
            members = [r for r in subset if _value(r, col) == value] if n <= 6 else []
            parts.append(f'"{value[:32]}" {n}{_named(members)}')
        detail.append(f"{col} ({_plain(col)}): " + " vs ".join(parts))
    lines.append(
        "- FIELDS THAT DO SEPARATE THEM (computed, smallest distinguished group first): "
        + "; ".join(detail)
        + ". Choose the ONE of these that bears on what the question actually asks, rank on "
        "it, and say in your answer which recorded property you used — in ordinary words, "
        "never the field's own name — and that the field the question named holds the same "
        "value on all of them."
    )
    return lines


def _missing_lines(rows, col, question):
    """The records with NOTHING in a column, when the question asks which lack it.

    Stated with its complement: an absence line on its own is read as "there is nothing here",
    and the records that DO hold the field are usually half the answer.
    """
    if not _ASKS_ABSENCE_RE.search(question or ""):
        return []
    empty = [r for r in rows if not _value(r, col)]
    if not empty:
        return []
    ids = sorted(_ident(r) for r in empty)
    line = f"- {col} ({_plain(col)}) is NOT recorded on {len(empty)} of {len(rows)} records"
    if len(ids) <= MAX_IDS_LISTED:
        line += f": {', '.join(ids)}"
    return [
        line + f". Those records are the answer to a question asking which lack it; the other "
        f"{len(rows) - len(empty)} DO record it and are the answer to the rest of the "
        "question. A record with nothing in a column is UNKNOWN, never satisfactory."
    ]


def _value_split_lines(rows, col):
    """Every value a question-named column holds, counted — so "all of these" is checkable.

    "All of these routes start at a public entrance" was written over a table whose own rows
    gave one starting at a fire exit. A universal claim is a count, and it is counted here.
    """
    filled = [r for r in rows if _value(r, col)]
    counts = Counter(_value(r, col) for r in filled)
    # A vocabulary, not a list of identifiers: a column with a value per record (route
    # destinations, asset names) says nothing when counted, and printing it is noise.
    if not (2 <= len(counts) <= MAX_VALUES_SPLIT) or len(counts) * 2 > len(filled):
        return []
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    parts = []
    for value, n in ordered:
        members = [r for r in filled if _value(r, col) == value]
        parts.append(f'"{value[:48]}" {n}{_named(members)}')
    return [
        f"- {col} ({_plain(col)}) across the records (counted): "
        + "; ".join(parts)
        + ". Any sentence beginning 'all of these' or 'every record' must agree with this."
    ]


#: A question about the reader: "my access", "can I", "our team".
_FIRST_PERSON_RE = re.compile(r"\b(?:i|i'm|i've|me|my|mine|we|we're|our|ours|us)\b", re.IGNORECASE)

#: A column that scopes a record to a kind of person — a ROLE, never a named individual.
_ROLE_COLUMN_RE = re.compile(
    r"(role|team|department|discipline|trade|occupan|staff)", re.IGNORECASE
)


def _reader_lines(rows, columns, question):
    """Nothing here says which record is the reader's (BUG-709 rows 63, 64, 90).

    A role was assumed and an operational instruction issued to the wrong staff group; an
    evening entitlement was "confirmed" from a room's opening hours; a day plan silently
    decided which three timetabled sessions were the student's.
    """
    if not _FIRST_PERSON_RE.search(question or ""):
        return []
    content = _content_columns(rows, columns)
    role_cols = [c for c in content if _ROLE_COLUMN_RE.search(c)]
    lines = [
        f"- THE QUESTION IS ABOUT THE READER AND NO RECORD IDENTIFIES THEM. Answer it anyway, "
        f"from what IS recorded for the place, period or subject the question names — that is "
        f"the useful answer and it is available. None of the {len(rows)} records names the "
        f"person asking, so add that whose it is, is not recorded: do not select a record, "
        f"role, place or period as the reader's own, and do not confirm an entitlement."
    ]
    for col in role_cols[:1]:
        values = sorted({_value(r, col) for r in rows if _value(r, col)})
        # A SHARED vocabulary, not one role per record. `accountableRole` names a different
        # post on each of 20 departments: listing all twenty and saying "the question names
        # none of them" adds twelve lines of noise and a second nudge towards declining, to a
        # question ("who do I contact about a door") that the register answers.
        if not values or len(values) > max(2, len(rows) // 3):
            continue
        asked = (question or "").lower()
        named = [v for v in values if v.lower() in asked]
        lines.append(
            f"- The records are scoped by {col}, whose values are: "
            + ", ".join(f'"{v[:40]}"' for v in values[:MAX_KIND_VALUES])
            + (
                f". The question names {', '.join(named)} — use only those records."
                if named
                else ". The question names none of them, so no record can be said to be the "
                "reader's."
            )
        )
    return lines


#: A column holding the floor a record sits on, whatever a register calls it. Matched on the
#: column's WORDS (`onFloor` has no letter boundary a plain expression can find) AND on its
#: VALUES: `sensoryLevel` holds "moderate", "busy", "quiet", and grouping an answer by it
#: while calling it the record's floor would be a fabrication in the system's own voice.
_FLOOR_WORDS = ("floor", "level", "storey")
_FLOOR_VALUE_RE = re.compile(r"^(?:level|floor)?\s*-?\d{1,2}$", re.IGNORECASE)


def _is_floor_column(rows: List[Dict], col: str) -> bool:
    if not any(t.startswith(_FLOOR_WORDS) for t in _col_tokens(col)):
        return False
    values = [_value(r, col) for r in rows if _value(r, col)]
    return bool(values) and all(_FLOOR_VALUE_RE.match(v) for v in values)


_PLACE_QUESTION_RE = re.compile(
    r"\b(floor|floors|level|levels|room|rooms|space|spaces|storey|where|near|nearest|area)\b",
    re.IGNORECASE,
)


def _floor_lines(rows, columns, question):
    """The floor grouping, computed — rooms 2.15, 4.11 and 4.12 were each filed under floor 3.

    Two answers grouped spaces under a floor that neither their floor field nor their own room
    number gives, and then recommended "the two rooms on floor 3".

    THE GROUPING ONLY. A cross-check of the floor against the leading segment of a room code
    was written here too and taken out: the asset register records the floor a unit SERVES
    against a plant room on another floor, which is the register working as designed, and the
    check called it a contradiction on six records. A finding that is wrong about a correct
    register is worse than the defect it was aimed at.
    """
    if not _PLACE_QUESTION_RE.search(question or ""):
        return []
    content = _content_columns(rows, columns)
    floor_cols = [c for c in content if _is_floor_column(rows, c)]
    if not floor_cols:
        return []
    col = floor_cols[0]
    groups: Dict[str, List[str]] = defaultdict(list)
    for r in rows:
        v = _value(r, col)
        if v:
            groups[v].append(_ident(r))
    if not groups:
        return []
    shown = sorted(groups)[:MAX_KIND_VALUES]
    return [
        f"- By {col} (grouped by the system; this is the ONLY source of a record's floor — "
        f"never a rank, a row number, a seat count or a name): "
        + "; ".join(
            f"{g}: "
            + ", ".join(sorted(groups[g])[:MAX_IDS_LISTED])
            + (" …" if len(groups[g]) > MAX_IDS_LISTED else "")
            for g in shown
        )
        + "."
    ]


def _next_due_lines(rows, columns, today):
    """last-seen + interval = a due date, computed once instead of guessed per sentence.

    "AEP-014 … last visited 2026-09-16, inspection interval 7 days -> overdue" on 17 September,
    and "AEP-016 … 2025-10-15, interval 365 days -> overdue" — two subtractions, both wrong, in
    one answer. The register records the pair; the due date is arithmetic, so the system does it.
    """
    if today is None:
        return []
    last_cols = [c for c in columns if _LAST_COLUMN_RE.search(c)]
    interval_cols = [c for c in columns if _INTERVAL_COLUMN_RE.search(c)]
    if not last_cols or not interval_cols:
        return []
    col, interval_col = last_cols[0], interval_cols[0]
    past, upcoming = [], []
    for r in rows:
        try:
            when = date.fromisoformat(_value(r, col)[:10])
            due = when + timedelta(days=int(float(_value(r, interval_col))))
        except (TypeError, ValueError):
            continue
        (past if due < today else upcoming).append((due, _ident(r)))
    if not past and not upcoming:
        return []
    lines: List[str] = []
    if past:
        lines.append(
            f"- {col} + {interval_col} = the next due date, computed by the system. "
            f"{len(past)} of {len(past) + len(upcoming)} datable records are PAST it on "
            f"{today.isoformat()}: "
            + "; ".join(
                f"{ident} (due {due.isoformat()})" for due, ident in sorted(past)[:MAX_IDS_LISTED]
            )
            + "."
        )
    else:
        lines.append(
            f"- {col} + {interval_col} = the next due date, computed by the system. NONE of "
            f"the {len(upcoming)} datable records is past it on {today.isoformat()}."
        )
    if upcoming:
        soonest = sorted(upcoming)[0]
        lines.append(
            f"- The other {len(upcoming)} are NOT yet due (the soonest is {soonest[1]} on "
            f"{soonest[0].isoformat()}). A record inside its interval is not overdue, whatever "
            f"the size of the interval — do not call one overdue unless it is named above."
        )
    return lines


#: Words that appear in a column name without distinguishing what the column is ABOUT.
#: Pairing on these made `effectiveFrom` and `inheritsFrom` a pair, and `commissionedDuty`
#: and `dutyEvidence` — two columns the asset register keeps apart ON PURPOSE.
_WEAK_TOKENS = frozenset(
    {
        "record",
        "text",
        "from",
        "with",
        "this",
        "that",
        "into",
        "onto",
        "over",
        "when",
        "date",
        "value",
        "name",
        "code",
        "kind",
        "type",
        "time",
        "duty",
        "point",
        "area",
        "reference",
        "detail",
        "details",
        "item",
        "number",
    }
)


def _paired_columns(columns, marker):
    """Column pairs named for the same thing — ``servedByLift``/``liftStatus``.

    A column whose name carries another column's distinctive word describes THAT thing, so
    the two can be read against each other. Any other pairing would be a guess.
    """
    pairs = []
    for a in columns:
        for b in columns:
            if a == b or not marker(b):
                continue
            flat_b = _col_flat(b)
            for tok in _col_tokens(a):
                if len(tok) >= 4 and tok in flat_b and tok not in _WEAK_TOKENS:
                    pairs.append((a, b))
                    break
    return pairs


#: A column that says what something IS or is CLAIMED to be — the kind of column two records
#: can disagree about. A date and a measurement are not claims of this sort: two assets
#: surveyed on different days are not contradicting each other.
#: NOT "kind" or "classification": those say what a record IS, and two records of different
#: kinds sharing a fitting are not in conflict — pairing `holdOpenDevice` with `openingKind`
#: reported a fire door and a fire shutter as a contradiction.
_STATE_NAME_RE = re.compile(
    r"(status|state|condition|availabilit|mode|label)",
    re.IGNORECASE,
)


def _describes_a_state(col: str) -> bool:
    return bool(_STATE_NAME_RE.search(col))


def _disagreement_lines(rows, columns):
    """Where a register contradicts itself about the same thing, say so instead of choosing.

    The waste register keeps the recorded stream and the stream on the LABEL apart precisely so
    their disagreement is representable, and the route register records Lift B as both in
    service and out of service on two different routes. An answer listed "Lift B | open" two
    lines after saying Lift B was out of service.

    DIRECTION MATTERS, so the second column must be named for a state ("records sharing
    `liftStatus` record different `servedByLift` values" is the same pair read backwards and
    says nothing), and a date or a measurement is never a state: two assets surveyed on
    different days are not contradicting each other.
    """
    content = _content_columns(rows, columns)
    lines: List[str] = []
    seen = set()
    for subject, about in _paired_columns(content, _describes_a_state):
        if (about, subject) in seen or (subject, about) in seen:
            continue
        # The first column must NAME something — "Lift B", "General waste". A column of
        # lowercase descriptions ("at every seat", "perimeter only") describes the record
        # itself, and two records described differently are not in disagreement: pairing
        # `powerAccess` with `accessClassification` on the shared word "access" reported a
        # contradiction in a register that holds none.
        subject_values = {_value(r, subject) for r in rows if _value(r, subject)}
        if not subject_values or not all(
            v[:1].isupper() or v[:1].isdigit() for v in subject_values
        ):
            continue
        # The second column must hold a VOCABULARY — a handful of states drawn from a list.
        # A column with a different value on every row is free text or a measurement, and two
        # rows carrying different measurements are not disagreeing about anything.
        vocabulary = {_value(r, about) for r in rows if _value(r, about)}
        if len(vocabulary) > MAX_KIND_VALUES:
            continue
        groups: Dict[str, set] = defaultdict(set)
        for r in rows:
            key, state = _value(r, subject), _value(r, about)
            if key and state:
                groups[key].add(state)
        split = {k: v for k, v in groups.items() if len(v) > 1}
        # A column with a distinct value on every row identifies the row, not a thing the
        # rows share, and two rows cannot disagree about it.
        if not split or len(groups) >= len(rows):
            continue
        seen.add((subject, about))
        key = sorted(split)[0]
        detail = []
        for state in sorted(split[key]):
            ids = sorted(
                _ident(r) for r in rows if _value(r, subject) == key and _value(r, about) == state
            )
            detail.append(f'"{state[:32]}" ({", ".join(ids[:6])})')
        lines.append(
            f"- THE RECORDS DISAGREE WITH EACH OTHER: records sharing {subject} "
            f'"{key[:40]}" record different {about} values — '
            + "; ".join(detail)
            + ". Report both, name the record each came from, and do not state either as the "
            "register's position."
        )
        if len(lines) >= 2:
            break
    return lines


#: A recorded limit the record's own measurement is tested against.
_THRESHOLD_RE = re.compile(r"(threshold|limit|target|maximum|minimum)", re.IGNORECASE)


def _threshold_lines(rows, columns):
    """A threshold is a trigger the record is tested against, never an instruction.

    "Bins must be at or above the approved fill threshold … WCP-023: fill 55 % (threshold
    60 %) — below threshold — should be filled": a collection trigger turned into an
    instruction to a cleaner to add waste to a clinical sharps bin.
    """
    content = _content_columns(rows, columns)
    lines = []
    for measure, limit in _paired_columns(content, lambda c: bool(_THRESHOLD_RE.search(c))):
        if _THRESHOLD_RE.search(measure):
            continue
        at_or_over, under = [], []
        for r in rows:
            x, y = _as_number(_value(r, measure)), _as_number(_value(r, limit))
            if x is None or y is None:
                continue
            (at_or_over if x >= y else under).append(_ident(r))
        if not at_or_over and not under:
            continue
        line = (
            f"- {measure} against {limit} (compared by the system): {len(at_or_over)} record(s) "
            f"are AT OR ABOVE their threshold"
        )
        if at_or_over and len(at_or_over) <= MAX_IDS_LISTED:
            line += f" ({', '.join(sorted(at_or_over))})"
        line += (
            f"; {len(under)} are below it. Report that split as the answer. A threshold is the "
            "level at which the recorded action is triggered, so a record below it has simply "
            "not reached the trigger: never read it as a level anything should be brought UP "
            "to, and never turn it into an instruction to anyone."
        )
        lines.append(line)
        if len(lines) >= 2:
            break
    return lines


def register_facts(
    rows: List[Dict],
    question: str,
    today: Optional[date] = None,
    register_label: str = "",
) -> str:
    """A short block of counted facts, or "" when the rows carry no recorded status."""
    if not rows or not any(_value(r, STATUS) for r in rows):
        return ""
    columns = sorted({k for r in rows for k in r.keys()})
    lines = [
        # THE BLOCK IS FOR THE WRITER, NOT THE READER (run 5, 2026-09-18). Keyword-census text
        # reached the user on 23 of 147 answers, having reached it on none in four earlier
        # runs: "X: recorded, in fieldName" and "no field is named for it" are notes to
        # whoever is composing the answer, and they were copied out as prose.
        "- NOT FOR THE READER. This block is the system's working-out, handed to you so you do "
        "not have to count, filter or decide what the register holds. NEVER quote it, never "
        "repeat its wording, and never write one of the field names in it to the user. Write "
        "an ordinary answer about the building, whose every number and every list agrees with "
        "what is below.",
        "- EVERY COUNT AND LIST BELOW IS AUTHORITATIVE: restate them as they stand. Do not "
        "recount from the rows, and never write a number that disagrees with one here — if a "
        "group is given as 9 records and you show a table, that table has 9 rows, and every "
        "record named in the group is in it. EVERY GROUPING BELOW IS A PARTITION: each record "
        "appears under exactly ONE value, listing it under two is an error, and a heading "
        "naming a value may contain ONLY the records listed beside that value here.",
        f"- Records held: {len(rows)}.",
        f"- By recorded status: {_split(rows)}. A record has ONE recorded status: it appears "
        f"under one of these and no other, and a heading naming a status may contain only the "
        f"records listed beside it here.",
    ]

    for col in columns:
        if not col.lower().endswith("kind"):
            continue
        groups: Dict[str, List[Dict]] = defaultdict(list)
        for r in rows:
            groups[_value(r, col) or "(none)"].append(r)
        if len(groups) < 2 or len(groups) > MAX_KIND_VALUES:
            continue
        lines.append(
            f"- By {col} ({_plain(col)}), then recorded status — a record of one kind is NOT "
            f"another, and belongs to exactly ONE kind:"
        )
        for kind in sorted(groups):
            lines.append(f"  - {kind}: {_split(groups[kind])}")

    # A FIELD THE QUESTION NAMES, COUNTED (BUG-605). "Which HVAC systems run outside normal
    # hours, and is each exception approved?" answered four, six and seven across three runs of
    # a register holding approvedException on exactly 7 of 10 records. A field present on SOME
    # records is exactly the filter a language model gets wrong, so where the question names one
    # the system counts it and lists the records.
    asked = set(re.findall(r"[a-z]+", (question or "").lower()))
    _prov = provenance_fields(rows)
    _splits_used = 0
    for col in columns:
        if col == STATUS or col in _prov:
            continue
        col_words = {w.lower() for w in re.findall(r"[A-Za-z][a-z]+", col)}
        if not (asked & col_words):
            continue
        filled = [r for r in rows if _value(r, col)]
        if not filled:
            continue  # nothing recorded at all: no filter to get wrong
        if len(filled) != len(rows):
            ids = sorted(_ident(r) for r in filled)
            line = f"- {col} is recorded for {len(filled)} of {len(rows)} records"
            if len(ids) <= MAX_IDS_LISTED:
                line += f": {', '.join(ids)}"
            lines.append(line + ". State that count; do not recount from the rows.")
            # WHICH RECORDS LACK IT, NAMED (BUG-709). "Which are orphaned because no owner,
            # purpose or mapped opening can be evidenced" needs the empty rows, and the
            # count of the FULL ones was read as proof that none were empty.
            lines.extend(_missing_lines(rows, col, question))
        if _splits_used < MAX_SPLIT_LINES:
            _split_line = _value_split_lines(rows, col)
            _splits_used += len(_split_line)
            lines.extend(_split_line)
        # Checked even when the column is filled everywhere: a present value can still SAY
        # there is none, which is the department case (BUG-613).
        lines.extend(_absence_lines(rows, col, question))

    # A QUESTION ASKING WHICH RECORDS HAVE **NO** X (BUG-613). "Which departments have no
    # out-of-hours route?" was answered "every department has an out-of-hours route value
    # recorded" — true of the FIELD and false of the building: nine of the twenty say "No
    # cover, next working day". A field that is present can still say the thing is absent, and
    # the words that say so are the ordinary English ones.
    # A QUESTION WORD THAT IS ALSO A RECORDED STATUS (CAVEAT-604). "Which teaching sessions are
    # scheduled in Room 1.06?" answered six — the records whose recordStatus is "scheduled" —
    # of the 23 the room holds. Both readings are defensible, which is exactly why the answer
    # has to carry the total AND the split rather than silently pick one.
    statuses = {_value(r, STATUS).lower() for r in rows if _value(r, STATUS)}
    overlap = sorted(statuses & asked)
    if overlap:
        lines.append(
            # The instruction used to describe the shape and leave the wording open, and the
            # answer then reported the STATUS count alone about one run in three: "There are
            # 6 scheduled sessions recorded for this room", from a room holding 23. Both
            # readings of the word are defensible, which is exactly why the answer has to
            # carry both numbers — so the sentence that does it is written out here rather
            # than described.
            f"- CAREFUL: {', '.join(repr(w) for w in overlap)} is also a recorded STATUS here, "
            f"so the question has two defensible readings and the answer must carry BOTH "
            f"numbers. OPEN with this sentence, filled in from the counts above: "
            # NOT "The room holds": that noun was right for the timetable question this line
            # was written for and wrong everywhere else it fires. Any register whose status
            # values overlap a question word triggers it, so washroom, impairment and
            # server-room answers opened by calling the register a room (seen in the
            # 2026-09-15 stakeholder runs). The sentence must not assume what holds the rows.
            f'"There are {len(rows)} records in total — {_split(rows)}." '
            f"Only then list whichever subset the question meant. Never report a status count "
            f"alone as though it were the total."
        )

    lines.extend(_elapsed_lines(rows, columns, question, today))
    lines.extend(_comparison_lines(rows, columns, question))
    # BUG-709, the twenty rows of 2026-09-17: each of these replaces a judgement the
    # narration used to reason its way to with an operation it cannot argue with.
    lines.extend(_suitability_lines(rows, columns, question))
    lines.extend(_term_census_lines(rows, columns, question, register_label))
    lines.extend(_next_due_lines(rows, columns, today))
    lines.extend(_threshold_lines(rows, columns))
    lines.extend(_disagreement_lines(rows, columns))
    lines.extend(_floor_lines(rows, columns, question))
    lines.extend(_reader_lines(rows, columns, question))

    if _OVERDUE_RE.search(question or ""):
        due_cols = [c for c in columns if _DUE_COLUMN_RE.search(c)]
        overdue_status = any("overdue" in _value(r, STATUS).lower() for r in rows)
        if not due_cols and not overdue_status:
            lines.append(
                "- OVERDUE IS NOT RECORDED: no status is 'overdue' and no field holds a due date. "
                "Say so in the first sentence; do not treat an effective, start or created date "
                "as a deadline. Then answer whatever else the question asks from the counts "
                "above — one unrecorded thing does not make the question unanswerable."
            )
        elif due_cols and today is not None:
            for col in due_cols:
                past = []
                for r in rows:
                    raw = _value(r, col)[:10]
                    if _value(r, STATUS).lower() in _CLOSED_STATUSES:
                        continue
                    try:
                        if date.fromisoformat(raw) < today:
                            past.append(f"{_ident(r)} ({raw})")
                    except ValueError:
                        continue
                recorded = sorted(_ident(r) for r in rows if "overdue" in _value(r, STATUS).lower())
                not_marked = [p for p in sorted(past) if p.split(" (")[0] not in recorded]
                lines.append(
                    f"- {col} already passed on {today.isoformat()} for {len(past)} record(s) not "
                    f"closed" + (f": {', '.join(sorted(past)[:MAX_IDS_LISTED])}." if past else ".")
                )
                if not_marked:
                    # Fire exits whose test date was yesterday, still recorded "active": the
                    # narration reported only the two marked overdue and called the rest "not
                    # overdue". Both facts are true and the reader needs both.
                    lines.append(
                        f"- STATE BOTH: {len(recorded)} record(s) have the recorded status "
                        f"'overdue'; {len(not_marked)} more are past their {col} while their "
                        f"recorded status is not 'overdue' ({', '.join(not_marked[:MAX_IDS_LISTED])}). "
                        "Never call those 'not overdue'."
                    )
    return _within_budget(lines)


#: The whole block, handed over alongside a register table that may itself run to 34,000
#: characters. Naming every record in every group took the worst case from 4.0k to 5.8k, and a
#: prompt that outgrows the context returns an EMPTY COMPLETION rather than a worse answer
#: (BUG-188, BUG-474). So there is a ceiling, and what gives way is chosen rather than
#: truncated: a value split is the least load-bearing line here, and the longest goes first.
MAX_FACTS_CHARS = 5000
_VALUE_SPLIT_MARK = " across the records (counted): "


def _within_budget(lines: List[str]) -> str:
    block = "\n".join(lines)
    while len(block) > MAX_FACTS_CHARS:
        splits = [i for i, line in enumerate(lines) if _VALUE_SPLIT_MARK in line]
        if not splits:
            break  # nothing optional left: a long block beats a silently cut one
        lines.pop(max(splits, key=lambda i: len(lines[i])))
        block = "\n".join(lines)
    return block


def passed_due_not_marked(rows: List[Dict], question: str, today: Optional[date]) -> List[str]:
    """Records past a ``…Due`` date whose recorded status is not 'overdue', for an overdue question.

    BUG-589: with these listed in the facts, the narration still reported only the two
    records MARKED overdue in 4 of 4 runs. The answer's own completeness is not left to it.
    """
    if today is None or not rows or not _OVERDUE_RE.search(question or ""):
        return []
    columns = sorted({k for r in rows for k in r.keys()})
    out: List[str] = []
    for col in (c for c in columns if _DUE_COLUMN_RE.search(c)):
        for r in rows:
            status = _value(r, STATUS).lower()
            if status in _CLOSED_STATUSES or "overdue" in status:
                continue
            raw = _value(r, col)[:10]
            try:
                if date.fromisoformat(raw) < today:
                    out.append(f"{_ident(r)} ({col} {raw}, recorded {status or 'no status'})")
            except ValueError:
                continue
    return sorted(set(out))


def completeness_line(narration: str, missing: List[str]) -> str:
    """A system-written line naming past-due records the narration did not mention, or ""."""
    unmentioned = [m for m in missing if m.split(" (")[0] not in (narration or "")]
    if not unmentioned:
        return ""
    return (
        "\n\n**Also past their due date, though not recorded as overdue** (stated by the "
        "system from the register): " + "; ".join(unmentioned[:MAX_IDS_LISTED]) + "."
    )


_CODE_ONLY_LINE = re.compile(r"^\s*\**\s*[A-Z]{1,8}-\d[\w.-]*(\s*,\s*[\w.-]+)*\s*\**\s*$")


def strip_leaked_code_line(text: str) -> str:
    """Drop a first line that is nothing but record codes ("EV-003, 3", "**EV-003, EV-007**").

    The narration sometimes opens with a bare list of the ids it is about to discuss — a
    scratch line, not a sentence — and it reached the user as the answer's headline.
    """
    lines = (text or "").split("\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if _CODE_ONLY_LINE.match(line):
            return "\n".join(lines[:i] + lines[i + 1 :]).lstrip("\n")
        break
    return text
