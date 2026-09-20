#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""List facts the building states twice, differently.

WHY THIS EXISTS
---------------
A fact stated in two places is a disagreement waiting to surface: the reception desk was
open 07:30-18:00 in two registers and 09:00-16:30 in three capability topics, the same
service desk had two telephone numbers, a policy sent lone workers to a "Level 6" in a
building with floors 0-5, and one file said the server rooms were on floors 2 and 4 while
the graph declared three (floors 2, 4 and 5). Every one of them was found by reading, and
every one is a place a supervisor asking an ordinary question gets a different answer
depending on which lane replied (`bldg1_building_facts.ttl`: "one fact, one home").

This extracts (subject, attribute, value) triples for the facts that recur, from the record
documents (`documents/*.md`) and the authored TTL, and lists every (subject, attribute)
that carries more than one value.

WHAT IT DOES AND DOES NOT DO
----------------------------
It reads text. It never asks which value is right: that is the owner's decision, and the
report says where each value was found so the owner can make it. A rule is only as good as
its subject: a clause is attributed to the NEAREST subject keyword before it, and a bare
time range with no day is read as weekday hours. Both simplifications are stated here
because a wrong extraction that looked authoritative would be worse than none.

RULES (extend RULES / SUBJECT_KEYWORDS for another fact; nothing here names a building)
    hours      reception, cafe and the building's own access hours, per day class
    contacts   telephone numbers and e-mail addresses for security, the estates helpdesk,
               the IT service desk and health and safety, in prose and in directory tables
    levels     a "Level N" / "Floor N" beyond the highest floor the graph declares
    counts     "six air handling units" against the rows of an asset table
    places     the server-room floors each file states; the street address; the year built
    providers  the cleaning contract reference and provider

    python scripts/fact_conflicts.py                 # scan input/, exit 1 on a conflict
    python scripts/fact_conflicts.py --input bldg2   # another building
    python scripts/fact_conflicts.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]

#: TTL that carries no authored facts about the building: vocabularies and sensor lists.
_SKIP = re.compile(
    r"brick|saturation|expanded_protege|sensor_links|timeseries_extension|measured_origin|"
    r"floors_0_4_sensors|\.bak|damper_points|plant_points|waste_points|security_lighting",
    re.IGNORECASE,
)

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}  # fmt: skip


@dataclass(frozen=True)
class Fact:
    subject: str
    attribute: str
    value: str
    source: str
    line: int
    excerpt: str


# ── hours ──────────────────────────────────────────────────────────────────────────────

_TIME = r"(?P<a>\d{1,2}[:.]\d{2})\s*[-–—]\s*(?P<b>\d{1,2}[:.]\d{2})"
_DAY_WORDS = (
    ("weekend", r"sat(?:urday)?s?\s*(?:[-–—]|and|&|to)\s*sun(?:day)?s?|weekends?"),
    ("weekday", r"mon(?:day)?s?\s*(?:[-–—]|to)\s*fri(?:day)?s?|weekdays?"),
    ("sat", r"sat(?:urday)?s?"),
    ("sun", r"sun(?:day)?s?"),
)
_EVENT = re.compile(
    "|".join(f"(?P<d_{n}>\\b(?:{p})\\b)" for n, p in _DAY_WORDS)
    + rf"|(?P<time>{_TIME})|(?P<closed>\bclosed\b)",
    re.IGNORECASE,
)

#: The nearest of these BEFORE a range says whose hours it is. Deliberately narrow: a bare
#: "building" also appears in "runs the building day to day", which is not an opening hour.
SUBJECT_KEYWORDS: Dict[str, str] = {
    "reception": r"reception|front desk|front of house",
    "cafe": r"caf[eé]\b",
    "building": (
        r"card[- ]?holders?|building (?:access|hours|opening|is open)|building itself has|"
        r"standard (?:building )?hours|opening ?hours|opening times|open hours"
    ),
    # A different concept from the hours a card-holder may enter, so never compared with them.
    "core_hours": r"core hours",
}
_SUBJECT_RES = {k: re.compile(v, re.IGNORECASE) for k, v in SUBJECT_KEYWORDS.items()}

#: In a table row the subject and its hours sit in neighbouring cells ("Main entrance reception |
#: Mon-Fri 09:00-16:30"); further apart, the keyword belongs to another column.
TABLE_WINDOW = 24


def _norm_time(a: str, b: str) -> str:
    def one(t: str) -> str:
        h, m = re.split(r"[:.]", t)
        return f"{int(h):02d}:{m}"

    return f"{one(a)}-{one(b)}"


def _nearest_subject(prefix: str) -> Optional[str]:
    best: Tuple[int, Optional[str]] = (-1, None)
    for subject, rx in _SUBJECT_RES.items():
        for m in rx.finditer(prefix):
            if m.start() > best[0]:
                best = (m.start(), subject)
    return best[1]


def _kind(m: "re.Match[str]") -> str:
    """'time', 'closed' or 'd_<day class>' for one match of _EVENT."""
    if m.group("time"):
        return "time"
    if m.group("closed"):
        return "closed"
    return next(f"d_{n}" for n, _ in _DAY_WORDS if m.group(f"d_{n}"))


def _expand(day: str) -> List[str]:
    return ["sat", "sun"] if day == "weekend" else [day]


def hours_facts(line: str, source: str, number: int, window: int = 120) -> List[Fact]:
    """(subject, <day>_hours, range|closed) for every clause of one line.

    ``window`` is how far back a subject keyword may sit from the range it names: a table row
    names its subject in the cell beside the hours, and "teaching and reception | ... | Mon-Fri
    07:00-19:00" is an air-handling window for a zone, not the desk's opening hours.
    """
    facts: List[Fact] = []
    offset = 0
    for clause in re.split(r";|\.(?=\s)", line):
        start = line.find(clause, offset)
        offset = start + len(clause) if start >= 0 else offset
        events = [(_kind(m), m) for m in _EVENT.finditer(clause)]
        if not events:
            continue
        first = max(start, 0) + events[0][1].start()
        subject = _nearest_subject(line[max(0, first - window) : first])
        if subject is None:
            continue
        pairs: List[Tuple[List[str], str]] = []
        kinds = [k for k, _ in events]
        if kinds[0] in ("time", "closed"):  # "07:00-22:00 on weekdays": value first
            pending: Optional[str] = None
            for kind, m in events:
                if kind == "time":
                    pending = _norm_time(m.group("a"), m.group("b"))
                elif kind == "closed":
                    pending = "closed"
                elif pending is not None:
                    pairs.append((_expand(kind[2:]), pending))
                    pending = None
            if pending not in (None, "closed") and not any(k.startswith("d_") for k in kinds):
                pairs.append((["weekday"], pending))  # a bare range is read as weekday hours
        else:  # "Mon-Fri 09:00-16:30": day first
            days: List[str] = []
            for kind, m in events:
                if kind.startswith("d_"):
                    days += _expand(kind[2:])
                elif days:
                    value = _norm_time(m.group("a"), m.group("b")) if kind == "time" else "closed"
                    pairs.append((days, value))
                    days = []
        for days_, value in pairs:
            for day in days_:
                facts.append(
                    Fact(subject, f"{day}_hours", value, source, number, clause.strip()[:110])
                )
    return facts


# ── contacts ───────────────────────────────────────────────────────────────────────────

CONTACT_KEYWORDS: Dict[str, str] = {
    "estates_out_of_hours": r"out-of-hours (?:building )?emergenc\w*|estates emergency",
    "estates_helpdesk": r"estates (?:fm )?helpdesk|fm helpdesk|facilities helpdesk",
    "it_service_desk": r"it service desk|it support|it helpdesk|itservicedesk",
    "security": r"security",
    "health_safety": r"health (?:and|&) safety",
}
_CONTACT_RES = {k: re.compile(v, re.IGNORECASE) for k, v in CONTACT_KEYWORDS.items()}
_PHONE = re.compile(r"(?<![\d.])(0?29\s?\d{4}\s?\d{4})(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_EMAIL_SUBJECT = (
    (re.compile(r"^security@"), "security"),
    (re.compile(r"^estates@"), "estates_helpdesk"),
    (re.compile(r"^safety@"), "health_safety"),
)
#: Directory tables name a FUNCTION per row; these read that name, not the row's whole text.
TABLE_SUBJECTS = (
    (re.compile(r"^security\b", re.IGNORECASE), "security"),
    (re.compile(r"^health and safety\b", re.IGNORECASE), "health_safety"),
    (re.compile(r"^it\b|^information technology", re.IGNORECASE), "it_service_desk"),
)


def _digits(phone: str) -> str:
    d = re.sub(r"\D", "", phone)
    return d if d.startswith("0") else "0" + d


def contact_facts(line: str, source: str, number: int) -> List[Fact]:
    """Phone numbers and e-mail addresses attributed to the nearest service named before them."""
    facts: List[Fact] = []
    for m in _PHONE.finditer(line):
        best: Tuple[int, Optional[str]] = (-1, None)
        for subject, rx in _CONTACT_RES.items():
            for k in rx.finditer(line[: m.start()]):
                if k.start() > best[0]:
                    best = (k.start(), subject)
        if best[1]:
            facts.append(
                Fact(best[1], "phone", _digits(m.group(1)), source, number, line.strip()[:110])
            )
    for m in _EMAIL.finditer(line):
        for rx, subject in _EMAIL_SUBJECT:
            if rx.match(m.group(0).lower()):
                facts.append(
                    Fact(subject, "email", m.group(0).lower(), source, number, line.strip()[:110])
                )
    return facts


def table_contact_facts(rows: Iterable[Tuple[int, Dict[str, str]]], source: str) -> List[Fact]:
    facts: List[Fact] = []
    for number, row in rows:
        name = row.get("name", "").strip()
        subject = next((s for rx, s in TABLE_SUBJECTS if rx.search(name)), None)
        if not subject:
            continue
        phone = row.get("contact_phone", "").strip()
        if _PHONE.search(phone):
            facts.append(Fact(subject, "phone", _digits(phone), source, number, f"{name}: {phone}"))
        email = row.get("contact_email", "").strip().lower()
        if email:
            facts.append(Fact(subject, "email", email, source, number, f"{name}: {email}"))
    return facts


# ── places, counts, providers ──────────────────────────────────────────────────────────

_ADDRESS = re.compile(r"(Senghennydd Road)[^.\n]{0,30}?(CF\d{2}\s?\d[A-Z]{2})", re.IGNORECASE)
_YEAR = re.compile(r"(?:yearBuilt|built (?:in )?|constructed (?:in )?)\D{0,6}((?:19|20)\d{2})")
_CLEANING_REF = re.compile(r"cleaning[^.\n|]{0,70}?contract\s+((?:CON|CTR)-[\w-]+)", re.IGNORECASE)
_AHU_STATED = re.compile(r"(?:all )?(\w+) air handling units", re.IGNORECASE)
_LEVEL = re.compile(r"\b(?:Level|Floor)\s+(\d{1,2})\b(?!\.\d)")
_SERVER_LABEL = (
    re.compile(r"Server [Rr]oom\s*[—–-]\s*Floor\s*(\d)"),
    re.compile(r"Server room \(Floor (\d)\)"),
    re.compile(r"Room\s+(\d)\.\d+\s*[—–-]\s*Server Room"),
)
_FLOOR_FUNCTION = re.compile(r"bldg:Floor(\d)\s+hbco:spaceFunction\s+\"([^\"]*)\"")


#: The service a contract or a cost line is for. A provider is compared only within one topic,
#: and only when it is a firm: "In-house" and "Insurance inspector" are roles, not suppliers.
PROVIDER_TOPICS: Dict[str, "re.Pattern[str]"] = {
    name: re.compile(pattern, re.IGNORECASE)
    for name, pattern in {
        "cleaning": r"cleaning (?:contract|consumables|and washroom)|washroom services",
        "waste": r"waste (?:collection|and recycling)",
        "fire_alarm": r"fire alarm",
        "lift": r"\blift (?:maintenance|servicing)",
        "bms": r"\bBMS\b|building management",
        "water_hygiene": r"water hygiene|legionella",
        "av_support": r"\bAV support|lecture[- ]capture",
        "grounds": r"grounds",
        "security_staffing": r"security (?:staffing|services)",
    }.items()
}
_GENERIC_PROVIDER = re.compile(
    r"in-house|contractor|inspector|specialist|supplier|f-gas|gas safe|abseil|internal",
    re.IGNORECASE,
)


_CODE_DATE = re.compile(
    r"\b((?:[A-Z]{2,4})-[A-Z0-9]+(?:-[A-Z0-9]+)*)\b[^|.\n]{0,40}?(\d{4}-\d{2}-\d{2})"
)
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


def _cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _tables(text: str) -> List[Tuple[List[str], List[Tuple[int, Dict[str, str]]]]]:
    """[(header, [(line number, row)])] for each markdown table in the text."""
    out: List[Tuple[List[str], List[Tuple[int, Dict[str, str]]]]] = []
    header: Optional[List[str]] = None
    rows: List[Tuple[int, Dict[str, str]]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line.startswith("|"):
            if header and rows:
                out.append((header, rows))
            header, rows = None, []
            continue
        cells = _cells(line)
        if set("".join(cells)) <= set("-: "):
            continue
        if header is None:
            header, rows = [c.lower() for c in cells], []
        elif len(cells) == len(header):
            rows.append((number, dict(zip(header, cells))))
    if header and rows:
        out.append((header, rows))
    return out


def extract(path: Path, relative: str, declared_floors: Sequence[int]) -> List[Fact]:
    """Every fact one file states."""
    text = path.read_text(encoding="utf-8", errors="replace")
    is_doc = path.suffix == ".md"
    facts: List[Fact] = []
    tables = _tables(text) if is_doc else []
    table_lines = {n for _, rows in tables for n, _ in rows}
    for _, rows in tables:
        facts += table_contact_facts(rows, relative)
    server_floors = set()
    block_subject = ""
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#") and not is_doc:
            continue
        if not is_doc and line[:1] not in ("", " ", "\t", "@", "#"):
            block_subject = line.split()[0] if line.split() else ""
        hours_line = line
        if not is_doc and re.search(r"(?:^|[:_])Amenity_", block_subject):
            # `ontosage:openingHours` on an AMENITY is that amenity's hours. The extractor reads the
            # predicate NAME as the subject "building", which reported a cafe's 08:00-16:30 as a
            # contradiction with the building's 07:00-22:00 (2026-09-20). The amenity's own prose
            # (`locationText`, `answerText`) still names it and is still read.
            hours_line = re.sub(r"\bopeningHours\b", "amenityHoursText", line)
        facts += hours_facts(
            hours_line, relative, number, window=TABLE_WINDOW if number in table_lines else 120
        )
        if number not in table_lines:
            facts += contact_facts(line, relative, number)
        elif "@" not in line:
            facts += [f for f in contact_facts(line, relative, number) if f.attribute != "phone"]
        for m in _ADDRESS.finditer(line):
            facts.append(
                Fact(
                    "building",
                    "postcode",
                    re.sub(r"\s", "", m.group(2)).upper(),
                    relative,
                    number,
                    line.strip()[:110],
                )
            )
        for m in _YEAR.finditer(line):
            facts.append(
                Fact("building", "year_built", m.group(1), relative, number, line.strip()[:110])
            )
        for m in _CLEANING_REF.finditer(line):
            facts.append(
                Fact(
                    "cleaning",
                    "contract_reference",
                    m.group(1).upper(),
                    relative,
                    number,
                    line.strip()[:110],
                )
            )
        for m in _AHU_STATED.finditer(line):
            n = NUMBER_WORDS.get(m.group(1).lower()) or (
                int(m.group(1)) if m.group(1).isdigit() else None
            )
            if n:
                facts.append(
                    Fact(
                        "air_handling_units", "count", str(n), relative, number, line.strip()[:110]
                    )
                )
        if declared_floors:
            for m in _LEVEL.finditer(line):
                if int(m.group(1)) > max(declared_floors) and not line.lstrip().startswith("#"):
                    facts.append(
                        Fact(
                            "building",
                            "floor_numbers",
                            f"refers to floor {m.group(1)}",
                            relative,
                            number,
                            line.strip()[:110],
                        )
                    )
        if not is_doc:
            for rx in _SERVER_LABEL:
                server_floors |= {int(m.group(1)) for m in rx.finditer(line)}
            for m in _FLOOR_FUNCTION.finditer(line):
                if "server room" in m.group(2).lower():
                    server_floors.add(int(m.group(1)))
    if server_floors:
        facts.append(
            Fact(
                "server_rooms",
                "floors",
                ",".join(map(str, sorted(server_floors))),
                relative,
                0,
                "floors named in this file",
            )
        )
    for header, rows in tables:
        first = next((c for c in header if c in ("asset", "name", "item")), None)
        ahu = [
            n
            for n, r in rows
            if first and re.match(r"air handling unit", r.get(first, ""), re.IGNORECASE)
        ]
        if ahu:
            facts.append(
                Fact(
                    "air_handling_units",
                    "count",
                    str(len(ahu)),
                    relative,
                    ahu[0],
                    f"{len(ahu)} rows named Air Handling Unit",
                )
            )
        cols = set(header)
        for n, row in rows:
            desc = " ".join(row.get(c, "") for c in ("scope", "description", "task"))
            provider = (row.get("provider") or row.get("supplier") or "").strip()
            if provider and not _GENERIC_PROVIDER.search(provider):
                for topic, rx in PROVIDER_TOPICS.items():
                    if rx.search(desc):
                        facts.append(
                            Fact(
                                topic,
                                "provider",
                                provider,
                                relative,
                                n,
                                f"{desc[:60]} -> {provider}",
                            )
                        )
            ref = row.get("reference", "").strip()
            if ref and {"provider", "scope"} <= cols and PROVIDER_TOPICS["cleaning"].search(desc):
                facts.append(
                    Fact(
                        "cleaning",
                        "contract_reference",
                        ref.upper(),
                        relative,
                        n,
                        f"{desc[:60]} = {ref}",
                    )
                )
    return facts


def declared_floors(files: Sequence[Path]) -> List[int]:
    floors = set()
    for p in files:
        if p.suffix == ".ttl" and not _SKIP.search(p.name):
            floors |= {
                int(m)
                for m in re.findall(
                    r"#?\bFloor(\d)\b", p.read_text(encoding="utf-8", errors="replace")
                )
            }
    return sorted(floors)


def row_dates(files: Sequence[Path]) -> Dict[str, Dict[str, set]]:
    """{record code: {date, ...}} from the first cell of every table row that starts with one."""
    out: Dict[str, Dict[str, set]] = defaultdict(lambda: {"dates": set()})
    for path in files:
        if path.suffix != ".md":
            continue
        for _, rows in _tables(path.read_text(encoding="utf-8", errors="replace")):
            for _, row in rows:
                values = list(row.values())
                if values and re.fullmatch(r"[A-Z]{2,4}(?:-[A-Z0-9]+)+", values[0]):
                    out[values[0]]["dates"] |= set(_ISO.findall(" ".join(values)))
    return out


def cited_date_facts(path: Path, relative: str, known: Dict[str, Dict[str, set]]) -> List[Fact]:
    """A date written beside a record code that the coded record does not hold."""
    facts: List[Fact] = []
    for number, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        for m in _CODE_DATE.finditer(line):
            code, date = m.group(1), m.group(2)
            held = known.get(code, {}).get("dates")
            if held and date not in held:
                facts.append(
                    Fact(
                        code,
                        "cited_date",
                        f"{date} (its own record holds {', '.join(sorted(held))})",
                        relative,
                        number,
                        line.strip()[:110],
                    )
                )
    return facts


def scan(root: Path) -> List[Fact]:
    """Every extracted fact under one building's input folder."""
    files = sorted((root / "documents").glob("*.md")) + sorted(
        p for p in root.glob("*.ttl") if not _SKIP.search(p.name)
    )
    floors = declared_floors(files)
    known = row_dates(files)
    facts: List[Fact] = []
    for path in files:
        relative = f"{path.parent.name}/{path.name}" if path.suffix == ".md" else path.name
        facts += extract(path, relative, floors)
        facts += cited_date_facts(path, relative, known)
    return facts


def conflicts(facts: Iterable[Fact]) -> Dict[Tuple[str, str], Dict[str, List[Fact]]]:
    """{(subject, attribute): {value: [facts]}} for every attribute that carries >1 value."""
    grouped: Dict[Tuple[str, str], Dict[str, List[Fact]]] = defaultdict(lambda: defaultdict(list))
    for f in facts:
        grouped[(f.subject, f.attribute)][f.value].append(f)
    out = {}
    for key, values in grouped.items():
        if key[1] in ("floor_numbers", "cited_date"):  # a single occurrence is itself the finding
            out[key] = dict(values)
        elif len(values) > 1:
            out[key] = dict(values)
    return out


#: Disagreements that were read and are NOT provable from the data alone. They stay listed, so
#: the owner sees them, but they do not fail the check. Remove an entry once it is decided.
ACCEPTED: Dict[Tuple[str, str], str] = {
    ("grounds", "provider"): (
        "the grounds contract CON-2022-041 expired 2026-05-03 and the 2026-08 cost line names a "
        "different firm; a successor supplier would explain it, and only the owner can say"
    ),
}


def split_accepted(found: Dict[Tuple[str, str], Dict[str, List[Fact]]]):
    """(open conflicts, accepted-with-reason conflicts)."""
    open_ = {k: v for k, v in found.items() if k not in ACCEPTED}
    return open_, {k: v for k, v in found.items() if k in ACCEPTED}


def report(found: Dict[Tuple[str, str], Dict[str, List[Fact]]]) -> str:
    accepted_only = {k: v for k, v in found.items() if k in ACCEPTED}
    found = {k: v for k, v in found.items() if k not in ACCEPTED}
    tail = "".join(
        f"\n\naccepted, not resolved: {s}.{a}\n    {ACCEPTED[(s, a)]}"
        for (s, a) in sorted(accepted_only)
    )
    if not found:
        return "no conflicting facts found" + tail
    lines = [f"{len(found)} fact(s) stated with more than one value:"]
    for (subject, attribute), values in sorted(found.items()):
        lines.append(f"\n{subject}.{attribute}")
        for value, facts in sorted(values.items()):
            where = "; ".join(sorted({f"{f.source}:{f.line}" for f in facts})[:4])
            lines.append(f"    {value:28s} {where}")
    return "\n".join(lines) + tail


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--input", default=str(REPO / "input"), help="a building's input folder")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.input)
    if not root.is_dir():
        print(f"{root} does not exist (no active building)", file=sys.stderr)
        return 2
    found = conflicts(scan(root))
    if args.json:
        print(
            json.dumps(
                {
                    f"{s}.{a}": {v: [f"{f.source}:{f.line}" for f in fs] for v, fs in vals.items()}
                    for (s, a), vals in found.items()
                },
                indent=1,
            )
        )
    else:
        print(report(found))
    return 1 if split_accepted(found)[0] else 0


if __name__ == "__main__":
    sys.exit(main())
