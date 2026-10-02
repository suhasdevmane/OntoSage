# -*- coding: utf-8 -*-
"""Whole-building and per-floor questions answered by the store's own aggregates (row 2D-10).

WHY THIS EXISTS
---------------
"Which floor had the highest CO2 this week?" reached the SQL lane with 276 sensors and was
refused as "more than I can read row by row" (BUG-808). The refusal is a real budget: a week of
readings for 276 sensors is 276,000 rows, and summarising them by reading them is both slow and
easy to get wrong. But the question never needed the rows. A store can answer "the maximum of each
sensor over this window" with one GROUP BY, and combining a few hundred maxima into a per-floor
maximum is arithmetic. The refusal was the right answer to a question nobody had to ask that way.

The same gap turned up in four more questions, and they share this cause:

* "Has CO2 been high anywhere this week?"  -> refused, same text.
* "How much gas did we use this week?"     -> refused; it reaches 210 sensors.
* "How much water did floor 3 use yesterday?" -> "the sensor records flow rate, not volume ...
  add a volume-measuring sensor" (BUG-814): an instruction to buy hardware, for a series that can
  be integrated.
* "Which floor has the most people in it right now?" -> "cannot identify which floor".

WHAT THIS MODULE DOES, AND DELIBERATELY DOES NOT DO
---------------------------------------------------
Planning, SQL text, execution through the storage adapters, combining and wording are all here so
they can be tested with a fake adapter. It does NOT resolve which sensors a question is about: the
SPARQL lane has already done that and hands over the uuids, so a second resolver would be a second
answer to a question one lane should own. It adds only what the aggregate needs and the resolved
set lacks: where each sensor sits (room, floor) and its physical range.

The final text is written HERE, in code, from the numbers. A narrator that rewrote it could drift
from the figures (a "Floor 2 and 5" beside a bullet giving Floor 5 an exception was seen twice in
one day), and the boundary statement (which sensors, which window, what was left out) is the part
a reader most needs and a narrator most readily drops.

RULES THAT ARE NOT NEGOTIABLE
-----------------------------
* A verdict ("high", "exceeded") is given ONLY against a limit cited in the project's standards
  file, and the limit and its source are printed with it. With no cited limit the answer ranks and
  says it is not calling anything high or low.
* A quantity is never summed into a total unless it is additive: energy (interval energy) and
  volume are; a concentration or a temperature is not, and the answer says why.
* A volume from a rate series is an INTEGRAL over time, labelled as computed, and only when the
  series is regular enough; the sampling and the largest gap are stated.
* Stores are UTC. Windows are built with `requested_interval` and only DISPLAYED in building time.
* Nothing here names a building, a floor count, a namespace or a sensor id.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
)

from shared.utils import get_logger

logger = get_logger(__name__)

STAMP = "%Y-%m-%d %H:%M:%S"

#: Sensors per statement. A wide store answers a chunk in ONE pass over the window, so the chunk is
#: bounded by the width of the select list, not by the sensor count.
WIDE_CHUNK = 60
NARROW_CHUNK = 300

#: How recent a reading has to be to count as "right now". A sensor whose newest reading is older
#: than this is reported as having none, never quietly answered from an older value.
NOW_WINDOW_MINUTES = 60

#: A volume is integrated only for this many series: it needs a window function per series, which
#: reads every row of it, so it is bounded where the plain aggregate is not.
MAX_INTEGRATED_SERIES = 40

#: A gap is a spacing longer than this many times the series' usual spacing. Jitter is not a gap;
#: an outage is.
GAP_FACTOR = 3.0

#: A series is "regular enough" to integrate when the gaps it would have to bridge cover no more
#: than this share of the time its readings span, and its readings cover at least MIN_COVERAGE of
#: the window. Bridging a small hole by a straight line between its neighbours is a correction; when
#: the holes are a large part of the window the figure would be a guess presented as a measurement.
MAX_BRIDGED_SHARE = 0.10
MIN_COVERAGE = 0.5

_SAFE_ID = re.compile(r"^[0-9A-Za-z][0-9A-Za-z-]{7,63}$")
_SAFE_IDENT = re.compile(r"^[A-Za-z0-9_]+$")
_SAFE_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}$")

_STANDARDS_FILE = (
    Path(__file__).resolve().parents[1] / "data" / "standards" / "comfort_standards.json"
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. What was asked
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AggregateIntent:
    """The shape of an aggregate question: which statistic, over what grouping."""

    stat: str  # max | min | mean | exceed | total
    group: str  # floor | room | building
    descending: bool = True
    verdict: bool = False  # the question asks whether something WAS high
    now: bool = False  # "right now": the latest reading, not a window
    floors: Tuple[str, ...] = ()  # floors the question names
    worst: bool = False  # "worst" needs the measurand to say which end is bad


#: A question naming a FLOOR specifically ("on floor 2", "level 3"), as opposed to a room.
#: Used only to choose the grouping when a place-scoped claim is allowed (BUG-879), so the
#: figures are keyed by the floor rather than by each room on it. The floor word must carry a
#: NUMBER: "level" is also the second half of "noise level" and "CO2 level".
_FLOOR_NAMED_RE = re.compile(r"\b(?:floor|level|storey)\s*[a-z]?\d+\b", re.IGNORECASE)


_FLOOR_GROUP = re.compile(
    r"\b(?:which|what)\s+(?:floors?|levels?|storeys?)\b"
    r"|\b(?:each|every|per|by)\s+(?:floor|level|storey)\b"
    r"|\bfloor[\s-]by[\s-]floor\b|\bon\s+which\s+(?:floor|level)\b",
    re.IGNORECASE,
)
_ROOM_GROUP = re.compile(
    # up to three adjectives may sit between: "which COMMISSIONED CO2-MONITORED zones" is grouped
    # by zone like any other (live 2026-09-19); the same gap the other lanes' patterns carry
    r"\b(?:which|what)\s+(?:[\w-]+\s+){0,3}(?:rooms?|spaces?|zones?|areas?)\b"
    r"|\b(?:each|every|per|by)\s+(?:room|space|zone)\b"
    r"|\banywhere\b|\bsomewhere\b|\bwhere\b|\bany\s+(?:room|space|zone)s?\b",
    re.IGNORECASE,
)
_EXCEED = re.compile(
    r"\b(?:been|was|were|is|are|got|gone|gets|get)\s+(?:too\s+|very\s+)?"
    r"(?:high|elevated|above|over|excessive)\b"
    r"|\btoo\s+high\b|\bexceed\w*\b|\b(?:above|over)\s+(?:the\s+)?(?:limit|threshold|guideline)\b"
    r"|\bhigh\s+anywhere\b|\bunhealthy\b|\bunsafe\b"
    # "show SUSTAINED ELEVATED CO2", "high CO2 levels": the same question without a copula before
    # the word. Live 2026-09-19 that phrasing reached no lane and was refused as covering all 280
    # CO2 sensors, while "has CO2 been high anywhere this week?" was answered per floor.
    r"|\b(?:sustained|persistent|prolonged|repeated)\s+(?:\w+\s+){0,2}"
    r"(?:elevated|high|excessive|raised)\b"
    r"|\b(?:elevated|excessive)\s+(?:\w+\s+){0,2}(?:level|reading|concentration)s?\b",
    re.IGNORECASE,
)
_TOTAL = re.compile(
    r"\bhow\s+much\b|\btotal\b|\bin\s+total\b|\baltogether\b"
    r"|\b(?:did|do|does|have|has)\s+(?:we|you|it|the\s+building|(?:floor|level)\s*\d+)\s+us(?:e|ed)\b"
    r"|\bconsum\w*\b",
    re.IGNORECASE,
)
_MAX = re.compile(
    r"\b(?:highest|most|max(?:imum)?|peak|greatest|largest|biggest|warmest|hottest|busiest|"
    r"noisiest|brightest|stuffiest)\b",
    re.IGNORECASE,
)
_MIN = re.compile(
    r"\b(?:lowest|least|min(?:imum)?|smallest|coldest|coolest|quietest|dimmest|fewest|emptiest)\b"
    # "which floor has the LAST occupancy" is a slip for "least": a floor names the group, and
    # "the last <a measured quantity>" cannot otherwise mean anything (measured live 2026-09-20).
    # Only after "which <group> has/have/had the", so "the last reading" and "the last time" are
    # untouched.
    r"|\b(?:has|have|had|with)\s+the\s+last(?=\s+(?:occupancy|occupants?|headcount|footfall|"
    r"people|energy|power|electricity|co2|temperature|humidity|noise|light(?:ing)?|air)\b)",
    re.IGNORECASE,
)
_WORST = re.compile(r"\bworst\b", re.IGNORECASE)
_MEAN = re.compile(r"\b(?:average|mean|typical)\b", re.IGNORECASE)
_NOW = re.compile(
    r"\b(?:right\s+now|now|currently|at\s+the\s+moment|at\s+present|as\s+we\s+speak)\b",
    re.IGNORECASE,
)
_FLOOR_NUM = re.compile(r"\b(?:floor|level|storey)\s*(\d+)\b", re.IGNORECASE)
#: HOW a quantity is monitored: a question about the METHOD, not about the readings (BUG-1317).
#: Measured live 2026-09-30: "how is water consumption montored here?" was parsed as a TOTAL,
#: because `_TOTAL` matches `consum\w*`, and answered with seven flow-rate meters' latest values
#: -- "Water Flow Sensor HotWater recorded the highest flow rate of 26.10 L per min". The
#: relevance gate had deleted an earlier form of that answer with "Provides data, not explanation
#: of monitoring method", which is exactly right.
#:
#: Over both corpora 101 questions have this shape and the aggregate lane claims 24 of them, 23
#: from the REAL survey corpus: "How do you measure noise levels in dB?", "how is humidity
#: monitored", "How do you track occupancy?", "How does the building detect poor air quality?".
#: Each was answered with a building mean of the quantity it names.
#:
#: NOT CAUGHT, AND SAID SO RATHER THAN PAPERED OVER: the verbatim question above spells it
#: "montored". This is keyed on the verb, so a misspelling of the verb misses, and the real
#: corpus misspells freely ("rainwter", "buidling", "ventilaton"). CAVEAT-1318.
_MONITORING_METHOD = (
    r"how\s+(?:is|are|was|were|do|does|did|can|could|would|will)\s+(?:\w+[\s-]+){0,4}?"
    r"(?:monitor|monitors|monitored|monitoring|measure|measures|measured|measuring|"
    r"track|tracks|tracked|tracking|record|records|recorded|recording|"
    r"detect|detects|detected|detecting|sense|senses|sensed|"
    r"calculate[sd]?|calculated|computed?|collect|collects|collected|"
    r"gather|gathers|gathered|determined?|determines|assessed?|assesses)\b"
)

#: Questions that use an aggregate word but ask for something else: a forecast, a change over time,
#: a time of day, or the METHOD by which something is monitored. "Which floor will have the highest
#: CO2 tomorrow" is not a maximum of the past, and "how is humidity monitored" is not a mean of it.
_NOT_AN_AGGREGATE = re.compile(
    r"\b(?:will|going\s+to|tomorrow|next\s+(?:hour|day|week|month)|forecast|predict\w*|"
    r"expected|trend\w*|rise|rose|risen|rising|fall|fell|fallen|falling|increase[sd]?|"
    r"decrease[sd]?|chang(?:e|ed|es|ing)|over\s+time|what\s+time|when)\b"
    r"|\b" + _MONITORING_METHOD,
    re.IGNORECASE,
)


def parse_intent(question: str) -> Optional[AggregateIntent]:
    """The aggregate shape of a question, or None when it is not one.

    Needs a STATISTIC word: a question that merely mentions a floor is a lookup, not an aggregate.
    Order matters: "has CO2 been high anywhere" holds no max word and is an exceedance question;
    "which floor has the most people" holds "most" and no exceedance word.
    """
    q = question or ""
    if _NOT_AN_AGGREGATE.search(q):
        return None
    floors = tuple(dict.fromkeys(_FLOOR_NUM.findall(q)))
    now = bool(_NOW.search(q))
    if _EXCEED.search(q):
        stat, desc, verdict = "exceed", True, True
    elif _MEAN.search(q):
        # "the highest average" and "the lowest average" are means, ordered by the extreme word
        stat, desc, verdict = "mean", not _MIN.search(q), False
    elif _TOTAL.search(q) and not _MAX.search(q) and not _MIN.search(q):
        stat, desc, verdict = "total", True, False
    elif _MAX.search(q):
        stat, desc, verdict = "max", True, False
    elif _MIN.search(q):
        stat, desc, verdict = "min", False, False
    elif _WORST.search(q):
        return _with_group(q, "max", True, False, now, floors, worst=True)
    else:
        return None
    return _with_group(q, stat, desc, verdict, now, floors)


def _with_group(
    q: str,
    stat: str,
    desc: bool,
    verdict: bool,
    now: bool,
    floors: Tuple[str, ...],
    worst: bool = False,
) -> Optional[AggregateIntent]:
    if _ROOM_GROUP.search(q):
        group = "room"
    elif _FLOOR_GROUP.search(q) or floors:
        group = "floor"
    else:
        group = "building"
    return AggregateIntent(stat, group, desc, verdict, now, floors, worst)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Over what period
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Window:
    """A period on the STORES' clock (naive UTC), with the words to show it in building time."""

    start: str
    end: str
    label: str
    latest: bool = False


def _stamp(value: Any) -> Optional[datetime]:
    text = str(value or "").strip().replace("T", " ")[:19]
    # A date with no time is the start of that day, which is how every SQL builder reads it.
    for fmt in (STAMP, "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _show(when: datetime, tz_name: Optional[str]) -> str:
    from orchestrator.services.requested_interval import to_local

    return f"{to_local(when, tz_name):%a %d %b %H:%M}"


_PERIOD = re.compile(
    r"\b(?:(?:in\s+)?the\s+)?(?:last|past|previous)\s+(\d+|a|an|one|two|three)\s*"
    r"(hour|hr|day|week|month)s?\b",
    re.IGNORECASE,
)
_WORD_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3}


def resolve_window(
    question: str,
    start_date: Optional[str],
    end_date: Optional[str],
    tz_name: Optional[str],
    latest: bool = False,
    now: Optional[datetime] = None,
) -> Optional[Window]:
    """The period the answer covers, or None when neither the pipeline nor the words name one.

    The pipeline's own bounds win: dialogue has already resolved the phrase once, and a second
    reading of "this week" here would be a second answer to a question requested_interval exists
    to answer once. Only when it supplied none are the words read, and only the ones whose meaning
    is not in dispute (a calendar day, "this/last week", "last N hours/days").
    """
    from orchestrator.services.requested_interval import (
        calendar_day_bounds,
        local_now,
        store_now,
        to_local,
        to_store,
    )

    end_now = now or store_now()
    if latest:
        start = end_now - timedelta(minutes=NOW_WINDOW_MINUTES)
        return Window(
            start.strftime(STAMP),
            end_now.strftime(STAMP),
            f"the newest reading from each sensor in the last {NOW_WINDOW_MINUTES} minutes "
            f"(to {_show(end_now, tz_name)}, building time)",
            latest=True,
        )
    start_dt, end_dt = _stamp(start_date), _stamp(end_date)
    if start_dt is not None:
        end_dt = end_dt or end_now
    else:
        local = to_local(end_now, tz_name) if now is not None else local_now(tz_name)
        day = calendar_day_bounds(question, tz_name, now=local)
        if day:
            start_dt, end_dt = _stamp(day[0]), _stamp(day[1])
        else:
            low = (question or "").lower()
            midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
            m = _PERIOD.search(low)
            if re.search(r"\bthis\s+week\b", low):
                monday = midnight - timedelta(days=midnight.weekday())
                start_dt, end_dt = to_store(monday, tz_name), end_now
            elif re.search(r"\blast\s+week\b", low) and not m:
                monday = midnight - timedelta(days=midnight.weekday() + 7)
                start_dt = to_store(monday, tz_name)
                end_dt = to_store(monday + timedelta(days=7) - timedelta(seconds=1), tz_name)
            elif re.search(r"\bthis\s+month\b", low):
                start_dt, end_dt = to_store(midnight.replace(day=1), tz_name), end_now
            elif m:
                n = m.group(1).lower()
                count = int(n) if n.isdigit() else _WORD_NUM.get(n, 1)
                unit = m.group(2).lower()
                hours = count * {"hour": 1, "hr": 1, "day": 24, "week": 168, "month": 720}[unit]
                start_dt, end_dt = end_now - timedelta(hours=hours), end_now
            elif re.search(r"\b(?:this|the)\s+past\s+week\b|\bpast\s+week\b", low):
                start_dt, end_dt = end_now - timedelta(days=7), end_now
    if start_dt is None or end_dt is None or end_dt <= start_dt:
        return None
    return Window(
        start_dt.strftime(STAMP),
        end_dt.strftime(STAMP),
        f"{_show(start_dt, tz_name)} to {_show(end_dt, tz_name)} (building time)",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. What counts as high — only what the standards file cites
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Threshold:
    """A limit and where it comes from. A verdict without both is not allowed."""

    value: float
    unit: str
    standard: str
    measurand: str


#: Which standard the question named. Order: the specific before the general.
_STANDARD_WORDS = (
    ("well", re.compile(r"\bwell\b", re.IGNORECASE)),
    ("breeam", re.compile(r"\bbreeam\b", re.IGNORECASE)),
    ("en15251", re.compile(r"\ben\s*(?:15251|16798)\b", re.IGNORECASE)),
    ("iso50001", re.compile(r"\biso\s*50001\b", re.IGNORECASE)),
    ("ashrae55", re.compile(r"\bashrae\b", re.IGNORECASE)),
)
#: The standard used when the question names none: the analytics engine's own default.
_DEFAULT_STANDARD = "ashrae55"
_MEASURAND_UNITS = {
    "co2": "ppm",
    "temperature": "°C",
    "humidity": "%",
    "pm25": "µg/m³",
    "voc": "ppb",
}


def cited_threshold(
    measurand: Optional[str], question: str = "", path: Optional[Path] = None
) -> Optional[Threshold]:
    """The upper limit for a measurand from the standards file, or None when none is cited.

    None is a real answer: the caller then RANKS and says it is not calling anything high. The
    limit is the upper bound of the file's [low, high] pair; a lower bound is a different question
    ("too cold") and is not inferred from a question about "high".
    """
    if not measurand:
        return None
    try:
        raw = json.loads((path or _STANDARDS_FILE).read_text(encoding="utf-8"))
    except Exception as exc:  # a missing file means no verdict, not a failed answer
        logger.warning(f"[aggregate] standards file unreadable: {exc}")
        return None
    chosen = next((key for key, rx in _STANDARD_WORDS if rx.search(question or "")), None)
    order = [chosen] if chosen else []
    order += [_DEFAULT_STANDARD] + [k for k in raw if k not in (chosen, _DEFAULT_STANDARD)]
    for key in order:
        entry = raw.get(key) or {}
        band = entry.get(measurand)
        if isinstance(band, list) and len(band) == 2:
            try:
                return Threshold(
                    float(band[1]),
                    _MEASURAND_UNITS.get(measurand, ""),
                    str(entry.get("name") or key),
                    measurand,
                )
            except (TypeError, ValueError):
                continue
        if chosen and key == chosen:
            return None  # the standard the reader named does not cover this: do not substitute
    return None


_PM25 = re.compile(r"\bpm\s*2\.?5\b", re.IGNORECASE)


#: A quantity named in a lay word rather than a sensor's own: "prevent OVERHEATING", "felt HOT and
#: STUFFY". Read on the QUESTION only, and only where the word is about the air: "hot-water plant"
#: and "heating or cooling changeover" (tail G, 2026-09-20) name equipment and a process, and were
#: answered with a temperature summary before this gate asked what the question itself was about.
_LAY_QUANTITY_RE = re.compile(
    r"\boverheat\w*\b|(?<![-\w])(?:too\s+)?(?:hot|warm|cold|chilly|freezing|stuffy|stale|"
    r"humid|muggy|noisy|loud)\b(?![-\s]water)",
    re.IGNORECASE,
)


#: Lay words for the quantities, each mapped to the measurand a sensor would carry. "Hot and
#: stuffy" is two quantities and both are the question's own.
_LAY_MEASURANDS = (
    (
        re.compile(
            r"\boverheat\w*\b|(?<![-\w])(?:too\s+)?(?:hot|warm|cold|chilly|freezing)\b"
            r"(?![-\s]water)",
            re.IGNORECASE,
        ),
        "temperature",
    ),
    (re.compile(r"\b(?:stuffy|stale)\b", re.IGNORECASE), "co2"),
    (re.compile(r"\b(?:humid|muggy)\b", re.IGNORECASE), "humidity"),
    (re.compile(r"\b(?:noisy|loud)\b", re.IGNORECASE), "sound"),
    # busy / crowded / quiet-as-in-empty is occupancy; "ambient light" and "bright" are light.
    # "occupied" is deliberately NOT here: "during an approved occupied period" describes a period
    # of a CO2 question, and made that question's own quantity include occupancy.
    (re.compile(r"\b(?:busy|busier|busiest|crowded|uncrowded)\b", re.IGNORECASE), "occupancy"),
    (
        re.compile(
            r"\b(?:ambient\s+)?light(?:ing)?\b(?!\s*(?:switch|bulb|fitting|fixture))"
            r"|\b(?:bright|dim|dark)\b",
            re.IGNORECASE,
        ),
        "illuminance",
    ),
)

#: Quantities that answer to another's name: a question about "air quality" is answered by the CO2,
#: particulate and VOC sensors, so the sensors' measurand need not be the literal words.
_EQUIVALENT = {
    "air quality": {"co2", "pm25", "voc", "air quality"},
    "co2": {"co2", "air quality"},
}


def question_measurands(question: str) -> set:
    """Every quantity the question ITSELF names, in a sensor's word or a lay one."""
    from orchestrator.services.plausibility import measurand_of

    found = set()
    key = measurand_key([question])
    if key:
        found.add(key)
    text = question or ""
    # a question naming two quantities ("CO2 or temperature") names both
    for word in re.findall(r"[A-Za-z0-9₂]+", text):
        m = measurand_of(word)
        if m:
            found.add(m)
    for rx, m in _LAY_MEASURANDS:
        if rx.search(text):
            found.add(m)
    return found


def question_names_a_quantity(question: str) -> bool:
    """True when the question ITSELF names a measurable quantity, in a sensor's word or a lay one."""
    return bool(question_measurands(question))


def question_asks_about(question: str, measurand: Optional[str]) -> bool:
    """Is the sensors' quantity one the question is actually about?

    THE QUESTION AND THE SENSORS MUST AGREE (wave 7). `question_names_a_quantity` only asked that the
    question name SOME quantity; it did not ask that it be the quantity of the sensors the pipeline
    happened to bind, so a question about "busy" could be answered with a temperature summary.
    """
    if not measurand:
        return False
    asked = question_measurands(question)
    accepted = set(asked)
    for a in asked:
        accepted |= _EQUIVALENT.get(a, set())
    return measurand in accepted


def measurand_key(texts: Iterable[str]) -> Optional[str]:
    """The quantity a set of sensors measures, from their own names and classes."""
    from orchestrator.services.plausibility import measurand_of

    votes: Dict[str, int] = {}
    for text in texts:
        key = "pm25" if _PM25.search(text or "") else measurand_of(text or "")
        if key:
            votes[key] = votes.get(key, 0) + 1
    return max(votes, key=votes.get) if votes else None


_DISPLAY = {"co2": "CO2", "pm25": "PM2.5", "voc": "VOC", "ph": "pH"}


def display_name(measurand: Optional[str]) -> str:
    """How the answer names the quantity."""
    if not measurand:
        return "the reading"
    return _DISPLAY.get(measurand, measurand.replace("_", " "))


#: Words that may sit to the left of a quantity noun without qualifying WHICH quantity it is:
#: determiners, question and copula words, the statistic the reader asked for, and the place
#: words the grouping already handles. A CLOSED set of function words, deliberately — not a list
#: of quantities. Enumerating the domain is what lesson #170 says never to do; enumerating
#: English's function words is finite and does not rot when a building adds a modality.
_QUALIFIER_STOP = frozenset(
    """
    a an the this that these those any some all each every both either neither no
    what whats what's which who whose how when where why is are was were be been being am
    do does did has have had can could will would shall should may might must
    and or but nor if then than as of in on at to for from by with about into over under
    me my mine our ours your yours its their theirs his her hers
    average avg mean median typical usual current latest present highest lowest max maximum
    min minimum peak most least worst best top bottom highest-average total overall
    building buildings floor floors storey storeys level levels room rooms space spaces
    zone zones area areas site here there now today yesterday tonight
    sensor sensors reading readings value values figure figures data
    show tell give get find report say state
    right just still really very quite much many more less
    high higher low lower poor good bad better worse warm warmer cold colder hot hotter
    cool cooler loud louder quiet quieter stable steady comfortable uncomfortable safe unsafe
    normal abnormal acceptable excessive elevated raised reduced sudden
    """.split()
)

#: How far left the qualifier may reach. "supply air temperature" is three words; nothing a
#: reader writes to name a quantity needs more, and a longer reach starts swallowing clauses.
_QUALIFIER_MAX_WORDS = 3

_WORDS_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def asked_quantity_name(question: str, measurand: Optional[str], labels: Sequence[str] = ()) -> str:
    """What to CALL the quantity in the answer: the reader's own phrase, or the coarse measurand.

    `display_name(measurand)` is a vote over coarse categories and it is right for a set of room
    sensors. It is WRONG for a set that all measure something narrower, and the failure is a
    false statement about the building rather than a clumsy one. Measured live 2026-09-30
    (BUG-1255): *"What is the return air temperature?"* bound this building's six AHU return-air
    points -- correctly, one per floor, ~13,120 rows each, newest four minutes before the ask --
    and answered **"Across the building temperature is averaging 21.4 degC"** with a per-floor
    table beneath it reading "Floor 0 | 26.0". An occupant is told their floor is 26 degC when
    the figure is the air inside the ductwork. The answer-relevance gate deleted it and was
    right to.

    TWO THINGS MAKE THIS SAFE, and neither is a list of quantity names.

    * The phrase is the READER'S. It is read leftwards from the quantity word the question
      itself uses, across words that are not function words, so it can never be more specific
      than what was asked. A question that says only "temperature" still gets "temperature".
    * The phrase must be TRUE OF EVERY BOUND SENSOR. Each extra word must appear in every one
      of their names. If the reader asks for the outside air temperature and the pipeline binds
      room sensors, the labels do not carry "outside", the coarse name is kept, and the
      relevance gate goes on catching the off-topic answer as before. So this cannot invent a
      quantity, and it cannot rename a set that does not measure what was asked.

    Wording only. It changes no figure, no grouping and no decision about whether to answer.
    """
    base = display_name(measurand)
    if not question or not measurand:
        return base
    words = _WORDS_RE.findall(question)
    lowered = [w.lower() for w in words]
    #: the quantity word as the READER spelled it -- "temperature", "humidity", "noise"
    anchor = base.lower().split()[-1]
    try:
        at = lowered.index(anchor)
    except ValueError:
        return base
    # A word the coarse name ALREADY carries is not a qualifier. Without this, measurand
    # "air quality" read leftwards from "quality" over the question's own "air" and produced
    # "air air quality".
    stop = _QUALIFIER_STOP | set(base.lower().split())
    extra: List[str] = []
    i = at - 1
    while i >= 0 and len(extra) < _QUALIFIER_MAX_WORDS and lowered[i] not in stop:
        # A POSSESSIVE OR A FRAGMENT IS NOT A QUALIFIER, and the short words are where the
        # measured mistakes were. Over both corpora the three wrong names this produced were
        # "today's occupancy" -> "s occupancy", "the AI temperature settings" -> "ai
        # temperature" and a truncated "re temperature conditions" -> "re temperature". Nothing
        # under three letters names a quantity.
        if len(lowered[i]) < 3:
            break
        extra.insert(0, lowered[i])
        i -= 1
    if not extra:
        return base
    # WORD BY WORD, NOT BY SUBSTRING. "the AI temperature settings" passed a substring check
    # against every label reading "... air temperature", because "ai" sits inside "air", and
    # named the quantity "ai temperature".
    names = [set(w.lower() for w in _WORDS_RE.findall(str(lb or ""))) for lb in labels if lb]
    if not names or not all(set(extra) <= nm for nm in names):
        # THE READER'S QUALIFIER IS NOT TRUE OF THE BOUND SENSORS. This used to fall back to the
        # COARSE name, on the reasoning that it is "at least not a claim about a quantity nobody
        # measured". Measured live, that is not enough (BUG-1403):
        #
        #   Q  "What is the barometric pressure in the building?"
        #   A  "Across the building **pressure** is averaging 19.1 Pa, ranging from 0.0 to 51.5"
        #
        # The six bound sensors are all "Air Handling Unit — Floor N filter differential
        # pressure", typed `Filter_Differential_Pressure_Sensor`: the pressure drop across an
        # AHU filter, which is a filter-clogging indicator. Barometric pressure is ~101,325 Pa.
        # The coarse name was true of the sensors and answered a question about a DIFFERENT
        # physical quantity without ever saying the qualifier had been dropped. This building
        # holds no barometric sensor, so the right answer is that it cannot be given.
        #
        # So where the reader's qualifier does not hold, name the quantity THE SENSORS carry:
        # the run of words every bound label puts immediately before the quantity word. That
        # cannot invent anything — every word comes from every label — and it hands the reader
        # the discrepancy instead of hiding it ("filter differential pressure", not "pressure").
        # Where the labels share no such run, the coarse name stands as before.
        theirs = _shared_qualifier(labels, anchor)
        # THE LABELS ARE LOGGED, NOT JUST THE DECISION. Diagnosing this cost two probes: the
        # graph's own labels yield 'filter differential' and the live turn yielded '', so the
        # strings reaching here are not the strings the graph holds — and the old line recorded
        # the verdict without the input that produced it.
        logger.info(
            "[aggregate] qualifier %r not carried by all %d bound sensor names — naming what "
            "they DO carry: %r (from labels %r)",
            " ".join(extra),
            len(names),
            (theirs + " " + base).strip(),
            [str(lb)[:60] for lb in list(labels)[:6]],
        )
        return (theirs + " " + base).strip() if theirs else base
    return " ".join(extra) + " " + base


def _shared_qualifier(labels: Sequence[Any], anchor: str) -> str:
    """The words every bound label puts immediately before ``anchor``, or "" (BUG-1403).

    Derived from the labels and nothing else, so it cannot name a quantity the building does not
    measure. Returns "" unless EVERY label agrees, because a qualifier true of some sensors and
    not others is the defect this is here to fix, one level down.
    """
    # THE LABELS MAY NOT CONTAIN THE QUANTITY WORD AT ALL, and that is the live case. Measured:
    # the six bound pressure sensors reach this function as 'AHU F5 Filter DP', 'AHU F2 Filter
    # DP', ... -- short display names in which "differential pressure" is abbreviated to "DP",
    # so there is no "pressure" to read leftwards from and the first version of this returned ""
    # and left the answer calling AHU filter differential pressure simply "pressure".
    #
    # Where no label carries the anchor, use the words EVERY label shares instead, in the order
    # the first one spells them. For the six above that is "AHU Filter DP", which is true of all
    # six and cannot be mistaken for barometric pressure. Still incapable of inventing: a word
    # appears only if it appears in every bound label.
    # AT LEAST TWO LABELS, because the whole claim is "words EVERY label shares" and with one
    # label that is merely its own words. A single bound sensor named for a different quantity
    # would otherwise be read as naming this one (a test asserting that caught it).
    if len(list(labels)) >= 2 and not any(
        anchor in [w.lower() for w in _WORDS_RE.findall(str(lb or ""))] for lb in labels
    ):
        token_sets = [
            {w.lower() for w in _WORDS_RE.findall(str(lb or ""))} for lb in labels if str(lb or "")
        ]
        if not token_sets:
            return ""
        shared = set.intersection(*token_sets)
        first = [w for w in _WORDS_RE.findall(str(labels[0] or ""))]
        kept = [w for w in first if w.lower() in shared and len(w) > 1]
        return " ".join(kept) if kept else ""

    runs = []
    for lb in labels or ():
        words = [w.lower() for w in _WORDS_RE.findall(str(lb or ""))]
        if anchor not in words:
            return ""
        at = words.index(anchor)
        run: List[str] = []
        i = at - 1
        while i >= 0 and len(run) < _QUALIFIER_MAX_WORDS:
            w = words[i]
            if len(w) < 3 or w in _QUALIFIER_STOP:
                break
            run.insert(0, w)
            i -= 1
        if not run:
            return ""
        runs.append(tuple(run))
    if not runs or len(set(runs)) != 1:
        return ""
    return " ".join(runs[0])


# ─────────────────────────────────────────────────────────────────────────────
# 4. Where each sensor sits (the one thing the resolved set does not carry)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Place:
    room: str = ""  # the label of the space the sensor is in
    floor: str = ""  # the floor number, as the graph spells it
    on_floor: bool = False  # located on the FLOOR itself: a floor-level meter, not a room's


def build_location_query(uuids: Sequence[str]) -> str:
    """SPARQL for sensor -> (space, floor). The prefixes are declared; nothing is a literal id."""
    values = " ".join(f'"{u}"' for u in uuids if _SAFE_ID.match(str(u)))
    return (
        "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
        "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>\n"
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "SELECT DISTINCT ?uuid ?loc ?locLabel ?floorNum ?onFloor WHERE {\n"
        f"  VALUES ?uuid {{ {values} }}\n"
        "  ?ref ref:hasTimeseriesId ?uuid .\n"
        "  ?sensor ref:hasExternalReference ?ref .\n"
        "  OPTIONAL { ?sensor brick:hasLocation ?loc .\n"
        "    OPTIONAL { ?loc rdfs:label ?locLabel }\n"
        "    OPTIONAL { ?loc (brick:isPartOf|^brick:hasPart)* ?fl . ?fl a brick:Floor .\n"
        '               BIND(REPLACE(STR(?fl), "^.*[Ff]loor", "") AS ?floorNum) }\n'
        "    BIND(EXISTS { ?loc a brick:Floor } AS ?onFloor) }\n"
        "} LIMIT 20000"
    )


def parse_locations(result: Dict[str, Any]) -> Dict[str, Place]:
    """Places by uuid from a SPARQL-JSON result. A sensor with several is given its ROOM's."""
    out: Dict[str, Place] = {}
    bindings = ((result or {}).get("results") or {}).get("bindings") or []
    for b in bindings:
        uuid = (b.get("uuid") or {}).get("value")
        if not uuid:
            continue
        place = Place(
            room=(b.get("locLabel") or {}).get("value", ""),
            floor=(b.get("floorNum") or {}).get("value", ""),
            on_floor=str((b.get("onFloor") or {}).get("value", "")).lower() == "true",
        )
        held = out.get(uuid)
        if held is None or (held.on_floor and not place.on_floor) or (not held.room and place.room):
            out[uuid] = place
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 5. SQL — one statement per store shape. Every one aggregates in the store.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Statement:
    """A statement, what it returns, and which sensors it covers (for honest failure reports)."""

    sql: str
    kind: str
    uuids: Tuple[str, ...]


def layout_of(adapter: Any) -> str:
    """Which SQL shape an adapter speaks. Duck-typed: this module imports no adapter class."""
    kind = str(getattr(getattr(adapter, "adapter_type", None), "value", "") or "").lower()
    if kind == "mysql":
        return "mysql_narrow" if getattr(adapter, "table", None) else "mysql_wide"
    if kind in ("postgresql", "timescaledb"):
        return "pg_narrow" if getattr(adapter, "_narrow", None) else "pg_wide"
    if kind == "cassandra":
        return "cassandra"
    return "unsupported"


def _chunks(items: Sequence[str], size: int) -> List[List[str]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def _wide_table_of(adapter: Any) -> str:
    """The wide table an adapter reads: its own answer, never a name written here."""
    getter = getattr(adapter, "_wide_table", None)
    return _ident(getter() if callable(getter) else "sensor_data")


def _wide_ts_of(adapter: Any) -> str:
    """The wide table's time column, matched case-insensitively against the adapter's schema."""
    known = getattr(adapter, "_columns_cache", None) or set()
    by_lower = {str(c).lower(): str(c) for c in known}
    for candidate in ("datetime", "timestamp", "time", "ts", "recorded_at"):
        if candidate in by_lower:
            return _ident(by_lower[candidate])
    return "Datetime"


def _clean_stamp(value: str) -> str:
    text = str(value).replace("T", " ")[:19]
    if not _SAFE_STAMP.match(text):
        raise ValueError(f"unsafe window bound: {value!r}")
    return text


def _num(value: float) -> str:
    return repr(float(value))


def _banded(col: str, band: Optional[Tuple[float, float]]) -> str:
    """The column, or NULL wherever it is outside its physical range (so an aggregate skips it)."""
    if not band:
        return col
    return f"IF({col} BETWEEN {_num(band[0])} AND {_num(band[1])}, {col}, NULL)"


def _pg_banded(col: str, band: Optional[Tuple[float, float]]) -> str:
    if not band:
        return col
    return f"CASE WHEN {col} BETWEEN {_num(band[0])} AND {_num(band[1])} THEN {col} END"


def aggregate_statements(
    layout: str,
    adapter: Any,
    uuids: Sequence[str],
    window: Window,
    limit: Optional[float] = None,
    bands: Optional[Dict[str, Tuple[float, float]]] = None,
) -> List[Statement]:
    """GROUP BY statements returning per-sensor (count, min, max, sum, first, last, exceed).

    Never a row-level SELECT: the store reduces, this module only combines the reductions.
    """
    start, end = _clean_stamp(window.start), _clean_stamp(window.end)
    bands = bands or {}
    safe = [u for u in dict.fromkeys(uuids) if _SAFE_ID.match(str(u))]
    if not safe:
        return []
    out: List[Statement] = []

    if layout == "mysql_narrow":
        table = _ident(getattr(adapter, "table", ""))
        for band, group in _by_band(safe, bands):
            x = _banded("`value`", band)
            over = f", SUM({x} > {_num(limit)}) AS ex" if limit is not None else ", 0 AS ex"
            for part in _chunks(group, NARROW_CHUNK):
                inl = ", ".join(f"'{u}'" for u in part)
                out.append(
                    Statement(
                        f"SELECT `uuid`, COUNT({x}) AS n, MIN({x}) AS mn, MAX({x}) AS mx, "
                        f"SUM({x}) AS sm, MIN(`datetime`) AS t0, MAX(`datetime`) AS t1"
                        f"{over}, SUM(`value` IS NOT NULL AND {x} IS NULL) AS bad "
                        f"FROM `{table}` WHERE `uuid` IN ({inl}) AND `datetime` >= '{start}' "
                        f"AND `datetime` <= '{end}' GROUP BY `uuid`",
                        "narrow_agg",
                        tuple(part),
                    )
                )
    elif layout == "mysql_wide":
        table = _wide_table_of(adapter)
        ts = _wide_ts_of(adapter)
        known = getattr(adapter, "_columns_cache", None)
        cols = [u for u in safe if not known or u in known]
        for part in _chunks(cols, WIDE_CHUNK):
            picks: List[str] = []
            for i, u in enumerate(part):
                c = f"`{u}`"
                x = _banded(c, bands.get(u))
                picks.append(
                    f"COUNT({x}) AS n{i}, MIN({x}) AS mn{i}, MAX({x}) AS mx{i}, "
                    f"SUM({x}) AS sm{i}, "
                    f"MIN(CASE WHEN {c} IS NOT NULL THEN `{ts}` END) AS t0{i}, "
                    f"MAX(CASE WHEN {c} IS NOT NULL THEN `{ts}` END) AS t1{i}, "
                    + (f"SUM({x} > {_num(limit)}) AS ex{i}" if limit is not None else f"0 AS ex{i}")
                    + f", SUM({c} IS NOT NULL AND {x} IS NULL) AS bad{i}"
                )
            out.append(
                Statement(
                    f"SELECT {', '.join(picks)} FROM `{table}` WHERE `{ts}` >= '{start}' "
                    f"AND `{ts}` <= '{end}'",
                    "wide_agg",
                    tuple(part),
                )
            )
    elif layout == "pg_narrow":
        nb = getattr(adapter, "_narrow") or {}
        t, u_, ts, v = (_ident(nb.get(k, "")) for k in ("table", "uuid", "ts", "value"))
        for band, group in _by_band(safe, bands):
            x = _pg_banded(f'"{v}"', band)
            over = (
                f", COUNT(CASE WHEN {x} > {_num(limit)} THEN 1 END) AS ex"
                if limit is not None
                else ", 0 AS ex"
            )
            for part in _chunks(group, NARROW_CHUNK):
                inl = ", ".join(f"'{u}'" for u in part)
                out.append(
                    Statement(
                        f'SELECT "{u_}" AS uuid, COUNT({x}) AS n, MIN({x}) AS mn, MAX({x}) AS mx, '
                        f'SUM({x}) AS sm, MIN("{ts}") AS t0, MAX("{ts}") AS t1{over}, '
                        f'COUNT(CASE WHEN "{v}" IS NOT NULL AND {x} IS NULL THEN 1 END) AS bad '
                        f'FROM "{t}" WHERE "{u_}" IN ({inl}) AND "{ts}" >= \'{start}\' '
                        f'AND "{ts}" <= \'{end}\' GROUP BY "{u_}"',
                        "narrow_agg",
                        tuple(part),
                    )
                )
    elif layout == "cassandra":
        ks, tbl = _ident(getattr(adapter, "_keyspace", "")), _ident(
            getattr(adapter, "_default_table", "")
        )
        for u in safe:
            base = f"FROM {ks}.{tbl} WHERE uuid = '{u}' AND timestamp >= '{start}' AND timestamp <= '{end}'"
            out.append(
                Statement(
                    f"SELECT COUNT(value) AS n, MIN(value) AS mn, MAX(value) AS mx, SUM(value) AS sm, "
                    f"MIN(timestamp) AS t0, MAX(timestamp) AS t1 {base}",
                    "cql_agg",
                    (u,),
                )
            )
            if limit is not None:
                out.append(
                    Statement(
                        f"SELECT COUNT(value) AS ex {base} AND value > {_num(limit)} ALLOW FILTERING",
                        "cql_exceed",
                        (u,),
                    )
                )
    return out


def latest_statements(
    layout: str, adapter: Any, uuids: Sequence[str], window: Window
) -> List[Statement]:
    """Statements returning each sensor's NEWEST reading inside the window (the "right now" read)."""
    start, end = _clean_stamp(window.start), _clean_stamp(window.end)
    safe = [u for u in dict.fromkeys(uuids) if _SAFE_ID.match(str(u))]
    out: List[Statement] = []
    if layout == "mysql_narrow":
        table = _ident(getattr(adapter, "table", ""))
        for part in _chunks(safe, NARROW_CHUNK):
            inl = ", ".join(f"'{u}'" for u in part)
            out.append(
                Statement(
                    f"SELECT t.`uuid` AS uuid, t.`value` AS value, t.`datetime` AS ts "
                    f"FROM `{table}` t JOIN (SELECT `uuid`, MAX(`datetime`) AS md FROM `{table}` "
                    f"WHERE `uuid` IN ({inl}) AND `datetime` >= '{start}' AND `datetime` <= '{end}' "
                    f"AND `value` IS NOT NULL GROUP BY `uuid`) m "
                    f"ON t.`uuid` = m.`uuid` AND t.`datetime` = m.md",
                    "latest",
                    tuple(part),
                )
            )
    elif layout == "mysql_wide":
        table = _wide_table_of(adapter)
        ts = _wide_ts_of(adapter)
        known = getattr(adapter, "_columns_cache", None)
        cols = [u for u in safe if not known or u in known]
        for part in _chunks(cols, WIDE_CHUNK):
            branches = " UNION ALL ".join(
                f"(SELECT '{u}' AS uuid, `{u}` AS value, `{ts}` AS ts FROM `{table}` "
                f"WHERE `{u}` IS NOT NULL AND `{ts}` >= '{start}' AND `{ts}` <= '{end}' "
                f"ORDER BY `{ts}` DESC LIMIT 1)"
                for u in part
            )
            out.append(Statement(branches, "latest", tuple(part)))
    elif layout == "pg_narrow":
        nb = getattr(adapter, "_narrow") or {}
        t, u_, ts, v = (_ident(nb.get(k, "")) for k in ("table", "uuid", "ts", "value"))
        for part in _chunks(safe, NARROW_CHUNK):
            inl = ", ".join(f"'{u}'" for u in part)
            out.append(
                Statement(
                    f'SELECT DISTINCT ON ("{u_}") "{u_}" AS uuid, "{v}" AS value, "{ts}" AS ts '
                    f'FROM "{t}" WHERE "{u_}" IN ({inl}) AND "{ts}" >= \'{start}\' '
                    f'AND "{ts}" <= \'{end}\' AND "{v}" IS NOT NULL ORDER BY "{u_}", "{ts}" DESC',
                    "latest",
                    tuple(part),
                )
            )
    elif layout == "cassandra":
        ks, tbl = _ident(getattr(adapter, "_keyspace", "")), _ident(
            getattr(adapter, "_default_table", "")
        )
        for u in safe:
            out.append(
                Statement(
                    f"SELECT value, timestamp AS ts FROM {ks}.{tbl} WHERE uuid = '{u}' "
                    f"AND timestamp >= '{start}' AND timestamp <= '{end}' "
                    f"ORDER BY timestamp DESC LIMIT 1",
                    "cql_latest",
                    (u,),
                )
            )
    return out


def _integral_wrapper(inner: str, gap_expr: str) -> str:
    """Wrap an inner (uuid, t, v, nt, nv) select into per-sensor trapezoid figures.

    `usual` is the sensor's mean spacing; a gap is anything longer than GAP_FACTOR of it, and
    `gap_s` is the total time those gaps cover. It is what decides whether bridging them by a
    straight line between the readings on either side is a small correction or a guess.
    """
    return (
        "SELECT uuid, COUNT(*) AS n, SUM(area) AS integral, MAX(g) AS max_gap, "
        "AVG(g) AS mean_gap, MIN(t) AS t0, MAX(nt) AS t1, "
        f"SUM(CASE WHEN g > {GAP_FACTOR} * usual THEN g ELSE 0 END) AS gap_s "
        f"FROM (SELECT uuid, t, nt, {gap_expr} AS g, (v + nv) / 2 * {gap_expr} AS area, "
        f"AVG({gap_expr}) OVER (PARTITION BY uuid) AS usual "
        f"FROM ({inner}) x0 WHERE nt IS NOT NULL) x1 GROUP BY uuid"
    )


def integral_statements(
    layout: str, adapter: Any, uuids: Sequence[str], window: Window
) -> List[Statement]:
    """Statements returning, per sensor, the trapezoid integral of value over time, in the store.

    `LEAD` pairs each reading with the next, so the store computes sum((v + v_next) / 2 * dt), the
    number of intervals, the largest and mean gap, and the time covered by unusually long gaps, in
    one pass. A store with no window functions (Cassandra) is unsupported here.
    """
    start, end = _clean_stamp(window.start), _clean_stamp(window.end)
    safe = [u for u in dict.fromkeys(uuids) if _SAFE_ID.match(str(u))][:MAX_INTEGRATED_SERIES]
    out: List[Statement] = []
    my_gap = "TIMESTAMPDIFF(SECOND, t, nt)"
    if layout == "mysql_narrow":
        table = _ident(getattr(adapter, "table", ""))
        for part in _chunks(safe, NARROW_CHUNK):
            inl = ", ".join(f"'{u}'" for u in part)
            inner = (
                f"SELECT `uuid` AS uuid, `datetime` AS t, `value` AS v, "
                f"LEAD(`datetime`) OVER w AS nt, LEAD(`value`) OVER w AS nv "
                f"FROM `{table}` WHERE `uuid` IN ({inl}) AND `datetime` >= '{start}' "
                f"AND `datetime` <= '{end}' AND `value` IS NOT NULL "
                f"WINDOW w AS (PARTITION BY `uuid` ORDER BY `datetime`)"
            )
            out.append(Statement(_integral_wrapper(inner, my_gap), "integral", tuple(part)))
    elif layout == "mysql_wide":
        table = _wide_table_of(adapter)
        ts = _wide_ts_of(adapter)
        known = getattr(adapter, "_columns_cache", None)
        for u in safe:
            if known and u not in known:
                continue
            inner = (
                f"SELECT '{u}' AS uuid, `{ts}` AS t, `{u}` AS v, LEAD(`{ts}`) OVER w AS nt, "
                f"LEAD(`{u}`) OVER w AS nv FROM `{table}` WHERE `{u}` IS NOT NULL "
                f"AND `{ts}` >= '{start}' AND `{ts}` <= '{end}' WINDOW w AS (ORDER BY `{ts}`)"
            )
            out.append(Statement(_integral_wrapper(inner, my_gap), "integral", (u,)))
    elif layout == "pg_narrow":
        nb = getattr(adapter, "_narrow") or {}
        t, u_, ts, v = (_ident(nb.get(k, "")) for k in ("table", "uuid", "ts", "value"))
        for part in _chunks(safe, NARROW_CHUNK):
            inl = ", ".join(f"'{u}'" for u in part)
            inner = (
                f'SELECT "{u_}" AS uuid, "{ts}" AS t, "{v}" AS v, LEAD("{ts}") OVER w AS nt, '
                f'LEAD("{v}") OVER w AS nv FROM "{t}" WHERE "{u_}" IN ({inl}) '
                f'AND "{ts}" >= \'{start}\' AND "{ts}" <= \'{end}\' AND "{v}" IS NOT NULL '
                f'WINDOW w AS (PARTITION BY "{u_}" ORDER BY "{ts}")'
            )
            out.append(
                Statement(
                    _integral_wrapper(inner, "EXTRACT(EPOCH FROM (nt - t))"),
                    "integral",
                    tuple(part),
                )
            )
    return out


def peak_statement(
    layout: str, adapter: Any, uuid: str, value: float, window: Window
) -> Optional[Statement]:
    """When did this sensor first reach this value inside the window? One indexed lookup."""
    if not _SAFE_ID.match(str(uuid)):
        return None
    start, end = _clean_stamp(window.start), _clean_stamp(window.end)
    if layout == "mysql_narrow":
        table = _ident(getattr(adapter, "table", ""))
        sql = (
            f"SELECT MIN(`datetime`) AS ts FROM `{table}` WHERE `uuid` = '{uuid}' "
            f"AND `value` = {_num(value)} AND `datetime` >= '{start}' AND `datetime` <= '{end}'"
        )
    elif layout == "mysql_wide":
        table = _wide_table_of(adapter)
        ts = _wide_ts_of(adapter)
        sql = (
            f"SELECT MIN(`{ts}`) AS ts FROM `{table}` WHERE `{uuid}` = {_num(value)} "
            f"AND `{ts}` >= '{start}' AND `{ts}` <= '{end}'"
        )
    elif layout == "pg_narrow":
        nb = getattr(adapter, "_narrow") or {}
        t, u_, ts, v = (_ident(nb.get(k, "")) for k in ("table", "uuid", "ts", "value"))
        sql = (
            f'SELECT MIN("{ts}") AS ts FROM "{t}" WHERE "{u_}" = \'{uuid}\' '
            f'AND "{v}" = {_num(value)} AND "{ts}" >= \'{start}\' AND "{ts}" <= \'{end}\''
        )
    else:
        return None
    return Statement(sql, "peak", (uuid,))


def _ident(name: Any) -> str:
    text = str(name or "")
    if not _SAFE_IDENT.match(text):
        raise ValueError(f"unsafe identifier: {text!r}")
    return text


def _by_band(
    uuids: Sequence[str], bands: Dict[str, Tuple[float, float]]
) -> List[Tuple[Optional[Tuple[float, float]], List[str]]]:
    """Sensors grouped by physical range, so one statement carries one range."""
    groups: Dict[Optional[Tuple[float, float]], List[str]] = {}
    for u in uuids:
        groups.setdefault(bands.get(u), []).append(u)
    return list(groups.items())


# ─────────────────────────────────────────────────────────────────────────────
# 6. Reading what the store returned
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SensorAgg:
    """One sensor's reduction over the window."""

    uuid: str
    n: int = 0
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    total: float = 0.0
    exceed: int = 0
    excluded: int = 0
    first: Optional[datetime] = None
    last: Optional[datetime] = None


@dataclass
class SensorLatest:
    uuid: str
    value: float
    at: Optional[datetime]


@dataclass
class SensorIntegral:
    uuid: str
    intervals: int
    integral: float  # value-unit x seconds
    max_gap_s: float
    mean_gap_s: float
    first: Optional[datetime]
    last: Optional[datetime]
    gap_s: float = 0.0  # time covered by gaps longer than GAP_FACTOR x the usual spacing


def _f(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _i(value: Any) -> int:
    try:
        return int(float(value)) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _t(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return _stamp(value)


def parse_aggregates(statement: Statement, rows: List[Dict[str, Any]]) -> List[SensorAgg]:
    """Per-sensor aggregates from one statement's result rows."""
    out: List[SensorAgg] = []
    if statement.kind == "wide_agg":
        row = rows[0] if rows else {}
        for i, u in enumerate(statement.uuids):
            if _i(row.get(f"n{i}")) == 0 and _i(row.get(f"bad{i}")) == 0:
                continue
            out.append(
                SensorAgg(
                    u,
                    _i(row.get(f"n{i}")),
                    _f(row.get(f"mn{i}")),
                    _f(row.get(f"mx{i}")),
                    _f(row.get(f"sm{i}")) or 0.0,
                    _i(row.get(f"ex{i}")),
                    _i(row.get(f"bad{i}")),
                    _t(row.get(f"t0{i}")),
                    _t(row.get(f"t1{i}")),
                )
            )
    elif statement.kind == "narrow_agg":
        for row in rows:
            u = str(row.get("uuid") or "")
            if u and (_i(row.get("n")) or _i(row.get("bad"))):
                out.append(
                    SensorAgg(
                        u,
                        _i(row.get("n")),
                        _f(row.get("mn")),
                        _f(row.get("mx")),
                        _f(row.get("sm")) or 0.0,
                        _i(row.get("ex")),
                        _i(row.get("bad")),
                        _t(row.get("t0")),
                        _t(row.get("t1")),
                    )
                )
    elif statement.kind == "cql_agg":
        row = rows[0] if rows else {}
        if _i(row.get("n")):
            out.append(
                SensorAgg(
                    statement.uuids[0],
                    _i(row.get("n")),
                    _f(row.get("mn")),
                    _f(row.get("mx")),
                    _f(row.get("sm")) or 0.0,
                    0,
                    0,
                    _t(row.get("t0")),
                    _t(row.get("t1")),
                )
            )
    return out


def parse_latest(statement: Statement, rows: List[Dict[str, Any]]) -> List[SensorLatest]:
    """Newest reading per sensor; on a tie at one instant the last row wins."""
    held: Dict[str, SensorLatest] = {}
    for row in rows:
        u = str(row.get("uuid") or (statement.uuids[0] if statement.kind == "cql_latest" else ""))
        v = _f(row.get("value"))
        if not u or v is None:
            continue
        held[u] = SensorLatest(u, v, _t(row.get("ts")))
    return list(held.values())


def parse_integrals(rows: List[Dict[str, Any]]) -> List[SensorIntegral]:
    out: List[SensorIntegral] = []
    for row in rows:
        u = str(row.get("uuid") or "")
        n, integral = _i(row.get("n")), _f(row.get("integral"))
        if not u or not n or integral is None:
            continue
        out.append(
            SensorIntegral(
                u,
                n,
                integral,
                _f(row.get("max_gap")) or 0.0,
                _f(row.get("mean_gap")) or 0.0,
                _t(row.get("t0")),
                _t(row.get("t1")),
                _f(row.get("gap_s")) or 0.0,
            )
        )
    return out


async def _execute(
    adapter: Any, statements: Sequence[Statement]
) -> Tuple[List[Tuple[Statement, List[Dict[str, Any]]]], List[Statement]]:
    """Run each statement; return (statement, rows) pairs and the statements that failed."""
    done: List[Tuple[Statement, List[Dict[str, Any]]]] = []
    failed: List[Statement] = []
    for st in statements:
        try:
            res = await adapter.execute_query(st.sql)
        except Exception as exc:  # a store failing is a stated gap, not a crashed turn
            logger.warning(f"[aggregate] statement failed: {exc}")
            failed.append(st)
            continue
        if not getattr(res, "success", False):
            logger.warning(f"[aggregate] {st.kind} failed: {getattr(res, 'error', '')}")
            failed.append(st)
            continue
        done.append((st, list(getattr(res, "data", None) or [])))
    return done, failed


async def run_aggregates(
    adapter: Any,
    uuids: Sequence[str],
    window: Window,
    limit: Optional[float],
    bands: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Tuple[List[SensorAgg], List[str]]:
    """(per-sensor aggregates, uuids whose statement failed) for one store."""
    layout = layout_of(adapter)
    statements = aggregate_statements(layout, adapter, uuids, window, limit, bands)
    done, failed = await _execute(adapter, statements)
    aggs: Dict[str, SensorAgg] = {}
    pending_exceed: Dict[str, int] = {}
    for st, rows in done:
        if st.kind == "cql_exceed":
            pending_exceed[st.uuids[0]] = _i((rows[0] if rows else {}).get("ex"))
            continue
        for a in parse_aggregates(st, rows):
            aggs[a.uuid] = a
    for u, ex in pending_exceed.items():
        if u in aggs:
            aggs[u].exceed = ex
    return list(aggs.values()), [u for st in failed for u in st.uuids]


async def run_latest(
    adapter: Any, uuids: Sequence[str], window: Window
) -> Tuple[List[SensorLatest], List[str]]:
    layout = layout_of(adapter)
    done, failed = await _execute(adapter, latest_statements(layout, adapter, uuids, window))
    out: List[SensorLatest] = []
    for st, rows in done:
        out.extend(parse_latest(st, rows))
    return out, [u for st in failed for u in st.uuids]


async def run_integrals(
    adapter: Any, uuids: Sequence[str], window: Window
) -> Tuple[List[SensorIntegral], List[str]]:
    layout = layout_of(adapter)
    done, failed = await _execute(adapter, integral_statements(layout, adapter, uuids, window))
    out: List[SensorIntegral] = []
    for _st, rows in done:
        out.extend(parse_integrals(rows))
    return out, [u for st in failed for u in st.uuids]


async def peak_time(adapter: Any, uuid: str, value: float, window: Window) -> Optional[datetime]:
    """When a sensor first reached its peak, or None when the store cannot say."""
    st = peak_statement(layout_of(adapter), adapter, uuid, value, window)
    if st is None:
        return None
    done, _failed = await _execute(adapter, [st])
    if not done or not done[0][1]:
        return None
    return _t(done[0][1][0].get("ts"))


# ─────────────────────────────────────────────────────────────────────────────
# 7. Combining sensors into floors, rooms and a building
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Facts:
    """What is known about one sensor, from the pipeline's metadata and the graph."""

    uuid: str
    label: str = ""
    unit: str = ""
    floor: str = ""
    room: str = ""
    on_floor: bool = False
    #: A unit the label declares that the recorded one contradicts within the same quantity kind
    #: (L/min against L/s). Nothing here can tell which is right, so the answer says so.
    unit_conflict: str = ""


@dataclass
class GroupStat:
    """One floor, room or the building, reduced to the figure the question asked for."""

    key: str
    sensors: int = 0
    readings: int = 0
    value: Optional[float] = None
    low: Optional[float] = None
    high: Optional[float] = None
    mean: Optional[float] = None
    exceed_readings: int = 0
    exceed_sensors: int = 0
    #: The group's readings SUMMED, kept beside `readings` so a caller can build a mean over
    #: several groups from one population rather than averaging their means (wave 4).
    total: float = 0.0
    #: The sensor that set the group's figure, in the direction asked (the lowest for "min").
    peak_uuid: str = ""
    peak_value: Optional[float] = None
    peak_room: str = ""


def _floor_sort(key: str) -> Tuple[int, str]:
    return (int(key), key) if key.lstrip("-").isdigit() else (10**9, key)


def _measurand_classes(measurand: Optional[str]) -> List[str]:
    """The Brick class local names the building's catalogue declares for ``measurand``."""
    if not measurand:
        return []
    try:
        from orchestrator.services.deliberation.coverage_audit import load_modalities

        wanted = {measurand.lower(), measurand.lower().replace(" ", "_")}
        for spec in load_modalities(None):
            if str(getattr(spec, "name", "")).lower() in wanted:
                return [str(c) for c in (getattr(spec, "brick_classes", None) or [])]
    except Exception:  # pragma: no cover - the config is optional
        pass
    return []


def _floor_name(key: str) -> str:
    """A floor key a reader can read: the local name of an IRI, never the IRI (BUG-1407).

    Measured live. A temperature answer printed, in its table AND in its closing sentence:

        | Floor http://<the building's namespace>#Rooftop | 50.6 | 7.2 | 71.0 | 8 |
        Floor http://<the building's namespace>#Rooftop is the highest of the 7 floors

    Most floors group under a bare number ("3"), so nobody saw this until a named location —
    the rooftop plant area — became a group. The grouping KEY is left alone because sorting and
    matching use it; only the rendering changes.

    Building-agnostic: it splits on the IRI delimiters and never on a namespace, so it reads the
    same for any building. `camelCase` and `snake_case` local names are spaced out, because
    "Rooftop" is readable and "Plant_Room_2" is not.
    """
    text = str(key or "").strip()
    if not text:
        return text
    if "://" in text or "#" in text:
        text = re.split(r"[#/]", text)[-1] or text
    text = text.replace("_", " ").strip()
    # "RooftopPlant" -> "Rooftop Plant", leaving "3" and "Rooftop" untouched
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return text or str(key)


def facts_from(
    uuids: Sequence[str], metadata: Dict[str, Dict[str, Any]], places: Dict[str, Place]
) -> Dict[str, Facts]:
    """Merge the pipeline's per-sensor metadata with the graph's placement.

    THE SENSOR'S OWN LABEL OUTRANKS A CLASS-LEVEL UNIT OF ANOTHER KIND (wave 2). A floor-scoped
    SPARQL row carries no class, so "Floor3 water_flow_rate [L/s]" arrived with no unit at all and
    the question fell through to a lane that multiplied a mean by 86,400 seconds. Where the class
    IS known its modality entry says "L" — a volume, for a series that is a rate. Both readings are
    corrected by the one statement specific to this sensor: its label. See `aggregate_support`.
    """
    from orchestrator.services.aggregate_support import resolve_unit

    out: Dict[str, Facts] = {}
    for u in uuids:
        meta = metadata.get(u) or {}
        place = places.get(u) or Place()
        label = str(meta.get("label") or "")
        unit, conflict = resolve_unit(str(meta.get("unit") or ""), label)
        out[u] = Facts(
            uuid=u,
            label=label,
            unit=unit,
            floor=str(meta.get("floor") or place.floor or ""),
            room=place.room,
            on_floor=place.on_floor,
            unit_conflict=conflict,
        )
    return out


def _group_key(f: Facts, group: str) -> str:
    if group == "floor":
        return f.floor
    if group == "room":
        # A BARE NUMBER IS NOT A PLACE NAME (CAVEAT-938). Measured live 2026-09-29, immediately
        # after BUG-879 started letting room-scoped questions through: "the temperature in room
        # 5.01 this week compared with last week" labelled every figure "5 mean", "5 peak",
        # "5 lowest", because this point's resolved `room` is the string "5". The figures were
        # room 5.01's and the basis line said so, but "5" reads as FLOOR 5 -- which is exactly
        # the scope confusion the regrouping half of BUG-879 exists to prevent, arriving by the
        # label instead of by the grouping. The sensor's own label carries the room ("CO2 Level
        # Sensor 5.01"), so prefer it whenever `room` is too thin to name a place.
        room = (f.room or "").strip()
        if room and not room.isdigit():
            return room
        return f.label or room or "this room"
    return "building"


def combine_windowed(
    aggs: Sequence[SensorAgg], facts: Dict[str, Facts], intent: AggregateIntent
) -> Tuple[List[GroupStat], int]:
    """Per-group figures from per-sensor aggregates. Returns (groups, sensors left unplaced).

    The maximum of a group is the maximum of its sensors' maxima; the mean is total over count, not
    a mean of means, so a sensor with more readings weighs what it should.
    """
    groups: Dict[str, GroupStat] = {}
    sums: Dict[str, float] = {}
    unplaced = 0
    for a in aggs:
        f = facts.get(a.uuid)
        if f is None:
            continue
        key = _group_key(f, intent.group)
        if not key:
            unplaced += 1
            continue
        g = groups.setdefault(key, GroupStat(key))
        g.sensors += 1
        g.readings += a.n
        sums[key] = sums.get(key, 0.0) + a.total
        if a.exceed:
            g.exceed_readings += a.exceed
            g.exceed_sensors += 1
        where = f.room or f.label
        if a.maximum is not None and (g.high is None or a.maximum > g.high):
            g.high = a.maximum
            if intent.stat != "min":
                g.peak_uuid, g.peak_value, g.peak_room = a.uuid, a.maximum, where
        if a.minimum is not None and (g.low is None or a.minimum < g.low):
            g.low = a.minimum
            if intent.stat == "min":
                g.peak_uuid, g.peak_value, g.peak_room = a.uuid, a.minimum, where
    for key, g in groups.items():
        g.total = sums[key]
        g.mean = sums[key] / g.readings if g.readings else None
        g.value = {
            "max": g.high,
            "min": g.low,
            "mean": g.mean,
            "summary": g.mean,  # a summary leads with the average and prints the range beside it
            "exceed": float(g.exceed_readings),
            "total": sums[key],
        }.get(intent.stat, g.high)
    return list(groups.values()), unplaced


def _one_per_room(
    members: Sequence[Tuple[Facts, SensorLatest]]
) -> List[Tuple[Facts, SensorLatest]]:
    """Each room's newest reading, once. A sensor with no room is its own place and is kept."""
    best: Dict[str, Tuple[Facts, SensorLatest]] = {}
    loose: List[Tuple[Facts, SensorLatest]] = []
    for f, r in members:
        if not f.room:
            loose.append((f, r))
            continue
        held = best.get(f.room)
        if held is None or (r.at is not None and (held[1].at is None or r.at > held[1].at)):
            best[f.room] = (f, r)
    return list(best.values()) + loose


def combine_latest(
    latest: Sequence[SensorLatest], facts: Dict[str, Facts], intent: AggregateIntent, additive: bool
) -> Tuple[List[GroupStat], int]:
    """Per-group figures from each sensor's newest reading.

    A count of people is ADDITIVE, so a floor's figure is the sum of its sensors' newest readings.
    A temperature is not, so a floor's figure is their mean. When some sensors sit on the floor
    itself, those ARE the floor's figure and the room sensors are left out of it: adding a floor
    meter to the rooms it already counts would count the same people twice.

    ONE READING PER ROOM. A room with two counters contributes twice to any sum over sensors, and
    the difference is invisible in the total. When a sum is being taken, each room contributes its
    NEWEST reading and nothing else.
    """
    by_group: Dict[str, List[Tuple[Facts, SensorLatest]]] = {}
    unplaced = 0
    for r in latest:
        f = facts.get(r.uuid)
        if f is None:
            continue
        key = _group_key(f, intent.group)
        if not key:
            unplaced += 1
            continue
        by_group.setdefault(key, []).append((f, r))
    out: List[GroupStat] = []
    for key, members in by_group.items():
        if additive and intent.group == "floor" and any(f.on_floor for f, _ in members):
            members = [(f, r) for f, r in members if f.on_floor]
        elif additive:
            members = _one_per_room(members)
        vals = [r.value for _, r in members]
        g = GroupStat(key, sensors=len(members), readings=len(members))
        g.high, g.low = max(vals), min(vals)
        g.mean = sum(vals) / len(vals)
        g.value = sum(vals) if additive else g.mean
        top = max(members, key=lambda m: m[1].value)
        g.peak_uuid, g.peak_value, g.peak_room = (
            top[1].uuid,
            top[1].value,
            top[0].room or top[0].label,
        )
        out.append(g)
    return out, unplaced


def rank(groups: Sequence[GroupStat], descending: bool) -> List[GroupStat]:
    """Groups ordered by their figure, ties by floor number then name so the order is stable."""
    known = [g for g in groups if g.value is not None]
    return sorted(known, key=lambda g: (-g.value if descending else g.value, _floor_sort(g.key)))


# ─────────────────────────────────────────────────────────────────────────────
# 8. Volume from a rate
# ─────────────────────────────────────────────────────────────────────────────

#: rate unit -> (litres per unit-second). Only conversions `units.py` declares are used; a rate it
#: does not know is not integrated.
_RATE_TO_LITRES_PER_S = {"L/s": 1.0, "L/min": 1.0 / 60.0, "m³/h": 1000.0 / 3600.0, "m³/s": 1000.0}


def rate_litres_per_second(unit: str) -> Optional[float]:
    """Litres per second represented by one unit of this flow-rate unit, or None if unknown."""
    from orchestrator.services.units import normalise

    return _RATE_TO_LITRES_PER_S.get(normalise(unit))


def _span_s(item: SensorIntegral) -> float:
    if item.first is None or item.last is None:
        return 0.0
    return max(0.0, (item.last - item.first).total_seconds())


def is_regular(item: SensorIntegral, window: Window) -> Tuple[bool, str]:
    """Whether a series can be integrated honestly, and the reason when it cannot.

    Two ways to fail: its readings cover too little of the window, or the holes between them are
    too large a share of what they cover to be bridged by a straight line.
    """
    if item.intervals < 2 or item.mean_gap_s <= 0:
        return False, "it has too few readings in the window"
    start, end = _stamp(window.start), _stamp(window.end)
    length = (end - start).total_seconds() if start and end else 0.0
    span = _span_s(item)
    if length and span < MIN_COVERAGE * length:
        return False, (
            f"its readings cover only {span / 3600:.1f} h of the {length / 3600:.1f} h asked about"
        )
    if span and item.gap_s / span > MAX_BRIDGED_SHARE:
        return False, (
            f"gaps in its readings add up to {item.gap_s / 3600:.1f} h of the {span / 3600:.1f} h "
            f"they span, too much to bridge honestly"
        )
    return True, ""


def gap_statement(item: SensorIntegral, window: Window) -> str:
    """One sentence on what was bridged and how much of the window the readings cover."""
    start, end = _stamp(window.start), _stamp(window.end)
    length = (end - start).total_seconds() if start and end else 0.0
    span = _span_s(item)
    bits = [f"about every {item.mean_gap_s / 60:.1f} min"]
    if item.gap_s > 0:
        bits.append(
            f"a gap of {item.max_gap_s / 60:.0f} min was bridged by a straight line between the "
            f"readings on either side ({item.gap_s / span * 100:.1f}% of the covered time)"
            if span
            else "a gap was bridged"
        )
    if length and span < 0.9 * length:
        bits.append(
            f"the readings cover {span / 3600:.1f} h of the {length / 3600:.1f} h asked about"
        )
    return "; ".join(bits)


def volume_litres(item: SensorIntegral, unit: str) -> Optional[float]:
    """Litres from an integral of a flow rate, or None when the unit cannot be converted."""
    per_s = rate_litres_per_second(unit)
    return None if per_s is None else item.integral * per_s


# ─────────────────────────────────────────────────────────────────────────────
# 9. Wording — written from the numbers, in code
# ─────────────────────────────────────────────────────────────────────────────


def _n(x: Optional[float], digits: int = 0) -> str:
    """A figure for reading: thousands separated, decimals only where they carry information."""
    if x is None:
        return "n/a"
    if digits == 0 or abs(x) >= 100 or float(x).is_integer():
        return f"{x:,.0f}"
    return f"{x:,.{digits}f}"


def _place_name(group: str, key: str) -> str:
    if group == "floor":
        return f"Floor {_floor_name(key)}"
    return key


def render_extreme(
    intent: AggregateIntent,
    ranked: Sequence[GroupStat],
    *,
    measurand: str,
    unit: str,
    window: Window,
    sensors_used: int,
    sensors_requested: int,
    floors_seen: int,
    peak_at: Optional[str],
    excluded: int,
    excluded_sensors: int,
    no_reading: int,
    unplaced: int,
    bands_checked: bool,
    additive: bool = False,
    no_limit_note: bool = False,
    band_text: str = "",
    quantity: str = "",
) -> str:
    """The answer to 'which floor/room ... highest/lowest/most/least', with its boundary."""
    if not ranked:
        return ""
    name = quantity or display_name(measurand)
    u = f" {unit}" if unit else ""
    top = ranked[0]
    who = _place_name(intent.group, top.key)
    now = window.latest
    word = {"max": "highest", "min": "lowest", "mean": "highest average"}.get(
        intent.stat, "highest"
    )
    if not intent.descending:
        word = "lowest" if intent.stat != "mean" else "lowest average"
    if now and additive:
        word = "most" if intent.descending else "fewest"
    elif now and intent.stat in ("max", "min"):
        word += (
            " average"  # a group's figure "right now" is the mean of its sensors' newest readings
        )

    if intent.group == "building":
        lead = f"**The {word} {name} {'right now' if now else 'in the period'} was {_n(top.value, 1)}{u}**"
        if top.peak_room:
            lead += f", at {top.peak_room}"
        if peak_at:
            lead += f" ({peak_at})"
        lead += "."
    elif additive and measurand == "occupancy":
        lead = f"**{who} has the {word} people in it right now: {_n(top.value)}**."
    else:
        lead = f"**{who} had the {word} {name} {'right now' if now else 'in the period'}: {_n(top.value, 1)}{u}**"
        if intent.stat in ("max", "min") and not now and intent.group != "room" and top.peak_room:
            lead += f" (at {top.peak_room}{', ' + peak_at if peak_at else ''})"
        elif intent.group == "room" and peak_at:
            lead += f" (first reached {peak_at})"
        lead += "."
    lines = [lead, ""]

    if intent.group != "building" and len(ranked) > 1:
        head = {"max": "Peak", "min": "Lowest", "mean": "Average"}.get(intent.stat, "Value")
        if now:
            head = "Total now" if additive else "Average now"
        if additive and measurand == "occupancy":
            head, u = "People now", ""
        lines.append(f"| {'Floor' if intent.group == 'floor' else 'Space'} | {head}{u} | Sensors |")
        lines.append("|---|---|---|")
        shown = ranked if intent.group == "floor" else ranked[:8]
        for g in shown:
            lines.append(f"| {_place_name(intent.group, g.key)} | {_n(g.value, 1)} | {g.sensors} |")
        if len(ranked) > len(shown):
            lines.append(f"| ...and {len(ranked) - len(shown)} more | | |")
        lines.append("")

    if no_limit_note:
        lines.append(
            f"_This ranks the figures. This system's standards table cites no limit for {name}, "
            "so I am not calling any of them high or low._"
        )
    lines.append("")
    lines.append(
        _boundary(
            name,
            window,
            sensors_used,
            sensors_requested,
            floors_seen,
            excluded,
            excluded_sensors,
            no_reading,
            unplaced,
            bands_checked,
            how=_how(intent, now, additive),
            band_text=band_text,
        )
    )
    return "\n".join(x for x in lines).strip()


def _how(intent: AggregateIntent, now: bool, additive: bool = False) -> str:
    if now:
        return (
            "each floor's figure is its counter's newest reading, added up where a floor has several"
            if additive
            else "each figure is the mean of the newest reading from each sensor"
        )
    return {
        "max": "each sensor's maximum, computed in the store",
        "min": "each sensor's minimum, computed in the store",
        "mean": "each sensor's readings summed and counted in the store",
        "exceed": "a count of readings above the limit, computed in the store",
        "total": "each sensor's readings summed in the store",
    }[intent.stat]


def _boundary(
    name: str,
    window: Window,
    used: int,
    requested: int,
    floors: int,
    excluded: int,
    excluded_sensors: int,
    no_reading: int,
    unplaced: int,
    bands_checked: bool,
    how: str,
    band_text: str = "",
) -> str:
    parts = [
        f"Based on {used} {name} sensor{'s' if used != 1 else ''}"
        + (f" on {floors} floor{'s' if floors != 1 else ''}" if floors else "")
        + f", {window.label}: {how}."
    ]
    if no_reading:
        parts.append(
            f"{no_reading} of the {requested} sensors returned no readings in this period and are not counted."
        )
    if unplaced:
        parts.append(
            f"{unplaced} sensors have no recorded location and are left out of the grouping."
        )
    if excluded:
        parts.append(
            f"{excluded:,} reading{'s' if excluded != 1 else ''} from {excluded_sensors} sensor"
            f"{'s' if excluded_sensors != 1 else ''} fell outside the physically possible range for "
            f"{name}{' (' + band_text + ')' if band_text else ''} and "
            f"{'is' if excluded == 1 else 'are'} not included."
        )
    elif not bands_checked:
        parts.append("Readings were not screened against physical limits for this quantity.")
    return " ".join(parts)


def render_exceedance(
    ranked_rooms: Sequence[GroupStat],
    floors: Sequence[GroupStat],
    *,
    measurand: str,
    unit: str,
    window: Window,
    threshold: Threshold,
    sensors_used: int,
    sensors_requested: int,
    peak: Optional[GroupStat],
    peak_at: Optional[str],
    excluded: int,
    excluded_sensors: int,
    no_reading: int,
    unplaced: int,
    bands_checked: bool,
    band_text: str = "",
    quantity: str = "",
) -> str:
    """'Has X been high anywhere?' — yes/no against a CITED limit, and where."""
    name = quantity or display_name(measurand)
    u = f" {unit}" if unit else ""
    total_readings = sum(g.readings for g in floors) or sum(g.readings for g in ranked_rooms)
    over_readings = sum(g.exceed_readings for g in ranked_rooms)
    over_sensors = sum(g.exceed_sensors for g in ranked_rooms)
    limit = f"{_n(threshold.value)}{u}"
    cite = (
        f"the limit for {name} in the {threshold.standard} entry of this system's standards table"
    )
    if over_readings == 0:
        lead = f"**No.** No {name} reading was above {limit} ({cite}) in the period."
        if peak and peak.peak_value is not None:
            lead += (
                f" The highest was {_n(peak.peak_value, 1)}{u}"
                + (f" at {peak.peak_room}" if peak.peak_room else "")
                + (f" ({peak_at})" if peak_at else "")
                + "."
            )
        lines = [lead]
    else:
        share = over_readings / total_readings * 100 if total_readings else 0.0
        lead = (
            f"**Yes.** {name} was above {limit} ({cite}) on {over_sensors} of {sensors_used} sensors, "
            f"in {over_readings:,} of {total_readings:,} readings ({share:.1f}%)."
        )
        lines = [lead, ""]
        rows = [g for g in ranked_rooms if g.exceed_readings]
        lines.append("| Where | Readings above | Peak |")
        lines.append("|---|---|---|")
        for g in rows[:6]:
            lines.append(f"| {g.key} | {g.exceed_readings:,} | {_n(g.high, 1)}{u} |")
        if len(rows) > 6:
            lines.append(f"| ...and {len(rows) - 6} more | | |")
        lines.append("")
        per_floor = [f for f in floors if f.exceed_readings]
        if per_floor:
            lines.append(
                "By floor: "
                + "; ".join(
                    f"Floor {_floor_name(f.key)} {f.exceed_readings:,}"
                    for f in sorted(per_floor, key=lambda f: _floor_sort(f.key))
                )
                + " readings above the limit."
            )
        if peak and peak.peak_value is not None:
            lines.append(
                f"The highest reading was {_n(peak.peak_value, 1)}{u}"
                + (f" at {peak.peak_room}" if peak.peak_room else "")
                + (f" ({peak_at})" if peak_at else "")
                + "."
            )
    lines.append("")
    lines.append(
        _boundary(
            name,
            window,
            sensors_used,
            sensors_requested,
            len(floors),
            excluded,
            excluded_sensors,
            no_reading,
            unplaced,
            bands_checked,
            how="a count of readings above the limit, computed in the store",
            band_text=band_text,
        )
    )
    return "\n".join(lines).strip()


def render_volume(
    rows: Sequence[Tuple[str, float, str]],
    *,
    window: Window,
    scope: str,
    skipped: Sequence[Tuple[str, str]],
    cadence: str,
) -> str:
    """Water (or any liquid) volume by integrating flow readings; every series labelled."""
    total_l = sum(v for _, v, _ in rows)
    m3 = total_l / 1000.0
    lines = [
        f"**About {_n(m3, 1)} m³ ({_n(total_l)} L) of water{scope}**, {window.label}.",
        "",
        "This is computed by integrating the flow readings over the window (flow rate times the "
        "time between readings); it is not read from a volume meter.",
        "",
    ]
    if len(rows) > 1:
        lines += ["| Series | Volume (L) | Basis |", "|---|---|---|"]
        for label, litres, basis in rows:
            lines.append(f"| {label} | {_n(litres)} | {basis} |")
        lines.append("")
    else:
        lines.append(f"Series: {rows[0][0]} ({rows[0][2]}).")
    lines.append(cadence)
    for label, why in skipped:
        lines.append(f"Left out: {label}, because {why}.")
    return "\n".join(lines).strip()


def render_summary(
    ranked: Sequence[GroupStat],
    *,
    measurand: str,
    unit: str,
    window: Window,
    sensors_used: int,
    sensors_requested: int,
    floors_seen: int,
    excluded: int,
    excluded_sensors: int,
    no_reading: int,
    unplaced: int,
    bands_checked: bool,
    band_text: str = "",
    quantity: str = "",
) -> str:
    """What a quantity is doing across the building and floor by floor.

    The answer to a question that names a measurand and no place. It states the building figure
    first, because that is what was asked about, and then the floors, because that is the cheapest
    thing that would narrow it. No verdict: nothing here was compared with a limit.
    """
    if not ranked:
        return ""
    name = quantity or display_name(measurand)
    u = f" {unit}" if unit else ""
    now = window.latest
    highs = [g.high for g in ranked if g.high is not None]
    lows = [g.low for g in ranked if g.low is not None]

    # ONE STATISTIC OVER ONE POPULATION (wave 4). This averaged the FLOOR MEANS, unweighted, while
    # the range came from the readings — two populations, and on the held-out run they disagreed
    # visibly: "averaged 39.4 level, ranging from 45 to 105 level". A mean below its own minimum
    # is a number a reader checks in one second, and it discredits every other figure in the
    # answer. The building mean is now the summed readings over the counted readings, which is
    # the same population the range is taken from, and is also the right weighting: one floor
    # here carries 341 sensors and another 20.
    readings = sum(g.readings for g in ranked)
    whole = (sum(g.total for g in ranked) / readings) if readings else None
    if now:  # a "right now" figure has one reading per sensor, so the mean of them is the mean
        values = [g.value for g in ranked if g.value is not None]
        whole = sum(values) / len(values) if values else None

    word = "is averaging" if now else "averaged"
    lead = f"**Across the building {name} {word} {_n(whole, 1)}{u}**"
    if highs and lows:
        lead += f", ranging from {_n(min(lows), 1)} to {_n(max(highs), 1)}{u}"
    lead += "."

    # A FIGURE OUTSIDE ITS OWN RANGE IS NEVER PRINTED. The fix above removes the cause that was
    # found; this removes the CLASS. Any future disagreement between the lead figure and the
    # range — a store that reports a sum over a different filter, a unit family mixed by mistake
    # — stops here instead of reaching a reader, and says so in the log.
    if whole is not None and lows and highs and not (min(lows) <= whole <= max(highs)):
        logger.error(
            "[aggregate] summary suppressed: mean %.4g outside range %.4g..%.4g over %d readings "
            "on %d group(s) — the lead figure and the range disagree",
            whole,
            min(lows),
            max(highs),
            readings,
            len(ranked),
        )
        return ""
    lines = [lead, ""]
    if len(ranked) > 1:
        head = "Now" if now else "Mean"
        lines.append(f"| Floor | {head}{u} | Lowest | Highest | Sensors |")
        lines.append("|---|---|---|---|---|")
        for g in sorted(ranked, key=lambda g: _floor_sort(g.key)):
            lines.append(
                f"| Floor {_floor_name(g.key)} | {_n(g.value, 1)} | {_n(g.low, 1)} | {_n(g.high, 1)} "
                f"| {g.sensors} |"
            )
        lines.append("")
        top = ranked[0]
        lines.append(
            f"Floor {_floor_name(top.key)} is the highest of the {len(ranked)} floors at {_n(top.value, 1)}{u}; "
            f"Floor {_floor_name(ranked[-1].key)} the lowest at {_n(ranked[-1].value, 1)}{u}."
        )
    lines.append("")
    lines.append(
        _boundary(
            name,
            window,
            sensors_used,
            sensors_requested,
            floors_seen,
            excluded,
            excluded_sensors,
            no_reading,
            unplaced,
            bands_checked,
            how=(
                "each sensor's newest reading"
                if now
                else "each sensor's readings summed and counted in the store"
            ),
            band_text=band_text,
        )
    )
    return "\n".join(lines).strip()


def render_no_volume(skipped: Sequence[Tuple[str, str]], *, scope: str, window: Window) -> str:
    """Why a volume could not be worked out from the flow readings, naming each series."""
    lines = [
        f"**I can't total the water used{scope} for {window.label}** from the flow readings this "
        "building records, and I would rather say so than give you a figure I can't stand behind.",
        "",
    ]
    for label, why in skipped:
        lines.append(f"- {label}: {why}.")
    return "\n".join(lines).strip()


def render_not_additive(*, name: str, unit: str, sensors: int, asked: str) -> str:
    """One sentence: these sensors report a level, not an amount, and here is what they can show.

    ONE SENTENCE, AND NO FIGURES. The wave-1 live run answered "How much gas did we use this
    week?" with "No usage data available" and then the highest, lowest and mean ppm across 136
    gas-leak detectors. Every figure was real and none of them was about consumption, so the
    paragraph read as an attempt at the question that had been asked. The offer at the end is the
    question that WOULD be answered, so the reader has somewhere to go.
    """
    u = f" in {unit}" if unit else ""
    return (
        f'The {sensors} sensors matched to "{asked}" measure the {name} level{u} in the air '
        f"rather than an amount delivered, so I can't say how much {asked} was used, though I can "
        f"show you their readings if that would help."
    )


# ─────────────────────────────────────────────────────────────────────────────
# 9b. Is anyone there: a count of PLACES, over a denominator the answer states
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PresenceCount:
    """How many places have someone in them, and what the figure is over.

    Every field is a COUNT the caller computed from the store's own latest readings. Nothing
    here is inferred from wording: BUG-954's "two rooms are occupied" was a narrator naming the
    rows it could list beside its own statistics saying 103, so the count and the names it prints
    are derived from one list and cannot disagree.
    """

    occupied: List[str]  # places whose chosen series reads above zero
    empty: List[str]  # places whose chosen series reads zero
    #: "presence" when a status/presence flag decided it, "count" when a people counter did.
    basis: str = "presence"
    #: How many places each instrument actually decided. Kept apart from `basis` because the
    #: denominator sentence must not claim every place has the instrument most of them have.
    by_presence: int = 0
    by_counter: int = 0
    #: Places where a counter and a presence flag disagree about whether anyone is there.
    conflicted: List[str] = field(default_factory=list)
    conflict_low: Optional[float] = None
    conflict_high: Optional[float] = None
    #: Series with a reading that the graph does not place in a space, so they name no place.
    unplaced: int = 0
    #: Series that count a whole FLOOR. A floor is not a room and its counter is not a room's,
    #: so it is neither counted as a place nor silently dropped (the same rule `combine_latest`
    #: applies when it refuses to add a floor meter to the rooms it already covers).
    floor_level: int = 0
    #: Series the stores could not read at all.
    no_reading: int = 0
    first_at: Optional[datetime] = None
    last_at: Optional[datetime] = None


def _basis_sentence(by_presence: int, by_counter: int, place_word: str) -> str:
    """Which instrument decided each place's figure, counted rather than assumed.

    THE DENOMINATOR MUST NOT CLAIM AN INSTRUMENT IT DOES NOT HAVE. The lead sentence says "spaces
    with an occupancy sensor" and this says which kind, per place: a building where most spaces
    carry a presence flag and a handful carry only a counter would otherwise be described as
    though every space had the flag.
    """
    if by_presence and by_counter:
        return (
            f"{_n(by_presence)} of these {place_word} are decided by an occupancy-presence "
            f"sensor and {_n(by_counter)} by a people counter, each its newest reading."
        )
    if by_counter:
        return "Each figure is the newest reading of that space's people counter."
    if by_presence:
        return "Each figure is the newest reading of that space's occupancy-presence sensor."
    return ""


def _join_places(names: Sequence[str], limit: int = 8) -> str:
    """Up to `limit` place names, then how many more. Never a bare "and others".

    The remainder is a COUNT, not a hedge: a reader who is told eight of a hundred names needs
    to know it was a hundred. A place name can itself contain "and" ("Loading and Goods
    Storage"), so the remainder is separated by a comma rather than by another "and".
    """
    shown = list(names[:limit])
    rest = len(names) - len(shown)
    if not shown:
        return ""
    if rest:
        return ", ".join(shown) + f", and {rest} more"
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + f" and {shown[-1]}"


def render_presence(
    count: PresenceCount,
    *,
    wants: str,
    window: Window,
    tz_name: Optional[str],
    name_places: bool = True,
) -> str:
    """The count of occupied or empty places, with the denominator it is over.

    THE DENOMINATOR IS PLACES, AND IT IS STATED (lesson #139, BUG-883). "Two rooms are occupied"
    is a claim about rooms; a series is not a room, some rooms carry two occupancy series and
    some carry none. The figure below is over the places that HAVE one, the places that do not
    are counted separately, and the sentence says which of the two is which.
    """
    total = len(count.occupied) + len(count.empty)
    if total == 0:
        return ""
    noun = "occupancy sensor"
    place_word = "space" if total == 1 else "spaces"
    at = ""
    if count.last_at is not None:
        if count.first_at is not None and count.first_at != count.last_at:
            at = (
                f", read between {_show(count.first_at, tz_name)} and "
                f"{_show(count.last_at, tz_name)}"
            )
        else:
            at = f", read at {_show(count.last_at, tz_name)}"

    if wants == "empty":
        lead = (
            f"**{_n(len(count.empty))} of the {_n(total)} {place_word} with an {noun} have "
            f"nobody in them right now**; {_n(len(count.occupied))} have someone{at}."
        )
        listed, listed_label = count.empty, "Empty"
    else:
        lead = (
            f"**{_n(len(count.occupied))} of the {_n(total)} {place_word} with an {noun} have "
            f"someone in them right now**; {_n(len(count.empty))} do not{at}."
        )
        listed, listed_label = count.occupied, "Occupied"

    lines = [lead]
    if name_places and listed:
        lines.append("")
        lines.append(f"{listed_label}: {_join_places(listed)}.")

    extra: List[str] = []
    basis_note = _basis_sentence(count.by_presence, count.by_counter, place_word)
    if basis_note:
        extra.append(basis_note)
    if count.conflicted:
        band = ""
        if count.conflict_low is not None and count.conflict_high is not None:
            band = (
                f" reporting {_n(count.conflict_low)} to {_n(count.conflict_high)} people"
                if count.conflict_low != count.conflict_high
                else f" reporting {_n(count.conflict_low)} people"
            )
        extra.append(
            f"{_n(len(count.conflicted))} of these {place_word} carry a second occupancy series "
            f"that disagrees at the same moment: a people counter{band} where the presence "
            f"sensor reports nobody, or the reverse. The records give no way to decide between "
            f"two instruments in the same space, so the figure above is the presence sensors' "
            f"and this is stated rather than resolved."
        )
    if count.floor_level:
        extra.append(
            f"{_n(count.floor_level)} occupancy series count a whole floor rather than a space "
            f"and are not among the {_n(total)}: a floor is not a room, and adding its counter "
            "to the rooms it already covers would count the same people twice."
        )
    if count.unplaced:
        extra.append(
            f"{_n(count.unplaced)} occupancy series returned a reading but are not placed in a "
            f"space in the building model, so they are not in the {_n(total)} above."
        )
    if count.no_reading:
        extra.append(
            f"{_n(count.no_reading)} occupancy series returned no reading for {window.label} "
            "and are not counted."
        )
    if extra:
        lines.append("")
        lines.append(" ".join(extra))
    return "\n".join(lines).strip()


# ─────────────────────────────────────────────────────────────────────────────
# 10. The entry point the SQL lane calls
# ─────────────────────────────────────────────────────────────────────────────

_ADDITIVE_COUNT_KINDS = ("count",)

#: Verbs that ask for an amount CONSUMED. "How much CO2 is on floor 3" asks for a level and is
#: not answered here as a consumption question.
_CONSUME = re.compile(
    r"\b(?:us(?:e|ed|age)|consum\w*|burn\w*|spen[dt]|draw\w*|go(?:ne)?\s+through)\b",
    re.IGNORECASE,
)

#: Quantity kinds that describe a CONDITION rather than an amount delivered. Adding them up
#: answers no question anyone asks: a week of ppm readings summed is not a quantity of gas.
_LEVEL_KINDS = frozenset(
    {
        "concentration_ratio",
        "concentration_mass",
        "temperature",
        "ratio",
        "sound_level",
        "illuminance",
        "pressure",
    }
)


def wants_lane(
    question: str,
    n_sensors: int,
    budget_hit: bool,
    has_floor_metadata: bool,
    unit_kinds: Iterable[str] = (),
    headcount: bool = False,
    summary: bool = False,
    profile: bool = False,
) -> Optional[AggregateIntent]:
    """The intent when this lane should answer, else None.

    It takes a question in five cases and no others.

    1. The fetch budget would refuse it: the question is answerable in the store, so the refusal
       is the wrong outcome.
    2. It asks "which floor" and the resolved sensors carry no floor, so the row-based summariser
       cannot group them.
    3. It asks for a total of something measured as a rate: only an integral answers that.
    4. It asks for a total of something measured as a LEVEL. Nothing can answer that, and the two
       lanes that tried both produced a false one: "No usage data available" followed by a
       paragraph of ppm statistics about gas-leak detectors (wave-1 live run). A decline belongs
       to the lane that can say precisely why.
    5. It is a per-floor HEADCOUNT. The row-based lane sums room readings, which double-counts a
       room with two sensors and silently omits a floor whose rooms returned nothing: the live run
       answered five floors totalling 47 people three minutes after the building total said 23.
       Only this lane knows to prefer the floor's own counter.
    6. `summary`: the question names a measurand and no place, asks for no statistic in
       particular, and is a question this building's readings bear on. The caller decides that
       (`aggregate_support`); here it becomes a building-and-per-floor summary.
    """
    from orchestrator.services.aggregate_support import names_a_period

    if n_sensors < 1:
        return None
    intent = parse_intent(question)
    if intent is None and profile:
        # WHEN does it happen: the hourly profile, not a "how is it now" summary (wave 5).
        return AggregateIntent("profile", "building", True, False, False, ())
    if intent is None:
        # THE SUMMARY IS FOR A QUESTION WITH NO STATISTIC, NOT FOR ONE THIS MODULE REFUSED
        # (BUG-1316). `parse_intent` returns None for two different reasons, and only one of
        # them is a gap the summary should fill. Either it found no statistic word -- a bare
        # measurand, which is what case 6 exists for -- or `_NOT_AN_AGGREGATE` matched, which is
        # this module SAYING SO: "a forecast, a change over time, or a time of day ... is not a
        # maximum of the past". Case 6 could not tell the two apart and re-admitted every
        # question the parser had just declined.
        #
        # MEASURED LIVE, 2026-09-30, occupant on /v1, and it is why this is not cosmetic:
        #   "Has the humidity changed significantly in the past hour?" -> bound and fetched 275
        #     humidity series and answered with a window summary; the relevance gate deleted it
        #     (OFF_TOPIC, "does not address change, only gives current values") and the reader
        #     got a decline.
        #   "How has the temperature changed over time?" -> the same, deleted the same way.
        #   "how's the air quality index trending over the last few hours?" -> **the gate did NOT
        #     fire** and "Across the building air quality is averaging 69.2 level" was shipped as
        #     the answer to a TRENDING question. The gate is a messenger, not a backstop.
        #
        # BLAST RADIUS, both corpora, 11,211 questions: 147 move (91 asking how something
        # CHANGED, 32 about the future, 24 about when). Every real-corpus question in the two
        # non-delta families was hand-read and every one is a capability or explanation question
        # -- "Will I get alerts if air quality is poor?", "When noise levels are too high how
        # does the building help block that out?" -- which no building-wide mean answers. So the
        # move is from a statistic nobody asked for to a decline that names what CAN be read.
        if summary and _NOT_AN_AGGREGATE.search(question or ""):
            logger.info(
                "[aggregate] not claimed: the question asks about a change, a forecast or a "
                "time of day, which a summary of the window cannot answer"
            )
            return None
        # A BARE MEASURAND IS NOT A REFUSAL (wave 4). Five of the 24 unacceptable answers in the
        # fresh read were this lane's breadth refusal on a question that named a quantity and no
        # place: "how does the building prevent overheating in sun exposed areas?" was told it
        # covered 288 temperature sensors. A building-and-per-floor summary is cheap here — the
        # store computes it — and it is nearer the question than a refusal is.
        return AggregateIntent("summary", "floor", True, False, False, ()) if summary else None
    if budget_hit:
        return intent
    if intent.group == "floor" and not has_floor_metadata:
        return intent
    kinds = set(unit_kinds)
    if intent.stat == "total" and "volumetric_flow" in kinds:
        return intent
    if (
        intent.stat == "total"
        and _CONSUME.search(question or "")
        and kinds
        and kinds <= _LEVEL_KINDS
    ):
        return intent
    if headcount and intent.group == "floor" and (intent.now or not names_a_period(question)):
        # "Which floor has the most people?" names no period, and for a headcount that means now.
        # A floor's headcount summed over a week is not a quantity anyone means, so a question
        # that DOES name a period is left alone.
        return intent
    return None


def _kinds_of(units: Iterable[str]) -> List[str]:
    from orchestrator.services.units import _KIND, normalise

    return [_KIND.get(normalise(u), "") for u in units if u]


def _kind_of(unit: str) -> str:
    from orchestrator.services.units import _KIND, normalise

    return _KIND.get(normalise(unit), "")


async def _stores_ready(
    uuids: Sequence[str],
    storage_map: Dict[str, str],
    adapter_for: Callable[[str], Any],
    store_key: Callable[[str], str],
) -> Tuple[Dict[str, Tuple[Any, List[str]]], List[str]]:
    """(store -> (adapter, its sensors)) for the stores this lane can summarise, and the rest."""
    groups: Dict[str, List[str]] = {}
    for u in uuids:
        groups.setdefault(store_key(storage_map.get(u, "")), []).append(u)
    ready: Dict[str, Tuple[Any, List[str]]] = {}
    unsupported: List[str] = []
    for key, members in groups.items():
        adapter = adapter_for(storage_map.get(members[0], ""))
        if adapter is None:
            unsupported.extend(members)
            continue
        if hasattr(adapter, "_detect_narrow") and not getattr(adapter, "_narrow_checked", True):
            try:
                await adapter._detect_narrow()
            except Exception:  # a layout probe that fails leaves the store unsupported below
                pass
        if layout_of(adapter) in ("unsupported", "pg_wide"):
            unsupported.extend(members)
            continue
        ready[key] = (adapter, members)
    return ready, unsupported


def build_companion_query(seeds: Sequence[str]) -> str:
    """SPARQL: sensors of the SAME most-specific class as the seeds that sit on a floor itself.

    A floor-level meter is the floor's own figure. When a question is resolved to room-level
    sensors only, the floor meters of that class are invisible to the row-based lane and to any sum
    over rooms; this finds them without naming a class here.
    """
    values = " ".join(f'"{u}"' for u in list(seeds)[:25] if _SAFE_ID.match(str(u)))
    return (
        "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
        "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>\n"
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "SELECT DISTINCT ?uuid ?storage ?floorNum ?label WHERE {\n"
        f"  VALUES ?seed {{ {values} }}\n"
        "  ?r0 ref:hasTimeseriesId ?seed . ?s0 ref:hasExternalReference ?r0 . ?s0 a ?cls .\n"
        '  FILTER(STRSTARTS(STR(?cls), "https://brickschema.org/schema/Brick#"))\n'
        "  FILTER NOT EXISTS { ?s0 a ?sub . ?sub rdfs:subClassOf ?cls . FILTER(?sub != ?cls) }\n"
        "  ?s a ?cls ; brick:hasLocation ?fl . ?fl a brick:Floor .\n"
        '  BIND(REPLACE(STR(?fl), "^.*[Ff]loor", "") AS ?floorNum)\n'
        "  ?s ref:hasExternalReference ?r . ?r ref:hasTimeseriesId ?uuid .\n"
        "  OPTIONAL { ?r ref:storedAt ?storage }\n"
        "  OPTIONAL { ?s rdfs:label ?label }\n"
        "} LIMIT 200"
    )


def parse_companions(result: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """{uuid: {storage, floor, label}} for the floor-level sensors a companion query found."""
    out: Dict[str, Dict[str, str]] = {}
    for b in ((result or {}).get("results") or {}).get("bindings") or []:
        uuid = (b.get("uuid") or {}).get("value")
        if uuid:
            out[uuid] = {
                "storage": (b.get("storage") or {}).get("value", ""),
                "floor": (b.get("floorNum") or {}).get("value", ""),
                "label": (b.get("label") or {}).get("value", ""),
            }
    return out


async def try_answer(
    *,
    question: str,
    uuids: Sequence[str],
    storage_map: Optional[Dict[str, str]],
    metadata: Optional[Dict[str, Dict[str, Any]]],
    start_date: Optional[str],
    end_date: Optional[str],
    budget_hit: bool,
    tz_name: Optional[str],
    adapter_for: Callable[[str], Any],
    store_key: Callable[[str], str],
    sparql_exec: Optional[Callable[[str], Awaitable[Dict[str, Any]]]] = None,
    now: Optional[datetime] = None,
    standards_path: Optional[Path] = None,
    bands: Optional[Dict[str, Tuple[float, float]]] = None,
    resolution_clamp_s: Optional[float] = None,
    aggregate_only: bool = False,
    allow_named_place: bool = False,
) -> Optional[Dict[str, Any]]:
    """Answer an aggregate question from the stores, or return None to leave the lane as it was.

    None is returned for anything this module cannot do completely and honestly (no window named,
    no store it can summarise, a statistic it cannot compute for these units). The caller then
    behaves exactly as before, so declining here never makes an answer worse.

    The two privacy arguments mirror what the policy decision point told the SQL lane. A
    `resolution_clamp_s` means this reader may not have detail finer than that: a "right now"
    answer or the minute a peak was reached would be finer, so they are not given. `aggregate_only`
    means a list of per-room values is a map of where people are: rooms are not enumerated.
    """
    from orchestrator.services.aggregate_support import (
        asks_for_per_sensor_detail,
        asks_for_time_pattern,
        asks_which_place,
        counts_people,
        is_headcount,
        is_readings_question,
        names_a_period,
        names_a_place,
        presence_question,
        resolve_unit,
    )
    from orchestrator.services.units import normalise

    metadata = dict(metadata or {})
    storage_map = dict(storage_map or {})
    uuids = list(dict.fromkeys(uuids))
    has_floor = any((metadata.get(u) or {}).get("floor") for u in uuids)

    # WHAT THE SENSORS ARE is decided before whether to take the question: two of the five cases
    # in `wants_lane` turn on it, and both were reached by a lane that then answered wrongly.
    # Units come through `resolve_unit` here too, so the decision and the arithmetic below cannot
    # disagree about whether a series is a rate.
    units = [
        resolve_unit(
            str((metadata.get(u) or {}).get("unit") or ""),
            str((metadata.get(u) or {}).get("label") or ""),
        )[0]
        for u in uuids
    ]
    texts = [
        f"{(metadata.get(u) or {}).get('label', '')} {(metadata.get(u) or {}).get('kind', '')} "
        f"{(metadata.get(u) or {}).get('sensor_uri', '')}"
        for u in uuids
    ]
    measurand = measurand_key(texts) or measurand_key([question])
    kinds = _kinds_of(units)
    labels = [str((metadata.get(u) or {}).get("label") or "") for u in uuids]
    headcount = is_headcount(measurand, labels, kinds)

    # WHEN A BARE MEASURAND MAY BE SUMMARISED. All four conditions, because each one on its own
    # would take a question this lane should not answer: a named place makes a building-wide
    # summary an answer to a different question; a per-sensor request is the one shape the breadth
    # refusal is still right for; and a question about what the building PROVIDES, or about how a
    # technique works, belongs to the capability and knowledge lanes.
    #
    # THE QUANTITY MUST BE THE QUESTION'S OWN, NOT THE SENSORS' (tail G, 2026-09-20). `measurand`
    # is voted from the labels of whatever sensors the pipeline bound, and an unrelated question
    # binds whatever retrieval falls back to: "which approved paths have abnormal latency, jitter or
    # packet loss?", "which verified BMS/HVAC control issue deserves attention?" and "is the domestic
    # hot-water plant recovering?" were each answered with a TEMPERATURE or FLOW summary. A summary
    # answers a question that names its quantity; the question's own words are the only evidence of
    # that, so a question that names none is not this lane's.
    # BUG-879: a named place need not mean "decline" — it can mean "group by that place".
    #
    # The veto above reads "a named place makes a building-wide summary an answer to a different
    # question", and that is right about a BUILDING-WIDE summary. It is not right about the
    # question. When the pipeline has already bound this question's sensors to the place it
    # names, a summary over them IS that place's summary; what would be wrong is LABELLING it
    # as the building's. So the caller may lift the veto, and when it does the grouping moves to
    # the place, where `_group_key` names the group after the room or floor rather than
    # "building" — the label follows the scope by construction instead of by promise.
    #
    # Lifted only by an explicit caller flag, never inferred: the comparison lane knows it has
    # scoped both of its windows to one place, and nothing else does. Measured 2026-09-23: with
    # the veto in force, "compare the average CO2 in room 5.01 this week against last week"
    # refused BOTH of its windows with `not claimed: measurand=co2 place=True`, which is what
    # left W1-04 and W2-03 PARTIAL.
    _place_named = names_a_place(question)
    summary_ok = bool(
        measurand
        and question_asks_about(question, measurand)
        and (allow_named_place or not _place_named)
        and not asks_for_per_sensor_detail(question)
        and is_readings_question(question)
        and not asks_which_place(question)
    )
    # A TIME-OF-DAY question ("when are CO2 or temperature most likely to worsen") passes the same
    # four tests and is answered by the hourly profile. For a HEADCOUNT the profile is built from
    # the floor counters, never from a mean over room readings: a mean of counters is not a
    # headcount, but each floor's own counter is one, and the building's figure is their sum.
    profile_ok = summary_ok and asks_for_time_pattern(question)
    intent = wants_lane(
        question, len(uuids), budget_hit, has_floor, kinds, headcount, summary_ok, profile_ok
    )
    if intent is None and allow_named_place and summary_ok:
        # LIFTING THE VETO WAS NOT ENOUGH, AND THIS IS THE HALF THAT WAS MISSING (BUG-879).
        # `summary_ok` only ever reaches `wants_lane`'s SIXTH case, which fires when the question
        # parses to NO statistic in particular. "Compare the AVERAGE CO2 in room 5.01 this week
        # against last week" parses perfectly well � stat=mean, group=building � so it skipped
        # that case, matched none of the five others, and was declined for a reason that had
        # nothing to do with the place veto. Measured 2026-09-29, after the veto was lifted:
        # `summary_ok=True` and `wants_lane` still returned None for both window sizes.
        #
        # `wants_lane`'s five cases are all "this lane must take it because no other lane can".
        # This is a different claim and belongs to the caller: the comparison lane has already
        # scoped BOTH windows to one place and has nothing else to fall back on, so a decline
        # here leaves the user with nothing rather than with a worse answer. It is gated on
        # `summary_ok`, so every honesty test that guards the summary path � names the measurand,
        # asks about readings, asks for no per-sensor detail, does not ask WHICH place � guards
        # this too, and the regrouping below still moves the label onto the place.
        intent = parse_intent(question)
    if intent is None and measurand == "occupancy":
        # IS ANYONE THERE IS A COUNT OF PLACES, AND THIS LANE IS WHERE IT IS COUNTED (BUG-954).
        # It reaches here precisely because it holds no statistic word, so every branch above
        # has already declined it; taking it changes nothing that was being answered.
        #
        # The question must be about occupancy AND name no other quantity: "which zones show
        # sustained elevated CO2 during an approved occupied period?" holds the frame and the
        # word "occupied" and is an exceedance question about CO2, which the guard below leaves
        # to the branch that answers it.
        _asked = question_measurands(question)
        _wants = presence_question(question) if _asked <= {"occupancy"} else None
        if _wants is not None and not resolution_clamp_s:
            _window = resolve_window(question, start_date, end_date, tz_name, latest=True, now=now)
            if _window is not None:
                _places: Dict[str, Place] = {}
                if sparql_exec is not None:
                    try:
                        _places = parse_locations(await sparql_exec(build_location_query(uuids)))
                    except Exception as exc:  # placement is the grouping; without it, decline
                        logger.warning(f"[aggregate] presence locations unavailable: {exc}")
                _answer = await _answer_presence(
                    wants=_wants,
                    uuids=uuids,
                    storage_map=storage_map,
                    facts=facts_from(uuids, metadata, _places),
                    window=_window,
                    adapter_for=adapter_for,
                    store_key=store_key,
                    tz_name=tz_name,
                    # `aggregate_only` means this reader may not have a map of where people
                    # are, so the count is given and the places are not named.
                    name_places=not aggregate_only,
                )
                if _answer is not None:
                    logger.info(
                        "[aggregate] presence claim: wants=%s spaces=%s",
                        _wants,
                        (_answer.get("aggregate") or {}).get("sensors"),
                    )
                    return _answer
    if intent is None:
        logger.info(
            "[aggregate] not claimed: measurand=%s place=%s per_sensor=%s readings=%s "
            "budget_hit=%s q=%r",
            measurand,
            names_a_place(question),
            asks_for_per_sensor_detail(question),
            is_readings_question(question),
            budget_hit,
            (question or "")[:80],
        )
        return None
    if headcount and intent.stat == "summary":
        # A bare "is it busy?" about people is answered per floor from the floor counters, the same
        # source "how many people are in the building" uses. A summary whose lead figure is the mean
        # of room counters ("averaging 2.2 people") is not a headcount and disagrees with it.
        intent = AggregateIntent("max", "floor", True, False, True, ())
    if headcount and intent.group == "floor" and not intent.now and not names_a_period(question):
        # Present tense with no period named: "which floor has the most people" is about now.
        intent = AggregateIntent(intent.stat, intent.group, intent.descending, False, True)
    _grp = "floor" if _FLOOR_NAMED_RE.search(question or "") else "room"
    if (
        allow_named_place
        and _place_named
        and intent.group != _grp
        and intent.group in ("building", "floor")
    ):
        # THE LABEL MUST FOLLOW THE SCOPE (BUG-879). Claiming a place-named question while still
        # grouping as "building" would key every figure "building mean" over one room's sensors
        # — the same shape as BUG-883, where one sensor was reported as a floor's. Grouping by
        # the place makes `_group_key` name the group after the room or floor instead, so the
        # figure cannot claim a scope it does not have.
        #
        # "building" WAS NOT THE ONLY WRONG GROUP (CAVEAT-938, widened 2026-09-29). This guard
        # first fired only on `group == "building"`, and the live re-ask showed why that is not
        # enough: "the temperature in room 5.01 this week compared with last week" does not
        # parse to an intent at all, so it is claimed by the bare-measurand SUMMARY path, which
        # hardcodes `group="floor"`. The guard was skipped, `_group_key(f, "floor")` returned
        # the floor number, and every figure was labelled "5 mean" over a group holding ONE
        # sensor — a room's reading wearing a floor's name, which is BUG-883 exactly. A question
        # that names a ROOM must group by room whatever the claiming path assumed; a question
        # that names a FLOOR is left alone when it is already grouped by floor.
        intent = AggregateIntent(
            intent.stat,
            _grp,
            intent.descending,
            intent.verdict,
            intent.now,
            intent.floors,
            intent.worst,
        )
        logger.info(f"[aggregate] place-scoped claim: grouping by {_grp} so the figures name it")
    window = resolve_window(question, start_date, end_date, tz_name, latest=intent.now, now=now)
    if intent.stat == "profile":
        # A pattern needs several days. A pipeline window of a class-length afternoon would give one
        # reading per hour, and "usually" over one day is that day's weather.
        from orchestrator.services import aggregate_profile as _prof
        from orchestrator.services.requested_interval import store_now as _store_now

        if window is None or (_stamp(window.end) - _stamp(window.start)).days < 3:
            window = _prof.default_window(now or _store_now(), tz_name)
    if window is None and summary_ok:
        # A question that names a period gets it; one that names none is about now. "…during an
        # approved occupied period" names no window, and returning None here is what sent that
        # question to the refusal with 280 sensors attached.
        intent = AggregateIntent("summary", "floor", True, False, True, ())
        window = resolve_window(question, None, None, tz_name, latest=True, now=now)
    if window is None:
        return None

    places: Dict[str, Place] = {}
    if sparql_exec is not None:
        try:
            places = parse_locations(await sparql_exec(build_location_query(uuids)))
        except Exception as exc:  # placement is an enrichment; the answer degrades, not fails
            logger.warning(f"[aggregate] locations unavailable: {exc}")
    facts = facts_from(uuids, metadata, places)

    if resolution_clamp_s and (intent.now or measurand == "occupancy"):
        return None  # a clamped reader keeps the clamped (row-based) path
    if aggregate_only and intent.group == "room":
        return None

    if intent.stat == "total":
        return await _answer_total(
            intent, question, uuids, storage_map, facts, window, adapter_for, store_key, measurand
        )

    if intent.stat == "profile":
        from orchestrator.services import aggregate_profile as _prof
        from orchestrator.services.aggregate_support import (
            WHOLE_BUILDING_NOTE,
            names_a_possessive_place,
        )

        note = WHOLE_BUILDING_NOTE if names_a_possessive_place(question) else ""
        if headcount:
            counters = {
                u: facts[u].floor
                for u in uuids
                if facts[u].on_floor and facts[u].floor and counts_people(facts[u].label)
            }
            if len(counters) < 2 and sparql_exec is not None:
                try:
                    found = parse_companions(
                        await sparql_exec(
                            build_companion_query(
                                [u for u in uuids if counts_people(facts[u].label)] or uuids
                            )
                        )
                    )
                except Exception as exc:
                    logger.warning(f"[aggregate] floor counters unavailable: {exc}")
                    found = {}
                for u, c in found.items():
                    storage_map[u] = c["storage"]
                    counters[u] = c["floor"]
            # No fallback to a mean over rooms: it is not a headcount, and saying nothing here
            # leaves the question to a lane that will at least not pass it off as one.
            return await _prof.answer_headcount_profile(
                counters=counters,
                storage_map=storage_map,
                window=window,
                tz_name=tz_name,
                adapter_for=adapter_for,
                store_key=store_key,
                intent=intent,
                note=note,
            )

        families: Dict[str, List[str]] = {}
        for u in uuids:
            families.setdefault(normalise(facts[u].unit), []).append(u)
        if bands is None:
            bands, _checked = await _bands_for(uuids, sparql_exec)
        res = await _prof.answer_profile(
            families=families,
            facts=facts,
            storage_map=storage_map,
            window=window,
            tz_name=tz_name,
            adapter_for=adapter_for,
            store_key=store_key,
            measurand=measurand,
            bands=bands,
            intent=intent,
        )
        if res and note:
            res["formatted_response"] += "\n\n" + note
        return res

    # A STATUS FLAG IS NOT A HEADCOUNT, and both live in one table: a question about people binds
    # 256 counting series and 243 occupancy-status series together. Dropped by NAME rather than by
    # letting the unit-family vote below decide it — that vote would be won by a margin of 13
    # series, which is not a property anything should rest on.
    counting = [u for u in uuids if counts_people(facts[u].label, _kind_of(facts[u].unit))]
    not_counting = len(uuids) - len(counting)
    if headcount and counting:
        uuids = counting

    # One unit family per answer: ppm and µg/m³ are not one quantity, and the rest are named.
    by_unit: Dict[str, List[str]] = {}
    for u in uuids:
        by_unit.setdefault(normalise(facts[u].unit), []).append(u)
    unit = max(by_unit, key=lambda k: len(by_unit[k]))
    use = list(by_unit[unit])
    left_out_units = len(uuids) - len(use)

    if intent.floors:
        placed = [u for u in use if facts[u].floor]
        if placed:
            use = [u for u in placed if facts[u].floor in intent.floors]
            if not use:
                return None

    limit_t: Optional[Threshold] = None
    no_limit_note = False
    if intent.verdict:
        limit_t = cited_threshold(measurand, question, standards_path)
        if limit_t is None:
            no_limit_note = True
            intent = AggregateIntent("max", intent.group, True, False, intent.now, intent.floors)
    if intent.worst:
        if measurand not in ("co2", "pm25", "voc", "sound"):
            return None  # which end of the scale is "worst" depends on the quantity; not guessed
        intent = AggregateIntent(intent.stat, intent.group, True, False, intent.now, intent.floors)

    kind = _kind_of(unit)
    additive = intent.now and headcount and kind != "ratio"
    basis = ""
    if additive and intent.group == "floor":
        # THE FLOOR'S OWN COUNTER IS THE FLOOR'S FIGURE, and it is looked for whether or not the
        # resolved set already holds one. The live run resolved room sensors only, summed them,
        # and reported 47 people across five floors three minutes after the building total said
        # 23 from the six floor counters. Whichever set is used is stated, because the two are
        # different measurements and a reader comparing two answers must be able to see which.
        found: Dict[str, Dict[str, str]] = {}
        if sparql_exec is not None:
            try:
                found = parse_companions(await sparql_exec(build_companion_query(use)))
            except Exception as exc:
                logger.warning(f"[aggregate] floor-level companions unavailable: {exc}")
        on_floor_already = [u for u in use if facts[u].on_floor]
        if found:
            for u, c in found.items():
                storage_map[u] = c["storage"]
                facts[u] = Facts(u, c["label"], unit, c["floor"], "", True)
            use = list(found)
            basis = (
                "Each floor's figure is the reading of that floor's own counter; the room-level "
                "counters are not added to it, so nobody is counted twice."
            )
        elif on_floor_already:
            use = on_floor_already
            basis = (
                "Each floor's figure is the reading of that floor's own counter; the room-level "
                "counters are not added to it, so nobody is counted twice."
            )
        else:
            basis = (
                "No floor has its own counter, so each floor's figure is the sum of one reading "
                "per room that has a counter; a room without one is not in it."
            )

    if bands is None:
        bands, bands_checked = await _bands_for(use, sparql_exec)
    else:
        bands_checked = True

    ready, unsupported = await _stores_ready(use, storage_map, adapter_for, store_key)
    aggs: List[SensorAgg] = []
    lat: List[SensorLatest] = []
    failed: List[str] = []
    limit_value = limit_t.value if limit_t is not None else None
    for _key, (adapter, members) in ready.items():
        if intent.now:
            got_l, bad = await run_latest(adapter, members, window)
            lat.extend(got_l)
        else:
            got_a, bad = await run_aggregates(adapter, members, window, limit_value, bands)
            aggs.extend(got_a)
        failed.extend(bad)
    # A "right now" reading is screened against the physical range too. The windowed path does it
    # in SQL; this path takes each sensor's newest row, so it is done here, and the range printed
    # beside a figure ("ranging from 10 to 958 ppm") can no longer begin below what the air holds.
    lat, band_dropped = drop_out_of_band(lat, bands)
    if not aggs and not lat:
        return None

    answered = {a.uuid for a in aggs} | {r.uuid for r in lat}
    if intent.now:
        groups, unplaced = combine_latest(lat, facts, intent, additive)
    else:
        groups, unplaced = combine_windowed(aggs, facts, intent)
    ranked = rank(groups, intent.descending)
    if not ranked:
        return None
    # THE INVARIANT, FOR EVERY PATH THAT PRINTS A MEAN: a stated figure outside its stated range is
    # never printed. `render_summary` and the hourly profile carry their own; this covers a plain
    # "highest average" ranking, where each group's mean is printed beside nothing that would show
    # the disagreement but is still a number a reader will check against the range it came from.
    if intent.stat in ("mean", "summary") and not _means_inside_ranges(ranked):
        return None

    common = dict(
        measurand=measurand or "",
        # WHAT THE ANSWER CALLS THE QUANTITY (BUG-1255). Computed from the question's own
        # qualifier and checked against every bound sensor's name, so a set that all measures
        # something narrower than the coarse measurand is not summarised under the coarse word.
        # Over the sensors that ANSWERED, not over everything the pipeline bound: the name has to
        # be true of the set the figures came from.
        quantity=asked_quantity_name(
            question,
            measurand,
            [str((metadata.get(u) or {}).get("label") or "") for u in sorted(answered)],
        ),
        unit=unit,
        window=window,
        sensors_used=len(answered),
        sensors_requested=len(use),
        excluded=sum(a.excluded for a in aggs) + len(band_dropped),
        excluded_sensors=sum(1 for a in aggs if a.excluded) + len(band_dropped),
        no_reading=len([u for u in use if u not in answered and u not in band_dropped]),
        unplaced=unplaced,
        bands_checked=bands_checked,
        band_text=_band_text(aggs, bands, unit, band_dropped),
    )
    if limit_t is not None:
        floors_only, _ = combine_windowed(aggs, facts, AggregateIntent("exceed", "floor"))
        rooms_all, _ = combine_windowed(aggs, facts, AggregateIntent("exceed", "room"))
        rooms = sorted(rooms_all, key=lambda g: (-g.exceed_readings, -(g.high or 0)))
        overall = max(rooms_all, key=lambda g: g.high or float("-inf")) if rooms_all else None
        at = None
        if not resolution_clamp_s:
            at = await _peak_label(overall, ready, storage_map, store_key, window, tz_name)
        text = render_exceedance(
            rooms, floors_only, threshold=limit_t, peak=overall, peak_at=at, **common
        )
        figures = {
            **group_figures(rooms),
            **group_figures(floors_only),
            "limit": limit_t.value,
            "readings above the limit": float(sum(g.exceed_readings for g in rooms)),
            "readings": float(sum(g.readings for g in rooms)),
            "sensors above the limit": float(sum(g.exceed_sensors for g in rooms)),
        }
    elif intent.stat == "summary":
        text = render_summary(
            ranked,
            floors_seen=len({facts[u].floor for u in answered if facts[u].floor}),
            **common,
        )
        if not text:
            return None  # the renderer withheld it; the lane must not ship an empty answer
        figures = group_figures(ranked)
    else:
        at = None
        if not intent.now and not resolution_clamp_s and intent.stat in ("max", "min"):
            at = await _peak_label(ranked[0], ready, storage_map, store_key, window, tz_name)
        text = render_extreme(
            intent,
            ranked,
            peak_at=at,
            floors_seen=len({facts[u].floor for u in answered if facts[u].floor}),
            additive=additive,
            no_limit_note=no_limit_note,
            **common,
        )
        figures = group_figures(ranked)
    figures.update(
        {
            "sensors requested": float(len(use)),
            "readings excluded as impossible": float(common["excluded"]),
            "sensors excluded as impossible": float(common["excluded_sensors"]),
            "sensors without readings": float(common["no_reading"]),
            "floors": float(len({facts[u].floor for u in answered if facts[u].floor})),
        }
    )
    extra: List[str] = [basis] if basis else []
    # "My shared office is usually busy": the reader's own space cannot be resolved, so the answer
    # is the building's, and says so, rather than being refused or passed off as the office's.
    from orchestrator.services.aggregate_support import (
        WHOLE_BUILDING_NOTE,
        names_a_possessive_place,
    )

    if names_a_possessive_place(question):
        extra.append(WHOLE_BUILDING_NOTE)
    # A FLOOR WITH NO FIGURE IS NAMED, NOT DROPPED. The live run listed five floors and omitted the
    # sixth in silence, so a reader had no way to tell a floor that is empty from one that was
    # never read. Only for a per-floor ranking, and only when the building's own floor list can be
    # read: guessing which floors exist is how a floor nobody has would get named.
    if intent.group == "floor" and sparql_exec is not None:
        try:
            from orchestrator.services.aggregate_support import (
                build_floors_query,
                missing_floors_note,
                parse_floors,
            )

            all_floors = parse_floors(await sparql_exec(build_floors_query()))
            # Which floors HOLD a sensor of this kind is the graph's fact, not the fetch's: a
            # capped candidate list handed this lane 8 of 280 CO2 points on 2026-10-02 and the
            # sentence below declared five floors sensorless. None when it cannot be read, and
            # then nothing is claimed about sensors.
            floors_with: Optional[List[str]] = None
            try:
                from orchestrator.services.aggregate_support import (
                    build_floors_with_class_query,
                )

                _classes = _measurand_classes(measurand)
                if _classes:
                    floors_with = parse_floors(
                        await sparql_exec(build_floors_with_class_query(_classes))
                    )
            except Exception as exc:  # pragma: no cover - then nothing is claimed about sensors
                logger.debug(f"[aggregate] floors-with-sensor lookup skipped: {exc}")
            present = [g.key for g in ranked]
            if (
                intent.stat == "summary"
                and len(ranked) == 1
                and len(all_floors) > 1
                and floors_with is not None
                and set(floors_with) <= {str(ranked[0].key)}
            ):
                # "No figure for Floor 0, 1, 2, 3 and 4" is true and reads like a fault. The
                # building simply does not measure this quantity anywhere else, and that is a
                # fact about the building rather than a gap in the answer -- said only when the
                # graph agrees.
                extra.append(
                    f"This building records {display_name(measurand)} on one floor only "
                    f"(Floor {_floor_name(ranked[0].key)}); the other {len(all_floors) - 1} floors have no "
                    "sensor of this kind."
                )
            else:
                note = missing_floors_note(
                    all_floors, present, display_name(measurand), floors_with
                )
                if note:
                    extra.append(note)
        except Exception as exc:  # a completeness note must never cost the answer
            logger.warning(f"[aggregate] floor list unavailable: {exc}")
    if unsupported:
        extra.append(
            f"{len(unsupported)} sensors are in a store this kind of summary is not available for "
            "and are not counted."
        )
    if failed:
        extra.append(
            f"{len(set(failed))} sensors could not be summarised just now and are not counted."
        )
    if left_out_units:
        extra.append(
            f"{left_out_units} sensors report in a different unit and are not combined with these."
        )
    if headcount and not_counting:
        extra.append(
            f"{not_counting} sensors record whether a space is occupied rather than how many "
            "people are in it, and are not counted."
        )
    if extra:
        text = f"{text}\n\n" + " ".join(extra)
    return _result(text, intent, window, len(answered), figures)


def _means_inside_ranges(groups: Sequence[GroupStat]) -> bool:
    """Is each group's mean inside the extremes of the readings it is the mean of?

    A mean is a weighted average of readings, so it cannot lie outside their range. When it does,
    the sum and the extremes came from different populations (a filter applied to one and not the
    other, two unit families mixed), and any sentence built from them would be arithmetic nobody
    can defend. The lane declines instead and says why in the log.
    """
    for g in groups:
        if g.mean is None or g.low is None or g.high is None:
            continue
        # a hair of tolerance: a mean of floats may exceed its extreme by rounding, never by more
        slack = 1e-9 * max(1.0, abs(g.high), abs(g.low))
        if not (g.low - slack <= g.mean <= g.high + slack):
            logger.error(
                "[aggregate] withheld: group %r mean %.6g is outside its range %.6g..%.6g "
                "(%d readings from %d sensors)",
                g.key,
                g.mean,
                g.low,
                g.high,
                g.readings,
                g.sensors,
            )
            return False
    return True


def drop_out_of_band(
    latest: Sequence[SensorLatest], bands: Optional[Dict[str, Tuple[float, float]]]
) -> Tuple[List[SensorLatest], set]:
    """Newest readings inside their sensor's physical range, and the uuids that were outside it."""
    kept: List[SensorLatest] = []
    dropped: set = set()
    for r in latest:
        band = (bands or {}).get(r.uuid)
        if band is not None and not (band[0] <= r.value <= band[1]):
            dropped.add(r.uuid)
        else:
            kept.append(r)
    return kept, dropped


def _band_text(
    aggs: Sequence[SensorAgg],
    bands: Dict[str, Tuple[float, float]],
    unit: str,
    also: Iterable[str] = (),
) -> str:
    """The physical range the excluded readings fell outside, when there is one shared range."""
    ranges = {bands[a.uuid] for a in aggs if a.excluded and a.uuid in bands}
    ranges |= {bands[u] for u in also if u in bands}
    if len(ranges) != 1:
        return ""
    lo, hi = next(iter(ranges))
    return f"{_n(lo)} to {_n(hi)}{(' ' + unit) if unit else ''}"


async def _peak_label(
    group: Optional[GroupStat],
    ready: Dict[str, Tuple[Any, List[str]]],
    storage_map: Dict[str, str],
    store_key: Callable[[str], str],
    window: Window,
    tz_name: Optional[str],
) -> Optional[str]:
    """When the sensor that set a group's figure first reached it, as building time; else None."""
    if group is None or not group.peak_uuid or group.peak_value is None:
        return None
    pair = ready.get(store_key(storage_map.get(group.peak_uuid, "")))
    if pair is None:
        return None
    when = await peak_time(pair[0], group.peak_uuid, group.peak_value, window)
    return _show(when, tz_name) if when else None


_BANDS_CACHE: Dict[int, Any] = {}


async def _bands_for(
    uuids: Sequence[str],
    sparql_exec: Optional[Callable[[str], Awaitable[Dict[str, Any]]]],
) -> Tuple[Dict[str, Tuple[float, float]], bool]:
    """Physical ranges by uuid from the graph, and whether the check could be made at all."""
    if sparql_exec is None:
        return {}, False
    try:
        from orchestrator.services.physical_bands import PhysicalBands

        # One loader per executor, so a turn does not reload every band in the building.
        pb = _BANDS_CACHE.get(id(sparql_exec))
        if pb is None:
            pb = _BANDS_CACHE[id(sparql_exec)] = PhysicalBands(sparql_exec)
        found: Dict[str, Tuple[float, float]] = {}
        for u in uuids:
            band = await pb.band_for(u)
            if band is not None:
                found[u] = (band.low, band.high)
        return found, bool(getattr(pb, "_by_uuid", None))
    except Exception as exc:
        logger.warning(f"[aggregate] physical bands unavailable: {exc}")
        return {}, False


async def _answer_presence(
    *,
    wants: str,
    uuids: Sequence[str],
    storage_map: Dict[str, str],
    facts: Dict[str, Facts],
    window: Window,
    adapter_for: Callable[[str], Any],
    store_key: Callable[[str], str],
    tz_name: Optional[str],
    name_places: bool = True,
) -> Optional[Dict[str, Any]]:
    """How many spaces have someone in them, counted in code from each series' newest reading.

    THE COUNT IS COMPUTED, NOT NARRATED (BUG-954). Nothing in this module parsed "which rooms are
    occupied at the moment" — it holds no statistic word, so `parse_intent` returned None and
    `wants_lane` declined, twice per phrasing on the live runs of 2026-09-30. The turn then
    fetched the readings and left the count to the narration, which named the five rooms it could
    list under a headline of five, beside its own statistics saying 131 of 234 read zero. The
    figure below comes from one list of places; the names printed are that list's members, so the
    headline and the names cannot disagree.

    A SPACE IS NOT A SERIES. Grouping is by the space the graph places each series in. Where one
    space carries both a presence flag and a people counter the flag decides it — it is the
    instrument that answers "is anyone there" — and the disagreement is reported rather than
    hidden, because two instruments in one space reading differently is a fact about the records.
    """
    ready, _unsupported = await _stores_ready(uuids, storage_map, adapter_for, store_key)
    if not ready:
        return None
    latest: List[SensorLatest] = []
    for _key, (adapter, members) in ready.items():
        got, _bad = await run_latest(adapter, members, window)
        latest.extend(got)
    if not latest:
        return None

    from orchestrator.services.aggregate_support import counts_people

    # place -> family -> newest reading. A series the graph does not place names no space, so it
    # cannot be counted as one; it is disclosed instead.
    by_place: Dict[str, Dict[str, float]] = {}
    unplaced = 0
    floor_level = 0
    first_at: Optional[datetime] = None
    last_at: Optional[datetime] = None
    for r in latest:
        f = facts.get(r.uuid)
        if f is None:
            continue
        if f.on_floor:
            # A FLOOR IS NOT A ROOM. Its counter covers every room on it, so counting it as one
            # more place would both inflate the denominator and count those people twice.
            floor_level += 1
            continue
        place = (f.room or "").strip()
        if not place or place.isdigit():
            unplaced += 1
            continue
        family = "count" if counts_people(f.label, _kind_of(f.unit)) else "presence"
        held = by_place.setdefault(place, {})
        # One reading per family per place: a space with two presence flags is still one space,
        # and the newest of them is what "right now" means there.
        if family not in held or r.value > held[family]:
            held[family] = r.value
        if r.at is not None:
            first_at = r.at if first_at is None or r.at < first_at else first_at
            last_at = r.at if last_at is None or r.at > last_at else last_at
    if not by_place:
        return None

    basis = "presence" if any("presence" in v for v in by_place.values()) else "count"
    occupied: List[str] = []
    empty: List[str] = []
    conflicted: List[str] = []
    conflict_values: List[float] = []
    by_presence = by_counter = 0
    for place in sorted(by_place):
        seen = by_place[place]
        chosen = seen.get(basis)
        if chosen is None:
            # This space has no series of the family that decided the rest, so its own is used.
            # Counted separately: the denominator sentence must not say every space has the
            # instrument most of them have.
            other = next(iter(seen))
            chosen = seen[other]
            by_presence, by_counter = (
                (by_presence + 1, by_counter)
                if other == "presence"
                else (by_presence, by_counter + 1)
            )
        elif basis == "presence":
            by_presence += 1
        else:
            by_counter += 1
        (occupied if chosen > 0 else empty).append(place)
        if len(seen) > 1 and len({v > 0 for v in seen.values()}) > 1:
            conflicted.append(place)
            other = "count" if basis == "presence" else "presence"
            if other in seen:
                conflict_values.append(seen[other])

    count = PresenceCount(
        occupied=occupied,
        empty=empty,
        basis=basis,
        by_presence=by_presence,
        by_counter=by_counter,
        conflicted=conflicted,
        conflict_low=min(conflict_values) if conflict_values else None,
        conflict_high=max(conflict_values) if conflict_values else None,
        unplaced=unplaced,
        floor_level=floor_level,
        no_reading=len([u for u in uuids if u not in {r.uuid for r in latest}]),
        first_at=first_at,
        last_at=last_at,
    )
    text = render_presence(
        count, wants=wants, window=window, tz_name=tz_name, name_places=name_places
    )
    if not text:
        return None
    intent = AggregateIntent("presence", "room", True, False, True, ())
    return _result(
        text,
        intent,
        window,
        len(latest),
        {
            "spaces with someone in them": float(len(occupied)),
            "spaces with nobody in them": float(len(empty)),
            "spaces counted": float(len(occupied) + len(empty)),
            "spaces whose two occupancy series disagree": float(len(conflicted)),
        },
    )


async def _answer_total(
    intent: AggregateIntent,
    question: str,
    uuids: Sequence[str],
    storage_map: Dict[str, str],
    facts: Dict[str, Facts],
    window: Window,
    adapter_for: Callable[[str], Any],
    store_key: Callable[[str], str],
    measurand: Optional[str],
) -> Optional[Dict[str, Any]]:
    """A 'how much' question: rates are integrated, energy summed, levels declined with a reason."""
    use = list(uuids)
    if intent.floors:
        placed = [u for u in use if facts[u].floor]
        if placed:
            use = [u for u in placed if facts[u].floor in intent.floors]
    if not use:
        return None
    by_kind: Dict[str, List[str]] = {}
    for u in use:
        by_kind.setdefault(_kind_of(facts[u].unit), []).append(u)
    scope = f" on floor {', '.join(intent.floors)}" if intent.floors else " in the building"

    rates = by_kind.get("volumetric_flow", [])
    if rates:
        return await _answer_volume(
            question,
            rates,
            storage_map,
            facts,
            window,
            adapter_for,
            store_key,
            scope,
            volume_meters=[facts[u].label for u in by_kind.get("volume", [])],
        )

    energy = by_kind.get("energy", [])
    if energy and len(energy) * 2 >= len(use):
        return await _answer_energy(
            intent, energy, storage_map, facts, window, adapter_for, store_key, scope
        )

    levels = [
        u
        for k in (
            "concentration_ratio",
            "concentration_mass",
            "temperature",
            "ratio",
            "sound_level",
        )
        for u in by_kind.get(k, [])
    ]
    if levels and len(levels) * 2 >= len(use) and _CONSUME.search(question or ""):
        # NO STORE IS ASKED. The readings cannot answer the question, so fetching them can only
        # produce the paragraph the wave-1 run produced: "No usage data available", then the
        # highest and lowest ppm across 136 gas-leak detectors, which answers a question nobody
        # asked and reads as though the figures were an attempt at the one they did.
        return _result(
            render_not_additive(
                name=display_name(measurand) if measurand else _asked_noun(question),
                unit=facts[levels[0]].unit,
                sensors=len(levels),
                asked=_asked_noun(question),
            ),
            intent,
            window,
            len(levels),
            {"sensors": float(len(levels))},
        )
    return None


async def _answer_energy(
    intent: AggregateIntent,
    energy: Sequence[str],
    storage_map: Dict[str, str],
    facts: Dict[str, Facts],
    window: Window,
    adapter_for: Callable[[str], Any],
    store_key: Callable[[str], str],
    scope: str,
) -> Optional[Dict[str, Any]]:
    """Interval energy summed in the store; a reading is the energy of its own interval."""
    from orchestrator.services.units import aggregation_decision

    decision = aggregation_decision({facts[u].unit for u in energy})
    if not decision.ok:
        return None
    unit = decision.target
    ready, _unsupported = await _stores_ready(energy, storage_map, adapter_for, store_key)
    aggs: List[SensorAgg] = []
    for _key, (adapter, members) in ready.items():
        got, _bad = await run_aggregates(adapter, members, window, None, None)
        aggs.extend(got)
    if not aggs:
        return None
    total = sum(a.total for a in aggs)
    groups, _ = combine_windowed(aggs, facts, AggregateIntent("total", "floor"))
    table = ""
    if len(groups) > 1:
        table = (
            "| Floor | Total |\n|---|---|\n"
            + "\n".join(
                f"| Floor {_floor_name(g.key)} | {_n(g.value)} {unit} |"
                for g in sorted(groups, key=lambda g: _floor_sort(g.key))
            )
            + "\n\n"
        )
    text = (
        f"**{_n(total)} {unit} was used{scope}**, {window.label}.\n\n{table}"
        f"Each reading is the energy of its own interval, so a total is their sum "
        f"({sum(a.n for a in aggs):,} readings from {len(aggs)} meters)."
    )
    figures = {**group_figures(groups), "total": total, "readings": float(sum(a.n for a in aggs))}
    return _result(text, intent, window, len(aggs), figures)


def _asked_noun(question: str) -> str:
    m = re.search(r"how\s+much\s+(\w+)", question or "", re.IGNORECASE)
    return m.group(1) if m else "that"


#: A word inside a label such as "Floor3 water_flow_rate [L/s]": an underscore or a digit beside it
#: is a separator, which the regex word boundary does not treat it as.
_WATER = re.compile(r"(?<![a-z])water(?![a-z])", re.IGNORECASE)
_AIR = re.compile(r"(?<![a-z])air(?![a-z])", re.IGNORECASE)


async def _answer_volume(
    question: str,
    rates: Sequence[str],
    storage_map: Dict[str, str],
    facts: Dict[str, Facts],
    window: Window,
    adapter_for: Callable[[str], Any],
    store_key: Callable[[str], str],
    scope: str,
    volume_meters: Sequence[str] = (),
) -> Optional[Dict[str, Any]]:
    """Integrate each water flow series inside the store and total the ones that are regular."""
    candidates = [u for u in rates if _WATER.search(facts[u].label)]
    if not candidates:
        return None  # a flow that is not named as water is not assumed to be water
    skipped: List[Tuple[str, str]] = [
        (
            facts[u].label,
            (
                "it measures air, not water"
                if _AIR.search(facts[u].label)
                else "it is not named as water"
            ),
        )
        for u in rates
        if u not in candidates
    ]
    ready, _unsupported = await _stores_ready(candidates, storage_map, adapter_for, store_key)
    integrals: List[SensorIntegral] = []
    for _key, (adapter, members) in ready.items():
        got, _bad = await run_integrals(adapter, members, window)
        integrals.extend(got)
    if not integrals:
        return None
    rows: List[Tuple[str, float, str]] = []
    notes: List[str] = []
    for it in integrals:
        f = facts[it.uuid]
        ok, why = is_regular(it, window)
        litres = volume_litres(it, f.unit)
        if f.unit_conflict:
            skipped.append(
                (
                    f.label,
                    f"its recorded unit ({f.unit}) and the unit written on it ({f.unit_conflict}) "
                    "disagree, and a volume differs by that factor",
                )
            )
        elif litres is None:
            skipped.append(
                (f.label, f"its unit ({f.unit or 'none recorded'}) cannot be converted to litres")
            )
        elif not ok:
            skipped.append((f.label, why))
        else:
            rows.append((f.label, litres, f"{it.intervals:,} intervals"))
            notes.append(gap_statement(it, window))
    if not rows:
        # SAY WHY, rather than hand the question back. Returning None here sent the wave-1 run to
        # a lane that multiplied a mean flow by 86,400 seconds and reported "2,058,048 L" with no
        # statement of method at all. A stated inability is a better answer than an unstated sum.
        return _result(
            render_no_volume(skipped, scope=scope, window=window),
            AggregateIntent("total", "building"),
            window,
            0,
            None,
        )
    cadence = "Sampling: " + " | ".join(dict.fromkeys(notes)) + "."
    if volume_meters:
        shown = ", ".join(sorted(volume_meters)[:3])
        cadence += (
            f" {len(volume_meters)} meter(s) here report a volume per reading ({shown}"
            f"{', ...' if len(volume_meters) > 3 else ''}); they are not added to this figure, "
            "because whether each reading is a per-interval amount or a running total is not recorded."
        )
    text = render_volume(rows, window=window, scope=scope, skipped=skipped, cadence=cadence)
    figures: Dict[str, float] = {
        "total litres": sum(v for _, v, _ in rows),
        "total cubic metres": sum(v for _, v, _ in rows) / 1000.0,
    }
    for it in integrals:
        figures[f"{facts[it.uuid].label} intervals"] = float(it.intervals)
        figures[f"{facts[it.uuid].label} mean spacing minutes"] = it.mean_gap_s / 60.0
        figures[f"{facts[it.uuid].label} largest gap minutes"] = it.max_gap_s / 60.0
    for label, litres, _basis in rows:
        figures[f"{label} litres"] = litres
    return _result(text, AggregateIntent("total", "building"), window, len(rows), figures)


def group_figures(groups: Sequence[GroupStat]) -> Dict[str, float]:
    """The numbers a set of groups will be quoted with, keyed by what they are."""
    out: Dict[str, float] = {}
    for g in groups:
        for label, value in (
            ("figure", g.value),
            ("peak", g.high),
            ("lowest", g.low),
            ("mean", g.mean),
            ("sensors", g.sensors),
            ("readings", g.readings),
            ("readings above the limit", g.exceed_readings),
        ):
            if value is not None:
                out[f"{g.key} {label}"] = float(value)
    return out


def _result(
    text: str,
    intent: AggregateIntent,
    window: Window,
    sensors: int,
    figures: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """The dict the SQL lane returns: the answer, written, and marked so nothing rewrites it.

    The figures the text quotes are recorded as computed evidence, the way a live COUNT is: a
    number that came from a store's own aggregate is a query result, and a claim binder that
    cannot find it would read it as an invention (CAVEAT-769).
    """
    if figures:
        try:
            from orchestrator.services.evidence.computed import record

            record("aggregate_lane", {**figures, "sensors used": sensors})
        except Exception as exc:  # a recorder must never fail a lane
            logger.debug(f"[aggregate] figures not recorded: {exc}")
    return {
        "success": True,
        "query": "Aggregate lane (GROUP BY in the store, no row-level read)",
        "results": {"data": []},
        "formatted_response": text,
        "analytics_required": False,
        "aggregate_lane": True,
        "aggregate": {
            "stat": intent.stat,
            "group": intent.group,
            "window": {"start": window.start, "end": window.end},
            "sensors": sensors,
        },
        # The figures the text quotes, machine-readable (W1-04). They were computed here and
        # recorded as evidence, and then only the PROSE left this function -- so a caller that
        # wanted to compare two of these answers had to parse numbers back out of English, which
        # is the failure this repository keeps paying for. Returning them costs nothing and is
        # what lets the comparison lane subtract two periods without reading either answer.
        "figures": dict(figures or {}),
    }
