# -*- coding: utf-8 -*-
"""Does this answer respond to this question? One local-model check, with a hard fail-open (2D-16 wave 8).

Six unseen sets of stakeholder questions read 148 of 370 hand-labelled answers WEIRD (40%). Every
per-answer fix moved the answers it was shown and left the rate where it was, because the tail is
long. This is the one general lever left: a last check, by the configured model, that an answer is a
sensible response to the question that was asked. It does NOT judge whether a figure is true.

WHAT WAS MEASURED (offline, untuned; `scripts/answer_judge_experiment.py`, recorded in
`docs/phase0/answer_judge_experiment.jsonl`: 372 answers from tails D-I, each hand-labelled)
    * over every lane: it flags 50% of WEIRD answers and 12% of GOOD_ANSWER;
    * it is accurate on the DATA lanes (sensor_data 17/30 weird flagged, 0/10 good; events 8/9, 1/1
      good; automation_capability 5/6; deliberate 3/3; compare 2/3; trend 2/2; planner 2/3) and
      NOISY on the register and document lanes (metadata flags 7 of 62 GOOD wrongly; capability 3 of
      17), which is why those two are NOT in the default lane list;
    * with the default lane list: 48 of 149 WEIRD caught, 2 of 111 GOOD_ANSWER replaced, weird rate
      40.1% -> 27.2%.
THAT LANE CHOICE WAS INFORMED BY THE SAME 372 ANSWERS. The 27.2% is therefore an estimate that
selected its own best case; the true rate has to be confirmed on a set nobody has read. The replay
test pins the measurement, so a prompt or lane edit that changes it fails loudly.

WHAT IT MAY NEVER DO
    * Cost an answer by failing: a timeout, a provider error, an unparsed or unknown verdict leave
      the original answer standing (`RelevanceVerdict.judged` is False).
    * Judge a lane that writes state or a file. The side effect has already happened, and replacing
      the text would tell the user it did not (`NEVER_JUDGED`, applied whatever the setting says).
    * Judge what needs no judging: a standard honest decline, a clarification question, a filing
      confirmation, or anything under `MIN_WORDS` words.
    * Reach the model any way but `llm_manager` (core contract 10), and by plain `generate` only.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

ADDRESSES = "ADDRESSES"
LABELS = ("ADDRESSES", "OFF_TOPIC", "CONTRADICTORY", "GARBLED", "ACTION_MISFIRE")

#: The labels that REPLACE an answer. CONTRADICTORY is judged and logged but never replaces one.
#: 2026-09-20, live: a correct scripted answer ("What is the average TVOC on floor 3 today?", which
#: lists two sensors' averages and names the highest and lowest) was replaced with a decline because
#: the model called it "conflicting average values". In the 372 labelled answers the label fired on
#: two, so giving it up costs nothing measurable; a false positive costs a demo answer.
REPLACING_LABELS = frozenset({"OFF_TOPIC", "GARBLED", "ACTION_MISFIRE"})

#: The lanes the measurement supports. `metadata` and `capability` are absent on purpose.
DEFAULT_LANES = (
    "sensor_data,events,automation_capability,diagnosis,compare,analytics,trend,planner,report,"
    "deliberate,observability,discovery,floor_plan,register,asset_state,anomaly"
)

#: Lanes whose answer describes something the pipeline has ALREADY DONE. Never judged.
NEVER_JUDGED: FrozenSet[str] = frozenset(
    {
        "maintenance",
        "complaint",
        "safety_report",
        "suggestion",
        "feedback",
        "preference_management",
        "alert",
        "control",
        "lab_booking",
        "clarification",
        "greeting",
    }
)

MIN_WORDS = 12
MAX_QUESTION_CHARS = 1200
MAX_ANSWER_CHARS = 2600

#: Copied verbatim from `scripts/answer_judge_experiment.py`, the prompt the measurement used.
SYSTEM = (
    "You audit answers given by a building-information assistant. You are NOT judging whether the "
    "facts are true (you cannot know the building). You judge only whether the answer is a sensible "
    "response to the question that was asked.\n"
    "Return exactly one label:\n"
    "ADDRESSES - the answer responds to what was asked, or honestly says the information is not held.\n"
    "OFF_TOPIC - it answers a different question, a different quantity, or lists unrelated records "
    "or statistics.\n"
    "CONTRADICTORY - it states figures or facts that conflict with each other inside the answer.\n"
    "GARBLED - a broken sentence, a raw identifier or code as the whole answer, or a fragment.\n"
    "ACTION_MISFIRE - it says it saved, filed, logged, queued or changed something the user did not "
    "ask for.\n"
    "Reply on ONE line as: LABEL | reason of at most 12 words."
)

# WHY A ONE-LINE REPLY AND NOT generate_structured (2026-09-20). The first build asked the client for a
# JSON schema. With the local reasoning model that path returns an EMPTY completion on every call
# (the schema-constrained decoder and the model's thinking share one token budget), the client
# retried three times, tripped its circuit breaker, and the gate failed open on all 32 answers of a
# live run - correctly, and uselessly. Plain generation with a one-line label answers in about a
# second and gave the verdicts measured offline.

SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": list(LABELS)},
        "reason": {"type": "string"},
    },
    "required": ["label", "reason"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class RelevanceVerdict:
    """What the gate concluded. ``judged`` is False whenever the answer must simply stand."""

    label: str = ADDRESSES
    reason: str = ""
    judged: bool = False
    skipped: str = ""  # why no call was made, or "error: ..." when one failed

    @property
    def replace(self) -> bool:
        """True only for a real verdict that the answer does not respond to the question."""
        return self.judged and self.label in REPLACING_LABELS


# ── what is not worth a call ─────────────────────────────────────────────────────────────────

_FOOTER = re.compile(r"\n\s*---\s*\n", re.IGNORECASE)
_LEAD_MARKUP = re.compile(r"^[\s*_#>`]+")
_STANDARD_DECLINE = re.compile(
    r"^(?:i\s+did\s+not\s+find|i\s+could\s+not\s+find|i\s+couldn'?t\s+find|"
    r"i\s+couldn'?t\s+answer|i\s+can'?t\s+answer|i\s+cannot\s+answer|"
    r"i\s+found\s+nothing|i\s+don'?t\s+have|i\s+worked\s+out\s+an\s+answer\s+but)\b|"
    r"^[^.\n]{0,80}\bdocuments?\s+do(?:es)?\s+not\s+answer\b|"
    r"^[^.\n]{0,80}\bdoes\s+not\s+exist\b|"
    # the standard declines added since wave 8 (each costs a call and buys a swap of one decline
    # for another, which the paired run on tail K measured six times)
    r"^i\s+couldn'?t\s+tie\s+that\s+question\b|"
    r"^i\s+don'?t\s+hold\b|"
    r"^this\s+building\s+(?:doesn'?t|does\s+not)\s+keep\b|"
    r"^[^.\n]{0,120}\b(?:cannot|can'?t|could\s+not|couldn'?t)\s+answer\s+(?:this|that)\b",
    re.IGNORECASE,
)
_FILING_CONFIRMATION = re.compile(
    r"^(?:i(?:'ve|\s+have)\s+(?:filed|logged|saved|recorded|queued|submitted|noted|raised)|"
    r"(?:thanks|thank\s+you)\b|"
    r"your\s+(?:report|request|suggestion|feedback|preference|booking)\s+(?:has\s+been|was|is)\b)",
    re.IGNORECASE,
)


def _body(answer: str) -> str:
    """The answer without its trailing sources / suggestions block."""
    m = _FOOTER.search(answer or "")
    return (answer or "")[: m.start()] if m else (answer or "")


def skip_reason(answer: str, lane: Optional[str]) -> str:
    """Why this answer is not judged, or "" when it is worth a call."""
    body = _body(answer).strip()
    if len(body.split()) < MIN_WORDS:
        return "too short to judge"
    lead = _LEAD_MARKUP.sub("", body).replace("’", "'")
    if _STANDARD_DECLINE.search(lead):
        return "already an honest decline"
    if _FILING_CONFIRMATION.search(lead):
        return "a filing or control confirmation"
    if body.rstrip().endswith("?"):
        return "a clarification question"
    return ""


def lanes(configured: Optional[str] = None) -> FrozenSet[str]:
    """The lanes to judge: the setting's list, minus every lane that writes state or a file."""
    raw = DEFAULT_LANES if configured is None else configured
    return frozenset(x.strip() for x in str(raw).split(",") if x.strip()) - NEVER_JUDGED


def judges_lane(lane: Optional[str], configured: Optional[str] = None) -> bool:
    """True when ``lane`` is one the gate may judge."""
    return bool(lane) and str(lane) in lanes(configured) and str(lane) not in NEVER_JUDGED


# ── the judge ────────────────────────────────────────────────────────────────────────────────


def _client() -> Any:
    """The project's provider-independent model client (a seam the tests replace)."""
    from orchestrator.llm_manager import llm_manager

    return llm_manager


def _task_type() -> Any:
    from orchestrator.llm_manager import TaskType

    return TaskType.INTENT


def _timeout_s() -> float:
    try:
        from shared.config import settings

        value = float(getattr(settings, "ANSWER_RELEVANCE_TIMEOUT_S", 8.0))
        return value if value > 0 else 8.0
    except Exception:
        return 8.0


async def relevance_verdict(
    question: str, answer: str, lane: Optional[str], timeout_s: Optional[float] = None
) -> RelevanceVerdict:
    """Whether ``answer`` responds to ``question``. Never raises; every failure leaves it standing."""
    if lane in NEVER_JUDGED:
        return RelevanceVerdict(skipped=f"lane {lane!r} writes state or a file")
    why = skip_reason(answer, lane)
    if why:
        return RelevanceVerdict(skipped=why)
    # The question goes on ONE line beside its label: `QUESTION:` alone on a line is what the
    # client's empty-slot check reads as a missing question, and it warned on every judged answer.
    one_line = " ".join((question or "").split())[:MAX_QUESTION_CHARS]
    prompt = f"QUESTION: {one_line}\n\nANSWER: {(answer or '').strip()[:MAX_ANSWER_CHARS]}"
    limit = float(timeout_s) if timeout_s else _timeout_s()
    try:
        raw = await asyncio.wait_for(
            _client().generate(
                prompt,
                system_message=SYSTEM,
                temperature=0,
                task_type=_task_type(),
            ),
            timeout=limit,
        )
    except asyncio.TimeoutError:
        return RelevanceVerdict(skipped=f"error: timed out after {limit:g}s")
    except Exception as exc:  # a judge must never cost an answer
        return RelevanceVerdict(skipped=f"error: {type(exc).__name__}")
    label, reason = parse_verdict(raw)
    if label not in LABELS:
        return RelevanceVerdict(skipped="error: unparsed verdict")
    return RelevanceVerdict(label=label, reason=reason, judged=True, skipped="")


_LABEL_LINE = re.compile(
    r"^\W*(" + "|".join(LABELS) + r")\b\W*(?:[|:\-–—]\s*)?(.*)$", re.IGNORECASE | re.DOTALL
)


def parse_verdict(raw: Any) -> "tuple[str, str]":
    """(label, reason) from a one-line reply, tolerating JSON and stray markup. ("", "") if neither."""
    if isinstance(raw, dict):  # a client that already parsed it
        return str(raw.get("label", "")).strip().upper(), str(raw.get("reason", ""))[:120]
    text = str(raw or "").strip()
    if not text:
        return "", ""
    if text.startswith("{"):
        try:
            data = json.loads(text)
            return str(data.get("label", "")).strip().upper(), str(data.get("reason", ""))[:120]
        except ValueError:
            pass
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    m = _LABEL_LINE.match(first)
    if not m:
        return "", ""
    return m.group(1).upper(), m.group(2).strip()[:120]
