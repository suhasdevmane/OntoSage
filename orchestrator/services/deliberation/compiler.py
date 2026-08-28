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
from typing import Awaitable, Callable, Dict, List, Optional

from orchestrator.services.deliberation.coverage_audit import ModalitySpec
from orchestrator.services.deliberation.cqir import (
    CQIR,
    AmbiguitySignal,
    Constraint,
    DecisionKind,
    Direction,
    Hardness,
    SpatialQualifier,
    SpatialRelation,
    ThresholdSource,
    TimeBasis,
    TimeSpec,
)
from shared.utils import get_logger

logger = get_logger(__name__)

LlmCall = Callable[[str], Awaitable[str]]

# lay-term hints handed to the LLM per modality (keeps the mapping grounded in
# the SAME vocabulary the coverage audit uses; extended per building via the
# modality config, never hardcoded here)
_LAY_HINTS: Dict[str, str] = {
    "noise": "quiet, silent, loud, noisy, sound level",
    "co2": "stuffy, fresh air, air quality, ventilation, CO2",
    "temperature": "warm, cold, hot, chilly, temperature, cosy",
    "humidity": "humid, damp, dry, muggy",
    "occupancy": "busy, crowded, empty, free, people, occupancy, quiet in terms of people",
    "illuminance": "bright, dark, well-lit, light levels, daylight",
    "door_contact": "door open, door closed, door activity",
    "window_contact": "window open, window closed",
}

_DECISIONS = {d.value for d in DecisionKind}
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


def _modality_lines(modalities: List[ModalitySpec]) -> str:
    lines = []
    for spec in modalities:
        hint = _LAY_HINTS.get(spec.name, "")
        lines.append(f"- {spec.name}" + (f" ({hint})" if hint else ""))
    return "\n".join(lines)


def _normalise_question(query: str) -> str:
    """Collapse the incidental differences between two askings of one question."""
    return " ".join((query or "").lower().split()).strip(" ?!.")


def _compile_cache_key(query: str, modalities: List[ModalitySpec]) -> str:
    """cqir_compile:<sha256> over everything that can change the compiled plan.

    Provider AND model are in the key, deliberately. A key on the question alone
    would hand model B the plan model A compiled, and the multi-model invariance
    benchmark would then be measuring this cache rather than the models -- it would
    report a perfect score for the very property it exists to test. The embedding
    cache already keys on text+provider+model for the same reason.

    The modality set is in the key because a building that gains a modality can
    legitimately compile the same words differently; the prompt is in it because
    editing the prompt is editing the compiler.
    """
    import hashlib

    from shared.config import settings

    provider = str(getattr(settings, "MODEL_PROVIDER", "") or "")
    if provider == "openai":
        model = str(getattr(settings, "OPENAI_MODEL", "") or "")
    else:
        model = str(getattr(settings, "OLLAMA_MODEL", "") or "")

    material = "␟".join(
        [
            _normalise_question(query),
            ",".join(sorted(m.name for m in modalities)),
            provider,
            model,
            hashlib.sha256(_PROMPT.encode("utf-8")).hexdigest()[:16],
        ]
    )
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


def _parse_compiled(raw: str, query: str, known: set) -> CQIR:
    """Validate one raw compiler response into a CQIR.

    Split out of ``compile_query`` so the cache-hit path and the fresh-compile path
    run the SAME validation. Caching a parsed object instead would let a stored plan
    drift out of step with the parser that produced it; caching the text and
    re-validating it cannot.

    Every field is checked against the closed vocabulary here -- anything unknown
    becomes an AmbiguitySignal, never a guess.
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

    _whole_building = re.compile(
        r"^(?:(?:in\s+)?the\s+)?(?:whole|entire|full)?\s*building(?:\s*-?\s*wide)?$"
        r"|^anywhere$|^overall$|^all\s+floors?$",
        re.IGNORECASE,
    )
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
        if _whole_building.match(anchor) or _whole_building.match(
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
            signals.append(
                AmbiguitySignal(
                    kind="unresolved_anchor",
                    phrase=str(s.get("phrase", "")),
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
    resolved_past = _fold_deterministic_past_window(time_spec, query, unclear)
    if unclear and not resolved_past:
        signals.append(AmbiguitySignal(kind="unparseable_time", phrase=unclear))
    for u in data.get("unmapped", []) or []:
        if str(u).strip():
            signals.append(AmbiguitySignal(kind="unmapped_term", phrase=str(u).strip()))

    if not constraints and not any(s.kind == "unmapped_term" for s in signals):
        signals.append(AmbiguitySignal(kind="vague", phrase=query, note="no mappable criteria"))

    return CQIR(
        decision=decision,
        constraints=constraints,
        spatial=spatial,
        time=time_spec,
        signals=signals,
        event_criteria=_fold_event_criteria(query),
        raw_query=query,
    )


# V5-T25 — availability / booking-pressure phrases are folded DETERMINISTICALLY
# (like the horizon fold): the closed-vocabulary LLM prompt stays untouched and


async def compile_query(
    query: str,
    modalities: List[ModalitySpec],
    llm_call: Optional[LlmCall] = None,
    *,
    use_cache: bool = True,
) -> CQIR:
    """Compile a NL constraint query into a validated CQIR (signals on anything unclear).

    ``use_cache=False`` forces a fresh compile. The multi-model benchmark MUST pass it:
    with the cache on, a repeat measures the cache, not the compiler (CAVEAT-327).
    """
    if llm_call is None:  # pragma: no cover - live wiring
        from orchestrator.llm_manager import llm_manager

        async def llm_call(prompt: str) -> str:
            return await llm_manager.generate(prompt, temperature=0.0)

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
_PAST_WINDOW_HOURS = (
    (r"\byesterday\b", 24.0),
    (r"\blast\s+night\b", 12.0),
    (r"\b(?:this|the)\s+morning\b", 12.0),
    (r"\b(?:this|the)\s+afternoon\b", 12.0),
    (r"\btoday\b", 24.0),
    (r"\b(?:last|past|previous)\s+hour\b", 1.0),
    (r"\b(?:last|past|previous)\s+(\d+)\s*hours?\b", None),  # captured number
    (r"\b(?:last|past|previous)\s+(\d+)\s*days?\b", None),
    (r"\b(?:last|past|previous|this)\s+week\b", 168.0),
    (r"\b(?:last|past|previous|this)\s+month\b", 720.0),
    (r"\bovernight\b", 12.0),
    (r"\bso\s+far\s+today\b", 24.0),
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
    identical phrases. Unrecognized phrases keep the LLM's number; a missing
    number defaults to 24 h.
    """
    from orchestrator.services.deliberation.cqir import TimeBasis as _TB
    from orchestrator.services.forecasting.horizon_parser import match_horizon

    if time_spec.basis != _TB.FORECAST:
        return
    matched = match_horizon(query)
    if matched is not None:
        time_spec.horizon_hours = matched.total.total_seconds() / 3600.0
    elif time_spec.horizon_hours is None:
        time_spec.horizon_hours = 24.0
