# -*- coding: utf-8 -*-
"""Labelled general guidance for a building-knowledge question that needs no building data.

Owner policy (2026-09-19): answer more, honestly. "Does humidity affect CO2 sensor accuracy?",
"how do I control CO2?", "how do BREEAM and LEED differ?" and "what does a delta-T mean?" ask for
knowledge, not for a reading. The routing contract sends them here (``guidance_shape`` decides and
``guidance_node`` connects); this module WRITES the answer and holds the answer to five rules that
no prompt alone can guarantee, so they are enforced on the text after the model has spoken:

1. it is LABELLED at the top, so it can never be mistaken for something this building recorded;
2. it is SHORT (at most 120 words in all, label and pointer included);
3. it states NO building-specific fact and NO figure that the question did not itself contain -- a
   textbook value ("below 1000 ppm") is exactly the kind of number that gets read as this
   building's target, so a sentence carrying one is dropped;
4. it names a standard only if the project's own standards data holds it (or the question named it);
5. it ends with a pointer to what THIS building can tell the reader, written by code, not by the
   model, so the closing sentence cannot be skipped.

The model call is injectable, so every rule is unit-tested with a fake. On any failure the function
returns "" and the caller says what happened; it never returns an unlabelled or unchecked answer.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    FrozenSet,
    Iterable,
    List,
    Optional,
    Set,
    Union,
)

from shared.utils import get_logger

logger = get_logger(__name__)

#: The label every guidance answer carries (guidance_node.LABEL is the same string).
LABEL = "General guidance (not from this building's records):"

#: The closing pointer, written by code so the model cannot omit or reword it.
POINTER = (
    "For this building's own readings and records, ask about a room, a floor or a record and I "
    "will answer from those."
)

#: Words in all: label + body + pointer.
MAX_WORDS = 120

_STANDARDS_DIR = Path(__file__).resolve().parents[1] / "data" / "standards"

LlmCall = Callable[[str, str], Union[str, Awaitable[str]]]


# ── the standards the project holds ──────────────────────────────────────────────────────────


def _norm_standard(text: str) -> str:
    """'ISO 50001:2018' / 'iso50001' -> 'iso50001'; a comparison key, never shown."""
    core = re.sub(r"[:\-]\s*\d{4}\b", "", text.lower())
    return re.sub(r"[^a-z0-9]", "", core)


@lru_cache(maxsize=1)
def allowed_standards() -> FrozenSet[str]:
    """Comparison keys of every standard named in the project's standards data."""
    keys: Set[str] = set()
    try:
        data = json.loads((_STANDARDS_DIR / "comfort_standards.json").read_text(encoding="utf-8"))
    except Exception as exc:  # no data means no standard may be cited, which is the safe side
        logger.debug(f"[general_guidance] standards data unreadable: {exc}")
        return frozenset()
    for key, body in (data or {}).items():
        keys.add(_norm_standard(str(key)))
        name = str((body or {}).get("name", "")) if isinstance(body, dict) else ""
        for part in re.split(r"\s*/\s*", name):
            if part.strip():
                keys.add(_norm_standard(part))
                first = re.match(r"([A-Za-z]+(?:\s+(?:Standard\s+)?\d+[\w.\-]*)?)", part.strip())
                if first:
                    keys.add(_norm_standard(re.sub(r"\bStandard\b", "", first.group(1))))
                acronym = re.match(r"[A-Za-z]+", part.strip())
                if acronym:  # naming the body ("ASHRAE") is naming a standard the project holds
                    keys.add(_norm_standard(acronym.group(0)))
    keys.discard("")
    return frozenset(keys)


def standard_names() -> List[str]:
    """Display names of the standards the project holds, for the prompt."""
    try:
        data = json.loads((_STANDARDS_DIR / "comfort_standards.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    return [
        str(b.get("name")) for b in (data or {}).values() if isinstance(b, dict) and b.get("name")
    ]


# What looks like a citation of a standard. Broad on purpose: anything matched that is neither in
# the standards data nor in the question is not allowed to stand.
_STANDARD_RE = re.compile(
    r"\b(?:ASHRAE(?:\s+Standard)?(?:\s+\d+(?:\.\d+)?)?|ISO\s*\d{3,5}(?::\d{4})?|"
    r"EN\s*\d{4,5}(?:-\d+)?|CIBSE(?:\s+(?:Guide|TM|AM|KS)\s*\w*)?|BS\s*\d{3,5}|BREEAM|LEED|"
    r"WELL(?:\s+Building\s+Standard)?|Passivhaus|Part\s+[A-Z]\b|HTM\s*\d+|SBEM|NABERS|"
    r"Green\s+Star|DGNB|Energy\s+Star|Fitwel)\b"
)


# ── the checks that run on the model's text ──────────────────────────────────────────────────

#: A number with an optional unit. Digits inside a chemical or particle name are masked first.
_NUMBER_RE = re.compile(
    r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*"
    r"(?:%|°\s?[CF]|ppm|ppb|µg/m³|ug/m3|mg/m³|mg/m3|kWh|kW|MW|W\b|lux|lx|dB(?:A)?|Pa|kPa|m/s|"
    r"m³/h|m3/h|l/s|L/s|m²|m2|K\b|hours?|hrs?|days?|minutes?|mins?|years?|months?|weeks?|"
    r"seconds?|air changes?)?",
    re.IGNORECASE,
)
_MASK_RE = re.compile(
    r"\b(?:CO2|PM\s?2\.5|PM\s?10|NO2|SO2|N2O|CH4|H2O|O3|VOCs?|CO)\b", re.IGNORECASE
)
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_BUILDING_SPECIFIC_RE = re.compile(
    r"\b(?:this|your|our)\s+(?:building|room|floor|space|zone|lab|laboratory|office|site|campus|"
    r"estate)\b|\b(?:room|rm|floor|level|zone|storey|wing|block)\s*[\d.]+",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def _digits_in(text: str) -> Set[str]:
    masked = _MASK_RE.sub(" ", text or "")
    return {m.group(1).replace(",", ".") for m in _NUMBER_RE.finditer(masked)}


def _standard_keys_in(text: str) -> Set[str]:
    return {_norm_standard(m.group(0)) for m in _STANDARD_RE.finditer(text or "")}


def _building_names() -> List[str]:
    try:
        from shared.config import settings

        name = str(getattr(settings, "BUILDING_NAME", "") or "").strip()
        return [name] if name else []
    except Exception:  # pragma: no cover - configuration is optional here
        return []


def sanitise(text: str, question: str, *, building_names: Optional[Iterable[str]] = None) -> str:
    """The model's text with every sentence that breaks a rule removed; '' when none survive.

    Pure string work, no model. A sentence is dropped, never patched, because deleting a number
    or a name from the middle of a sentence leaves prose that reads worse than the gap.
    """
    body = _FENCE_RE.sub(" ", str(text or ""))
    body = _URL_RE.sub("", body)
    body = re.sub(r"^\s*#{1,6}\s*", "", body, flags=re.MULTILINE)
    body = re.sub(r"\*\*|__|`", "", body)
    # The label is added by code; a model that wrote its own must not be quoted twice.
    body = re.sub(r"^\s*general guidance[^:\n]{0,60}:\s*", "", body, flags=re.IGNORECASE)
    names = [
        n.lower() for n in (building_names if building_names is not None else _building_names())
    ]
    q_digits = _digits_in(question)
    q_standards = _standard_keys_in(question)
    allowed = allowed_standards()

    kept: List[str] = []
    for paragraph in re.split(r"\n\s*\n|\n(?=\s*[-*•]\s)", body):
        for raw in _SENTENCE_RE.split(paragraph.strip()):
            sentence = re.sub(r"^\s*[-*•]\s*", "", raw).strip()
            if not sentence:
                continue
            low = sentence.lower()
            if any(n and n in low for n in names) or _BUILDING_SPECIFIC_RE.search(sentence):
                continue
            if _digits_in(sentence) - q_digits:
                continue
            cited = _standard_keys_in(sentence)
            if cited - allowed - q_standards:
                continue
            kept.append(sentence)
    return " ".join(kept).strip()


def truncate_to_words(text: str, limit: int) -> str:
    """The longest run of whole sentences of ``text`` that fits in ``limit`` words."""
    out: List[str] = []
    used = 0
    for sentence in _SENTENCE_RE.split(text.strip()):
        n = len(sentence.split())
        if used + n > limit:
            break
        out.append(sentence)
        used += n
    return " ".join(out).strip()


def assemble(body: str) -> str:
    """Label + body + pointer, within :data:`MAX_WORDS`; '' when nothing of the body remains."""
    if not body.strip():
        return ""
    budget = MAX_WORDS - len(LABEL.split()) - len(POINTER.split())
    fitted = truncate_to_words(body, max(budget, 0))
    if not fitted:
        return ""
    return f"{LABEL} {fitted}\n\n{POINTER}"


# ── the prompt ───────────────────────────────────────────────────────────────────────────────

_AUDIENCE: Dict[str, str] = {
    "occupant": "a building occupant: plain words, no jargon",
    "visitor": "a visitor: plain words, no jargon",
    "student": "a student: plain words, define any term you must use",
    "facility_manager": "a facility manager: practical and operational",
    "operator": "a building operator: practical and operational",
    "engineer": "a building services engineer: precise and technical",
    "analyst": "a data analyst: precise, say what would confound a measurement",
    "researcher": "a researcher: precise, say what is uncertain",
    "executive": "an executive: short, outcome-focused, no jargon",
    "sustainability_officer": "a sustainability officer: outcome-focused",
    "safety_officer": "a safety officer: cautious, name the risk plainly",
}


def system_prompt(persona: Optional[str]) -> str:
    """The strict system prompt; the checks in :func:`sanitise` enforce it after the fact."""
    audience = _AUDIENCE.get(str(persona or "").strip().lower(), "a general reader: plain words")
    held = ", ".join(standard_names()) or "none"
    return (
        "You write short general guidance about buildings, building services and indoor "
        f"environment for {audience}.\n"
        "RULES, each enforced by a checker after you answer:\n"
        f"- At most {MAX_WORDS - 40} words. Plain sentences. No headings, no lists, no links.\n"
        "- You have NO access to any building's records or sensors. Never state anything about a "
        "particular building, room, floor or its readings, and never say 'your building'.\n"
        "- Do NOT give numbers, thresholds, limits or units unless the question itself contains "
        "them. Explain the idea in words instead.\n"
        f"- Name a standard only if it is one of: {held}. Otherwise describe the concept without "
        "naming a standard. Never quote a clause.\n"
        "- If you are unsure, say what is uncertain rather than guessing.\n"
        "- Do not address the reader's specific situation; that is answered from the building's "
        "own data, and a closing sentence pointing there is added for you.\n"
        "- Do not write the words 'General guidance'; the label is added for you."
    )


# ── the entry point ──────────────────────────────────────────────────────────────────────────


async def _default_llm(prompt: str, system_message: str) -> str:
    from orchestrator.llm_manager import TaskType, llm_manager

    return await llm_manager.generate(
        prompt, system_message=system_message, task_type=TaskType.GENERAL
    )


def _is_building_domain(question: str) -> bool:
    """False only when the shape test is available AND says the question is not about buildings."""
    try:
        from orchestrator.services.guidance_shape import names_building_domain
    except Exception:  # the shape module is optional to this one
        return True
    return names_building_domain(question)


async def general_guidance(
    question: str, persona: Optional[str] = None, *, llm: Optional[LlmCall] = None
) -> str:
    """Labelled general guidance for ``question``, or '' when none can be written safely.

    '' is returned for a question that is not about buildings, for a model that fails or returns
    nothing, and for an answer that does not survive :func:`sanitise`. The caller then says so
    plainly; this function never returns text that has not been checked.
    """
    q = str(question or "").strip()
    if not q or not _is_building_domain(q):
        return ""
    call: LlmCall = llm or _default_llm
    try:
        reply: Any = call(f"Question: {q}\n\nAnswer:", system_prompt(persona))
        if hasattr(reply, "__await__"):
            reply = await reply
    except Exception as exc:
        logger.warning(f"[general_guidance] model unavailable: {exc}")
        return ""
    body = sanitise(str(reply or ""), q)
    text = assemble(body)
    if not text:
        logger.info("[general_guidance] nothing survived the checks; declining to write guidance")
    return text
