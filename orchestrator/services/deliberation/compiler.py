"""
compiler.py — NL → CQ-IR compilation, ARBITER's single neural step (V4-T15).

The LLM's only job here is words→symbols: emit JSON naming which KNOWN modality
each phrase refers to, the preference direction, spatial qualifiers and the time
anchor. Every field is then validated in code against the closed vocabulary
(saturation_modalities.yaml + the CQ-IR enums); anything unknown becomes an
AmbiguitySignal for the clarify-or-proceed policy — never a guess, never a
number. Temperature 0; the LLM callable is injectable so tests run offline.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Dict,
    FrozenSet,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
)

from orchestrator.services.deliberation.coverage_audit import ModalitySpec
from orchestrator.services.deliberation.cqir import (
    CQIR,
    SCORING_OPERATORS,
    V2_DECISIONS,
    AggregateSpec,
    AmbiguitySignal,
    CompareRelation,
    CompareSpec,
    Constraint,
    DecisionKind,
    Direction,
    EventCriterion,
    FacetCriterion,
    FacetOperator,
    GroupBy,
    Hardness,
    PeriodRef,
    PeriodSpec,
    RelateSpec,
    RelationKind,
    SortOrder,
    SpatialQualifier,
    SpatialRelation,
    Statistic,
    ThresholdSource,
    TimeBasis,
    TimeSpec,
    operation_facet_keys,
)
from shared.utils import get_logger

if TYPE_CHECKING:  # pragma: no cover - facets imports this module, so never at runtime
    from orchestrator.services.deliberation.facets import Facet, FacetCatalogue

logger = get_logger(__name__)

LlmCall = Callable[[str], Awaitable[str]]
#: Reads the values a facet actually holds in the graph (v2 inspection). Read-only and
#: deterministic; injected so the compiler stays offline-testable.
ValueReader = Callable[["Facet"], Awaitable[Sequence[str]]]

# lay-term hints handed to the LLM per modality (keeps the mapping grounded in
# the SAME vocabulary the coverage audit uses; extended per building via the
# modality config, never hardcoded here)
_LAY_HINTS: Dict[str, str] = {
    "noise": "quiet, silent, loud, noisy, sound level",
    "co2": "stuffy, fresh air, air quality, ventilation, CO2",
    "temperature": "warm, cold, cool, hot, chilly, temperature, cosy",
    "humidity": "humid, damp, dry, muggy",
    "occupancy": "busy, crowded, empty, free, people, occupancy, quiet in terms of people",
    "illuminance": "bright, dark, well-lit, light levels, daylight, lights on, lights off",
    "door_contact": "door open, door closed, door activity",
    "window_contact": "window open, window closed",
}


def _base_form(word: str) -> str:
    """Reduce a comparative or superlative to the form a lay-term table lists.

    "Which rooms are the STUFFIEST right now?" compiled to modality "stuffiest", which is not
    a modality name and not in the hint list either, so the whole query became unexecutable:
    "I couldn't map part of your request (stuffiest)". The plain form mapped cleanly to co2.
    People ask for the extreme far more often than the plain adjective, and listing every
    inflection of every lay term is a losing game (BUG-640).
    """
    w = (word or "").strip().lower()
    for suffix, replacement in (("iest", "y"), ("ier", "y"), ("est", ""), ("er", "")):
        # The stem must survive with at least two letters: "driest" -> "dry" is a word,
        # "est" -> "" is not. An earlier bound of len(suffix) + 2 was one character too
        # strict and dropped exactly that case.
        if w.endswith(suffix) and len(w) - len(suffix) >= 2:
            return w[: -len(suffix)] + replacement
    return w


def _modality_from_lay_term(term: str) -> Optional[str]:
    """Map a lay word — in any inflection — to the modality it describes, or None."""
    wanted = _base_form(term)
    if not wanted:
        return None
    for name, hint in _LAY_HINTS.items():
        for phrase in hint.split(","):
            for token in phrase.strip().lower().split():
                if _base_form(token) == wanted:
                    return name
    return None


#: Lay words whose GOOD END is in the word itself: "coolest" can only mean the low end of
#: temperature. Only words that carry their own polarity are listed — "temperature" and
#: "occupancy" are not here, because there the better end really is a preference and
#: `_infer_direction` already refuses to invent one.
_LAY_POLARITY: Dict[str, Direction] = {
    "cool": Direction.MINIMIZE,
    "cold": Direction.MINIMIZE,
    "chilly": Direction.MINIMIZE,
    "warm": Direction.MAXIMIZE,
    "hot": Direction.MAXIMIZE,
    "cosy": Direction.MAXIMIZE,
    "quiet": Direction.MINIMIZE,
    "silent": Direction.MINIMIZE,
    "loud": Direction.MAXIMIZE,
    "noisy": Direction.MAXIMIZE,
    "stuffy": Direction.MAXIMIZE,
    "busy": Direction.MAXIMIZE,
    "crowded": Direction.MAXIMIZE,
    "empty": Direction.MINIMIZE,
    "humid": Direction.MAXIMIZE,
    "damp": Direction.MAXIMIZE,
    "muggy": Direction.MAXIMIZE,
    "dry": Direction.MINIMIZE,
    "bright": Direction.MAXIMIZE,
    "dark": Direction.MINIMIZE,
}

#: A phrase that asks to AVOID something states the opposite preference from the word it
#: contains ("avoids the noisiest areas" is minimize, not maximize). Rather than guess which
#: way round, a phrase carrying one of these is left unmapped — the salvage below only runs
#: on plainly-worded phrases.
_AVOIDANCE_RE = re.compile(
    r"\b(?:avoid|avoids|avoiding|without|away from|free of|free from|less|least|"
    r"no|not|never|except|excluding|other than)\b",
    re.IGNORECASE,
)

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-]*")


def _direction_from_phrase_polarity(phrase: str) -> Optional[Direction]:
    """The end a phrase asks for, when one of its words carries its own polarity — or None.

    Used only where the model gave a modality but no usable direction. Three ways it declines
    rather than guesses, each closing a way this could answer the wrong question:

    * An avoidance phrasing is left alone. "less stuffy" and "stuffy" name the same modality
      and OPPOSITE ends, and `_AVOIDANCE_RE` is the existing test for that.
    * Two words that disagree return None. "warm but not too hot" carries both ends; picking
      one would be a coin toss wearing a number.
    * A word with no polarity of its own contributes nothing, which is what leaves
      "temperature" and "occupancy" refusable — those have no better end without a preference.
    """
    text = (phrase or "").strip()
    if not text or _AVOIDANCE_RE.search(text):
        return None
    found = {
        _LAY_POLARITY[_base_form(t)]
        for t in _WORD_RE.findall(text)
        if _base_form(t) in _LAY_POLARITY
    }
    return found.pop() if len(found) == 1 else None


def _constraint_from_phrase(phrase: str, known: set, decision: DecisionKind):
    """A lay word inside an UNMAPPED phrase, turned into the constraint it names — or None.

    BUG (row 117 of the 2026-09-17 stakeholder read): "I'm pregnant and overheating — where's
    the coolest place to work today?" came back as "I couldn't map part of your request
    (coolest place to work today; pregnant)". The compile had put the whole clause in
    `unmapped`, so nothing at all mapped and the question was declared unexecutable — a
    question whose every room this lane can rank on temperature.

    `_modality_from_lay_term` already translates a lay word the compile step mis-emitted as a
    MODALITY NAME; it was never applied to the phrases in `unmapped`, which is where a failed
    mapping actually lands. This is the same translation, one field over, and it is not a
    guess: it only succeeds when a word in the phrase is a lay term for a modality this
    building has, and when the direction comes either from the word itself or from a standard
    (`_infer_direction`). Anything phrased as an avoidance is left alone, because "avoids the
    noisiest areas" and "the noisiest areas" name the same modality and opposite ends.
    """
    text = (phrase or "").strip()
    if not text or _AVOIDANCE_RE.search(text):
        return None
    for token in _WORD_RE.findall(text):
        base = _base_form(token)
        modality = _modality_from_lay_term(token)
        if not modality or modality not in known:
            continue
        direction = _LAY_POLARITY.get(base) or _infer_direction(modality, decision, None)
        if direction is None:
            continue
        return Constraint(
            modality=modality,
            direction=direction,
            hardness=Hardness.SOFT,
            threshold=None,
            threshold_source=ThresholdSource.RECIPE,
            source_phrase=text,
        )
    return None


#: The v1 compile vocabulary. The v2 operations are NOT in it: a v1 compile (flag off, or no
#: catalogue) must read "aggregate_rank" exactly as it always did -- as an unknown decision --
#: and the v1 JSON schema built from this set must stay byte for byte what it was.
_DECISIONS = {d.value for d in DecisionKind if d not in V2_DECISIONS}
#: The facet compiler's vocabulary: every decision, the v2 operations included.
_FACET_DECISIONS = {d.value for d in DecisionKind}
_DIRECTIONS = {d.value for d in Direction}
_RELATIONS = {r.value for r in SpatialRelation}
_BASES = {b.value for b in TimeBasis}

_PROMPT = """You convert a building question into a JSON constraint program.
Map each requirement to EXACTLY one modality from this closed list (lay-term hints in parentheses):
{modality_lines}

Rules:
- Use ONLY listed modality names. If a requirement matches none, put it in "unmapped".
- direction: minimize | maximize | below | above | near_value
- hardness: "hard" only when the user makes it an absolute requirement; else "soft".
- threshold: number ONLY if the user stated one (never invent); then threshold_source="user".
- decision: select_one | rank_all | superlative | list_matching
- spatial relations: on_floor | near_amenity | in_space | adjacent_to
  (near_amenity anchors: DrinkingWater, ToiletFacility, StudyArea, Cafe, Lift)
- time.basis: now | window | forecast. "tomorrow"/"later" => forecast with horizon_hours.
  If a time phrase exists but you cannot interpret it, set basis="now" and copy it to "time_phrase_unclear".

Question: {query}

Return ONLY JSON:
{{"decision": "...", "constraints": [{{"phrase": "...", "modality": "...", "direction": "...",
  "hardness": "...", "threshold": null}}],
 "spatial": [{{"relation": "...", "anchor": "...", "phrase": "..."}}],
 "time": {{"basis": "now", "horizon_hours": null, "window_hours": null, "phrase": ""}},
 "time_phrase_unclear": "", "unmapped": ["..."]}}"""


# ── v2: facets of the graph ──────────────────────────────────────────────────────────────
#
# The v1 prompt above is NEVER edited for v2: with the flag off, or with no catalogue, the
# compiler sends `_PROMPT` byte for byte (pinned by a test against the unmodified code). The
# facet compiler is a second template that keeps every v1 rule and adds the facet section.

_FACET_OPERATORS = {o.value for o in FacetOperator}

_NUMERIC_OPERATORS = frozenset(
    {
        FacetOperator.BELOW,
        FacetOperator.ABOVE,
        FacetOperator.AT_LEAST,
        FacetOperator.AT_MOST,
        FacetOperator.MINIMIZE,
        FacetOperator.MAXIMIZE,
        FacetOperator.NEAR,
    }
)

#: Which operators fit which value type. Decided HERE, in code, and checked on every criterion
#: the model emits; the prompt merely tells the model the same table.
_OPERATORS_BY_VALUE_TYPE: Dict[str, frozenset] = {
    "number": _NUMERIC_OPERATORS,
    "integer": _NUMERIC_OPERATORS,
    "boolean": frozenset({FacetOperator.IS_TRUE, FacetOperator.IS_FALSE}),
    "enum": frozenset({FacetOperator.EQUALS, FacetOperator.ONE_OF}),
    "text": frozenset({FacetOperator.CONTAINS}),
}

#: Spellings a model reaches for that name an operator exactly. Not a guess: each maps to the
#: one operator with the same meaning.
_OPERATOR_ALIASES: Dict[str, str] = {
    "in": "one_of",
    "any_of": "one_of",
    "oneof": "one_of",
    "is": "equals",
    "eq": "equals",
    "=": "equals",
    "==": "equals",
    ">": "above",
    "<": "below",
    ">=": "at_least",
    "<=": "at_most",
    "gte": "at_least",
    "lte": "at_most",
    "min": "minimize",
    "minimise": "minimize",
    "max": "maximize",
    "maximise": "maximize",
    "true": "is_true",
    "false": "is_false",
    "has": "contains",
}

#: A sensor facet emitted as a facet criterion becomes the legacy Constraint, so the sensor
#: execution path is the v1 one. A yes/no reading has no threshold to invent: "true" is the
#: high end of a binary band and "false" the low end.
_SENSOR_DIRECTION: Dict[FacetOperator, Direction] = {
    FacetOperator.BELOW: Direction.BELOW,
    FacetOperator.AT_MOST: Direction.BELOW,
    FacetOperator.ABOVE: Direction.ABOVE,
    FacetOperator.AT_LEAST: Direction.ABOVE,
    FacetOperator.MINIMIZE: Direction.MINIMIZE,
    FacetOperator.MAXIMIZE: Direction.MAXIMIZE,
    FacetOperator.NEAR: Direction.NEAR_VALUE,
    FacetOperator.IS_TRUE: Direction.MAXIMIZE,
    FacetOperator.IS_FALSE: Direction.MINIMIZE,
}

#: The key the facet catalogue gives floor membership (facets._floor_facet).
_FLOOR_FACET = "spatial:floor"
#: How a period comparison may reduce the spaces of each period (C4): their mean or summed period
#: means, the lowest minimum or the highest maximum reading.
_PERIOD_STATS = (Statistic.MEAN, Statistic.SUM, Statistic.MIN, Statistic.MAX)
#: The executor's two availability checks, as facet keys (facets._EVENT_FACETS).
_FREE_WINDOW_FACET = "event:free_window"
_BOOKING_PRESSURE_FACET = "event:booking_pressure"
#: The value type of an event source (facets.INTERVAL; facets imports this module, so the value
#: is repeated here and a test pins the two together).
_INTERVAL = "interval"
#: "After" an event, when the question states no length: the hour after it ends. Declared in the
#: answer as a default, never presented as what was asked.
DEFAULT_LAG_MINUTES = 60.0
#: The longest "after" a relation reads: a day. Longer is not "after" an event but a period.
MAX_LAG_MINUTES = 24 * 60.0
#: How many event sources the prompt lists (the ones the question names first).
_MAX_EVENT_LINES = 12

#: How many facets the first compile is shown, and how many each inspection search returns.
FACET_SHORTLIST_K = 25
_INSPECT_K = 5
#: The model may ask to inspect at most this many facets or words per compile.
_MAX_INSPECT = 3
#: Unmapped terms searched per inspection round.
_MAX_INSPECT_TERMS = 6
#: Values shown for one inspected facet.
_MAX_VALUES_SHOWN = 40
#: THE BOUND ON THE AGENTIC STEP: at most this many recompiles after the first compile.
MAX_RECOMPILES = 2
#: ...and none once the compile has taken this many seconds (`_compile_with_facets`).
INSPECTION_BUDGET_S = 45.0

_PROMPT_FACETS = """You convert a building question into a JSON constraint program.
Map each sensed requirement to EXACTLY one modality from this closed list (lay-term hints in parentheses):
{modality_lines}

Facets you may use: facts the building RECORDS about its spaces (registers, model properties,
bookings). One per line as key | label | value type | unit | values:
{facet_lines}

Rules:
- A requirement a listed modality MEASURES goes in "constraints" (a sensor reading always wins).
  A requirement only a facet records goes in "facet_criteria". Never put one requirement in both.
- Use ONLY listed modality names and ONLY listed facet keys. If a requirement matches neither, put it in "unmapped".
- direction: minimize | maximize | below | above | near_value
- facet operator, by the facet's value type:
  number / integer: below | above | at_least | at_most | minimize | maximize | near
  boolean: is_true | is_false
  enum: equals | one_of (copy the value(s) exactly from the facet's listed values)
  text: contains
  event: free_for (value = the number of hours the space must stay free)
- hardness: "hard" only when the user makes it an absolute requirement; else "soft".
- threshold / value: a number ONLY if the user stated one (never invent); then threshold_source="user".
- record_group: criteria that must hold for ONE record (for example one device that is a projector
  AND is ready) share the same short record_group label; otherwise leave it empty.
- inspect: up to 3 facet keys or words whose recorded values you need before deciding; leave it
  empty when the lists above are enough.
- decision: select_one | rank_all | superlative | list_matching | aggregate_rank | compare_facets |
  period_compare | relate
- aggregate_rank: the question ranks GROUPS of spaces (floors, the whole building, kinds of room) by
  one figure per group: "which floor has the fewest people", "the largest gap between the warmest and
  coolest room on each floor", "how evenly is CO2 spread across the floors". Fill "aggregate":
  facet = a modality name or facet key (empty only to count spaces); group_by: floor | building |
  space_kind; statistic: mean | sum | min | max | range | stdev | count | count_above | count_below;
  threshold = a number ONLY for count_above / count_below and only one the user stated;
  order: asc (fewest / lowest / smallest first) | desc (most / highest / largest first).
  sum is for amounts that add up (people, seats); mean / min / max for levels (temperature, CO2);
  range = the gap between a group's highest and lowest space; stdev = how evenly it is spread.
- compare_facets: the question sets TWO numeric facts about the same spaces side by side: "the
  occupancy versus the capacity in each room", "is the building over its design occupancy". Fill
  "compare": facet_a and facet_b (modality names or facet keys, in the question's order);
  relation: ratio | difference | exceeds (exceeds = facet_a is above facet_b); total: true only when
  the question is about the whole building rather than each space.
- period_compare: the question compares ONE measured modality across TWO periods: "this week against
  last week", "today versus yesterday", "weekdays against weekends". Fill "period": facet = a modality
  name; statistic: mean | sum | min | max (how the spaces are reduced per period); group_by: floor |
  building | space_kind, or null. Never write dates: the periods are read from the question in code.
- relate: the question asks how ONE measured modality behaves during, after or alongside something
  else in the same spaces: "is CO2 higher during timetabled sessions", "does noise rise in the hour
  after access events", "when occupancy goes up does CO2 go up", "what happens to temperature while
  the window is open". Fill "relate": series = the modality asked about; relation: during | after |
  co_movement; events = an event key from the list below (with during or after), or other_series = a
  modality (with co_movement, or with during when it is a yes/no reading such as a window being
  open); group_by: floor | building | space_kind, or null. Never write a lag, a period or dates: they
  are read from the question in code. The answer is co-occurrence, never a cause.
- With aggregate_rank, compare_facets, period_compare or relate, "constraints" and
  "facet_criteria" only NARROW which spaces count ("bookable", "above 1000 ppm"); never repeat the
  operation's facet there. Otherwise leave "aggregate", "compare", "period" and "relate" null.
- spatial relations: on_floor | near_amenity | in_space | adjacent_to
  (near_amenity anchors: DrinkingWater, ToiletFacility, StudyArea, Cafe, Lift)
- time.basis: now | window | forecast. "tomorrow"/"later" => forecast with horizon_hours.
  If a time phrase exists but you cannot interpret it, set basis="now" and copy it to "time_phrase_unclear".

Recorded events (only for relate), one per line as key | label | where | recorded:
{event_lines}
{inspection_block}
Question: {query}

Return ONLY JSON:
{{"decision": "...", "constraints": [{{"phrase": "...", "modality": "...", "direction": "...",
  "hardness": "...", "threshold": null}}],
 "facet_criteria": [{{"phrase": "...", "facet": "...", "operator": "...", "value": null,
  "hardness": "...", "record_group": ""}}],
 "aggregate": null, "compare": null, "period": null, "relate": null,
 "spatial": [{{"relation": "...", "anchor": "...", "phrase": "..."}}],
 "time": {{"basis": "now", "horizon_hours": null, "window_hours": null, "phrase": ""}},
 "time_phrase_unclear": "", "unmapped": ["..."], "inspect": []}}"""


def facets_enabled() -> bool:
    """``ARBITER_FACETS_ENABLED`` — read at call time, so a test or an ablation run can flip it."""
    try:
        from shared.config import settings

        return bool(getattr(settings, "ARBITER_FACETS_ENABLED", True))
    except Exception:  # pragma: no cover - settings always import in this tree
        return False


def catalogue_fingerprint(catalogue: "FacetCatalogue") -> str:
    """Hash of every facet key and its rung on the availability ladder.

    In the compile cache key, so a catalogue that gains, loses or re-grades a facet cannot
    replay a plan compiled against the old one.
    """
    import hashlib

    material = "\n".join(sorted(f"{f.key}={f.status}" for f in catalogue))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


#: The shape `_parse_compiled` reads, as a JSON schema the provider can enforce (ARCH-A1).
#:
#: DERIVED FROM THE PARSER, NOT FROM `_PROMPT`. The prose above and the code below drifted
#: apart once already; a schema copied from the prose would preserve the drift and call it a
#: contract. Every enum here comes from the same `_DECISIONS` / `_DIRECTIONS` / `_RELATIONS` /
#: `_BASES` sets the parser validates against, which come in turn from the CQ-IR enums — so
#: the schema cannot fall behind the IR without the IR moving too.
#:
#: What is deliberately NOT constrained:
#:   * `modality` and `anchor` are free strings. They are BUILDING-SPECIFIC — the closed list
#:     is the active building's modality set, which belongs in the prompt and in the parser's
#:     `known` check, never in a schema literal. `unmapped` is the model's escape hatch and
#:     an enum would take it away.
#:   * Nothing but `decision` is required, and no object is closed. The flag may only ADD
#:     guarantees: a response this schema rejects must not be one the current path accepts.
#:
#: What IS constrained is exactly the set of fields whose bad values the parser currently
#: turns into an AmbiguitySignal — an unknown direction, an unknown relation, an unknown
#: basis. Those are the compile failures a user experiences as "I couldn't map part of
#: your request".
def _cqir_schema(facets: bool = False) -> Dict[str, object]:
    """The CQ-IR compile contract as a JSON schema (built fresh; callers may bind it).

    ``facets=True`` adds the v2 fields the facet parser reads (``facet_criteria``, ``inspect``),
    derived the same way: the operator enum is the IR's own ``FacetOperator`` set, and the
    facet KEY stays a free string because it is the active building's vocabulary. With
    ``facets=False`` the schema is the v1 one, byte for byte.
    """
    _nullable_number = {"type": ["number", "null"]}
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": sorted(_DECISIONS)},
            "constraints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "phrase": {"type": "string"},
                        "modality": {"type": "string"},
                        "direction": {"type": "string", "enum": sorted(_DIRECTIONS)},
                        "hardness": {"type": "string", "enum": ["hard", "soft"]},
                        "threshold": _nullable_number,
                    },
                    "required": ["modality", "direction"],
                },
            },
            "spatial": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "relation": {"type": "string", "enum": sorted(_RELATIONS)},
                        "anchor": {"type": "string"},
                        "phrase": {"type": "string"},
                    },
                    "required": ["relation"],
                },
            },
            "time": {
                "type": "object",
                "properties": {
                    "basis": {"type": "string", "enum": sorted(_BASES)},
                    "horizon_hours": _nullable_number,
                    "window_hours": _nullable_number,
                    "phrase": {"type": "string"},
                },
                "required": ["basis"],
            },
            "time_phrase_unclear": {"type": "string"},
            "unmapped": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["decision"],
    }
    if facets:
        properties = schema["properties"]
        properties["facet_criteria"] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "phrase": {"type": "string"},
                    "facet": {"type": "string"},
                    "operator": {"type": "string", "enum": sorted(_FACET_OPERATORS)},
                    "value": {
                        "type": ["number", "string", "boolean", "array", "null"],
                        "items": {"type": "string"},
                    },
                    "hardness": {"type": "string", "enum": ["hard", "soft"]},
                    "record_group": {"type": ["string", "null"]},
                },
                "required": ["facet", "operator"],
            },
        }
        properties["inspect"] = {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": _MAX_INSPECT,
        }
        # The operations (C3, C2, C4): enums from the IR's own types, the facet KEYS left open.
        properties["decision"] = {"type": "string", "enum": sorted(_FACET_DECISIONS)}
        properties["aggregate"] = {
            "type": ["object", "null"],
            "properties": {
                "phrase": {"type": "string"},
                "facet": {"type": ["string", "null"]},
                "group_by": {"type": "string", "enum": sorted(g.value for g in GroupBy)},
                "statistic": {"type": "string", "enum": sorted(s.value for s in Statistic)},
                "threshold": _nullable_number,
                "order": {"type": "string", "enum": sorted(o.value for o in SortOrder)},
                "top_k": {"type": ["integer", "null"]},
            },
            "required": ["statistic"],
        }
        properties["compare"] = {
            "type": ["object", "null"],
            "properties": {
                "phrase": {"type": "string"},
                "facet_a": {"type": "string"},
                "facet_b": {"type": "string"},
                "relation": {"type": "string", "enum": sorted(r.value for r in CompareRelation)},
                "total": {"type": ["boolean", "null"]},
            },
            "required": ["facet_a", "facet_b"],
        }
        # C4: the periods are deliberately NOT in the schema -- they are read from the question
        # by requested_interval, so there is no date field for the model to fill in.
        properties["period"] = {
            "type": ["object", "null"],
            "properties": {
                "phrase": {"type": "string"},
                "facet": {"type": "string"},
                "statistic": {"type": "string", "enum": sorted(s.value for s in _PERIOD_STATS)},
                "group_by": {
                    "type": ["string", "null"],
                    "enum": sorted(g.value for g in GroupBy) + [None],
                },
            },
            "required": ["facet"],
        }
        # C5: no lag, window or date field either -- all three are read from the question in code
        # (`_relation_window`, `_stated_lag_minutes`), so there is nothing for the model to invent.
        properties["relate"] = {
            "type": ["object", "null"],
            "properties": {
                "phrase": {"type": "string"},
                "series": {"type": "string"},
                "relation": {"type": "string", "enum": sorted(r.value for r in RelationKind)},
                "events": {"type": ["string", "null"]},
                "other_series": {"type": ["string", "null"]},
                "group_by": {
                    "type": ["string", "null"],
                    "enum": sorted(g.value for g in GroupBy) + [None],
                },
            },
            "required": ["series"],
        }
    return schema


CQIR_SCHEMA_NAME = "cqir_compile"


def _modality_lines(modalities: List[ModalitySpec]) -> str:
    lines = []
    for spec in modalities:
        hint = _LAY_HINTS.get(spec.name, "")
        lines.append(f"- {spec.name}" + (f" ({hint})" if hint else ""))
    return "\n".join(lines)


def _normalise_question(query: str) -> str:
    """Collapse the incidental differences between two askings of one question."""
    return " ".join((query or "").lower().split()).strip(" ?!.")


def _compile_cache_key(
    query: str,
    modalities: List[ModalitySpec],
    catalogue: Optional["FacetCatalogue"] = None,
) -> str:
    """cqir_compile:<sha256> over everything that can change the compiled plan.

    Provider AND model are in the key, deliberately. A key on the question alone
    would hand model B the plan model A compiled, and the multi-model invariance
    benchmark would then be measuring this cache rather than the models -- it would
    report a perfect score for the very property it exists to test. The embedding
    cache already keys on text+provider+model for the same reason.

    The modality set is in the key because a building that gains a modality can
    legitimately compile the same words differently; the prompt is in it because
    editing the prompt is editing the compiler.

    v2: with a facet ``catalogue`` the key hashes the FACET prompt template instead and adds
    the catalogue's fingerprint (facet keys + statuses), so a changed catalogue invalidates
    every compile made against the old one. Without a catalogue the key is the v1 key, byte
    for byte.
    """
    import hashlib

    from shared.config import settings

    provider = str(getattr(settings, "MODEL_PROVIDER", "") or "")
    if provider == "openai":
        model = str(getattr(settings, "OPENAI_MODEL", "") or "")
    else:
        model = str(getattr(settings, "OLLAMA_MODEL", "") or "")

    template = _PROMPT if catalogue is None else _PROMPT_FACETS
    parts = [
        _normalise_question(query),
        ",".join(sorted(m.name for m in modalities)),
        provider,
        model,
        hashlib.sha256(template.encode("utf-8")).hexdigest()[:16],
    ]
    # A schema-constrained compile and a free-text one are different compilers and must not
    # share a cache entry — otherwise turning the flag on replays the plans the old path
    # produced and the acceptance run measures the cache. Appended only when the flag is ON,
    # so every key in a flag-OFF tree is byte-for-byte what it was.
    if getattr(settings, "STRUCTURED_PLAN_ENABLED", False):
        parts.append("structured")
    if catalogue is not None:
        parts.append("facets:" + catalogue_fingerprint(catalogue))
    material = "␟".join(parts)
    return f"cqir_compile:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


#: How long a compiled plan stays valid. A question's meaning does not change, but
#: the building's modality set can, and that is already in the key -- this is a
#: bound on stale prompt-era entries rather than a correctness mechanism.
_COMPILE_CACHE_TTL = 86_400


def _cache_enabled() -> bool:
    """``CQIR_COMPILE_CACHE=false`` turns the cache off for the whole process.

    The multi-model benchmark needs this. Cross-model comparison is safe with the
    cache ON -- the model is in the key, so each arm compiles for itself -- but the
    NOISE FLOOR arm, the same model run twice, would come back 8/8 by construction
    and mean nothing. The two numbers answer different questions and must be measured
    differently:

      cache OFF  what the compiler does      -- the honest wobble, 3/8 when measured
      cache ON   what a user experiences     -- a repeat replays its own plan

    Reporting the second as if it were the first is how a fix becomes a fiction.
    """
    import os

    return os.getenv("CQIR_COMPILE_CACHE", "true").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _parse_compiled(
    raw: str,
    query: str,
    known: set,
    catalogue: Optional["FacetCatalogue"] = None,
    notes: Optional[Dict[str, Any]] = None,
) -> CQIR:
    """Validate one raw compiler response into a CQIR.

    Split out of ``compile_query`` so the cache-hit path and the fresh-compile path
    run the SAME validation. Caching a parsed object instead would let a stored plan
    drift out of step with the parser that produced it; caching the text and
    re-validating it cannot.

    Every field is checked against the closed vocabulary here -- anything unknown
    becomes an AmbiguitySignal, never a guess.

    v2: with a facet ``catalogue`` the facet fields are validated too (`_apply_facets`), after
    every v1 field has been read exactly as before. ``notes`` collects what the inspection
    step needs (the model's inspect requests, facets whose values failed validation).
    """
    match = re.search(r"\{[\s\S]*\}", raw or "")
    if not match:
        return CQIR(
            decision=DecisionKind.SELECT_ONE,
            raw_query=query,
            signals=[AmbiguitySignal(kind="vague", phrase=query, note="no JSON in LLM output")],
        )
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return CQIR(
            decision=DecisionKind.SELECT_ONE,
            raw_query=query,
            signals=[AmbiguitySignal(kind="vague", phrase=query, note=f"bad JSON: {exc}")],
        )

    signals: List[AmbiguitySignal] = []

    decision_raw = str(data.get("decision", "")).strip().lower()
    decision = DecisionKind(decision_raw) if decision_raw in _DECISIONS else DecisionKind.SELECT_ONE

    constraints: List[Constraint] = []
    for c in data.get("constraints", []) or []:
        modality = str(c.get("modality", "")).strip().lower()
        phrase = str(c.get("phrase", "")).strip()
        if modality not in known:
            # An unknown modality may be a lay word the compile step failed to translate.
            # Translating it here is not a guess: it only succeeds when the word maps to a
            # modality this building actually has.
            _mapped = _modality_from_lay_term(modality)
            if _mapped and _mapped in known:
                logger.info(f"[compiler] '{modality}' resolved to modality '{_mapped}'")
                modality = _mapped
        if modality not in known:
            signals.append(
                AmbiguitySignal(
                    kind="unmapped_term",
                    phrase=phrase or modality,
                    note=f"'{modality}' is not a known modality",
                )
            )
            continue
        threshold = c.get("threshold")
        try:
            threshold = float(threshold) if threshold is not None else None
        except (TypeError, ValueError):
            threshold = None
        direction_raw = str(c.get("direction", "")).strip().lower()
        if direction_raw not in _DIRECTIONS:
            inferred = _infer_direction(modality, decision, threshold)
            if inferred is None:
                # Before giving up, read the PHRASE the constraint came from. `_LAY_POLARITY`
                # already knows that "warm" is the high end of temperature and "stuffy" the
                # high end of CO2; the salvage below applies it to phrases the model left in
                # `unmapped`, and it was never applied here, where a mapped constraint arrives
                # with its direction missing. The answer was in the signal's own phrase field.
                #
                # WHY THIS IS A ROBUSTNESS FIX AND NOT NEW LICENCE TO GUESS. Measured
                # 2026-09-23: "is anywhere both hot and noisy" compiled with both directions
                # and ranked rooms correctly, while "which rooms are both warm and stuffy"
                # emitted direction "none" for both and was refused -- same class of word, the
                # same two modalities, different provider output on the day. A refusal
                # manufactured out of temp-0 wobble is not honesty. `_infer_direction` still
                # owns every word that does NOT carry its own polarity ("temperature",
                # "occupancy"), and still refuses those, because there the better end really
                # is a preference and inventing one would answer a question nobody asked.
                inferred = _direction_from_phrase_polarity(phrase)
                if inferred is not None:
                    logger.info(
                        f"[compiler] direction for {modality} read from the phrase "
                        f"{phrase!r} -> {inferred.value}"
                    )
            if inferred is None:
                signals.append(
                    AmbiguitySignal(
                        kind="vague",
                        phrase=phrase,
                        note=f"unknown direction '{direction_raw}' for {modality}",
                    )
                )
                continue
            direction_raw = inferred.value
        constraints.append(
            Constraint(
                modality=modality,
                direction=Direction(direction_raw),
                hardness=(
                    Hardness.HARD if str(c.get("hardness", "")).lower() == "hard" else Hardness.SOFT
                ),
                threshold=threshold,
                threshold_source=(
                    ThresholdSource.USER if threshold is not None else ThresholdSource.RECIPE
                ),
                source_phrase=phrase,
            )
        )

    _fold_unbounded_threshold_direction(constraints, decision)
    constraints = _fold_air_quality(constraints)

    # This was a local pattern anchoring on `^anywhere$`, so it matched the bare word and not
    # "anywhere IN THE BUILDING" — the ordinary way of saying it. One decision, one owner:
    # `_is_whole_building_scope` now answers it for the spatial anchor and the unmapped list
    # alike, and knows the building's own name from its config (TODO-629).
    spatial: List[SpatialQualifier] = []
    for s in data.get("spatial", []) or []:
        # normalize before validating: models write "on floor" / "on-floor" /
        # "NEAR_AMENITY" for the same relation — spelling is not ambiguity
        relation_raw = (
            str(s.get("relation", "")).strip().lower().replace(" ", "_").replace("-", "_")
        )
        anchor = str(s.get("anchor", "")).strip()
        # whole-building scope is the DEFAULT scope, not a qualifier — 'in the
        # whole building' must never become an unresolved anchor (BUG-163 tail)
        if _is_whole_building_scope(anchor) or _is_whole_building_scope(
            re.sub(
                r"^(?:in|across|of|for)\s+",
                "",
                str(s.get("phrase", "")).strip(),
                flags=re.IGNORECASE,
            )
        ):
            continue
        if relation_raw == "on_floor" and not anchor:
            # some models put the floor into the phrase instead of the anchor
            m = re.search(r"(?:floor|level)\s*([\w.]+)", str(s.get("phrase", "")), re.IGNORECASE)
            if m:
                anchor = m.group(1)
        if relation_raw not in _RELATIONS or not anchor:
            # AN EMPTY ANCHOR IS NO ANCHOR, NOT AN AMBIGUOUS ONE (BUG-755).
            #
            # Measured live 2026-09-17: "I'm pregnant and overheating — where's the coolest
            # place to work today?" compiled PERFECTLY (temperature, minimize) and was still
            # refused with "I couldn't map part of your request". The model had emitted
            # `in_space` with anchor "" for the phrase "coolest place to work today" — it
            # named no space, because the question names no space — and that became an
            # `unresolved_anchor` signal. Two things then followed: `is_executable()` is false
            # while ANY signal stands, and `clarify_policy.absorb_unmapped`, which exists to
            # drop an unsensable extra like "pregnant" when real constraints mapped, returns
            # early whenever a non-unmapped signal remains. One phantom anchor therefore
            # blocked a ranking this lane can do over every room in the building.
            #
            # A phrase that names no space at all is the DEFAULT scope, exactly as
            # "in the whole building" is. A phrase that does look like a named space
            # (a digit, as in "2.01", or a capitalised proper name) still raises the signal,
            # so a real "which room did you mean?" is never silently widened to the building.
            # Only for a relation this lane understands: an unknown relation ("teleport") is a
            # compile fault and stays a signal whatever its anchor.
            _phrase = str(s.get("phrase", ""))
            if relation_raw in _RELATIONS and not anchor and not _looks_like_a_named_space(_phrase):
                logger.info(
                    f"[compiler] '{_phrase}' names no space — whole-building scope, not an "
                    "unresolved anchor"
                )
                continue
            signals.append(
                AmbiguitySignal(
                    kind="unresolved_anchor",
                    phrase=_phrase,
                    note=f"relation='{relation_raw}' anchor='{anchor}'",
                )
            )
            continue
        spatial.append(
            SpatialQualifier(
                relation=SpatialRelation(relation_raw),
                anchor=anchor,
                source_phrase=str(s.get("phrase", "")),
            )
        )

    t = data.get("time", {}) or {}
    basis_raw = str(t.get("basis", "now")).strip().lower()
    basis = TimeBasis(basis_raw) if basis_raw in _BASES else TimeBasis.NOW
    unclear = str(data.get("time_phrase_unclear", "")).strip()
    time_spec = TimeSpec(
        basis=basis,
        horizon_hours=_num(t.get("horizon_hours")),
        window_hours=_num(t.get("window_hours")),
        unparseable=bool(unclear),
        source_phrase=str(t.get("phrase", "")) or unclear,
    )
    _fold_deterministic_horizon(time_spec, query)
    # The calendar day runs FIRST and unconditionally; the hours table only sees phrases
    # that are genuinely durations. Either one resolving the anchor clears the clarify
    # signal — BUG-183 was a facility manager told "yesterday" could not be mapped.
    resolved_day = _fold_named_calendar_day(time_spec, query)
    # Only ONE fold may own a phrase. Without this the hours table could still overwrite a
    # resolved interval's derived span with its own number, leaving a spec whose two halves
    # described different lengths of time — the same two-sources-of-truth failure, inside a
    # single object.
    resolved_past = resolved_day or _fold_deterministic_past_window(time_spec, query, unclear)
    if unclear and not (resolved_day or resolved_past):
        signals.append(AmbiguitySignal(kind="unparseable_time", phrase=unclear))
    for u in data.get("unmapped", []) or []:
        phrase = str(u).strip()
        if not phrase:
            continue
        # "ANYWHERE in the building" is not a place this compiler failed to resolve — it is
        # the ABSENCE of a place, which is already this lane's default scope (TODO-629).
        # Recorded as unmapped it made the whole query unexecutable, and the building
        # answered "I couldn't map part of your request (anywhere in the building) — could
        # you rephrase or drop that part?" to a question whose every room it could rank.
        # Asking someone to drop the only word that said "look everywhere" is the wrong
        # half to drop.
        if _is_whole_building_scope(phrase):
            logger.info(f"[compiler] '{phrase}' means the whole building — no spatial anchor")
            continue
        signals.append(AmbiguitySignal(kind="unmapped_term", phrase=phrase))

    # NOTHING MAPPED IS THE ONLY CASE THIS RUNS IN.
    #
    # When something else mapped, the unmapped extras are already dropped and DECLARED by
    # `clarify_policy.absorb_unmapped`, and a ranking that works today must not silently gain
    # a criterion. It is the all-unmapped case that is a wrongful denial: the question is
    # rejected whole although one of its words names a modality this building measures.
    if not constraints:
        _kept: List[AmbiguitySignal] = []
        for s in signals:
            salvaged = (
                _constraint_from_phrase(s.phrase, known, decision)
                if s.kind == "unmapped_term"
                else None
            )
            if salvaged is not None and not any(
                c.modality == salvaged.modality for c in constraints
            ):
                logger.info(
                    f"[compiler] '{s.phrase}' names {salvaged.modality} "
                    f"({salvaged.direction.value}) — mapped rather than refused"
                )
                constraints.append(salvaged)
            else:
                _kept.append(s)
        signals = _kept

    if not constraints and not any(s.kind == "unmapped_term" for s in signals):
        signals.append(AmbiguitySignal(kind="vague", phrase=query, note="no mappable criteria"))

    compiled = CQIR(
        decision=decision,
        constraints=constraints,
        spatial=spatial,
        time=time_spec,
        signals=signals,
        event_criteria=_fold_event_criteria(query),
        raw_query=query,
    )
    if catalogue is not None:
        compiled = _apply_facets(compiled, data, query, known, catalogue, notes)
    return compiled


# ── v2: validating facet criteria ────────────────────────────────────────────────────────

#: Number words a question uses for a quantity. Generic English; compounds such as "twenty
#: four" are summed below.
_NUMBER_WORD_VALUES: Dict[str, float] = {
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
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
    "dozen": 12,
}
_TENS = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}
_DIGITS_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
_WORDS_RE = re.compile(r"[a-z]+")


def _stated_numbers(query: str) -> Set[float]:
    """Every number the question itself states, in digits or in words."""
    text = (query or "").lower()
    found: Set[float] = {float(m) for m in _DIGITS_RE.findall(text)}
    words = _WORDS_RE.findall(text)
    for i, word in enumerate(words):
        value = _NUMBER_WORD_VALUES.get(word)
        if value is None:
            continue
        found.add(float(value))
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if word in _TENS and nxt in _NUMBER_WORD_VALUES and _NUMBER_WORD_VALUES[nxt] < 10:
            found.add(float(value + _NUMBER_WORD_VALUES[nxt]))
    return found


def _user_stated(number: float, query: str) -> bool:
    """True when the question states this number. The compiler never accepts one it invented."""
    return any(abs(number - n) < 1e-9 for n in _stated_numbers(query))


def _as_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        return float(match.group(0)) if match else None
    return None


def _as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in ("true", "yes", "1"):
        return True
    if text in ("false", "no", "0"):
        return False
    return None


def _normalise_operator(raw: Any) -> str:
    text = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    return _OPERATOR_ALIASES.get(text, text)


def _norm_text(text: Any) -> str:
    return " ".join(str(text or "").lower().split())


def value_set_complete(facet: "Facet") -> bool:
    """True when the catalogue holds a facet's WHOLE value set, so a value can be checked.

    Only an enum qualifies, and only when its examples were not cut: the catalogue keeps at
    most ``ENUM_MAX_VALUES`` values and shortens a long one to an excerpt.
    """
    from orchestrator.services.deliberation.facets import ENUM_MAX_VALUES

    if facet.value_type != "enum" or not facet.examples:
        return False
    if len(facet.examples) >= ENUM_MAX_VALUES:
        return False
    return not any(str(v).endswith("…") for v in facet.examples)


def _match_enum(value: str, allowed: Sequence[str]) -> Optional[str]:
    """The building's own spelling of ``value`` among ``allowed``, case-insensitively, or None."""
    wanted = _norm_text(value)
    for candidate in allowed:
        if _norm_text(candidate) == wanted:
            return str(candidate)
    return None


def _floor_named(value: str, floors: Sequence[str]) -> bool:
    """True when ``value`` names one of the building's floors (any spelling of its number)."""
    from orchestrator.services.deliberation.capability_schema import _norm_floor

    if _match_enum(value, floors) is not None:
        return True
    return _norm_floor(str(value), list(floors)) is not None


@dataclass
class _FacetParse:
    """What one emitted facet criterion became: a criterion, a legacy form, or a signal."""

    kind: str  # criterion | constraint | event | spatial | signal
    payload: Any
    #: A facet whose recorded values the inspection step should read (a value failed).
    inspect_key: Optional[str] = None


def _facet_signal(kind: str, phrase: str, note: str, inspect_key: Optional[str] = None):
    return _FacetParse("signal", AmbiguitySignal(kind=kind, phrase=phrase, note=note), inspect_key)


def _facet_by_short_name(text: str, catalogue: "FacetCatalogue") -> Optional["Facet"]:
    """A facet the model named by its FIELD alone or by its label -- when exactly one matches.

    The prompt lists full keys ("record:WorkspaceProfile.seatCount") and the model sometimes
    answers with the field ("seatCount"). Measured live, 2026-10-08: "Are any meeting rooms over
    their seating capacity right now?" compiled to a correct occupancy-versus-seatCount comparison
    that the parser then threw away as "'seatCount' is not a facet this building holds", and the
    question fell back to a selection. Space facets are preferred, and two candidates are refused
    rather than guessed between (two registers with a ``status`` field must not be confused).
    """
    wanted = (text or "").strip().lower()
    if not wanted:
        return None
    hits = [
        f
        for f in catalogue
        if f.key.lower().rsplit(".", 1)[-1] == wanted
        or f.key.lower().split(":", 1)[-1] == wanted
        or (f.label or "").strip().lower() == wanted
    ]
    pool = [f for f in hits if f.entity_type == "space"] or hits
    return pool[0] if len(pool) == 1 else None


def _facet_item(
    item: Dict[str, Any], query: str, known: set, catalogue: "FacetCatalogue"
) -> _FacetParse:
    """Validate ONE emitted facet criterion against the catalogue. Never a guess.

    The facet must be a catalogue key; the operator must fit the facet's value type; an enum
    value must be one the building records (when the catalogue holds the whole set); a number
    must be one the question states. A sensor facet becomes the legacy Constraint, an
    availability facet folds onto the executor's check, and a single hard floor becomes the
    v1 floor scope -- so those parts run exactly as v1 runs them.
    """
    phrase = str(item.get("phrase", "") or "").strip()
    key = str(item.get("facet", "") or "").strip()
    operator = _normalise_operator(item.get("operator"))
    value = item.get("value")
    hardness = Hardness.HARD if _norm_text(item.get("hardness")) == "hard" else Hardness.SOFT
    group = str(item.get("record_group") or "").strip() or None

    facet = catalogue.get(key)
    if facet is None and key.lower() in known:
        facet = catalogue.get(f"sensor:{key.lower()}")
    if facet is None:
        facet = _facet_by_short_name(key, catalogue)
    if facet is None:
        return _facet_signal(
            "unmapped_term", phrase or key, f"'{key}' is not a facet this building holds"
        )
    if facet.entity_type != "space":
        return _facet_signal(
            "unmapped_term",
            phrase or facet.label,
            f"'{facet.label}' describes a {facet.entity_type}, not a space",
        )
    if operator not in _FACET_OPERATORS:
        return _facet_signal(
            "invalid_facet", phrase or facet.label, f"'{operator}' is not an operator here"
        )
    op = FacetOperator(operator)
    if facet.source_kind == "sensor":
        return _sensor_facet(facet, op, value, hardness, phrase, query, known)
    if facet.source_kind == "event":
        return _event_facet(facet, op, value, hardness, phrase, query)
    if facet.key == _FLOOR_FACET:
        return _floor_facet(facet, op, value, hardness, phrase)
    return _recorded_facet(facet, op, value, hardness, group, phrase, query)


def _sensor_facet(facet, op, value, hardness, phrase, query, known) -> _FacetParse:
    modality = facet.modality or facet.key.split(":", 1)[-1]
    if modality not in known:
        return _facet_signal(
            "unmapped_term", phrase or modality, f"'{modality}' is not a known modality"
        )
    direction = _SENSOR_DIRECTION.get(op)
    if direction is None:
        return _facet_signal(
            "invalid_facet", phrase or facet.label, f"'{op.value}' does not apply to a reading"
        )
    threshold = None
    if op in (
        FacetOperator.BELOW,
        FacetOperator.ABOVE,
        FacetOperator.AT_LEAST,
        FacetOperator.AT_MOST,
        FacetOperator.NEAR,
    ):
        number = _as_number(value)
        if number is not None and _user_stated(number, query):
            threshold = number
    return _FacetParse(
        "constraint",
        Constraint(
            modality=modality,
            direction=direction,
            hardness=hardness,
            threshold=threshold,
            threshold_source=(
                ThresholdSource.USER if threshold is not None else ThresholdSource.RECIPE
            ),
            source_phrase=phrase,
        ),
    )


def _event_facet(facet, op, value, hardness, phrase, query) -> _FacetParse:
    if facet.key == _FREE_WINDOW_FACET:
        if op not in (FacetOperator.FREE_FOR, FacetOperator.IS_TRUE):
            return _facet_signal(
                "invalid_facet",
                phrase or facet.label,
                f"'{op.value}' does not apply to availability; it takes free_for <hours>",
            )
        hours = _as_number(value)
        if hours is not None and hours > 0 and _user_stated(hours, query):
            source = ThresholdSource.USER
            hours = max(0.25, min(24.0, hours))
        else:
            # The same default the v1 fold uses for "free now", DECLARED by the answer.
            hours, source = 1.0, ThresholdSource.DEFAULT
        return _FacetParse(
            "criterion",
            FacetCriterion(
                facet=facet.key,
                operator=FacetOperator.FREE_FOR,
                value=hours,
                hardness=hardness,
                threshold_source=source,
                source_phrase=phrase,
            ),
        )
    if facet.key == _BOOKING_PRESSURE_FACET and op == FacetOperator.MINIMIZE:
        return _FacetParse("event", EventCriterion(kind="low_booking_pressure"))
    return _facet_signal(
        "invalid_facet",
        phrase or facet.label,
        f"'{op.value}' on {facet.label} is not a check this lane runs",
    )


def _floor_facet(facet, op, value, hardness, phrase) -> _FacetParse:
    values = value if isinstance(value, list) else [value]
    values = [str(v).strip() for v in values if str(v or "").strip()]
    if op not in (FacetOperator.EQUALS, FacetOperator.ONE_OF) or not values:
        return _facet_signal(
            "invalid_facet", phrase or facet.label, "a floor criterion names one or more floors"
        )
    for v in values:
        if not _floor_named(v, facet.examples):
            return _facet_signal(
                "unresolved_anchor",
                phrase or v,
                f"no floor of this building is called '{v}'",
            )
    if len(values) == 1 and hardness == Hardness.HARD:
        # One required floor is the v1 floor SCOPE, resolved by admission exactly as before.
        return _FacetParse(
            "spatial",
            SpatialQualifier(
                relation=SpatialRelation.ON_FLOOR, anchor=values[0], source_phrase=phrase
            ),
        )
    return _FacetParse(
        "criterion",
        FacetCriterion(
            facet=facet.key,
            operator=FacetOperator.ONE_OF,
            value=values,
            hardness=hardness,
            source_phrase=phrase,
        ),
    )


def _recorded_facet(facet, op, value, hardness, group, phrase, query) -> _FacetParse:
    """A record field, a TTL property of a space, capacity, or a route fact reaching a space."""
    value_type = facet.value_type
    # Two spellings of one meaning, normalised rather than refused.
    if value_type == "boolean" and op == FacetOperator.EQUALS and _as_bool(value) is not None:
        op, value = (FacetOperator.IS_TRUE if _as_bool(value) else FacetOperator.IS_FALSE), None
    if value_type == "enum" and op == FacetOperator.EQUALS and isinstance(value, list):
        op = FacetOperator.ONE_OF
    allowed = _OPERATORS_BY_VALUE_TYPE.get(value_type, frozenset())
    if op not in allowed:
        fits = ", ".join(sorted(o.value for o in allowed)) or "none yet"
        return _facet_signal(
            "invalid_facet",
            phrase or facet.label,
            f"'{op.value}' does not apply to {facet.label} ({value_type} values; fits: {fits})",
            inspect_key=facet.key,
        )
    source = ThresholdSource.USER
    if value_type in ("number", "integer"):
        if op in SCORING_OPERATORS and op != FacetOperator.NEAR:
            value, source = None, ThresholdSource.DEFAULT
        else:
            number = _as_number(value)
            stated = number is not None and _user_stated(number, query)
            if op == FacetOperator.NEAR and not stated:
                return _facet_signal(
                    "invalid_facet",
                    phrase or facet.label,
                    f"'near' needs a value for {facet.label} that the question states",
                )
            if not stated:
                # NEVER AN INVENTED NUMBER. A bound the question did not state is dropped and
                # the polarity kept: "a big room" ranks by capacity, it does not filter at 20.
                demoted = (
                    FacetOperator.MAXIMIZE
                    if op in (FacetOperator.ABOVE, FacetOperator.AT_LEAST)
                    else FacetOperator.MINIMIZE
                )
                logger.info(
                    f"[compiler] {facet.key}: {op.value} {value!r} is not a number the question "
                    f"states -> {demoted.value}"
                )
                op, value, source = demoted, None, ThresholdSource.DEFAULT
            else:
                value = number
    elif value_type == "boolean":
        value = None
    elif value_type == "enum":
        values = value if isinstance(value, list) else [value]
        values = [str(v).strip() for v in values if str(v or "").strip()]
        if not values:
            return _facet_signal(
                "invalid_facet",
                phrase or facet.label,
                f"{facet.label} needs a value",
                inspect_key=facet.key,
            )
        if value_set_complete(facet):
            canonical = []
            for v in values:
                match = _match_enum(v, facet.examples)
                if match is None:
                    return _facet_signal(
                        "invalid_facet",
                        phrase or v,
                        f"'{v}' is not a value {facet.label} takes in this building's records "
                        f"(recorded: {', '.join(facet.examples)})",
                        inspect_key=facet.key,
                    )
                canonical.append(match)
            values = canonical
        if op == FacetOperator.EQUALS and len(values) > 1:
            op = FacetOperator.ONE_OF
        value = values[0] if op == FacetOperator.EQUALS else values
    elif value_type == "text":
        if not isinstance(value, str) or not value.strip():
            return _facet_signal(
                "invalid_facet",
                phrase or facet.label,
                f"{facet.label} needs the text to look for",
                inspect_key=facet.key,
            )
        value = value.strip()
    return _FacetParse(
        "criterion",
        FacetCriterion(
            facet=facet.key,
            operator=op,
            value=value,
            hardness=hardness,
            threshold_source=source,
            source_phrase=phrase,
            record_group=group,
        ),
    )


# ── v2: the operations a plan can run instead of ranking spaces (C3, C2) ─────────────────

#: Spellings a model reaches for that name one statistic, grouping, order or relation exactly.
_STATISTIC_ALIASES: Dict[str, str] = {
    "average": "mean",
    "avg": "mean",
    "total": "sum",
    "minimum": "min",
    "maximum": "max",
    "spread": "range",
    "gap": "range",
    "std": "stdev",
    "stddev": "stdev",
    "std_dev": "stdev",
    "standard_deviation": "stdev",
    "sd": "stdev",
    "number": "count",
    "count_greater": "count_above",
    "count_less": "count_below",
}
_GROUP_ALIASES: Dict[str, str] = {
    "floors": "floor",
    "level": "floor",
    "levels": "floor",
    "storey": "floor",
    "story": "floor",
    "whole_building": "building",
    "the_building": "building",
    "kind": "space_kind",
    "space_type": "space_kind",
    "room_type": "space_kind",
    "room_kind": "space_kind",
    "type": "space_kind",
}
_ORDER_ALIASES: Dict[str, str] = {"ascending": "asc", "descending": "desc"}
_RELATION_ALIASES: Dict[str, str] = {
    "versus": "difference",
    "vs": "difference",
    "minus": "difference",
    "over": "exceeds",
    "above": "exceeds",
    "greater": "exceeds",
    "more_than": "exceeds",
    "share": "ratio",
    "percentage": "ratio",
    "percent": "ratio",
}

#: Words that put the SMALLER figure first, and the larger. Read only for statistics whose order
#: is a plain "more or less of it": for a spread, "most even" means the SMALLEST deviation, so
#: range and stdev are never second-guessed by these words.
_ASC_WORDS = frozenset(
    {"fewest", "least", "lowest", "smallest", "minimum", "fewer", "less", "lower"}
)
_DESC_WORDS = frozenset({"most", "highest", "largest", "biggest", "greatest", "maximum", "more"})
_ORDER_CHECKED = frozenset(
    {
        Statistic.MEAN,
        Statistic.SUM,
        Statistic.MIN,
        Statistic.MAX,
        Statistic.COUNT,
        Statistic.COUNT_ABOVE,
        Statistic.COUNT_BELOW,
    }
)
#: A question that names floors, for a grouping the compile left out.
_FLOOR_WORD_RE = re.compile(r"\b(?:floors?|levels?|storeys?|stories)\b", re.IGNORECASE)

_SPACE_WORDS = r"(?:rooms?|spaces?|offices?|labs?|desks?|areas?)"
#: A question about ONE space in each group -- "the busiest room on each floor", "the room with
#: the most people" -- keeps a per-space highest or lowest. Generic English.
_ONE_SPACE_RE = re.compile(
    r"\b(?:busiest|fullest|emptiest|single|individual)\s+(?:\w+\s+)?" + _SPACE_WORDS + r"\b"
    r"|\b" + _SPACE_WORDS + r"\s+(?:with|that\s+has|holding)\s+the\s+"
    r"(?:most|fewest|least|highest|lowest|largest|smallest)\b",
    re.IGNORECASE,
)
#: A question that counts SPACES: "the most occupied rooms", "how many offices".
_COUNTS_SPACES_RE = re.compile(
    r"\b(?:most|fewest|least|more|fewer|how\s+many|number\s+of)\s+(?:[\w-]+\s+){0,2}?"
    + _SPACE_WORDS
    + r"\b",
    re.IGNORECASE,
)


def _question_order(query: str) -> Optional[SortOrder]:
    """The order the question's own words ask for, when they ask for exactly one."""
    words = set(_WORDS_RE.findall((query or "").lower()))
    asc, desc = bool(words & _ASC_WORDS), bool(words & _DESC_WORDS)
    if asc and not desc:
        return SortOrder.ASC
    if desc and not asc:
        return SortOrder.DESC
    return None


def _slug(value: Any) -> str:
    return _norm_text(value).replace(" ", "_").replace("-", "_")


def _operation_signal(phrase: str, note: str) -> AmbiguitySignal:
    return AmbiguitySignal(kind="invalid_operation", phrase=phrase or "that", note=note)


def _operation_facet(
    raw: Any, phrase: str, known: set, catalogue: "FacetCatalogue", role: str
) -> Tuple[Optional["Facet"], Optional[AmbiguitySignal]]:
    """The facet an operation reads: a catalogue key, or a modality name or lay word for one.

    Only a facet that has ONE value per space can be aggregated or compared: not a booking check
    (a yes/no about a time window), not the floor (that is what spaces are grouped BY), and not a
    route's figure (it depends on where the route starts, which the plan cannot choose).
    """
    text = str(raw or "").strip()
    facet = catalogue.get(text)
    if facet is None and text.lower() in known:
        facet = catalogue.get(f"sensor:{text.lower()}")
    if facet is None and text:
        mapped = _modality_from_lay_term(text)
        if mapped and mapped in known:
            facet = catalogue.get(f"sensor:{mapped}")
    if facet is None and text:
        facet = _facet_by_short_name(text, catalogue)
    if facet is None:
        return None, AmbiguitySignal(
            kind="unmapped_term",
            phrase=phrase or text or role,
            note=f"'{text or role}' is not a facet this building holds",
        )
    label = facet.label or facet.key
    if facet.entity_type != "space":
        return None, AmbiguitySignal(
            kind="unmapped_term",
            phrase=phrase or label,
            note=f"'{label}' describes a {facet.entity_type}, not a space",
        )
    if facet.source_kind == "event":
        return None, _operation_signal(
            phrase or label, f"{label} is a check over a time window, not a figure per space"
        )
    if facet.key == _FLOOR_FACET:
        return None, _operation_signal(
            phrase or label, "the floor is how spaces are grouped, not a figure to compute"
        )
    if facet.source_kind == "spatial":
        if facet.record_class:  # a route's figure
            return None, _operation_signal(
                phrase or label,
                f"{label} depends on where the route starts, which the question does not fix",
            )
        # Any other spatial facet -- the kind of space -- is what spaces are filtered or grouped
        # by. The old message here said every spatial facet "depends on where the route starts",
        # which is false for a kind of room and was shown to a reader on 2026-10-08.
        return None, _operation_signal(
            phrase or label, f"{label} is what spaces are filtered or grouped by, not a figure"
        )
    return facet, None


def _aggregate_item(
    raw: Any,
    query: str,
    known: set,
    catalogue: "FacetCatalogue",
    criteria_facets: FrozenSet[str] = frozenset(),
) -> Tuple[Optional[AggregateSpec], List[AmbiguitySignal]]:
    """Validate the model's aggregate against the catalogue and the facet's units. Never a guess."""
    from orchestrator.services.deliberation.operations import additive

    if not isinstance(raw, dict) or not raw:
        return None, [
            _operation_signal(query, "a ranking of floors needs the figure each floor is ranked on")
        ]
    phrase = str(raw.get("phrase", "") or "").strip()
    stat_raw = _slug(raw.get("statistic"))
    stat_raw = _STATISTIC_ALIASES.get(stat_raw, stat_raw)
    if stat_raw not in {s.value for s in Statistic}:
        return None, [
            _operation_signal(phrase, f"'{stat_raw or 'nothing'}' is not a statistic here")
        ]
    statistic = Statistic(stat_raw)

    group_raw = _slug(raw.get("group_by"))
    group_raw = _GROUP_ALIASES.get(group_raw, group_raw)
    if group_raw not in {g.value for g in GroupBy}:
        if group_raw or not _FLOOR_WORD_RE.search(query or ""):
            return None, [
                _operation_signal(
                    phrase, "say what to group the spaces by: floors, the building or room kinds"
                )
            ]
        group_raw = GroupBy.FLOOR.value  # the question itself names floors
    group_by = GroupBy(group_raw)

    facet = None
    key = str(raw.get("facet") or "").strip()
    if key and statistic == Statistic.COUNT:
        # A COUNT whose "figure" is a kind -- "which floor has the most meeting rooms" compiled
        # with facet=spatial:space_kind (live, 2026-10-08) -- counts the spaces OF that kind. The
        # kind itself is a filter, so it is honoured only when the plan also filters on it.
        named = catalogue.get(key) or _facet_by_short_name(key, catalogue)
        kind_like = (
            named is not None
            and named.value_type == "enum"
            and named.source_kind in ("spatial", "record", "ttl")
            and named.key != _FLOOR_FACET  # the floor is what spaces are grouped BY
        )
        if kind_like:
            if named.key not in criteria_facets:
                return None, [
                    _operation_signal(
                        phrase or named.label, f"say which {named.label} to count"
                    )
                ]
            key = ""
    if key:
        facet, problem = _operation_facet(key, phrase, known, catalogue, "the figure")
        if problem is not None:
            return None, [problem]
    elif statistic != Statistic.COUNT:
        return None, [_operation_signal(phrase, f"the {statistic.value} of what was not named")]

    signals: List[AmbiguitySignal] = []
    threshold: Optional[float] = None
    if facet is not None:
        label = facet.label or facet.key
        numeric = facet.value_type in ("number", "integer")
        if statistic != Statistic.COUNT and not numeric:
            return None, [
                _operation_signal(
                    phrase or label,
                    f"{label} holds {facet.value_type} values, so it has no {statistic.value}",
                )
            ]
        # AN AMOUNT THAT ADDS UP IS RANKED BY ITS TOTAL, decided here and not by the model.
        # Measured live, 2026-10-08: "Which floor has the most people in it right now?" compiled
        # to statistic=max -- the busiest single room per floor -- although the prompt says sum is
        # for people. v1's own aggregate lane made the same mistake with a mean per sensor and
        # named Floor 0 (1.8 a sensor, 18 sensors) over Floor 5 (1.6, 54 sensors), the opposite of
        # their totals. A per-space highest or lowest stays only when the question asks about one
        # space in each group ("the busiest room on each floor").
        # The same for "count": with an amount that adds up, a count of the SPACES holding a value
        # ("most people" -> how many rooms report occupancy) answers a different question, and a
        # low-effort compile measured on 2026-10-08 chose exactly that. A count of spaces stays
        # only when the question counts spaces ("the most occupied ROOMS").
        if (
            statistic == Statistic.COUNT
            and numeric
            and additive(facet)[0]
            and not _COUNTS_SPACES_RE.search(query or "")
        ):
            logger.info(f"[cqir] {label} adds up: groups ranked by their total, not a count")
            statistic = Statistic.SUM
        if (
            statistic in (Statistic.MAX, Statistic.MIN)
            and numeric
            and additive(facet)[0]
            and not _ONE_SPACE_RE.search(query or "")
        ):
            logger.info(
                f"[cqir] {label} adds up: groups ranked by their total, not their "
                f"{statistic.value} space"
            )
            statistic = Statistic.SUM
        if statistic == Statistic.SUM:
            adds_up, why = additive(facet)
            if not adds_up:
                return None, [
                    _operation_signal(
                        phrase or label,
                        f"{why}; ask for the average, the highest or the lowest instead",
                    )
                ]
        if statistic in (Statistic.COUNT_ABOVE, Statistic.COUNT_BELOW):
            number = _as_number(raw.get("threshold"))
            if number is None or not _user_stated(number, query):
                return None, [
                    _operation_signal(
                        phrase or label,
                        f"counting spaces {statistic.value.split('_')[1]} a limit needs the limit "
                        "as a number in the question",
                    )
                ]
            threshold = number

    order_raw = _slug(raw.get("order"))
    order_raw = _ORDER_ALIASES.get(order_raw, order_raw)
    stated = _question_order(query) if statistic in _ORDER_CHECKED else None
    if order_raw in {o.value for o in SortOrder}:
        order = SortOrder(order_raw)
        if stated is not None and stated != order:
            # "Which floor has the FEWEST people" compiled most-first would answer the opposite
            # question with real numbers. The question's own words win the argument by asking.
            signals.append(
                _operation_signal(
                    phrase or query,
                    f"the question asks for the {'smallest' if stated == SortOrder.ASC else 'largest'} "
                    "figure first, and the plan ranked the other way",
                )
            )
    else:
        order = stated or SortOrder.DESC
    top_k = raw.get("top_k")
    try:
        top_k = int(top_k) if top_k is not None and int(top_k) >= 1 else None
    except (TypeError, ValueError):
        top_k = None
    spec = AggregateSpec(
        facet=facet.key if facet is not None else None,
        group_by=group_by,
        statistic=statistic,
        threshold=threshold,
        order=order,
        top_k=top_k,
        source_phrase=phrase,
    )
    return (None, signals) if signals else (spec, [])


def _compare_item(
    raw: Any, query: str, known: set, catalogue: "FacetCatalogue"
) -> Tuple[Optional[CompareSpec], List[AmbiguitySignal]]:
    """Validate the model's comparison: two numeric facets of a space, and a relation their
    units support (``operations.compare_fit``). Never a guess."""
    from orchestrator.services.deliberation.operations import compare_fit

    if not isinstance(raw, dict) or not raw:
        return None, [_operation_signal(query, "a comparison needs the two figures to compare")]
    phrase = str(raw.get("phrase", "") or "").strip()
    facet_a, problem_a = _operation_facet(raw.get("facet_a"), phrase, known, catalogue, "a figure")
    facet_b, problem_b = _operation_facet(raw.get("facet_b"), phrase, known, catalogue, "a figure")
    problems = [p for p in (problem_a, problem_b) if p is not None]
    if problems:
        return None, problems
    if facet_a.key == facet_b.key:
        return None, [_operation_signal(phrase, f"{facet_a.label} was compared with itself")]
    relation_raw = _slug(raw.get("relation"))
    relation_raw = _RELATION_ALIASES.get(relation_raw, relation_raw)
    if relation_raw in {r.value for r in CompareRelation}:
        requested = CompareRelation(relation_raw)
    elif not relation_raw:
        requested = CompareRelation.DIFFERENCE  # both figures are shown either way
    else:
        return None, [_operation_signal(phrase, f"'{relation_raw}' is not a comparison here")]
    fit = compare_fit(facet_a, facet_b, requested)
    if fit.refusal:
        return None, [_operation_signal(phrase or facet_a.label, fit.refusal)]
    spec = CompareSpec(
        facet_a=facet_a.key,
        facet_b=facet_b.key,
        relation=fit.relation or requested,
        requested_relation=requested if fit.relation != requested else None,
        total=bool(_as_bool(raw.get("total"))),
        source_phrase=phrase,
    )
    return spec, []


#: Peak and off-peak: periods only a TARIFF can define. Never guessed from the clock.
_PEAK_RE = re.compile(r"\b(?:off[\s-]?peak|peak)\b", re.IGNORECASE)
_PEAK_WORD_RE = re.compile(r"\bpeak\b", re.IGNORECASE)


def _peak_signal(query: str, catalogue: "FacetCatalogue") -> AmbiguitySignal:
    """Why "peak against off-peak" cannot be read, said with what the building does record.

    Peak hours belong to a tariff, so they are looked for in the catalogue -- a facet that names
    them -- and nowhere else: no clock hours are assumed for any building.
    """
    from orchestrator.services.deliberation.facets import split_camel

    named = sorted(
        {
            f.label or f.key
            for f in catalogue
            if _PEAK_WORD_RE.search(
                f"{f.label} {split_camel((f.predicate or '').rsplit('#', 1)[-1])}"
            )
        }
    )
    if named:
        note = (
            f"the building records peak hours ({', '.join(named[:3])}), but splitting readings "
            "by them is not something this lane does yet; compare two named periods instead"
        )
    else:
        note = (
            "this building's tariff records define no peak hours, so peak and off-peak cannot be "
            "told apart; compare two named periods instead -- this week and last week, today and "
            "yesterday, or weekdays and weekends"
        )
    return _operation_signal(query, note)


def _period_item(
    raw: Any, query: str, known: set, catalogue: "FacetCatalogue"
) -> Tuple[Optional[PeriodSpec], List[AmbiguitySignal]]:
    """Validate a period comparison. The model names the reading; the periods are read from the
    question by ``requested_interval.compared_periods`` -- never from a date the model wrote."""
    from orchestrator.services.deliberation.operations import additive
    from orchestrator.services.requested_interval import building_tz, compared_periods

    if not isinstance(raw, dict) or not raw:
        return None, [
            _operation_signal(query, "a comparison of two periods needs the reading to compare")
        ]
    phrase = str(raw.get("phrase", "") or "").strip()
    facet, problem = _operation_facet(raw.get("facet"), phrase, known, catalogue, "the reading")
    if problem is not None:
        return None, [problem]
    label = facet.label or facet.key
    if facet.source_kind != "sensor":
        return None, [
            _operation_signal(
                phrase or label,
                f"{label} is recorded, not measured over time, so two periods of it cannot differ",
            )
        ]
    if facet.value_type not in ("number", "integer"):
        return None, [
            _operation_signal(
                phrase or label, f"{label} is a yes/no state, not a figure to compare over time"
            )
        ]
    stat_raw = _slug(raw.get("statistic")) or Statistic.MEAN.value
    stat_raw = _STATISTIC_ALIASES.get(stat_raw, stat_raw)
    if stat_raw not in {s.value for s in _PERIOD_STATS}:
        return None, [
            _operation_signal(
                phrase or label, f"'{stat_raw}' is not a way to compare two periods here"
            )
        ]
    statistic = Statistic(stat_raw)
    if statistic == Statistic.SUM:
        adds_up, why = additive(facet)
        if not adds_up:
            return None, [_operation_signal(phrase or label, f"{why}; ask for the average instead")]
    group_raw = _slug(raw.get("group_by"))
    group_raw = _GROUP_ALIASES.get(group_raw, group_raw)
    group_by: Optional[GroupBy] = None
    if group_raw and group_raw not in ("null", "none"):
        if group_raw not in {g.value for g in GroupBy}:
            return None, [
                _operation_signal(phrase or label, f"'{group_raw}' is not a way to group spaces")
            ]
        group_by = GroupBy(group_raw)
    if _PEAK_RE.search(query or ""):
        return None, [_peak_signal(query, catalogue)]
    periods, why = compared_periods(query, building_tz())
    if len(periods) != 2:
        return None, [_operation_signal(query, why or "two periods are needed")]
    spec = PeriodSpec(
        facet=facet.key,
        statistic=statistic,
        group_by=group_by,
        periods=[PeriodRef(**p) for p in periods],
        source_phrase=phrase,
    )
    return spec, []


# ── v2: a series related to recorded events or to a second series (C5) ──────────────────

#: Spellings a model reaches for that name one relation exactly.
_RELATION_KIND_ALIASES: Dict[str, str] = {
    "while": "during",
    "whilst": "during",
    "when": "during",
    "throughout": "during",
    "in": "during",
    "following": "after",
    "afterwards": "after",
    "post": "after",
    "correlation": "co_movement",
    "correlate": "co_movement",
    "correlates": "co_movement",
    "comovement": "co_movement",
    "co_move": "co_movement",
    "covariation": "co_movement",
    "together": "co_movement",
    "with": "co_movement",
    "relationship": "co_movement",
}
#: The question's own words for "after" and "during", read only when the compile names no relation.
_AFTER_WORDS_RE = re.compile(r"\b(?:after|following|afterwards|post)\b", re.IGNORECASE)
_DURING_WORDS_RE = re.compile(r"\b(?:during|while|whilst|throughout)\b", re.IGNORECASE)

_LAG_NUMBER = (
    r"(?P<n>\d+(?:\.\d+)?|an?|one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|"
    r"twenty|thirty|forty|forty[\s-]five|fifty|sixty|ninety|half\s+an?)"
)
_LAG_UNIT = r"(?P<u>minutes?|mins?|hours?|hrs?)"
#: A stated length of "after": "30 minutes after", "within two hours of", "in the hour after".
_LAG_RE = re.compile(
    r"\b(?:within|in\s+the|for\s+the|during\s+the|over\s+the|up\s+to)\s+(?:first\s+|next\s+)?"
    + _LAG_NUMBER
    + r"\s*"
    + _LAG_UNIT
    + r"\s+(?:after|following|of)\b"
    r"|\b"
    + _LAG_NUMBER.replace("?P<n>", "?P<n2>")
    + r"\s*"
    + _LAG_UNIT.replace("?P<u>", "?P<u2>")
    + r"\s+(?:after|following|later|afterwards)\b"
    r"|\b(?:in|within|during|for|over)\s+the\s+(?P<u3>hour|minute)\s+(?:after|following)\b",
    re.IGNORECASE,
)


def _stated_lag_minutes(query: str) -> Optional[float]:
    """The length of "after" the question states, in minutes, or None. Read in code, never compiled."""
    match = _LAG_RE.search(query or "")
    if not match:
        return None
    if match.group("u3"):
        return 60.0 if match.group("u3").lower() == "hour" else 1.0
    number = (match.group("n") or match.group("n2") or "").lower().replace("-", " ")
    unit = (match.group("u") or match.group("u2") or "").lower()
    if number.startswith("half"):
        value = 0.5
    elif number in ("a", "an"):
        value = 1.0
    elif number.replace(".", "", 1).isdigit():
        value = float(number)
    else:
        words = number.split()
        value = float(sum(_NUMBER_WORD_VALUES.get(w, 0) for w in words))
        if not value:
            return None
    return value * (60.0 if unit.startswith("h") else 1.0)


def _relation_window(
    query: str, tz_name: Optional[str] = None, now=None
) -> Tuple[Optional[str], Optional[str], Optional[float], str, str]:
    """(start, end, trailing hours, label, why not) -- the ONE window a relation reads.

    Read from the question by the same resolvers every other lane uses: a named calendar day, one
    named calendar period ("last week", "this month"), or a trailing duration ("over the last three
    days"). Nothing named is (None, None, None, "", ""): the executor then reads a declared default
    window. Two periods named is a C4 comparison, not a window -- said, never guessed between.
    """
    from orchestrator.services.requested_interval import (
        calendar_day_bounds,
        compared_periods,
        named_day,
        named_period,
        period_bounds,
    )

    low = (query or "").lower()
    pair, _ = compared_periods(query or "", tz_name, now)
    if len(pair) == 2:
        return (
            None,
            None,
            None,
            "",
            "the question names two periods, and a relation reads one window; ask about one "
            "period, or compare the two periods without the events",
        )
    day = named_day(low)
    if day is not None:
        bounds = calendar_day_bounds(query, tz_name, now)
        if bounds:
            return bounds[0], bounds[1], None, day, ""
    named = named_period(low)
    if named is not None and len(named[1]) == 1:
        unit, (back,) = named
        start, end = period_bounds(unit, back, tz_name, now)
        return start, end, None, f"{'this' if back == 0 else 'last'} {unit}", ""
    hours = match_past_window(query or "")
    if hours:
        if hours >= 48 and hours % 24 == 0:
            label = f"the last {hours / 24:g} days"
        else:
            label = f"the last {hours:g} hours"
        return None, None, float(hours), label, ""
    return None, None, None, "", ""


def _event_source_for(
    text: str, phrase: str, catalogue: "FacetCatalogue"
) -> Tuple[Optional["Facet"], Optional[AmbiguitySignal]]:
    """The event source a compiled ``events`` value names: a catalogue key, the record class, or
    words naming exactly ONE source. Never a guess between two, and never a register that is not
    placed on the clock."""
    raw = (text or "").strip()
    facet = catalogue.get(raw)
    if (facet is None or facet.value_type != _INTERVAL) and raw and ":" not in raw:
        facet = catalogue.get(f"event:{raw}")
    if facet is None or facet.value_type != _INTERVAL:
        named = catalogue.match_event_sources(raw)
        facet = named[0] if len(named) == 1 else None
    if facet is not None and facet.value_type == _INTERVAL and facet.at_least("suitable"):
        return facet, None
    held = [f.label for f in catalogue.event_sources()]
    note = f"'{raw or phrase}' is not something this building records with a time and a place"
    note += (
        f"; it does record: {', '.join(held)}"
        if held
        else "; it records no events placed in a space and on the clock"
    )
    return None, AmbiguitySignal(kind="unmapped_term", phrase=phrase or raw or "events", note=note)


def _relate_item(
    raw: Any, query: str, known: set, catalogue: "FacetCatalogue"
) -> Tuple[Optional[RelateSpec], List[AmbiguitySignal]]:
    """Validate a relation (C5) against the catalogue. The model names the reading and what it is
    set against; the window and the lag are read from the question in code. Never a guess."""
    from orchestrator.services.requested_interval import building_tz

    if not isinstance(raw, dict) or not raw:
        return None, [
            _operation_signal(query, "a relation needs the reading and what it is set against")
        ]
    phrase = str(raw.get("phrase", "") or "").strip()
    series, problem = _operation_facet(raw.get("series"), phrase, known, catalogue, "the reading")
    if problem is not None:
        return None, [problem]
    label = series.label or series.key
    if series.source_kind != "sensor":
        return None, [
            _operation_signal(
                phrase or label,
                f"{label} is recorded, not measured over time, so it has no level during or "
                "after anything",
            )
        ]
    if series.value_type not in ("number", "integer"):
        return None, [
            _operation_signal(
                phrase or label,
                f"{label} is a yes/no state, not a figure; relate a measured figure to it instead",
            )
        ]
    events: Optional["Facet"] = None
    other: Optional["Facet"] = None
    events_raw = str(raw.get("events") or "").strip()
    if events_raw and events_raw.lower() not in ("null", "none"):
        events, problem = _event_source_for(events_raw, phrase, catalogue)
        if problem is not None:
            return None, [problem]
    other_raw = str(raw.get("other_series") or "").strip()
    if other_raw and other_raw.lower() not in ("null", "none"):
        other, problem = _operation_facet(other_raw, phrase, known, catalogue, "the second reading")
        if problem is not None:
            return None, [problem]
        if other.source_kind != "sensor":
            return None, [
                _operation_signal(
                    phrase or other.label,
                    f"{other.label} is recorded, not measured over time; relate the reading to "
                    "recorded events or to a second reading",
                )
            ]
        if other.key == series.key:
            return None, [_operation_signal(phrase, f"{label} was related to itself")]
    if events is not None and other is not None:
        return None, [
            _operation_signal(
                phrase or query,
                "one relation at a time: the reading against recorded events, or against a "
                "second reading",
            )
        ]
    relation_raw = _slug(raw.get("relation"))
    relation_raw = _RELATION_KIND_ALIASES.get(relation_raw, relation_raw)
    if not relation_raw:
        # Left blank by the compile: the question's own words decide, as they decide an order.
        if events is not None:
            relation_raw = "after" if _AFTER_WORDS_RE.search(query or "") else "during"
        elif other is not None and other.value_type == "boolean":
            relation_raw = "during" if _DURING_WORDS_RE.search(query or "") else "co_movement"
        else:
            relation_raw = "co_movement"
    if relation_raw not in {r.value for r in RelationKind}:
        return None, [_operation_signal(phrase, f"'{relation_raw}' is not a relation here")]
    relation = RelationKind(relation_raw)
    sources = [f.label for f in catalogue.event_sources()]
    if relation in (RelationKind.DURING, RelationKind.AFTER):
        if events is None and other is None:
            held = f" ({', '.join(sources)})" if sources else ""
            return None, [
                _operation_signal(
                    phrase or query,
                    f"say what {label} is set against: events the building records{held}, or a "
                    "second reading",
                )
            ]
        if other is not None and relation == RelationKind.AFTER:
            return None, [
                _operation_signal(
                    phrase or other.label,
                    f"'after' needs recorded events; ask what happens to {label} while "
                    f"{other.label} is on, or how the two move together",
                )
            ]
        if other is not None and other.value_type != "boolean":
            return None, [
                _operation_signal(
                    phrase or other.label,
                    f"'during' needs recorded events or a yes/no reading, and {other.label} is a "
                    "measured figure; ask how the two move together instead",
                )
            ]
    elif other is None:
        return None, [
            _operation_signal(
                phrase or query,
                "how two readings move together needs the second reading"
                + (
                    "; a reading set against recorded events is 'during' or 'after'"
                    if events is not None
                    else ""
                ),
            )
        ]
    group_raw = _slug(raw.get("group_by"))
    group_raw = _GROUP_ALIASES.get(group_raw, group_raw)
    group_by: Optional[GroupBy] = None
    if group_raw and group_raw not in ("null", "none"):
        if group_raw not in {g.value for g in GroupBy}:
            return None, [
                _operation_signal(phrase or label, f"'{group_raw}' is not a way to group spaces")
            ]
        group_by = GroupBy(group_raw)
    start, end, hours, window_label, why = _relation_window(query, building_tz())
    if why:
        return None, [_operation_signal(query, why)]
    lag: Optional[float] = None
    lag_source = ThresholdSource.DEFAULT
    if relation == RelationKind.AFTER:
        stated = _stated_lag_minutes(query)
        if stated is not None:
            if not 0 < stated <= MAX_LAG_MINUTES:
                return None, [
                    _operation_signal(
                        query,
                        f"'after' reads at most {MAX_LAG_MINUTES / 60:g} hours after each event; "
                        "a longer span is a period, not an aftermath",
                    )
                ]
            lag, lag_source = stated, ThresholdSource.USER
        else:
            lag = DEFAULT_LAG_MINUTES
    spec = RelateSpec(
        series=series.key,
        relation=relation,
        events=events.key if events is not None else None,
        other_series=other.key if other is not None else None,
        lag_minutes=lag,
        lag_source=lag_source,
        group_by=group_by,
        window_start=start,
        window_end=end,
        window_hours=hours,
        window_label=window_label,
        source_phrase=phrase,
    )
    return spec, []


def _normalise_operation_plan(
    constraints: List[Constraint],
    criteria: List[FacetCriterion],
    op_keys: Sequence[str],
    catalogue: "FacetCatalogue",
) -> Tuple[List[Constraint], List[FacetCriterion]]:
    """In a plan that aggregates or compares, every other criterion NARROWS the spaces counted.

    * A preference on the operation's own facet ("fewest people" also emitted as "minimise
      occupancy") restates the operation and is dropped.
    * A facet requirement is a filter, so it is HARD -- "bookable seats" counts bookable spaces,
      it does not prefer them. A preference on another facet stays, and the executor names it as
      not applied: a preference cannot decide which spaces are counted.
    * Sensed criteria are SOFT here: the executor filters on a stated limit by the reading itself,
      so a space with no sensor is reported per group as not verified rather than dropped unseen.
    """
    op_modalities = {
        (catalogue.get(k).modality or "") for k in op_keys if catalogue.get(k) is not None
    } - {""}
    kept_constraints: List[Constraint] = []
    for c in constraints:
        # "above" / "below" with NO stated limit has nothing to filter by: on the operation's own
        # figure it is the comparison said again as a preference ("occupancy > seatCount" lifted
        # into a comparison, 2026-10-08). With a limit the user stated it stays a real filter.
        restates = c.modality in op_modalities and (
            c.direction in (Direction.MINIMIZE, Direction.MAXIMIZE, Direction.NEAR_VALUE)
            or (c.direction in (Direction.ABOVE, Direction.BELOW) and c.threshold is None)
        )
        if restates:
            logger.info(f"[compiler] {c.modality} {c.direction.value} restates the operation")
            continue
        kept_constraints.append(c.model_copy(update={"hardness": Hardness.SOFT}))
    kept_criteria: List[FacetCriterion] = []
    for f in criteria:
        if f.operator in SCORING_OPERATORS:
            if f.facet in op_keys:
                logger.info(f"[compiler] {f.facet} {f.operator.value} restates the operation")
                continue
            kept_criteria.append(f)
            continue
        kept_criteria.append(f.model_copy(update={"hardness": Hardness.HARD}))
    return kept_constraints, kept_criteria


@dataclass
class _Operation:
    """The operation one compile asked for, validated: at most one of the four is set."""

    aggregate: Optional[AggregateSpec] = None
    compare: Optional[CompareSpec] = None
    period: Optional[PeriodSpec] = None
    relate: Optional[RelateSpec] = None

    @property
    def spec(self) -> Any:
        return self.aggregate or self.compare or self.period or self.relate


#: A constraint phrase that STATES a comparison: "occupancy > seatCount", "people over capacity".
_STATED_COMPARISON_RE = re.compile(
    r"[<>]|\b(?:over|above|exceeds?|exceeding|more\s+than|greater\s+than|below|under|less\s+than|"
    r"fewer\s+than|versus|vs\.?|against|compared\s+(?:with|to))\b",
    re.IGNORECASE,
)
_ABOVE_WORDS_RE = re.compile(r">|\b(?:over|above|exceeds?|exceeding|more|greater)\b", re.I)


def _lift_stated_comparison(
    data: Dict[str, Any], known: set, catalogue: "FacetCatalogue"
) -> Dict[str, Any]:
    """A sensed constraint whose phrase compares it with a DECLARED facet is that comparison.

    Measured 2026-10-08, three compiles of three: "Are any meeting rooms over their seating
    capacity right now?" came back as a list with the constraint ``occupancy above``, phrase
    "occupancy > seatCount" -- the model saw the comparison and wrote it where a preference goes,
    so the plan ranked meeting rooms by occupancy and compared nothing. Lifted only when no
    operation was asked for, the phrase states a comparison, the constraint is a sensed figure and
    the phrase names exactly one numeric facet a space records (by key, field or label).
    """
    if not isinstance(data, dict) or any(
        isinstance(data.get(k), dict) and data.get(k)
        for k in ("aggregate", "compare", "period", "relate")
    ):
        return data
    if _slug(data.get("decision")) in {
        DecisionKind.AGGREGATE_RANK.value,
        DecisionKind.COMPARE_FACETS.value,
        DecisionKind.PERIOD_COMPARE.value,
        DecisionKind.RELATE.value,
    }:
        return data
    constraints = data.get("constraints") or []
    for index, item in enumerate(constraints):
        if not isinstance(item, dict):
            continue
        phrase = str(item.get("phrase") or "")
        modality = str(item.get("modality") or "").strip().lower()
        if modality not in known or not _STATED_COMPARISON_RE.search(phrase):
            continue
        sensor = catalogue.get(f"sensor:{modality}")
        if sensor is None or sensor.value_type not in ("number", "integer"):
            continue
        named = {
            f.key
            for token in re.findall(r"[A-Za-z][A-Za-z_.:]+", phrase)
            for f in [catalogue.get(token) or _facet_by_short_name(token, catalogue)]
            if f is not None
            and f.source_kind in ("record", "ttl")
            and f.entity_type == "space"
            and f.value_type in ("number", "integer")
        }
        if len(named) != 1:
            continue
        declared = named.pop()
        lifted = dict(data)
        lifted["decision"] = DecisionKind.COMPARE_FACETS.value
        lifted["compare"] = {
            "facet_a": f"sensor:{modality}",
            "facet_b": declared,
            "relation": "exceeds" if _ABOVE_WORDS_RE.search(phrase) else "difference",
            "phrase": phrase,
        }
        lifted["constraints"] = [c for i, c in enumerate(constraints) if i != index]
        logger.info(f"[cqir] '{phrase}' states a comparison: lifted to {modality} vs {declared}")
        return lifted
    return data


def _parse_operation(
    data: Dict[str, Any], query: str, known: set, catalogue: "FacetCatalogue"
) -> Tuple[_Operation, List[AmbiguitySignal]]:
    """The operation the model compiled, validated -- or signals saying why it cannot run."""
    data = _lift_stated_comparison(data, known, catalogue)
    decision = _slug(data.get("decision"))
    agg_raw = data.get("aggregate")
    cmp_raw = data.get("compare")
    per_raw = data.get("period")
    rel_raw = data.get("relate")
    wanted = [
        kind
        for kind, raw in (
            (DecisionKind.AGGREGATE_RANK, agg_raw),
            (DecisionKind.COMPARE_FACETS, cmp_raw),
            (DecisionKind.PERIOD_COMPARE, per_raw),
            (DecisionKind.RELATE, rel_raw),
        )
        if decision == kind.value or (isinstance(raw, dict) and bool(raw))
    ]
    if len(wanted) > 1:
        return _Operation(), [
            _operation_signal(
                query, "the plan asks for more than one operation at once; ask one at a time"
            )
        ]
    if not wanted:
        return _Operation(), []
    if wanted[0] == DecisionKind.AGGREGATE_RANK:
        criteria_facets = frozenset(
            str(c.get("facet") or "").strip()
            for c in (data.get("facet_criteria") or [])
            if isinstance(c, dict)
        )
        resolved = {
            (catalogue.get(k) or _facet_by_short_name(k, catalogue) or None) for k in criteria_facets
        }
        criteria_facets = criteria_facets | {f.key for f in resolved if f is not None}
        aggregate, signals = _aggregate_item(agg_raw, query, known, catalogue, criteria_facets)
        return _Operation(aggregate=aggregate), signals
    if wanted[0] == DecisionKind.COMPARE_FACETS:
        compare, signals = _compare_item(cmp_raw, query, known, catalogue)
        return _Operation(compare=compare), signals
    if wanted[0] == DecisionKind.RELATE:
        relate, signals = _relate_item(rel_raw, query, known, catalogue)
        return _Operation(relate=relate), signals
    period, signals = _period_item(per_raw, query, known, catalogue)
    return _Operation(period=period), signals


def assign_record_groups(criteria: List[FacetCriterion], catalogue: "FacetCatalogue") -> None:
    """Settle which criteria must hold for ONE record. In place.

    THE RULE, and it is the only one:
      * Only criteria read from RECORDS have a group: a facet with a record class and a join
        to the space (a register field, or a route fact reaching the space). A TTL property,
        the capacity, floor membership and availability are facts about the space itself.
      * A group never spans two record classes: an AV component and a workspace profile are
        different records whatever label the model gave them.
      * When the model OMITS the group, every criterion on the same record class in the
        question shares one group -- "a projector that is ready" is one AV component, not a
        room with some projector and some ready device.
      * When the model NAMES groups, criteria with the same name on the same class share a
        group, and an unnamed criterion on that class is its own default group.
    Labels are prefixed with the class so the executor can never join across classes; the
    fingerprint hashes groups by their members, so the label itself carries no meaning.
    """
    for criterion in criteria:
        facet = catalogue.get(criterion.facet)
        recorded = (
            facet is not None
            and facet.source_kind in ("record", "spatial")
            and bool(facet.record_class)
            and bool(facet.join_predicate)
        )
        if not recorded:
            criterion.record_group = None
            continue
        label = (criterion.record_group or "").strip()
        criterion.record_group = f"{facet.record_class}:{label}" if label else facet.record_class


def _phrase_covered(phrase: str, mapped: Sequence[str]) -> bool:
    """True when an unmapped phrase is the phrase of a criterion that DID map."""
    p = _norm_text(phrase)
    if len(p) < 3:
        return False
    for other in mapped:
        o = _norm_text(other)
        if len(o) >= 3 and (p == o or p in o or o in p):
            return True
    return False


def _apply_facets(
    cqir: CQIR,
    data: Dict[str, Any],
    query: str,
    known: set,
    catalogue: "FacetCatalogue",
    notes: Optional[Dict[str, Any]],
) -> CQIR:
    """Merge the validated facet criteria into a v1-parsed plan."""
    notes = notes if notes is not None else {}
    requests = data.get("inspect") or []
    if isinstance(requests, str):
        requests = [requests]
    notes["inspect"] = (
        [str(r).strip() for r in requests if str(r or "").strip()][:_MAX_INSPECT]
        if isinstance(requests, list)
        else []
    )
    items = data.get("facet_criteria") or []
    if not isinstance(items, list):
        items = []

    constraints = list(cqir.constraints)
    spatial = list(cqir.spatial)
    events = list(cqir.event_criteria)
    signals = list(cqir.signals)
    criteria: List[FacetCriterion] = []
    invalid_keys: List[str] = []
    mapped_phrases: List[str] = [c.source_phrase for c in constraints if c.source_phrase]
    for item in items:
        if not isinstance(item, dict):
            continue
        parsed = _facet_item(item, query, known, catalogue)
        if parsed.kind == "signal":
            signals.append(parsed.payload)
            if parsed.inspect_key and parsed.inspect_key not in invalid_keys:
                invalid_keys.append(parsed.inspect_key)
            continue
        payload = parsed.payload
        if parsed.kind == "constraint":
            if any(
                c.modality == payload.modality and c.direction == payload.direction
                for c in constraints
            ):
                continue  # the model gave one reading twice, once in each list
            constraints.append(payload)
        elif parsed.kind == "event":
            if any(e.kind == payload.kind for e in events):
                continue  # the deterministic fold already owns this phrase
            events.append(payload)
        elif parsed.kind == "spatial":
            if any(q.relation == payload.relation for q in spatial):
                continue
            spatial.append(payload)
        else:
            if payload.operator == FacetOperator.FREE_FOR and any(
                e.kind == "free_window" for e in events
            ):
                # The deterministic fold already checks availability for this phrase, as v1
                # does; a second check would read the same bookings twice.
                logger.info("[compiler] free_for already folded from the question — kept once")
                continue
            if any(
                c.facet == payload.facet
                and c.operator == payload.operator
                and c.value == payload.value
                for c in criteria
            ):
                continue
            criteria.append(payload)
        if getattr(payload, "source_phrase", ""):
            mapped_phrases.append(payload.source_phrase)

    # The operation (C3 / C2 / C4 / C5), when the plan computes something other than a ranking of
    # spaces.
    op, op_signals = _parse_operation(data, query, known, catalogue)
    signals.extend(op_signals)
    decision = cqir.decision
    operation = op.spec
    if op.aggregate is not None:
        decision = DecisionKind.AGGREGATE_RANK
    elif op.compare is not None:
        decision = DecisionKind.COMPARE_FACETS
    elif op.period is not None:
        decision = DecisionKind.PERIOD_COMPARE
    elif op.relate is not None:
        decision = DecisionKind.RELATE
    if operation is not None:
        if operation.source_phrase:
            mapped_phrases.append(operation.source_phrase)
        if cqir.time.basis == TimeBasis.FORECAST:
            signals.append(
                _operation_signal(
                    cqir.time.source_phrase or query,
                    (
                        "a relation is read from readings already taken, never forecast; ask "
                        "about a past period"
                        if op.relate is not None
                        else "a forecast of a figure per group of spaces is not something this "
                        "lane computes; ask about now or a past period"
                    ),
                )
            )

    assign_record_groups(criteria, catalogue)
    _fold_unbounded_threshold_direction(constraints, cqir.decision)
    constraints = _fold_air_quality(constraints)
    if operation is not None:
        op_keys = operation_facet_keys(op.aggregate, op.compare, op.period, op.relate)
        constraints, criteria = _normalise_operation_plan(constraints, criteria, op_keys, catalogue)
    if constraints or criteria or operation is not None:
        # Something mapped: the v1 "nothing mapped" signal no longer describes this plan, and an
        # "unmapped" phrase that IS a mapped criterion's phrase was not dropped at all.
        signals = [
            s
            for s in signals
            if not (s.kind == "vague" and s.note == "no mappable criteria")
            and not (s.kind == "unmapped_term" and _phrase_covered(s.phrase, mapped_phrases))
        ]
    notes["invalid_keys"] = invalid_keys
    return cqir.model_copy(
        update={
            "decision": decision,
            "constraints": constraints,
            "spatial": spatial,
            "event_criteria": events,
            "signals": signals,
            "facet_criteria": criteria,
            "aggregate": op.aggregate,
            "compare": op.compare,
            "period": op.period,
            "relate": op.relate,
        }
    )


# ── v2: the prompt view and the bounded inspection ───────────────────────────────────────


def _promptable(facet: "Facet") -> bool:
    """A facet the facet section may list: about a space, recorded rather than sensed, and of a
    value type some operator fits. Sensors stay in the modality list, exactly as v1 lists them.
    """
    if facet.source_kind == "sensor" or facet.entity_type != "space":
        return False
    if facet.value_type == _INTERVAL:
        return False  # an event source is listed in its own section, for relate only
    if facet.source_kind == "event":
        return True
    return facet.value_type in _OPERATORS_BY_VALUE_TYPE or facet.key == _FLOOR_FACET


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(json.dumps(str(v), ensure_ascii=False) for v in values)


def _facet_values_text(facet: "Facet") -> str:
    if facet.key == _FREE_WINDOW_FACET:
        return "hours"
    if facet.value_type == "boolean":
        return "true / false"
    if facet.value_type == "enum" and facet.examples:
        prefix = "one of: " if value_set_complete(facet) else "e.g. "
        return prefix + _quoted(facet.examples)
    if facet.examples and facet.value_type in ("number", "integer"):
        return "e.g. " + ", ".join(str(v) for v in facet.examples)
    if facet.examples:
        # Recorded text holds commas of its own ("East-facing, morning sun"): quoted, so one
        # example cannot read as two.
        return "e.g. " + _quoted(facet.examples)
    return "-"


def _facet_line(facet: "Facet") -> str:
    value_type = "event" if facet.source_kind == "event" else facet.value_type
    return (
        f"- {facet.key} | {facet.label} | {value_type} | {facet.unit or '-'} | "
        f"{_facet_values_text(facet)}"
    )


class _FacetPromptView:
    """The facets one compile is shown: the retrieval shortlist, plus what inspection added."""

    def __init__(self, catalogue: "FacetCatalogue", query: str) -> None:
        self.listed: Dict[str, "Facet"] = {}
        for _, facet in catalogue.retrieve(query, k=FACET_SHORTLIST_K, min_status="suitable"):
            if _promptable(facet):
                self.listed[facet.key] = facet
        self.value_sets: Dict[str, tuple] = {}
        # Event sources (C5): the ones the question names first, then the rest, bounded. A
        # building has few, and the model needs their keys to relate a reading to one.
        events = {f.key: f for f in catalogue.match_event_sources(query)}
        for facet in catalogue.event_sources():
            events.setdefault(facet.key, facet)
        self.events: List["Facet"] = list(events.values())[:_MAX_EVENT_LINES]

    def facet_lines(self) -> str:
        if not self.listed:
            return "- (no recorded facet matched this question)"
        return "\n".join(_facet_line(f) for f in self.listed.values())

    def event_lines(self) -> str:
        if not self.events:
            return "- (this building records no events placed in a space and on the clock)"
        lines = []
        for facet in self.events:
            span = (
                f"{facet.examples[0]} to {facet.examples[-1]}" if len(facet.examples) >= 2 else "-"
            )
            lines.append(f"- {facet.key} | {facet.label} | in {facet.coverage} space(s) | {span}")
        return "\n".join(lines)

    def inspection_block(self) -> str:
        if not self.value_sets:
            return ""
        lines = ["", "Values present in the building's records for the facets inspected:"]
        for key, values in self.value_sets.items():
            lines.append(f"- {key}: {_quoted(values)}")
        return "\n".join(lines) + "\n"


def _facet_prompt(query: str, modalities: List[ModalitySpec], view: _FacetPromptView) -> str:
    return _PROMPT_FACETS.format(
        modality_lines=_modality_lines(modalities),
        facet_lines=view.facet_lines(),
        event_lines=view.event_lines(),
        inspection_block=view.inspection_block(),
        query=query,
    )


async def _full_value_set(facet: "Facet", value_reader: Optional[ValueReader]) -> tuple:
    """Every value a facet holds: the catalogue's own set when complete, else a graph read."""
    if value_set_complete(facet) or value_reader is None:
        return tuple(facet.examples)
    try:
        values = await value_reader(facet)
    except Exception as exc:  # inspection is an aid, never a failure path
        logger.info(f"[compiler] could not read the values of {facet.key}: {exc}")
        return tuple(facet.examples)
    distinct = sorted({str(v).strip() for v in values or () if str(v).strip()}, key=str.lower)
    return tuple(distinct[:_MAX_VALUES_SHOWN])


async def _inspect(
    cqir: CQIR,
    notes: Dict[str, Any],
    catalogue: "FacetCatalogue",
    view: _FacetPromptView,
    value_reader: Optional[ValueReader],
) -> List[str]:
    """ONE round of the bounded, read-only, deterministic inspection. Returns what it ADDED.

    Two tools, and the model chooses neither the query nor the code behind them:
      facet_search(term)   ``catalogue.retrieve(term, k=5, min_status="suitable")`` for every
                           term still unmapped and every word the model asked to inspect;
      describe_facet(key)  the facet's whole value set, for every facet the model asked to
                           inspect and every facet whose value failed validation.
    Nothing new means nothing to recompile with: the caller stops.
    """
    added: List[str] = []
    requests = list(notes.get("inspect") or [])
    terms = [s.phrase for s in cqir.signals if s.kind == "unmapped_term" and s.phrase]
    terms += [r for r in requests if catalogue.get(r) is None]
    for term in list(dict.fromkeys(terms))[:_MAX_INSPECT_TERMS]:
        for _, facet in catalogue.retrieve(term, k=_INSPECT_K, min_status="suitable"):
            if _promptable(facet) and facet.key not in view.listed:
                view.listed[facet.key] = facet
                added.append(f"facet {facet.key} (for '{term}')")
    keys = [r for r in requests if catalogue.get(r) is not None]
    keys += list(notes.get("invalid_keys") or [])
    for key in list(dict.fromkeys(keys)):
        facet = catalogue.get(key)
        if facet is None or not _promptable(facet) or key in view.value_sets:
            continue
        if key not in view.listed:
            view.listed[key] = facet
            added.append(f"facet {key}")
        values = await _full_value_set(facet, value_reader)
        if values and set(values) != set(facet.examples):
            view.value_sets[key] = values
            added.append(f"{len(values)} recorded values of {key}")
    return added


async def _compile_with_facets(
    query: str,
    modalities: List[ModalitySpec],
    catalogue: "FacetCatalogue",
    llm_call: Optional[LlmCall],
    *,
    use_cache: bool,
    value_reader: Optional[ValueReader],
) -> CQIR:
    """The v2 compile: one structured call over sensors + facets, then bounded inspection."""
    if llm_call is None:  # pragma: no cover - live wiring
        llm_call = _default_llm_call(facets=True)
    known = {m.name for m in modalities}
    view = _FacetPromptView(catalogue, query)

    cache_key = ""
    if use_cache and _cache_enabled():
        try:
            cache_key = _compile_cache_key(query, modalities, catalogue=catalogue)
            from orchestrator.redis_manager import redis_manager

            cached = await redis_manager.get_cache(cache_key)
            if isinstance(cached, str) and cached.strip():
                # The cached text is the FINAL compile of the bounded loop, so replaying it
                # repeats neither the inspection nor the recompiles.
                logger.debug("[cqir] compile cache hit (facets)")
                return _parse_compiled(cached, query, known, catalogue=catalogue)
        except Exception as exc:  # cache is an optimisation; never a failure path
            logger.debug(f"[cqir] compile cache unavailable: {exc}")
            cache_key = ""

    started = time.monotonic()
    try:
        raw = await llm_call(_facet_prompt(query, modalities, view))
    except Exception as exc:
        logger.error(f"[cqir] LLM call failed: {exc}")
        return CQIR(
            decision=DecisionKind.SELECT_ONE,
            raw_query=query,
            signals=[
                AmbiguitySignal(kind="vague", phrase=query, note=f"compiler LLM error: {exc}")
            ],
        )
    notes: Dict[str, Any] = {}
    cqir = _parse_compiled(raw, query, known, catalogue=catalogue, notes=notes)
    logger.info(
        f"[cqir] facet compile: {len(view.listed)} facet(s) shown, "
        f"{len(cqir.facet_criteria)} facet criterion(s), {len(cqir.constraints)} sensor "
        f"constraint(s), {len(cqir.signals)} signal(s)"
    )

    for round_no in range(1, MAX_RECOMPILES + 1):
        if not (
            any(s.kind == "unmapped_term" for s in cqir.signals)
            or notes.get("inspect")
            or notes.get("invalid_keys")
        ):
            break
        # THE INSPECTION IS THE OPTIONAL STEP, and it costs a whole LLM call. Measured on a
        # development capture, 2026-10-08: under four concurrent questions on the shared gateway
        # two escalated questions spent their 300 s deadline queueing for compile and recompile
        # and reached no answer. When the compile has already taken this long, the plan in hand
        # is kept -- an unmapped word is then dropped and DECLARED, as it always is.
        if time.monotonic() - started > INSPECTION_BUDGET_S:
            logger.info(
                f"[cqir] inspection round {round_no} skipped: compile already took "
                f"{time.monotonic() - started:.0f}s (budget {INSPECTION_BUDGET_S:.0f}s)"
            )
            break
        added = await _inspect(cqir, notes, catalogue, view, value_reader)
        if not added:
            logger.info(f"[cqir] inspection round {round_no}: nothing new — compile kept")
            break
        logger.info(f"[cqir] inspection round {round_no}: added {added}; recompiling")
        try:
            raw = await llm_call(_facet_prompt(query, modalities, view))
        except Exception as exc:
            logger.warning(f"[cqir] recompile {round_no} failed, keeping the last compile: {exc}")
            break
        notes = {}
        cqir = _parse_compiled(raw, query, known, catalogue=catalogue, notes=notes)

    if cache_key:
        try:
            from orchestrator.redis_manager import redis_manager

            await redis_manager.set_cache(cache_key, raw, ttl=_COMPILE_CACHE_TTL)
        except Exception as exc:  # storing is best-effort
            logger.debug(f"[cqir] could not store compile: {exc}")
    return cqir


# V5-T25 — availability / booking-pressure phrases are folded DETERMINISTICALLY
# (like the horizon fold): the closed-vocabulary LLM prompt stays untouched and


def _default_llm_call(facets: bool = False) -> LlmCall:
    """The compiler's own LLM call — schema-constrained when `STRUCTURED_PLAN_ENABLED`.

    ``facets`` selects the v2 schema (with ``facet_criteria`` and ``inspect``) for the facet
    compiler; the v1 compiler keeps the v1 schema.

    Both branches return TEXT, and that is the point: everything downstream of the call
    (the raw-text compile cache, `_parse_compiled`, every deterministic fold) is untouched
    by the flag. The structured branch changes only WHERE the JSON's shape is enforced —
    at the provider and at a validator, rather than at a regex over free text.

    A structured failure propagates as `StructuredGenerationError`, which `compile_query`
    catches like any other LLM error and turns into a `vague` AmbiguitySignal: the question
    goes to clarify. It never becomes a half-read plan.
    """
    from orchestrator.llm_manager import llm_manager
    from shared.config import settings

    if not getattr(settings, "STRUCTURED_PLAN_ENABLED", False):

        async def _free_text(prompt: str) -> str:
            from orchestrator.llm_manager import EmptyCompletionError

            try:
                return await llm_manager.generate(prompt, temperature=0.0)
            except EmptyCompletionError as exc:
                if not facets:
                    raise  # the v1 compile, byte for byte
                # A REASONING MODEL CAN THINK PAST ANY BUDGET. Measured 2026-10-08: "how does the
                # number of people on each floor compare with its capacity?" spent 4,096 and then
                # 8,192 tokens on hidden reasoning and returned nothing, twice. One retry at LOW
                # effort -- which compiled valid plans in under two seconds on the same day -- is
                # better than no plan: a weaker plan is still checked by every rule below.
                logger.warning(f"[cqir] compile returned nothing ({exc}); retrying at low effort")
                return await llm_manager.generate(
                    prompt, temperature=0.0, provider_kwargs={"reasoning_effort": "low"}
                )

        return _free_text

    schema = _cqir_schema(facets=facets)

    async def _structured(prompt: str) -> str:
        obj = await llm_manager.generate_structured(
            prompt,
            schema,
            schema_name=CQIR_SCHEMA_NAME,
            temperature=0.0,
        )
        return json.dumps(obj)

    return _structured


async def compile_query(
    query: str,
    modalities: List[ModalitySpec],
    llm_call: Optional[LlmCall] = None,
    *,
    use_cache: bool = True,
    catalogue: Optional["FacetCatalogue"] = None,
    value_reader: Optional[ValueReader] = None,
) -> CQIR:
    """Compile a NL constraint query into a validated CQIR (signals on anything unclear).

    ``use_cache=False`` forces a fresh compile. The multi-model benchmark MUST pass it:
    with the cache on, a repeat measures the cache, not the compiler (CAVEAT-327).

    v2: given a facet ``catalogue`` (and ``ARBITER_FACETS_ENABLED``), the compile also maps
    requirements onto facets of the graph, with a bounded inspection step
    (`_compile_with_facets`). ``catalogue=None`` -- or the flag off -- is the v1 compile,
    byte for byte: same prompt, same cache key, same parse.
    """
    if catalogue is not None and not facets_enabled():
        catalogue = None  # the flag is authoritative at every layer, not only at the caller
    if catalogue is not None:
        return await _compile_with_facets(
            query,
            modalities,
            catalogue,
            llm_call,
            use_cache=use_cache,
            value_reader=value_reader,
        )
    if llm_call is None:  # pragma: no cover - live wiring
        llm_call = _default_llm_call()

    known = {m.name for m in modalities}
    prompt = _PROMPT.format(modality_lines=_modality_lines(modalities), query=query)

    # The RAW LLM text is what gets cached, not the parsed CQIR. Everything below this
    # point is deterministic validation against a closed vocabulary, so replaying the
    # text reproduces the plan exactly while keeping the cache a single string -- no
    # serialisation of a dataclass graph, and no risk of a cached object drifting out of
    # step with the parser that produced it.
    #
    # CAVEAT-327: the same model at temperature 0 reproduced only 3 of 8 plans between
    # runs, so cross-model agreement (2/8) sat AT OR BELOW the noise floor and no
    # difference could be attributed to the model at all. A repeat of a question now
    # replays its own compile.
    cache_key = ""
    if use_cache and _cache_enabled():
        try:
            cache_key = _compile_cache_key(query, modalities)
            from orchestrator.redis_manager import redis_manager

            cached = await redis_manager.get_cache(cache_key)
            if isinstance(cached, str) and cached.strip():
                logger.debug("[cqir] compile cache hit")
                return _parse_compiled(cached, query, known)
        except Exception as exc:  # cache is an optimisation; never a failure path
            logger.debug(f"[cqir] compile cache unavailable: {exc}")
            cache_key = ""

    raw = ""
    try:
        raw = await llm_call(prompt)
    except Exception as exc:
        logger.error(f"[cqir] LLM call failed: {exc}")
        return CQIR(
            decision=DecisionKind.SELECT_ONE,
            raw_query=query,
            signals=[
                AmbiguitySignal(kind="vague", phrase=query, note=f"compiler LLM error: {exc}")
            ],
        )

    if cache_key:
        try:
            from orchestrator.redis_manager import redis_manager

            await redis_manager.set_cache(cache_key, raw, ttl=_COMPILE_CACHE_TTL)
        except Exception as exc:  # storing is best-effort
            logger.debug(f"[cqir] could not store compile: {exc}")

    return _parse_compiled(raw, query, known)


# V5-T25 — availability / booking-pressure phrases are folded DETERMINISTICALLY
# (like the horizon fold): the closed-vocabulary LLM prompt stays untouched and
# identical phrasings always yield identical criteria.
_FREE_WINDOW_RE = re.compile(
    r"\b(?:free|available|not booked|unbooked|no bookings?)\b.{0,40}"
    r"\b(?:for the next|for|next)\s+(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b",
    re.IGNORECASE,
)
_FREE_NOW_RE = re.compile(
    r"\b(?:free|available|not booked|unbooked)\s+(?:right\s+)?now\b"
    r"|\bcurrently\s+(?:free|available|unbooked)\b"
    r"|\bthat(?:'s| is)\s+(?:free|available|not booked)\b",
    re.IGNORECASE,
)
_LOW_PRESSURE_RE = re.compile(
    r"\brarely booked\b|\bleast booked\b|\blow(?:est)? booking\b|\beasy to book\b"
    r"|\bnot (?:in )?high demand\b|\bseldom (?:booked|used)\b",
    re.IGNORECASE,
)


def _fold_event_criteria(query: str) -> list:
    from orchestrator.services.deliberation.cqir import EventCriterion

    out = []
    m = _FREE_WINDOW_RE.search(query or "")
    if m:
        out.append(
            EventCriterion(kind="free_window", hours=max(0.25, min(24.0, float(m.group(1)))))
        )
    elif _FREE_NOW_RE.search(query or ""):
        out.append(EventCriterion(kind="free_window", hours=1.0))
    if _LOW_PRESSURE_RE.search(query or ""):
        out.append(EventCriterion(kind="low_booking_pressure"))
    return out


def _num(value) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# BUG-183 — historical windows had no deterministic pass. Forecast horizons get
# one (below), so "tomorrow" always means the same thing; but a past phrase rested
# entirely on the compiler LLM's judgement, and it flagged "yesterday" — one of the
# most common words in the question corpus — as unparseable. That became an
# AmbiguitySignal, which made the CQ-IR non-executable, which made the admission
# gate return CLARIFY before any fetch. A facility manager asking "which rooms had
# the highest occupancy yesterday?" was told the request could not be mapped.
#
# Phrases here are resolved in CODE and their signal dropped. Genuinely vague
# anchors ("recently", "a while back", "lately") are deliberately absent: those
# SHOULD clarify rather than be guessed into a window.
#
# "yesterday" and "today" USED TO BE HERE, both mapped to 24.0 hours (V12-08). Two
# different days resolved to the same duration, and `fetch.py` turned that duration into
# `utcnow() - 24h` with no upper bound — so an ARBITER answer about yesterday was computed
# over a rolling window ending now, half of it today, in UTC rather than the building's
# zone. That is BUG-480 exactly, in the lane where it was never fixed.
#
# A named calendar day is not a duration and cannot be expressed in this table at all. It
# is resolved to ABSOLUTE BOUNDS by `_fold_named_calendar_day` below, from the one resolver
# in services/requested_interval.py.
_PAST_WINDOW_HOURS = (
    (r"\blast\s+night\b", 12.0),
    (r"\b(?:this|the)\s+morning\b", 12.0),
    (r"\b(?:this|the)\s+afternoon\b", 12.0),
    (r"\b(?:last|past|previous)\s+hour\b", 1.0),
    (r"\b(?:last|past|previous)\s+(\d+)\s*hours?\b", None),  # captured number
    (r"\b(?:last|past|previous)\s+(\d+)\s*days?\b", None),
    (r"\b(?:last|past|previous|this)\s+week\b", 168.0),
    (r"\b(?:last|past|previous|this)\s+month\b", 720.0),
    (r"\bovernight\b", 12.0),
    # "so far today" left with the other named days (V12-08): as 24.0 it meant "24 hours
    # ending now", which reaches back into yesterday. It resolves to today's bounds, and a
    # store holding no future rows returns exactly the part of the day that has happened.
)
_PAST_WINDOW_RES = [
    (re.compile(pattern, re.IGNORECASE), hours) for pattern, hours in _PAST_WINDOW_HOURS
]


def match_past_window(query: str) -> Optional[float]:
    """Hours of history a recognised past phrase means, or None if unrecognised."""
    for rx, hours in _PAST_WINDOW_RES:
        m = rx.search(query or "")
        if not m:
            continue
        if hours is not None:
            return hours
        try:
            n = float(m.group(1))
        except (IndexError, ValueError):
            continue
        # the pattern that captured a number tells us its unit by its own text
        return n * (24.0 if "day" in m.group(0).lower() else 1.0)
    return None


_RANKING_DECISIONS = (
    DecisionKind.RANK_ALL,
    DecisionKind.SUPERLATIVE,
    DecisionKind.SELECT_ONE,
)

#: A threshold direction and the preference direction with the same polarity.
_UNBOUNDED_EQUIVALENT = {
    Direction.ABOVE: Direction.MAXIMIZE,
    Direction.BELOW: Direction.MINIMIZE,
}


#: The user asked for the BAD end of air quality. The direction the compiler model returned for an
#: "air quality" phrase cannot be trusted either way ("best" comes back as MAXIMIZE as often as
#: MINIMIZE, which is why the fold below ignores it), so the question's own words decide.
_WORST_AIR_RE = re.compile(
    r"\b(?:worst|poorest|unhealthiest|most\s+polluted|most\s+unhealthy|lowest\s+quality)\b",
    re.IGNORECASE,
)


def _fold_air_quality(constraints: list) -> list:
    """'Air quality' ranks on CO2 and PM2.5, never on the unit-mixed air_quality modality (WB-16).

    `air_quality` gathers every Air_Quality_Sensor — CO2 in ppm next to index-scale devices —
    so no single cited band can score it, and "which room has the best air quality right now?"
    declined building-wide with "no scorable data". CO2 (ASHRAE 62.1) and PM2.5 (WHO 2021) each
    carry a standard; better air is LOWER of both, so "worst" is the HIGHER end of both — "Which
    rooms have the worst air quality right now?" returned the room with the LOWEST CO2, the best
    air in the building, because this fold always minimised (BUG-823). An explicit co2/pm25
    constraint is kept.
    """
    if not any(c.modality == "air_quality" for c in constraints):
        return constraints
    kept = [c for c in constraints if c.modality != "air_quality"]
    template = next(c for c in constraints if c.modality == "air_quality")
    present = {c.modality for c in kept}
    direction = (
        Direction.MAXIMIZE
        if _WORST_AIR_RE.search(getattr(template, "source_phrase", None) or "")
        else Direction.MINIMIZE
    )
    for modality in ("co2", "pm25"):
        if modality not in present:
            kept.append(
                Constraint(
                    modality=modality,
                    direction=direction,
                    hardness=template.hardness,
                    threshold=None,
                    threshold_source=ThresholdSource.RECIPE,
                    source_phrase=template.source_phrase,
                )
            )
    return kept


def _fold_unbounded_threshold_direction(
    constraints: List[Constraint], decision: DecisionKind
) -> None:
    """Turn "above, but no number" into a real ordering (BUG-197).

    BELOW and ABOVE are *filter* directions: they mean something only against a
    number. When the compiler LLM answers a ranking with one of them and no
    threshold — which it does for "rank the zones by CO2", where there is no
    number to give — the scorer substitutes the anchor's own edge, and every
    candidate lands on the pass side of it. For CO2 that edge is 420 ppm, which
    every occupied room is above, so all utilities come out at exactly 1.0 and
    the "ranking" is a tie decided alphabetically.

    An alphabetical list presented as a CO2 ranking is a plausible answer with
    no basis behind it, which is the one thing this system must never emit. The
    polarity the model expressed is still usable, so keep it and drop the
    filter framing: ABOVE becomes MAXIMIZE, BELOW becomes MINIMIZE, and the
    candidates spread across the band as an ordering the dossier can defend.

    Only ranking decisions are touched. LIST_MATCHING with no bound is a
    genuinely under-specified filter and keeps its ambiguity.
    """
    if decision not in _RANKING_DECISIONS:
        return
    for c in constraints:
        if c.threshold is None and c.direction in _UNBOUNDED_EQUIVALENT:
            was = c.direction
            c.direction = _UNBOUNDED_EQUIVALENT[was]
            logger.info(
                f"[compiler] {c.modality}: {was.value} with no threshold in a "
                f"{decision.value} -> {c.direction.value} (a bound-less filter cannot rank)"
            )


#: Phrases that scope a question to the WHOLE building rather than naming a place inside it.
#: Generic English only — the building's own name is stripped separately, from its config, so
#: nothing here has to know what this building is called.
_WHOLE_BUILDING_SCOPE_RE = re.compile(
    r"^(?:in|at|across|throughout|within|around|over)?\s*"
    r"(?:anywhere|somewhere|everywhere|any\s*(?:room|rooms|space|spaces|zone|zones|area|areas)"
    r"|(?:the\s+)?(?:whole|entire|complete)\s+(?:building|site|premises|place)"
    r"|(?:the\s+)?building\s*-?\s*wide"
    r"|(?:the\s+)?(?:building|site|premises)"
    # Carried over from the pattern this replaced — "all floors" scopes to everywhere too,
    # and dropping it while consolidating would have been a silent regression.
    r"|(?:all|every|each)\s+(?:floor|floors|level|levels|room|rooms|space|spaces|zone|zones)"
    # A bare PLURAL space noun names no particular place: "which rooms in the building are
    # the stuffiest" compiled "rooms in the building" as a spatial anchor and could not
    # resolve it, so the question became unexecutable after "stuffiest" had been fixed. The
    # singular is deliberately absent — "room 5.01" and "the room" DO name somewhere.
    r"|(?:rooms|spaces|zones|areas|floors|levels)"
    r"|overall|in\s+general)"
    r"(?:\s*(?:in|of|at|across|within|throughout)?\s*(?:the\s+)?"
    r"(?:building|site|premises|place))?\s*$",
    re.IGNORECASE,
)


#: A digit ("2.01", "floor 3") or a Capitalised word that is not the sentence's first — the two
#: shapes a NAMED space takes in a stakeholder's words, in any building. A phrase with neither
#: names no particular space.
_NAMED_SPACE_RE = re.compile(r"\d|(?<=\s)[A-Z][a-zA-Z]")


def _looks_like_a_named_space(phrase: str) -> bool:
    """True when the phrase could be naming one space (BUG-755).

    Deliberately generous: this decides whether an EMPTY anchor is treated as the default
    whole-building scope or kept as an ambiguity to ask about, and widening a question the
    user scoped to one room is the worse error of the two.
    """
    text = (phrase or "").strip()
    if not text:
        return False
    return bool(_NAMED_SPACE_RE.search(text))


def _is_whole_building_scope(phrase: str) -> bool:
    """True when the phrase says 'everywhere' rather than naming somewhere.

    A question scoped to the whole building carries no spatial anchor, which is this lane's
    default — so treating the phrase as an unresolved term denies a question the building can
    answer completely.
    """
    text = (phrase or "").strip().lower().strip(".,!?")
    if not text:
        return False
    # The building may be named rather than called "the building": "anywhere in <name>".
    # Taken from the active building's own config, never written in here.
    try:
        from shared.config import settings

        name = (getattr(settings, "BUILDING_NAME", "") or "").strip().lower()
        if name:
            text = text.replace(name, "building")
            # A name that already ends in the word "building" leaves it doubled.
            text = re.sub(r"\bbuilding(\s+building)+\b", "building", text)
    except Exception:  # the compiler must not depend on a booted stack
        pass
    return bool(_WHOLE_BUILDING_SCOPE_RE.match(text))


def _infer_direction(modality: str, decision: DecisionKind, threshold) -> Optional[Direction]:
    """Supply the missing end of a ranking when a STANDARD names it (BUG-196).

    "Rank all zones by average CO2 over the last week" is not an ambiguous
    question, but a careful compiler LLM emits ``direction: null`` for it —
    the user named the criterion and no preference, so the model correctly
    declines to invent one. Discarding the constraint for that turned a clear
    question into "I couldn't map part of your request", which is a wrongful
    denial: for CO2 the good end is not a matter of taste.

    Two rails keep this from becoming a guess:

    * only modalities in ``DEFAULT_PREFERENCE`` qualify — ranking by temperature
      or occupancy still asks, because there the better end really is a
      preference;
    * a stated ``threshold`` blocks inference entirely. "Rooms below 800 ppm"
      and "rooms above 800 ppm" differ only in direction, so when the user has
      given a number, the direction is load-bearing and must come from them.

    The inferred direction is not hidden: it reaches the dossier as this
    constraint's direction, next to the anchor citation it came from.
    """
    from orchestrator.services.deliberation.scorer import DEFAULT_PREFERENCE

    if threshold is not None:
        return None
    if decision not in (
        DecisionKind.RANK_ALL,
        DecisionKind.SUPERLATIVE,
        DecisionKind.SELECT_ONE,
    ):
        return None
    return DEFAULT_PREFERENCE.get(modality)


def _fold_named_calendar_day(
    time_spec, query: str, tz_name: Optional[str] = None, now=None
) -> bool:
    """Resolve a named calendar day to ABSOLUTE local bounds (V12-08). True when it fired.

    Runs unconditionally and OVERRIDES whatever the compiler LLM produced, for the reason
    the dialogue agent gives for the same override: the question is the authoritative
    source and the compile is one reading of it. Here that matters more, because the thing
    being overridden was not merely imprecise — `yesterday` and `today` both compiled to
    "24 hours", so ARBITER could not tell two different days apart at all.

    FORECAST is left alone. "How will it be today" asks about hours that have not happened,
    and resolving it to a past interval would answer a question nobody asked.

    The zone comes from the building context, never a literal: a day is the occupants'
    Tuesday, not UTC's.
    """
    from orchestrator.services.deliberation.cqir import TimeBasis as _TB
    from orchestrator.services.requested_interval import (
        calendar_day_bounds,
        interval_hours,
    )

    if time_spec.basis == _TB.FORECAST:
        return False
    if tz_name is None and now is None:
        try:
            from orchestrator.services.building_context import resolve_building_context

            _bctx = resolve_building_context(None)
            tz_name = getattr(_bctx, "timezone", None) if _bctx else None
        except Exception:  # pragma: no cover - local time is a sane fallback
            tz_name = None

    bounds = calendar_day_bounds(query, tz_name, now=now)
    if not bounds:
        return False

    start, end = bounds
    if (time_spec.resolved_start, time_spec.resolved_end) != (start, end):
        logger.info(
            "[cqir] calendar day named in the question — interval set to %s .. %s "
            "(compiled basis=%s window_hours=%s)",
            start,
            end,
            time_spec.basis.value,
            time_spec.window_hours,
        )
    time_spec.basis = _TB.WINDOW
    time_spec.resolved_start, time_spec.resolved_end = start, end
    # Kept in step rather than left stale: `EvidenceCell.window_hours` and the dossier both
    # report a span, and a span that disagrees with the interval beside it is the same
    # two-sources-of-truth failure one layer down. DERIVED from the bounds, never asserted.
    time_spec.window_hours = interval_hours(start, end)
    time_spec.unparseable = False
    if not time_spec.source_phrase:
        time_spec.source_phrase = query
    return True


def _fold_deterministic_past_window(time_spec, query: str, unclear: str) -> bool:
    """Resolve a recognised past phrase in code. True when the signal can be dropped.

    Only acts when the LLM actually flagged something OR left a WINDOW basis with
    no window: a clean compile is never second-guessed.
    """
    from orchestrator.services.deliberation.cqir import TimeBasis as _TB

    if not unclear and not (time_spec.basis == _TB.WINDOW and time_spec.window_hours is None):
        return False
    hours = match_past_window(query)
    if hours is None:
        return False
    time_spec.basis = _TB.WINDOW
    time_spec.window_hours = hours
    time_spec.unparseable = False
    if not time_spec.source_phrase:
        time_spec.source_phrase = unclear
    return True


def _fold_deterministic_horizon(time_spec, query: str) -> None:
    """Make the deterministic horizon table the single authority (V5-T12).

    For FORECAST-basis queries, a phrase the trend lane's rule table
    recognizes ("tomorrow", "next week") overrides whatever hours the compiler
    LLM guessed, so ARBITER and the trend lane report identical horizons for
    identical phrases. Unrecognized phrases keep the LLM's number.

    AN UNPARSED PHRASE IS LEFT UNPARSED. This used to write 24.0 in when nothing had
    resolved the phrase, which made the horizon indistinguishable from one the table had
    actually recognised — so row 99's "next Wednesday after 2 p.m." was reported as
    "forecast 24h ahead from recent history", a sentence claiming next Wednesday had been
    projected. The executor still runs on 24 hours when no horizon is given, so the
    computation is unchanged; what changes is that the answer can now say the time it was
    asked about was not the time it projected (clarify_policy owns that sentence, and its
    honest branch was unreachable while this line ran).
    """
    from orchestrator.services.deliberation.cqir import TimeBasis as _TB
    from orchestrator.services.forecasting.horizon_parser import match_horizon

    if time_spec.basis != _TB.FORECAST:
        return
    matched = match_horizon(query)
    if matched is not None:
        time_spec.horizon_hours = matched.total.total_seconds() / 3600.0
