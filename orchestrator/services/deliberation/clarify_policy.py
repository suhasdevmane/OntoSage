"""
clarify_policy.py — clarify-or-proceed with a one-question budget (V4-T21).

The admission gate already decided WHETHER something blocks execution; this
policy turns that verdict into dialogue behavior:

  PROCEED — every default the system chose is DECLARED as an assumption with
            its citation (recipe/standard band, equal weights, time default):
            partial answers with stated assumptions beat interrogation.
  ASK     — exactly ONE question (the admission gate's), with concrete options;
            the compiled CQ-IR parks so the reply RESUMES the plan instead of
            restarting the conversation (the mid-plan resume BUG-146's missing
            binder never allowed).
  DECLINE — zero-coverage modalities: honest, with the missing kinds named.

bind_answer() patches the parked CQ-IR from the user's reply (option number,
exact text, or unique substring). Anything unbindable returns None — the caller
falls back to recompiling with the reply appended, never to guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from orchestrator.services.deliberation.capability_schema import (
    ADMIT,
    CLARIFY,
    AdmissionResult,
    ClarifyQuestion,
)
from orchestrator.services.deliberation.cqir import (
    CQIR,
    SpatialQualifier,
    SpatialRelation,
    ThresholdSource,
    TimeBasis,
)
from orchestrator.services.deliberation.scorer import DEFAULT_ANCHORS, ScoreAnchor
from shared.utils import get_logger

logger = get_logger(__name__)

PENDING_TYPE_PREFIX = "deliberate"  # pending_clarification_type = 'deliberate:<slot>'

_SLOT_RELATION = {
    "floor": SpatialRelation.ON_FLOOR,
    "amenity": SpatialRelation.NEAR_AMENITY,
    "space": SpatialRelation.IN_SPACE,
}


@dataclass
class Assumption:
    text: str
    source: str = ""


@dataclass
class ClarifyDecision:
    action: str  # 'proceed' | 'ask' | 'decline'
    question: Optional[ClarifyQuestion] = None
    assumptions: List[Assumption] = field(default_factory=list)
    pending: Optional[Dict] = None  # serialized state to park for the next turn
    reason: str = ""


def build_assumptions(
    cqir: CQIR, anchors: Optional[Dict[str, ScoreAnchor]] = None
) -> List[Assumption]:
    """Every default the pipeline will apply, declared up front (dossier + prose)."""
    anchors = {**DEFAULT_ANCHORS, **(anchors or {})}
    out: List[Assumption] = []
    for c in cqir.constraints:
        if c.threshold_source == ThresholdSource.USER:
            continue  # the user's own number is not an assumption
        anchor = anchors.get(c.modality)
        if anchor:
            out.append(
                Assumption(
                    text=(
                        f"'{c.source_phrase or c.modality}' scored as {c.direction.value} "
                        f"{c.modality} against the {anchor.lo:g}-{anchor.hi:g} band"
                    ),
                    source=anchor.citation or "default band",
                )
            )
    weights = {c.weight for c in cqir.constraints}
    if len(weights) <= 1:
        out.append(Assumption(text="all stated preferences weighted equally", source="default"))
    if cqir.time.basis == TimeBasis.NOW and not cqir.time.source_phrase:
        out.append(Assumption(text="interpreted as current conditions", source="default"))
    elif cqir.time.basis == TimeBasis.FORECAST:
        out.append(
            Assumption(
                text=f"'{cqir.time.source_phrase or 'future'}' forecast "
                f"{cqir.time.horizon_hours or 24:g}h ahead from recent history",
                source="forecast horizon default" if not cqir.time.horizon_hours else "parsed",
            )
        )
    return out


def absorb_unmapped(cqir: CQIR):
    """Graceful degradation for unmapped terms BEFORE admission.

    A term the building cannot sense should not trap the user in a rephrase
    loop: when mappable constraints EXIST, the unmapped extras are dropped and
    DECLARED (they become assumptions in the answer); when nothing at all
    mapped, the caller should decline naming what the building senses instead
    of asking the user to guess vocabulary.

    Returns (cqir, dropped_phrases, must_decline).
    """
    unmapped = [s for s in cqir.signals if s.kind == "unmapped_term"]
    others = [s for s in cqir.signals if s.kind not in ("unmapped_term", "vague")]
    if not unmapped:
        return cqir, [], False
    if others:
        return cqir, [], False  # real ambiguity remains — normal ask path
    # a LOCATIONAL phrase ("near the aquarium") is a requirement, not a
    # preference — dropping it would silently change what the user asked for,
    # so it stays a blocking signal and takes the clarify path instead
    if any(
        re.search(r"\b(near|next to|beside|close to|by the)\b", s.phrase, re.IGNORECASE)
        for s in unmapped
        if s.phrase
    ):
        return cqir, [], False
    dropped = [s.phrase for s in unmapped if s.phrase]
    if cqir.constraints:
        cqir = cqir.model_copy(deep=True) if hasattr(cqir, "model_copy") else cqir.copy(deep=True)
        cqir.signals = []
        return cqir, dropped, False
    return cqir, dropped, True


def _clarify_off() -> bool:
    """Ablation switch (V4-T29 arm: clarify-off). Read at call time so runs
    can toggle it via env without a restart of the policy module."""
    import os

    return os.environ.get("DELIBERATE_CLARIFY_OFF", "").lower() in ("1", "true", "yes")


def decide(cqir: CQIR, admission: AdmissionResult) -> ClarifyDecision:
    """Admission verdict -> dialogue action. One question max; defaults declared."""
    if admission.verdict == ADMIT:
        return ClarifyDecision(action="proceed", assumptions=build_assumptions(cqir))
    if admission.verdict == CLARIFY and admission.question is not None and _clarify_off():
        # Ablation arm: never ask. Bindable slot -> force the first option and
        # DECLARE the guess; unbindable -> honest decline (never silent-guess
        # vocabulary the user could have disambiguated).
        bindable = admission.question.slot in _SLOT_RELATION and bool(admission.question.options)
        if bindable:
            forced = (admission.question.options or [])[0]
            return ClarifyDecision(
                action="forced_bind",
                question=admission.question,
                reason=f"clarify-off: auto-selected '{forced}' for slot {admission.question.slot}",
                pending={
                    "type": f"{PENDING_TYPE_PREFIX}:{admission.question.slot}",
                    "slot": admission.question.slot,
                    "options": list(admission.question.options or []),
                    "cqir": cqir.model_dump() if hasattr(cqir, "model_dump") else cqir.dict(),
                },
            )
        return ClarifyDecision(
            action="decline", reason=f"clarify-off: unresolvable ambiguity ({admission.reason})"
        )
    if admission.verdict == CLARIFY and admission.question is not None:
        # Park the plan ONLY for bindable slots (concrete options to pick from).
        # A signals-slot ask ("rephrase that part?") stays stateless: the user's
        # next message compiles fresh — parking it would loop the same question.
        bindable = admission.question.slot in _SLOT_RELATION and bool(admission.question.options)
        return ClarifyDecision(
            action="ask",
            question=admission.question,
            reason=admission.reason,
            pending=(
                {
                    "type": f"{PENDING_TYPE_PREFIX}:{admission.question.slot}",
                    "slot": admission.question.slot,
                    "options": list(admission.question.options or []),
                    "cqir": cqir.model_dump() if hasattr(cqir, "model_dump") else cqir.dict(),
                }
                if bindable
                else None
            ),
        )
    return ClarifyDecision(action="decline", reason=admission.reason)


def _resolve_option(reply: str, options: List[str]) -> Optional[str]:
    """Option number, exact text, or UNIQUE substring — else None (never guess)."""
    text = (reply or "").strip()
    if not text:
        return None
    if text.isdigit():
        idx = int(text) - 1
        return options[idx] if 0 <= idx < len(options) else None
    lowered = text.lower()
    for opt in options:
        if opt.lower() == lowered:
            return opt
    partial = [o for o in options if lowered in o.lower() or o.lower() in lowered]
    return partial[0] if len(partial) == 1 else None


def bind_answer(pending: Dict, reply: str) -> Optional[CQIR]:
    """Patch the parked CQ-IR from the reply. None = unbindable -> recompile path."""
    slot = pending.get("slot", "")
    relation = _SLOT_RELATION.get(slot)
    if relation is None:
        return None  # 'signals' and unknown slots need a full recompile with the reply
    chosen = _resolve_option(reply, pending.get("options") or [])
    if chosen is None:
        return None
    try:
        cqir = CQIR(**pending["cqir"])
    except Exception as exc:
        logger.warning(f"[clarify] parked CQ-IR failed to rehydrate: {exc}")
        return None
    kept = [q for q in cqir.spatial if q.relation != relation]
    kept.append(SpatialQualifier(relation=relation, anchor=chosen, source_phrase=reply))
    cqir.spatial = kept
    # the answered slot's ambiguity is resolved; anchor-type signals clear
    cqir.signals = [s for s in cqir.signals if s.kind != "unresolved_anchor"]
    logger.info(f"[clarify] bound '{reply}' -> {slot}={chosen}; plan resumes")
    return cqir
