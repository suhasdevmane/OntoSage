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
    "temperature": "warm, cold, cool, hot, chilly, temperature, cosy",
    "humidity": "humid, damp, dry, muggy",
    "occupancy": "busy, crowded, empty, free, people, occupancy, quiet in terms of people",
    "illuminance": "bright, dark, well-lit, light levels, daylight",
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
def _cqir_schema() -> Dict[str, object]:
    """The CQ-IR compile contract as a JSON schema (built fresh; callers may bind it)."""
    _nullable_number = {"type": ["number", "null"]}
    return {
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

    parts = [
        _normalise_question(query),
        ",".join(sorted(m.name for m in modalities)),
        provider,
        model,
        hashlib.sha256(_PROMPT.encode("utf-8")).hexdigest()[:16],
    ]
    # A schema-constrained compile and a free-text one are different compilers and must not
    # share a cache entry — otherwise turning the flag on replays the plans the old path
    # produced and the acceptance run measures the cache. Appended only when the flag is ON,
    # so every key in a flag-OFF tree is byte-for-byte what it was.
    if getattr(settings, "STRUCTURED_PLAN_ENABLED", False):
        parts.append("structured")
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


def _default_llm_call() -> LlmCall:
    """The compiler's own LLM call — schema-constrained when `STRUCTURED_PLAN_ENABLED`.

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
            return await llm_manager.generate(prompt, temperature=0.0)

        return _free_text

    schema = _cqir_schema()

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
) -> CQIR:
    """Compile a NL constraint query into a validated CQIR (signals on anything unclear).

    ``use_cache=False`` forces a fresh compile. The multi-model benchmark MUST pass it:
    with the cache on, a repeat measures the cache, not the compiler (CAVEAT-327).
    """
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
