# -*- coding: utf-8 -*-
"""Keeping causal wording inside what the evidence can carry (V6-T33).

Master 12.2's worked example, and acceptance test 5: the system *may* report that temperature
rose after occupancy rose; it *must not* conclude that the occupants caused the overheating.
Both sentences describe the same two series. Only one of them is a claim the data supports.

**Why a guard and not a prompt instruction.** "Do not make causal claims" is unenforceable --
it is a request to a model, checked by nobody, and the failure is silent and fluent. This
project has already learned that shape: BUG-189 fabricated a corridor because nothing checked
the model's spatial claim against the graph, and the fix was a gate, not a better prompt.

**Why not ban causal language outright.** The anomaly-diagnosis lane exists to reason about
causes, and often has the evidence to do it: if the graph asserts that AHU-3 serves 2.15 and
AHU-3 was off, "the room warmed because its air handler was off" is a mechanism, not a guess.
A blanket ban would delete the system's most useful answers in order to prevent its worst, and
the two are distinguishable.

So the guard grades the CLAIM against the SUPPORT (:class:`CausalSupport`) and acts only when
the claim outruns it. Correlation licenses co-occurrence wording and nothing more.

**On rewriting.** Rewriting a model's prose is dangerous -- clumsy surgery turns a correct
answer into gibberish, which is a worse failure than the one being fixed. Two decisions keep
it safe:

* the rewrite works at SENTENCE granularity and never edits inside a clause it did not split;
* the replacement uses a colon (*"Also observed over the same period: ..."*), which reads
  correctly whether the cause was a clause (*"occupancy increased"*) or a noun phrase (*"the
  open window"*). Substituting the connective in place -- "rose coinciding with occupancy
  increased" -- does not.

Like every V6 gate this is **advisory by default**: it reports what it would rewrite and
changes nothing until policy says otherwise. A guard that rewords answers is precisely the one
whose blast radius should be measured before it is switched on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from orchestrator.services.evidence.gates import GateVerdict
from orchestrator.services.evidence.policy import EvidencePolicy
from shared.models import CausalSupport
from shared.utils import get_logger

logger = get_logger(__name__)

GATE = "causal_claim"

#: What each grade of support licenses. MECHANISTIC and INTERVENTIONAL license attribution;
#: the other two do not. Held as a set rather than an ordering because these are not one
#: ladder -- an intervention is not "more correlational" than a correlation.
_LICENSES_ATTRIBUTION = frozenset({CausalSupport.MECHANISTIC, CausalSupport.INTERVENTIONAL})

#: Connectives that ASSERT a cause, grouped by the direction they run in.
#:
#: Direction matters for the rewrite and for nothing else: "A because B" puts the effect
#: first, "B caused A" puts the cause first, and a rewrite that had this backwards would
#: report the effect as the thing that merely co-occurred.
_FORWARD = (  # effect <connective> cause
    "because of",
    "because",
    "due to",
    "owing to",
    "caused by",
    "as a result of",
    "attributable to",
    "on account of",
    "thanks to",
    "as a consequence of",
)
_REVERSE = (  # cause <connective> effect
    "caused",
    "causes",
    "led to",
    "leads to",
    "resulted in",
    "results in",
    "gave rise to",
    "drove",
    "drives",
    "triggered",
    "triggers",
    "is responsible for",
    "was responsible for",
    "are responsible for",
    "explains",
    "explain",
)

#: Wording that is already correlational. Present so the guard can recognise an answer that
#: was ALREADY phrased correctly, rather than treating "coincided with" as a near-miss.
_CORRELATIONAL = (
    "coincided with",
    "coincides with",
    "at the same time as",
    "over the same period",
    "alongside",
    "correlate",
    "associated with",
    "in step with",
)

#: A cause side that refers to the SYSTEM or to data availability, not to the building.
#:
#: This exclusion is load-bearing. "I cannot answer because no readings are recorded for that
#: room" is a causal sentence by every syntactic test, and it is exactly the honest refusal
#: the whole V6 plan exists to produce. A guard that mangled those would damage the answers it
#: was built to protect.
_META_CAUSE = re.compile(
    r"\b(?:i|no|not|none|insufficient|missing|unavailable|unknown|restricted|stale|policy"
    r"|permission|access|nothing|neither|lack|lacks|lacking|absence|absent"
    r"|without|uninstrumented|unrecorded|unreported|declined)\b"
    r"|\b(?:data|readings?|records?|sensors?|coverage)\b[^.]*\b(?:not|lack|absent|empty)\b",
    re.IGNORECASE,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class CausalClaim:
    """One causal assertion found in an answer."""

    sentence: str
    connective: str
    #: The half asserted to be the effect, and the half asserted to be its cause.
    effect: str
    cause: str
    #: True when the cause side is about the system or its data rather than the building.
    is_meta: bool = False

    def restate(self) -> str:
        """The same two observations, with the attribution removed.

        **One template, used for every claim.** The obvious design is two -- keep the effect
        as a sentence and append the cause -- and it breaks on the first passive or transitive
        construction it meets, because there the connective IS the sentence's verb. Removing
        it leaves a fragment:

            "The overheating was caused by the open window."  ->  "The overheating was."
            "High occupancy drove the CO2 above 1000 ppm."    ->  "The CO2 above 1000 ppm."

        Both were produced by an earlier version of this method, and both are worse than the
        overreaching sentence they replaced. Neither half of a causal sentence can be assumed
        to stand alone, so neither is asked to: both are presented after a colon, which reads
        correctly for a clause and a noun phrase alike, and the connective's own verb is never
        load-bearing.
        """
        first, second = _clean(self.effect), _clean(self.cause)
        if not first or not second:
            return self.sentence
        return (
            f"Observed together over the same period: {first}; {second}. "
            "The evidence does not establish that one caused the other."
        )


def find_claims(text: str) -> List[CausalClaim]:
    """Every causal assertion in `text`, with its two halves separated.

    Sentence by sentence, and at most one claim per sentence: a sentence carrying two
    connectives would be split twice and rewritten into something neither half said.
    """
    return [c for c in (_claim_in(s) for s in _sentences(text)) if c is not None]


def unlicensed_claims(text: str, support: CausalSupport) -> List[CausalClaim]:
    """The claims this evidence does not carry. Meta-sentences are never included."""
    if support in _LICENSES_ATTRIBUTION:
        return []
    return [c for c in find_claims(text) if not c.is_meta]


def qualify(text: str, support: CausalSupport) -> str:
    """Rewrite unlicensed causal sentences into what the evidence actually shows.

    Returns `text` unchanged when the support licenses the claim, when there is nothing to
    rewrite, or when a sentence cannot be split cleanly. Leaving prose alone is always safer
    than half-editing it.
    """
    out = text
    for claim in unlicensed_claims(text, support):
        restated = claim.restate()
        if restated != claim.sentence:
            out = out.replace(claim.sentence, restated, 1)
    return out


def causal_gate(policy: EvidencePolicy, text: str, support: CausalSupport) -> GateVerdict:
    """Does the answer's causal wording stay inside its evidence? (V6-T33)

    Fails when an attribution rests on correlational evidence or none. Failing does **not**
    downgrade the answer's status: the observation is still observed, and only its explanation
    overreached. Throwing away a good measurement to punish a bad sentence would be the wrong
    trade, so the remedy is the rewrite.
    """
    mode = policy.gate_mode(GATE)
    claims = unlicensed_claims(text, support)
    if not claims:
        return GateVerdict(gate=GATE, passed=True, mode=mode, threshold=f"support={support.value}")
    first = claims[0]
    return GateVerdict(
        gate=GATE,
        passed=False,
        mode=mode,
        reason=(
            f'the answer states a cause ("{first.connective}") on {support.value} evidence, '
            "which shows that the two changed together but not that one produced the other"
        ),
        remedy=(
            "Report both observations and their timing, and say what would establish a cause: "
            "a controlled change with a measured response, or an asserted serving relation."
        ),
        downgrade_to=None,
        threshold=f"support={support.value}",
    )


def support_from_evidence(
    has_asserted_relation: bool = False,
    has_intervention: bool = False,
    series_compared: int = 0,
) -> CausalSupport:
    """Grade the support available, from facts the caller already holds.

    Kept out of the graph so every branch is testable without one, and so the CALLER decides --
    it is the only party that knows whether it followed a `brick:feeds` edge or merely plotted
    two series next to each other. Inferring this from the answer text would be the same
    mistake the guard exists to prevent.
    """
    if has_intervention:
        return CausalSupport.INTERVENTIONAL
    if has_asserted_relation:
        return CausalSupport.MECHANISTIC
    if series_compared >= 2:
        return CausalSupport.CORRELATIONAL
    return CausalSupport.NONE


def is_already_correlational(text: str) -> bool:
    """True when the answer is phrased as co-occurrence -- nothing here to fix."""
    low = (text or "").lower()
    return any(p in low for p in _CORRELATIONAL) and not find_claims(text)


# -- internals ---------------------------------------------------------------


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]


def _claim_in(sentence: str) -> Optional[CausalClaim]:
    """The first causal connective in one sentence, with the halves either side of it.

    Longer connectives are preferred at the same position so "because of" is not matched as
    "because", which would leave a dangling "of" at the head of the cause.
    """
    low = sentence.lower()
    best: Optional[Tuple[int, int, str, bool]] = None  # (pos, -len, connective, forward)
    for connective in _FORWARD + _REVERSE:
        pos = _find_word(low, connective)
        if pos < 0:
            continue
        key = (pos, -len(connective), connective, connective in _FORWARD)
        if best is None or key[:2] < best[:2]:
            best = key
    if best is None:
        return None

    pos, _, connective, forward = best
    head = sentence[:pos].strip(" ,;")
    tail = sentence[pos + len(connective) :].strip(" ,;")
    if not head or not tail:
        # A sentence that opens or closes on the connective has only one half present, so
        # there is nothing to restate; a rewrite here would silently drop content.
        return None

    effect, cause = (head, tail) if forward else (tail, head)
    return CausalClaim(
        sentence=sentence,
        connective=connective,
        effect=effect,
        cause=cause,
        is_meta=bool(_META_CAUSE.search(cause)),
    )


def _find_word(haystack: str, needle: str) -> int:
    """Position of `needle` on word boundaries, or -1.

    Boundaries matter: without them "explain" matches inside "explained" and "drove" inside
    "drover", each splitting a sentence at a point that is not a connective at all.
    """
    m = re.search(rf"\b{re.escape(needle)}\b", haystack)
    return m.start() if m else -1


#: Auxiliaries and copulas that are left dangling when a passive connective is removed:
#: "The overheating was caused by X" splits to a head of "The overheating was".
_DANGLING = (
    "was",
    "were",
    "is",
    "are",
    "be",
    "been",
    "being",
    "has",
    "have",
    "had",
    "did",
    "does",
    "do",
    "will",
    "would",
    "may",
    "might",
    "can",
    "could",
)

#: Words that carry no content on their own. A half that reduces to one of these is a
#: back-reference to a previous sentence ("This is because the plant restarts"), and there is
#: nothing left to restate once the connective goes.
_CONTENTLESS = frozenset({"this", "that", "it", "these", "those", "there", "the", "a", "an"})


def _clean(fragment: str) -> str:
    """Trim a fragment for use mid-sentence after a colon, or return "" if nothing survives.

    Four jobs, each one earned by an artefact an earlier version actually emitted:

    * strip trailing punctuation, or the template inherits the original full stop and prints
      "1000 ppm..";
    * strip a **dangling auxiliary**, so "the overheating was" reads as "the overheating";
    * report **contentless** halves as empty, so "This is because the plant restarts" is left
      alone rather than restated as "this is" -- the sentence's subject lives in the previous
      sentence, and no rewrite confined to this one can recover it;
    * drop the sentence-initial capital when, and only when, the first word is an ordinary
      word capitalised for being first.

    That last test is deliberately narrow. `CO2`, `AHU-3`, `pH` and `kWh` must survive intact;
    lower-casing a measurand is an error a reader spots instantly. A word whose remaining
    letters are not all lower-case is left exactly as it came.
    """
    frag = fragment.strip().strip(" ,;.!?").strip()
    if not frag:
        return ""

    words = frag.split()
    while len(words) > 1 and words[-1].lower() in _DANGLING:
        words.pop()
    frag = " ".join(words)

    if len(words) == 1 and words[0].lower().strip(",;") in _CONTENTLESS:
        return ""

    head = words[0]
    if head[:1].isupper() and head[1:].islower():
        return frag[0].lower() + frag[1:]
    return frag
