# -*- coding: utf-8 -*-
"""Post-narration hygiene: advice, norms and counts that the data does not support.

The narration model is handed correct figures and then writes around them. Measured on the
44-question demo script and two unscripted tails (BUG-832, CAVEAT-833), the figures were right and
the prose around them was not:

* **advice nobody asked for** -- "Conduct a quick audit of the HVAC airflow ... rule out any
  blockage" on a 0.2 C spread; "increase ventilation" on a 0.6 % humidity spread; "implement alerts
  above 1,100 ppm", which is the observed maximum; "schedule a calibration check" with no reason;
* **norms with no source** -- "a delta-T of 10-12 C is typical", "the typical 10-15 C target",
  "a 1 C set-point change saves 5-10 %";
* **a count that disagrees with the list beside it** -- "the 2 without an exception (Floors 2 and
  5 and the parking ventilation)", "about 14 people per floor" under counts averaging 12;
* **a range presented as a delta** -- "the delta-T ranged up to about 53 C (maximum leaving minus
  minimum entering)": the maximum of one stream minus the minimum of another, at different
  instants, is not a temperature difference of anything;
* **advice that moves a value the wrong way** -- "increase ventilation on Floor 5 so its CO2 moves
  toward 800 ppm" where Floor 5 already has the LOWEST CO2.

Every function here is a pure string function: no I/O on the answer path, no model call, no
latency. Each removes only the sentence (or clause, or parenthesis) that carries the defect and
leaves every other byte of the answer alone; a validator that cannot decide leaves the text as it
was. Footers, tables, code and the dossier block are never edited. Nothing here contains a
building literal: the only reference data read is the project's own standards files.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, FrozenSet, List, Optional, Set, Tuple

__all__ = [
    "Change",
    "NarrationResult",
    "asks_for_advice",
    "drop_unasked_advice",
    "strip_uncited_norms",
    "check_counts_against_lists",
    "no_range_as_delta",
    "fix_advice_direction",
    "validate_narration",
    "apply_validators",
]


@dataclass(frozen=True)
class Change:
    """One edit a validator made: which validator, what it did, what it removed."""

    validator: str
    action: str
    removed: str
    replacement: str = ""


@dataclass
class NarrationResult:
    """The cleaned text and the edits that produced it."""

    text: str
    changes: List[Change] = field(default_factory=list)


# ── shared pieces ────────────────────────────────────────────────────────────

_DASHES = "-‐‑‒–—−"  # the ASCII hyphen first, so it is never a range
_DASH = "[" + _DASHES + "]"
_NUM = r"\d[\d,]*(?:\.\d+)?"
_UNIT = (
    r"(?:°\s?C|°\s?F|deg\s?C|degC|ppm|ppb|%|kWh|MWh|kW|MW|W|µg/m³|"
    r"μg/m³|ug/m3|lux|dB|L\s?min|m³|kPa|Pa|K)(?![A-Za-z])"
)
_READING_RE = re.compile(r"\d\s?(?:°\s?C|ppm|ppb|kWh|MWh|kW|%|µg/m³|μg/m³|lux|dB|L\s?min|m³)")
_CLOSERS = r"(?:\*\*|__|\*|_|[\"”’')\]])*"
_OPENERS = r"(?:\*\*|__|\*|_|[\"“‘'(\[])*"
_BOUNDARY_RE = re.compile(
    r"(?<=[.!?])(?P<close>" + _CLOSERS + r")(?P<ws>[ \t]+)(?=" + _OPENERS + r"[A-Z0-9Δ])"
)
_ABBREVIATIONS = frozenset(
    "e.g i.e etc approx vs fig no dr mr mrs ms st cf incl avg est jan feb mar apr jun jul aug sep "
    "sept oct nov dec".split()
)
_LIST_LEAD_RE = re.compile(r"^(?P<lead>\s*(?:[-*•+]\s+|\d+[.)]\s+)?)(?P<body>.*)$", re.S)
_RULE_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")
_BOLD_ONLY_RE = re.compile(r"^\s*(?P<m>\*\*|__)(?P<t>[^*_\n]{1,140})(?P=m)\s*:?\s*$")
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
_PROTECTED_RE = re.compile(
    r"^\s*(?:>\s*)?(?:\*\*|__|\*|_)?(?:you might also ask|sources?|evidence time|assumptions|"
    r"coverage|privacy|spatial basis|served at|check you can use it first)\b",
    re.I,
)
_STANDARD_NAME_RE = re.compile(
    r"\b(?:ASHRAE|BREEAM|LEED|CIBSE|EN\s?1(?:5251|6798)|ISO\s?\d{3,5}|OSHA|NIOSH|EPA|"
    r"Approved Document|Part L|SBEM|Passivhaus)\b|\bWELL\b|\bWHO\b|\bWELL v\d"
)


@dataclass
class _Line:
    raw: str
    kind: str  # code | details | protected | table | heading | rule | blank | quote | prose
    lead: str = ""
    body: str = ""
    dropped: bool = False
    override: Optional[str] = None  # replacement text for the whole line


def _classify(text: str) -> List[_Line]:
    lines: List[_Line] = []
    in_code = False
    in_details = False
    for raw in text.split("\n"):
        if _FENCE_RE.match(raw):
            in_code = not in_code
            lines.append(_Line(raw, "code"))
            continue
        if in_code:
            lines.append(_Line(raw, "code"))
            continue
        low = raw.lower()
        if "<details" in low:
            in_details = True
        if in_details:
            lines.append(_Line(raw, "details"))
            if "</details>" in low:
                in_details = False
            continue
        s = raw.strip()
        if not s:
            lines.append(_Line(raw, "blank"))
        elif _RULE_RE.match(raw):
            lines.append(_Line(raw, "rule"))
        elif _PROTECTED_RE.match(raw):
            lines.append(_Line(raw, "protected"))
        elif s.startswith("|"):
            lines.append(_Line(raw, "table"))
        elif s.startswith(">"):
            lines.append(_Line(raw, "quote"))
        elif _MD_HEADING_RE.match(raw) or _BOLD_ONLY_RE.match(raw):
            lines.append(_Line(raw, "heading"))
        else:
            m = _LIST_LEAD_RE.match(raw)
            lines.append(_Line(raw, "prose", m.group("lead"), m.group("body")))
    return lines


def _render(lines: List[_Line]) -> str:
    out: List[str] = []
    for ln in lines:
        if ln.dropped:
            continue
        out.append(ln.override if ln.override is not None else ln.raw)
    if lines and lines[-1].dropped:  # the tail went: the blank line that led into it goes too
        while out and not out[-1].strip():
            out.pop()
    text = "\n".join(out)
    # a dropped paragraph must not leave a run of blank lines behind
    return re.sub(r"\n{3,}", "\n\n", text) if any(ln.dropped for ln in lines) else text


def _split_sentences(body: str) -> List[Tuple[str, str]]:
    """``[(sentence, trailing whitespace), ...]``; concatenated they rebuild ``body`` exactly."""
    out: List[Tuple[str, str]] = []
    pos = 0
    for m in _BOUNDARY_RE.finditer(body):
        head = body[pos : m.start()]
        word = re.search(r"([A-Za-z.]+)$", head)
        if word and word.group(1).lower().rstrip(".") in _ABBREVIATIONS:
            continue
        if re.search(r"(?:^|\s)[A-Za-z]$", head):  # "A. Smith", a single initial
            continue
        out.append((body[pos : m.end("close")], m.group("ws")))
        pos = m.end()
    out.append((body[pos:], ""))
    return out


def _words(s: str) -> int:
    return len(re.findall(r"[A-Za-zΔ]+", s))


def _balance_emphasis(s: str) -> str:
    """Drop a dangling ``**`` left by cutting the sentence that closed it."""
    if s.count("**") % 2 == 1:
        s2 = re.sub(r"\s*\*\*\s*$", "", s, count=1)
        if s2 != s:
            return s2
        s2 = re.sub(r"^(\s*)\*\*\s*", r"\1", s, count=1)
        if s2 != s:
            return s2
    return s


def _strip_marks(s: str) -> str:
    return re.sub(r"^[\s*_\"“‘'(\[]+", "", s)


# A decision returns None (keep), "drop" (remove the sentence) or a replacement sentence.
_Decide = Callable[[str], Optional[str]]


def _edit_sentences(
    lines: List[_Line], decide: _Decide, validator: str, changes: List[Change]
) -> None:
    """Apply ``decide`` to every sentence of every prose line; rebuild only the lines it changed."""
    skip_deeper_than: Optional[int] = None
    for ln in lines:
        if skip_deeper_than is not None:
            # the children of a dropped list item go with it
            if ln.kind == "prose" and len(ln.raw) - len(ln.raw.lstrip()) > skip_deeper_than:
                ln.dropped = True
                changes.append(Change(validator, "drop_child_line", ln.raw.strip()))
                continue
            skip_deeper_than = None
        if ln.kind != "prose" or ln.dropped:
            continue
        parts = _split_sentences(ln.body)
        kept: List[str] = []
        touched = False
        for i, (sent, ws) in enumerate(parts):
            verdict = decide(sent) if sent.strip() else None
            if verdict is None:
                kept.append(sent + (ws if i < len(parts) - 1 else ""))
                continue
            touched = True
            if verdict == "drop":
                changes.append(Change(validator, "drop_sentence", sent.strip()))
            else:
                changes.append(Change(validator, "trim_sentence", sent.strip(), verdict.strip()))
                kept.append(verdict + (ws if i < len(parts) - 1 else ""))
        if not touched:
            continue
        rebuilt = "".join(kept).rstrip() if kept else ""
        if not re.sub(r"[\W_]+", "", rebuilt):
            ln.dropped = True
            if ln.lead.strip():
                skip_deeper_than = len(ln.raw) - len(ln.raw.lstrip())
            continue
        ln.override = ln.lead + _balance_emphasis(rebuilt) + _trailing_ws(ln.raw)


def _trailing_ws(raw: str) -> str:
    return raw[len(raw.rstrip()) :]


def _alnum(text: str) -> str:
    return re.sub(r"[\W_]+", "", text)


def _is_a_headline(raw: str) -> bool:
    """A bold line that states a finding ("**Floor 5 is the warmest at 23.4 C.**") is content."""
    core = _strip_marks(raw).rstrip("* _:")
    return bool(_READING_RE.search(core)) or core.endswith((".", "!"))


def _drop_orphan_headings(lines: List[_Line], changes: List[Change]) -> None:
    """A heading whose whole block this pass removed goes with it ("Key take-away" over nothing)."""
    validator = changes[-1].validator
    for i, ln in enumerate(lines):
        if ln.kind != "heading" or ln.dropped or _is_a_headline(ln.raw):
            continue
        saw_dropped = has_content = False
        for nxt in lines[i + 1 :]:
            if nxt.kind in ("heading", "rule", "protected"):
                break
            if nxt.dropped:
                saw_dropped = True
            elif nxt.kind != "blank":
                has_content = True
                break
        if saw_dropped and not has_content:
            ln.dropped = True
            changes.append(Change(validator, "drop_empty_heading", ln.raw.strip()))


def _finish(original: str, lines: List[_Line], changes: List[Change]) -> str:
    if not changes:
        return original
    _drop_orphan_headings(lines, changes)
    out = _render(lines)
    # never hand back an answer with nothing left in it
    return out if _alnum(out) else original


def _result(original: str, lines: List[_Line], changes: List[Change]) -> NarrationResult:
    """The finished text with the edits that survive; none when the guard kept the original."""
    out = _finish(original, lines, changes)
    return NarrationResult(out, list(changes) if out != original else [])


# ── (a) advice nobody asked for ──────────────────────────────────────────────

_ASK_RE = re.compile(
    r"\b(?:recommend\w*|suggest\w*|advi[cs]e\w*|should|improv\w*|reduc\w*|sav(?:e|es|ing|ings)|"
    r"how\s+(?:can|could|do|would|should|might)\s+(?:i|we)|"
    r"what\s+(?:can|could|should|would|might|do)\s+(?:i|we)|what\s+could|what\s+to\s+do|tips?|"
    r"next\s+steps?|action\s+(?:plan|items?)|ideas?|optimi[sz]\w*|fix\w*|"
    r"cut\s+(?:down|costs?|energy|consumption)|what\s+(?:do|would)\s+you\s+(?:do|suggest)|"
    r"help\s+me\s+(?:decide|plan))\b",
    re.I,
)

#: The lanes where a model narrates a computed result. Every other lane's sentences are content
#: (a policy quoted from a document, a register row, a template): they carry their own source, so
#: "advice" and "uncited norm" are not judgements this module can make about them.
_NARRATED_INTENTS = frozenset(
    {
        "analytics",
        "sensor_data",
        "compare",
        "trend",
        "anomaly",
        "report",
        "compliance",
        "visualization",
        "forecast",
        "export",
    }
)


def _narrated(intent: Optional[str]) -> bool:
    """True for a narrated-analysis lane, or when the lane is unknown (a replayed answer)."""
    name = str(intent or "").strip().lower()
    return not name or name in _NARRATED_INTENTS


def asks_for_advice(question: Optional[str], intent: Optional[str] = None) -> bool:
    """True when the question (or the recommend lane) legitimately calls for advice."""
    if str(intent or "").strip().lower() == "recommend":
        return True
    return bool(question and _ASK_RE.search(question))


_VERBS_ANY = (
    r"adjust|aggregate|audit|avoid|check|configure|conduct|confirm|consider|continue|"
    r"cross[‐‑‒–—−-]?check|deploy|enable|ensure|evaluate|extend|"
    r"implement|improve|increase|install|inspect|investigate|maintain|measure|monitor|perform|"
    r"plan|recalibrate|reduce|review|run|schedule|set|shift|test|track|trigger|update|use|verify|"
    r"watch|collect|compare|create|establish|introduce|replace|switch|tune|"
    r"fine[‐‑‒–—−-]?tune|dehumidify|ventilate|open|raise|lower|"
    r"balance|repeat|keep|carry\s+out|look\s+(?:into|at)|follow\s+up|analy[sz]e|identify"
)
_LEAD_IN = (
    r"(?:(?:to|in\s+order\s+to|so\s+as\s+to)\s+[^,.;:]{3,90},\s+|"
    r"(?:if|should|when|once|until)\s+[^,.;:]{3,90},\s+|"
    r"(?:otherwise|meanwhile|also|then|next|finally|overall|for\s+now),?\s+|"
    r"you\s+(?:may|might|could|should|can)\s+(?:also\s+)?(?:want\s+to\s+)?|"
    r"it\s+(?:may|might|would)\s+be\s+(?:worth|wise|advisable|sensible|prudent)\s+(?:to\s+)?|"
    r"we\s+(?:recommend|suggest|advise)\s+(?:that\s+you\s+)?)?"
)
_LABEL_RE = re.compile(
    r"^(?P<lead>\s*(?:[-*•+]\s+|\d+[.)]\s+)?)(?:\*\*|__|\*|_)*\s*"
    r"(?:(?:actionable|key|suggested|practical|final|main)\s+)?"
    r"(?:recommendations?|recommended\s+actions?)\s*"
    r"(?:[:：]\s*(?:\*\*|__|\*|_)*|(?:\*\*|__|\*|_)+\s*[:：])\s*(?P<rest>\S.*)$",
    re.I,
)
_LABEL_VERB_RE = re.compile(r"^" + _LEAD_IN + r"(?:" + _VERBS_ANY + r")\b", re.I)
_HEADING_REC_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*|__)?\s*(?:\d+[.)]\s*)?"
    r"(?:(?:actionable|key|suggested|practical|main)\s+)?recommendations?"
    r"(?:\s+(?:for|on|to|based|from)\b(?!.*\b(?:is|are|was|were|has|have|will|must|should)\b)"
    r"[^\n]{0,60})?\s*:?\s*(?:\*\*|__)?\s*:?\s*$",
    re.I,
)
_HAS_NUM_RE = re.compile(r"(?<![A-Za-z\d.,])\d")
_NUM_ANCHORED = r"(?<![A-Za-z\d.,])\d[\d,]*(?:\.\d+)?"
_OPS = (
    r"(?:HVAC|set[‐‑‒–—−-]?points?|ventilation|air[‐‑"
    r"‒–—−-]?flow|calibrat\w*|sensors?|alerts?|alarms?|monitor\w*|lighting|"
    r"equipment|schedules?|dehumidif\w*|boilers?|chillers?|pumps?|energy|consumption|usage|"
    r"occupancy|maintenance|thresholds?|filters?|dampers?|flow\s+rate|settings?)"
)
_F2_RE = re.compile(
    r"^" + _LEAD_IN + r"(?:schedule\s+(?:a|an|the)\b|conduct\b|implement\b|set\s+up\b|configure\b|"
    r"investigate\b|audit\b|cross[‐‑‒–—−-]?check\b|"
    r"perform\s+(?:a|an)\b|run\s+(?:a|an)\b|continue(?:\s+to)?\s+monitor\w*|monitor\b|verify\b|"
    r"review\b|adjust\b|increase\b|maintain\b|check\s+(?:whether|that)\b|ensure\b)",
    re.I,
)
_F3_RE = re.compile(
    r"\b(?:you\s+)?(?:might|may|could|would)\s+(?:want|wish)\s+to\s+"
    r"(?:check|review|verify|investigate|consider|monitor|adjust|look)\b|"
    r"\bit\s+(?:may|might|would)\s+be\s+(?:worth|wise|advisable|prudent)\s+to\b",
    re.I,
)
#: "..., but monitoring the delta-T trend will help catch any future drops": advice in the
#: indicative mood.
_WILL_HELP_RE = re.compile(
    r"\b(?:monitoring|tracking|watching|reviewing|logging)\b[^.;]{0,60}?\bwill\s+help\b", re.I
)
_CONSIDER_RE = re.compile(r"\bconsider\s+(?:also\s+)?(?:\w+[‐‑‒–—−-]){0,2}\w+ing\b", re.I)
_NEGATED_BEFORE_RE = re.compile(
    r"(?:cannot|can’t|can't|can\s+not|unable\s+to|not|won't|won’t|never)\s+(?:yet\s+)?$",
    re.I,
)


_SUBORDINATE_RE = re.compile(
    r"(?:because|since|as|while|although|though|if|when|once|given|with|due\s+to|to|so|in\s+order)\b",
    re.I,
)


def _trim_tail(sentence: str, trigger_at: int) -> Optional[str]:
    """The sentence up to the clause boundary before ``trigger_at`` (None when too little is left)."""
    head = sentence[:trigger_at]
    cut = max(head.rfind(","), head.rfind(";"), head.rfind("—"), head.rfind(" - "))
    if cut <= 0:
        return None
    kept = head[:cut].rstrip(" ,;—-")
    if _words(kept) < 4 or not re.search(r"\d|\b(?:is|are|was|were|has|have)\b", kept):
        return None
    if _SUBORDINATE_RE.match(_strip_marks(kept)):
        return None  # "Because Floor 3 is warmer" is a fragment once its main clause is gone
    tail_mark = re.search(r"([.!?][\"”’')\]*_]*)\s*$", sentence)
    return kept + (tail_mark.group(1) if tail_mark else ".")


def _advice_decision(sentence: str, whole: str) -> Optional[str]:
    """None to keep; "drop" or a trimmed sentence when ``sentence`` is unasked advice."""
    core = _strip_marks(sentence)
    if not core or "?" in core[-3:]:
        return None
    if not _READING_RE.search(whole):
        return None  # advice is only recognised beside a narrated reading
    label = _LABEL_RE.match(sentence)
    if label and _LABEL_VERB_RE.match(_strip_marks(label.group("rest"))):
        return "drop"
    m = _CONSIDER_RE.search(core)
    if m and not _NEGATED_BEFORE_RE.search(core[max(0, m.start() - 25) : m.start()]):
        if _F2_RE.match(core) or re.match(_LEAD_IN + r"consider\b", core, re.I):
            return "drop"
        return _trim_tail(sentence, sentence.lower().find(m.group(0).lower())) or "drop"
    if _F2_RE.match(core) and re.search(_OPS, core, re.I):
        return "drop"
    f3 = _F3_RE.search(core)
    if f3 and re.search(_OPS, core, re.I):
        return _trim_tail(sentence, sentence.find(f3.group(0))) or "drop"
    f4 = _WILL_HELP_RE.search(core)
    if f4:
        return _trim_tail(sentence, sentence.find(f4.group(0))) or "drop"
    return None


def _drop_recommendation_sections(lines: List[_Line], changes: List[Change]) -> None:
    """Remove a "Recommendations" heading and the block beneath it."""
    n = len(lines)
    i = 0
    while i < n:
        ln = lines[i]
        if ln.kind in ("heading", "prose") and _HEADING_REC_RE.match(ln.raw):
            is_md = ln.raw.lstrip().startswith("#")
            level = len(ln.raw.lstrip()) - len(ln.raw.lstrip().lstrip("#")) if is_md else 0
            j = i + 1
            block = [i]
            while j < n:
                nxt = lines[j]
                if nxt.kind in ("rule", "protected", "details", "code"):
                    break
                if nxt.kind == "heading":
                    if nxt.raw.lstrip().startswith("#"):
                        lvl = len(nxt.raw.lstrip()) - len(nxt.raw.lstrip().lstrip("#"))
                        if not is_md or lvl <= level:
                            break
                    elif lines[j - 1].kind == "blank" or not is_md:
                        break  # a bold-only heading after a blank line opens the next section
                block.append(j)
                j += 1
            while block and lines[block[-1]].kind == "blank":
                block.pop()
            for k in block:
                lines[k].dropped = True
            changes.append(
                Change(
                    "drop_unasked_advice",
                    "drop_section",
                    " / ".join(lines[k].raw.strip() for k in block if lines[k].raw.strip())[:400],
                )
            )
            i = j
            continue
        i += 1


def _drop_labelled_paragraphs(lines: List[_Line], changes: List[Change]) -> None:
    """Remove "Recommendation: <imperative>" paragraphs (label plus continuation lines)."""
    n = len(lines)
    i = 0
    while i < n:
        ln = lines[i]
        if ln.kind == "prose" and not ln.dropped:
            m = _LABEL_RE.match(ln.raw)
            if m and _LABEL_VERB_RE.match(_strip_marks(m.group("rest"))):
                ln.dropped = True
                removed = [ln.raw.strip()]
                indent = len(ln.raw) - len(ln.raw.lstrip())
                j = i + 1
                while j < n and lines[j].kind == "prose":
                    nxt = lines[j]
                    nxt_indent = len(nxt.raw) - len(nxt.raw.lstrip())
                    if nxt_indent <= indent and not nxt.raw.startswith(("  ", "\t")):
                        break
                    nxt.dropped = True
                    removed.append(nxt.raw.strip())
                    j += 1
                changes.append(Change("drop_unasked_advice", "drop_paragraph", " / ".join(removed)))
                i = j
                continue
        i += 1


def drop_unasked_advice(question: Optional[str], text: str, intent: Optional[str] = None) -> str:
    """Remove recommendation paragraphs and closing "consider ..." advice nobody asked for."""
    return _advice(question, text, intent).text


def _advice(question: Optional[str], text: str, intent: Optional[str]) -> NarrationResult:
    if not text or asks_for_advice(question, intent):
        return NarrationResult(text or "")
    if not _narrated(intent):
        return NarrationResult(text)
    changes: List[Change] = []
    lines = _classify(text)
    if _READING_RE.search(text):
        _drop_recommendation_sections(lines, changes)
        _drop_labelled_paragraphs(lines, changes)
    body_for_gate = "\n".join(ln.raw for ln in lines if ln.kind in ("prose", "table", "heading"))

    def decide(sentence: str) -> Optional[str]:
        return _advice_decision(sentence, body_for_gate)

    _edit_sentences(lines, decide, "drop_unasked_advice", changes)
    return _result(text, lines, changes)


# ── (b) norms with no source ─────────────────────────────────────────────────

_NORM_WORD = r"(?:typical|normal|expected|healthy|acceptable|ideal|optimal|usual|desirable)"
_NUM_UNIT = _NUM + r"\s*(?:" + _DASH + r"\s*" + _NUM + r"\s*)?" + _UNIT
#: "the typical 10-15 C target", "Typical buildings see 10 %-20 % savings": "typical" and the
#: number it introduces. "far above typical tap use" names no number, so it is not this shape.
_TYPICAL_NUM_RE = re.compile(
    r"\b(?:typical|typically|usual|usually)\b[^.;]{0,25}?(?<![A-Za-z\d.,])\d", re.I
)
#: "a delta-T of 8-9 C is typical for ..." and "9-11 C is normal": a number or RANGE declared to
#: be the norm. A single reading judged "normal" ("665 ppm is normal") is a verdict on the
#: reading, not a norm, so only a range takes the wider set of words.
_UNIT_IS_TYPICAL_RE = re.compile(
    _NUM_UNIT + r"[^.;]{0,50}?\b(?:is|are)\s+(?:generally\s+|considered\s+|also\s+)?"
    r"(?:typical|usual)\b",
    re.I,
)
_RANGE_IS_NORM_RE = re.compile(
    _NUM + r"\s*" + _DASH + r"\s*" + _NUM + r"\s*" + _UNIT + r"[^.;]{0,60}?"
    r"\b(?:is|are)\s+(?:generally\s+|considered\s+|also\s+)?" + _NORM_WORD + r"\b",
    re.I,
)
_NORM_NOUN_NUM_RE = re.compile(
    r"\b(?:typical|expected|normal|usual|ideal|optimal|acceptable|recommended|healthy)\s+"
    r"(?:operating\s+|working\s+|comfort\s+)?(?:range|band|level|values?|limit|threshold|drop|rise|"
    r"delta|ΔT|delta[‐‑‒–—−-]?T)\b[^.;]{0,30}?" + _NUM_UNIT,
    re.I,
)
_RULE_OF_THUMB_RE = re.compile(r"\brule of thumb\b", re.I)
_GENERIC_NORM_RE = re.compile(
    r"\b(?:typical|normal|expected|usual|standard)\s+for\b|\btypical\s+(?:buildings?|offices?)\b|"
    r"\brule of thumb\b",
    re.I,
)
#: For trimming: a norm phrase left standing in what is kept.
_NORM_ANY_RE = re.compile(
    r"\b(?:typical|typically|usual|usually|rule of thumb)\b|"
    r"\b(?:typical|expected|normal|usual|ideal|optimal|acceptable|recommended|healthy)\s+"
    r"(?:operating\s+|working\s+|comfort\s+)?(?:range|band|level|values?|limit|threshold|drop|rise)\b",
    re.I,
)
_SAVES_RE = re.compile(
    r"\b(?:each|every|per|a|an|one|typical\w*|generally|roughly|around)\b[^.;]{0,60}?"
    r"\b(?:set[‐‑‒–—−-]?point|thermostat|degree|°\s?C)\b"
    r"[^.;]{0,50}?\b(?:sav|cut|reduc|lower|shav)\w*\b[^.;]{0,25}?"
    + _NUM
    + r"\s*(?:"
    + _DASH
    + r"\s*"
    + _NUM
    + r"\s*)?%",
    re.I,
)
_THRESHOLD_ADVICE_RE = re.compile(
    r"\b(?:alerts?|alarms?|trigger\w*|flag|notify|review|investigate|schedule|escalate)\b[^.;]{0,90}?"
    r"\b(?:exceed\w*|above|over|below|under|beyond|higher\s+than|greater\s+than)\s+" + _NUM,
    re.I,
)
_WITHIN_NORM_CLAUSE_RE = re.compile(
    r",?\s+(?:which|that)\s+(?:is|are|falls?|lies?|lie|sits?|sit|stays?|remains?)\s+"
    r"(?:comfortably\s+|well\s+|firmly\s+|squarely\s+)?within\s+(?:the|a|an)\s+"
    + _NORM_WORD
    + r"(?:\s+\w+){0,2}\s+range[^.]*",
    re.I,
)
_WITHIN_NORM_RE = re.compile(
    r"\bwithin\s+(?:the\s+|a\s+|an\s+)?(?:expected|healthy|typical|acceptable|ideal|optimal)"
    r"(?:\s+\w+){0,2}\s+(?:range|band|limits?)\b",
    re.I,
)
#: A sentence that measures against something the building recorded is not asserting a norm.
_DATA_CUE_RE = re.compile(
    r"\b(?:approved|recorded|thresholds?|register\w*|records?|polic\w+|configured|scheduled|"
    r"targets?|regimes?|set[‐‑‒–—− -]?points?)\b",
    re.I,
)
_NUM_UNIT_RE = re.compile(
    r"(?<![A-Za-z\d.,])(?P<a>" + _NUM + r")(?:\s*" + _DASH + r"\s*(?P<b>" + _NUM + r"))?\s*"
    r"(?P<u>" + _UNIT + r")?"
)
_FAMILY_OF_UNIT = (
    (re.compile(r"^(?:°\s?[CF]|deg\s?C|degC|K)$"), "temperature"),
    (re.compile(r"^ppm$"), "co2"),
    (re.compile(r"^ppb$"), "voc"),
    (re.compile(r"^(?:µg/m³|μg/m³|ug/m3)$"), "pm"),
    (re.compile(r"^%$"), "humidity"),
)
_DELTA_RE = re.compile(r"Δ\s?T|delta[‐‑‒–—− -]?T|temperature\s+(?:rise|drop|lift|difference)", re.I)


@lru_cache(maxsize=1)
def _reference_numbers() -> Dict[str, FrozenSet[float]]:
    """Numbers the project's own standards files name, by quantity."""
    fam: Dict[str, Set[float]] = {k: set() for k in ("temperature", "humidity", "co2", "pm", "voc")}
    root = Path(__file__).resolve().parents[1] / "data" / "standards"
    key_map = {
        "temperature": "temperature",
        "humidity": "humidity",
        "co2": "co2",
        "pm25": "pm",
        "voc": "voc",
    }
    try:
        comfort = json.loads((root / "comfort_standards.json").read_text(encoding="utf-8"))
        for cfg in comfort.values():
            for key, val in cfg.items():
                if key in key_map and isinstance(val, list):
                    fam[key_map[key]].update(float(v) for v in val if isinstance(v, (int, float)))
    except Exception:  # pragma: no cover - reference data is best effort
        pass
    try:
        grades = json.loads((root / "iaq_grades.json").read_text(encoding="utf-8"))
        for g in grades:
            for key, dest in (("co2_max", "co2"), ("pm25_max", "pm")):
                if isinstance(g.get(key), (int, float)):
                    fam[dest].add(float(g[key]))
    except Exception:  # pragma: no cover
        pass
    try:
        alert = (
            Path(__file__).resolve().parents[2] / "config" / "alert_thresholds.yaml"
        ).read_text(encoding="utf-8")
        for block in re.split(r"\n\s*-\s+sensor_type:", alert)[1:]:
            kind = block.split("\n", 1)[0].strip().lower()
            val = re.search(r"threshold:\s*(" + _NUM + r")", block)
            if val:
                dest = (
                    "co2"
                    if "co2" in kind
                    else (
                        "temperature" if "temp" in kind else ("humidity" if "humid" in kind else "")
                    )
                )
                if dest:
                    fam[dest].add(float(val.group(1).replace(",", "")))
    except Exception:  # pragma: no cover
        pass
    return {k: frozenset(v) for k, v in fam.items()}


def _to_float(s: str) -> float:
    return float(s.replace(",", ""))


def _numbers_are_cited(claim: str, evidence_numbers: Set[float], context: str = "") -> bool:
    """True when every number in the claim is one the standards files or the evidence name."""
    refs = _reference_numbers()
    pairs = list(_NUM_UNIT_RE.finditer(claim))
    if not pairs:
        return False
    about_humidity = bool(re.search(r"humid|\bRH\b", claim + " " + context, re.I))
    for m in pairs:
        unit = (m.group("u") or "").replace(" ", "")
        family = next((f for rx, f in _FAMILY_OF_UNIT if unit and rx.match(unit)), None)
        if family == "humidity" and not about_humidity:
            family = None
        for g in ("a", "b"):
            if m.group(g) is None:
                continue
            val = _to_float(m.group(g))
            if val in evidence_numbers:
                continue
            if family and val in refs.get(family, frozenset()):
                continue
            return False
    return True


def _evidence_numbers(evidence: Optional[str]) -> Set[float]:
    out: Set[float] = set()
    for m in re.finditer(_NUM, evidence or ""):
        try:
            out.add(_to_float(m.group(0)))
        except ValueError:
            continue
    return out


def _measured_floats(text: str) -> List[float]:
    """Numbers that carry a unit; a bare integer in a date or an id is not a measurement."""
    out: List[float] = []
    for m in _NUM_UNIT_RE.finditer(text):
        if m.group("u"):
            out.extend(_to_float(m.group(g)) for g in ("a", "b") if m.group(g))
    return out


def _numbers_elsewhere(whole: str, sentence: str) -> Set[float]:
    """Measured numbers the answer states outside ``sentence``: what the data itself supplied."""
    left = Counter(_measured_floats(whole))
    left.subtract(Counter(_measured_floats(sentence)))
    return {n for n, c in left.items() if c > 0}


def _has_measure(core: str) -> bool:
    """True when the claim carries a measured quantity: a number with a unit, or a delta."""
    return any(m.group("u") for m in _NUM_UNIT_RE.finditer(core)) or bool(_DELTA_RE.search(core))


def _norm_decision(
    sentence: str, ev: Set[float], threshold_advice: bool, whole: str = ""
) -> Optional[str]:
    core = _strip_marks(sentence)
    if not core or "?" in core[-3:] or _STANDARD_NAME_RE.search(core):
        return None
    measured = _has_measure(core)
    kind = ""
    trigger = -1
    claim = core  # the part of the sentence that states the norm: only ITS numbers are checked
    if measured:
        for rx in (
            _TYPICAL_NUM_RE,
            _UNIT_IS_TYPICAL_RE,
            _RANGE_IS_NORM_RE,
            _NORM_NOUN_NUM_RE,
            _RULE_OF_THUMB_RE,
        ):
            hit = rx.search(core)
            if hit:
                kind, trigger = "norm", hit.start()
                if rx is not _RULE_OF_THUMB_RE:
                    claim = core[hit.start() : hit.end() + 25]
                break
        if not kind:
            hit = _SAVES_RE.search(core)
            if hit:
                kind, claim = "saves", hit.group(0)
        if not kind and threshold_advice:
            hit = _THRESHOLD_ADVICE_RE.search(core)
            if hit:
                kind, claim = "threshold", core[hit.start() : hit.end() + 25]
    if not kind:
        # No number to check: "... within the expected healthy range" with nothing recorded to
        # measure against is a norm asserted from nowhere.
        if _WITHIN_NORM_RE.search(core) and not _DATA_CUE_RE.search(core):
            clause = _WITHIN_NORM_CLAUSE_RE.search(sentence)
            head = sentence[: clause.start()] if clause else ""
            if clause and _words(head) >= 4 and _HAS_NUM_RE.search(head):
                tail_mark = re.search(r"([.!?][\"”’')\]*_]*)\s*$", sentence)
                return head.rstrip(" ,;") + (tail_mark.group(1) if tail_mark else ".")
            return "drop" if not _HAS_NUM_RE.search(core) else None
        return None
    # A typical-value claim built from numbers the answer itself reports is a summary of the
    # data; a threshold or a saving is never derivable from readings.
    # A norm stated for a CLASS ("typical for efficient heating circuits") is not a summary of
    # this answer's readings even when it happens to share their digits.
    from_data = kind == "norm" and not _GENERIC_NORM_RE.search(core)
    known = set(ev) | (_numbers_elsewhere(whole, sentence) if from_data else set())
    if _numbers_are_cited(claim, known, whole):
        return None
    if kind == "norm" and trigger > 0:
        head = _trim_tail(sentence, trigger)
        if head and _HAS_NUM_RE.search(head) and not _NORM_ANY_RE.search(head):
            return head  # keep the leading factual clause, cut the norm that trails it
    return "drop"


def strip_uncited_norms(text: str, evidence: Optional[str] = None) -> str:
    """Remove sentences asserting a typical/healthy/target range or threshold with no source."""
    return _norms(None, text, None, evidence).text


def _norms(
    question: Optional[str], text: str, intent: Optional[str], evidence: Optional[str]
) -> NarrationResult:
    if not text:
        return NarrationResult("")
    # The recommend lane is narrated too: "a 1 C set-point change saves 5-10 %" is an uncited norm
    # wherever it is written.
    lane = str(intent or "").strip().lower()
    if not (_narrated(intent) or lane == "recommend") or not re.search(r"\d|\bwithin\b", text):
        return NarrationResult(text)
    ev = _evidence_numbers(evidence)
    threshold_advice = not asks_for_advice(question, intent)
    changes: List[Change] = []
    lines = _classify(text)
    _edit_sentences(
        lines,
        lambda s: _norm_decision(s, ev, threshold_advice, text),
        "strip_uncited_norms",
        changes,
    )
    return _result(text, lines, changes)


# ── (c) a count that disagrees with the list beside it ───────────────────────

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}  # fmt: skip
_COUNT_LIST_RE = re.compile(
    r"(?P<n>\b\d{1,3}\b|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b)"
    r"(?P<mid>[^().;:\n\d]{0,70}?)\s*\((?P<items>[^()\n]{3,240})\)",
    re.I,
)
_LIST_MARKERS_RE = re.compile(
    r"^(?:e\.?g\.?|i\.?e\.?|including|incl\.?|such as|for example|for instance|among|mostly|"
    r"mainly|namely|see|from|between|at|on|of|by|per|about|around|approx)\b|\betc\b|…|\.\.\.",
    re.I,
)
_ID_ITEM_RE = re.compile(
    r"^(?:[A-Z]{1,8}[" + _DASHES + r"]?\d[" + _DASHES + r"\w.]*|"
    r"(?:Floors?|Levels?|Rooms?|Zones?|Lifts?)\s*\w[\w.\-]*|\d+(?:\.\d+)?)$"
)
#: "Floors 2 and 5" / "Rooms 4.01, 4.02 and 4.03": a plural entity word and a run of numbers.
_PLURAL_RUN_RE = re.compile(
    r"\b(?:Floors|Levels|Rooms|Zones)\s+\d[\w.]*(?:\s*(?:,|and|&)\s*\d[\w.]*)+", re.I
)


def _split_items(items: str) -> List[str]:
    parts = re.split(r"\s*(?:,|;|&|\band\b|\bor\b)\s*", items.strip())
    return [p.strip(" .") for p in parts if p and p.strip(" .")]


#: A number right after one of these is a label ("Floor 2 (Room 2.01, 2.02)"), not a count.
_LABEL_BEFORE_RE = re.compile(
    r"(?:floors?|levels?|rooms?|zones?|lifts?|bays?|blocks?|tables?|sections?|weeks?|days?|"
    r"pages?|items?|rows?|no\.?|#|w|week[‐‑‒–—−-])\s*$",
    re.I,
)


def _fix_count_lists(text: str, changes: List[Change]) -> str:
    def repl(m: "re.Match[str]") -> str:
        raw_n = m.group("n")
        n = _WORD_NUMBERS.get(raw_n.lower()) if not raw_n.isdigit() else int(raw_n)
        items_raw = m.group("items")
        mid = m.group("mid")
        if n is None or _LIST_MARKERS_RE.search(items_raw.strip()):
            return m.group(0)
        if _LABEL_BEFORE_RE.search(text[max(0, m.start() - 14) : m.start()]):
            return m.group(0)
        items = _split_items(items_raw)
        # Only a list LONGER than its count is provably inconsistent: a shorter one may be a
        # partial listing ("6 floors (Floor 0, Floor 1)"), and the count may be the right figure.
        if len(items) < 2 or len(items) <= n:
            return m.group(0)
        if all(_ID_ITEM_RE.match(it) for it in items) and _words(mid) <= 4:
            new = m.group(0).replace(raw_n, str(len(items)), 1)
            changes.append(Change("check_counts_against_lists", "recount", m.group(0), new))
            return new
        # A prose list that names entities by number ("the regimes on Floors 2 and 5 and the parking
        # ventilation"): the count and the free-text list disagree and neither is authoritative, so
        # the count stays and the unreliable enumeration goes. Only when the count is immediately
        # followed by the parenthesis, so a bracketed aside about part of a group is left alone.
        if not mid.strip() and _PLURAL_RUN_RE.search(items_raw):
            # "Floors 2 and 5" is two entities inside ONE list item: count them as two.
            joined = _PLURAL_RUN_RE.sub(
                lambda r: re.sub(r"\s*(?:,|\band\b|&)\s*", "|", r.group(0)), items_raw
            )
            entities = sum(1 + it.count("|") for it in _split_items(joined))
            if entities > n:
                new = m.group(0)[: m.start("items") - m.start(0) - 1].rstrip()
                changes.append(
                    Change("check_counts_against_lists", "drop_enumeration", m.group(0), new)
                )
                return new
        return m.group(0)

    return _COUNT_LIST_RE.sub(repl, text)


_AVG_CLAIM_RE = re.compile(
    r"(?:\babout|\baround|\broughly|\bapproximately|≈|~|\baverag\w+\s+(?:of\s+|is\s+|was\s+)?|"
    r"\bmean\s+(?:of\s+|is\s+|was\s+)?)\s*(?P<v>" + _NUM + r")\s*(?:[A-Za-z%°µ/³ ]{0,20}?)"
    r"\s+per\s+(?P<g>floor|room|zone|level|space|sensor)\b",
    re.I,
)
_ENTRY_RE = re.compile(
    r"(?P<g>Floors?|Levels?|Rooms?|Zones?)\s*(?P<id>\w[\w.]*)\s*(?:[:–—‐‑-]+|\|)\s*"
    r"\**\s*(?P<v>" + _NUM + r")(?!\s*[.:]\d)",
    re.I,
)


def _group_values(text: str, group: str) -> List[float]:
    seen: Dict[str, float] = {}
    for m in _ENTRY_RE.finditer(text):
        if m.group("g").lower().rstrip("s") != group.lower().rstrip("s"):
            continue
        seen.setdefault(m.group("id").lower(), _to_float(m.group("v")))
    return list(seen.values())


def _average_decision(sentence: str, whole: str) -> Optional[str]:
    m = _AVG_CLAIM_RE.search(sentence)
    if not m:
        return None
    values = _group_values(whole.replace(sentence, ""), m.group("g"))
    if len(values) < 3:
        return None
    mean = sum(values) / len(values)
    stated = _to_float(m.group("v"))
    if abs(stated - mean) > max(1.0, 0.15 * mean):
        return "drop"
    return None


def check_counts_against_lists(text: str) -> str:
    """Repair or drop a stated count that the list beside it contradicts."""
    return _counts(text).text


def _counts(text: str) -> NarrationResult:
    if not text or not re.search(r"\d|\b(?:one|two|three|four|five|six)\b", text, re.I):
        return NarrationResult(text or "")
    changes: List[Change] = []
    lines = _classify(text)
    for ln in lines:
        if ln.kind == "prose":
            fixed = _fix_count_lists(ln.body, changes)
            if fixed != ln.body:
                ln.override = ln.lead + fixed + _trailing_ws(ln.raw)
    whole = "\n".join((ln.override if ln.override is not None else ln.raw) for ln in lines)
    _edit_sentences(
        lines, lambda s: _average_decision(s, whole), "check_counts_against_lists", changes
    )
    return _result(text, lines, changes)


# ── (d) a range presented as a delta ─────────────────────────────────────────

_MAX_MINUS_MIN_RE = re.compile(
    r"\b(?:maximum|max|highest|peak)\s+(?P<a>[A-Za-z]+)(?:\s+"
    + _NUM
    + r"\s*"
    + r"(?:"
    + _UNIT
    + r")?)?"
    r"\s+minus\s+(?:the\s+)?(?:minimum|min|lowest)\s+(?P<b>[A-Za-z]+)",
    re.I,
)


def _range_delta_decision(sentence: str) -> Optional[str]:
    m = _MAX_MINUS_MIN_RE.search(sentence)
    if m and m.group("a").lower() != m.group("b").lower():
        return "drop"
    return None


def no_range_as_delta(text: str) -> str:
    """Drop a sentence that reports max-of-one-stream minus min-of-another as a delta."""
    return _range_delta(text).text


def _range_delta(text: str) -> NarrationResult:
    if not text or not re.search(r"\bminus\b", text, re.I):
        return NarrationResult(text or "")
    changes: List[Change] = []
    lines = _classify(text)
    _edit_sentences(lines, _range_delta_decision, "no_range_as_delta", changes)
    return _result(text, lines, changes)


# ── (e) advice that moves a value the wrong way ──────────────────────────────

# action -> the sign of its effect on each quantity it touches (-1 lowers, +1 raises)
_ACTIONS: Tuple[Tuple["re.Pattern[str]", Dict[str, int]], ...] = (
    (
        re.compile(
            r"\b(?:increas\w+|boost\w*|improv\w+|enhanc\w+|step\w*\s+up)\s+(?:the\s+)?"
            r"(?:ventilation|fresh[\s-]air|air[\s-]?(?:flow|exchange|change)s?)\b|"
            r"\bmore\s+(?:ventilation|fresh\s+air)\b|\bventilat\w+\s+more\b",
            re.I,
        ),
        {"co2": -1, "pm": -1, "voc": -1, "humidity": -1},
    ),
    (
        re.compile(r"\b(?:reduc\w+|cut\w*|lower\w*)\s+(?:the\s+)?ventilation\b", re.I),
        {"co2": 1, "pm": 1, "voc": 1, "humidity": 1},
    ),
    (re.compile(r"\bdehumidif\w+", re.I), {"humidity": -1}),
    (re.compile(r"\bhumidif\w+", re.I), {"humidity": 1}),
    (
        re.compile(
            r"\b(?:rais\w+|increas\w+|turn\w*\s+up)\s+(?:the\s+)?(?:heating|set[\s‐-―-]?points?|"
            r"heat)\b",
            re.I,
        ),
        {"temperature": 1},
    ),
    (
        re.compile(
            r"\b(?:lower\w*|reduc\w+|turn\w*\s+down|decreas\w+)\s+(?:the\s+)?(?:heating|"
            r"set[\s‐-―-]?points?)\b|\b(?:increas\w+|more)\s+(?:the\s+)?cooling\b",
            re.I,
        ),
        {"temperature": -1},
    ),
)
_UNIT_QUANTITY = (
    (re.compile(r"^ppm$", re.I), "co2"),
    (re.compile(r"^(?:µg/m³|μg/m³|ug/m3)$", re.I), "pm"),
    (re.compile(r"^ppb$", re.I), "voc"),
    (re.compile(r"^%$"), "humidity"),
    (re.compile(r"^(?:°\s?C|deg\s?C|degC)$", re.I), "temperature"),
)
_ENTITY_VALUE_RE = re.compile(
    r"(?P<g>Floors?|Levels?|Rooms?|Zones?)\s*(?P<id>\w[\w.]*)\s*(?:[:–—‐‑-]+|\|)\s*"
    r"\**\s*(?P<v>" + _NUM + r")\s*(?P<u>" + _UNIT + r")",
    re.I,
)
_ENTITY_IN_ADVICE_RE = re.compile(r"\b(?P<g>Floor|Level|Room|Zone)s?\s+(?P<id>\d[\w.]*)", re.I)
_TOWARD_RE = re.compile(
    r"\b(?:toward|towards|closer\s+to|up\s+to|in\s+line\s+with|match|level\s+with)\b", re.I
)


_QUANTITY_WORDS = {
    "co2": re.compile(r"CO\s?[2₂]|carbon dioxide|air quality", re.I),
    "humidity": re.compile(r"humid|moisture|damp", re.I),
    "temperature": re.compile(r"temperature|warm|\bhot\b|cool|heat|cold", re.I),
    "pm": re.compile(r"\bPM\s?\d|particulate|dust|air quality", re.I),
    "voc": re.compile(r"\bT?VOCs?\b|volatile|air quality", re.I),
}


def _quantity_is_the_topic(sentence: str, quantity: str) -> bool:
    """False when the advice names a DIFFERENT quantity than the listed values measure."""
    named = [q for q, rx in _QUANTITY_WORDS.items() if rx.search(sentence)]
    return not named or quantity in named


def _unit_quantity(unit: str) -> Optional[str]:
    unit = unit.replace(" ", "")
    return next((q for rx, q in _UNIT_QUANTITY if rx.match(unit)), None)


def _direction_decision(sentence: str, whole: str) -> Optional[str]:
    action = next(((rx, eff) for rx, eff in _ACTIONS if rx.search(sentence)), None)
    entity = _ENTITY_IN_ADVICE_RE.search(sentence)
    if not action or not entity:
        return None
    _, effect = action
    peers = whole.replace(sentence, "")
    by_quantity: Dict[str, Dict[str, float]] = {}
    for m in _ENTITY_VALUE_RE.finditer(peers):
        q = _unit_quantity(m.group("u"))
        if q is None or m.group("g").lower().rstrip("s") != entity.group("g").lower():
            continue
        by_quantity.setdefault(q, {}).setdefault(m.group("id").lower(), _to_float(m.group("v")))
    me = entity.group("id").lower().rstrip(".")
    for quantity, sign in effect.items():
        values = by_quantity.get(quantity, {})
        if len(values) < 3 or me not in values or not _quantity_is_the_topic(sentence, quantity):
            continue
        mine = values[me]
        others = [v for k, v in values.items() if k != me]
        wrong = (sign < 0 and mine < min(others)) or (sign > 0 and mine > max(others))
        target = re.search(
            r"(?:toward|towards|to|closer to)\s+(?:the\s+)?(" + _NUM + r")", sentence
        )
        if _TOWARD_RE.search(sentence) and target:
            goal = _to_float(target.group(1))
            wrong = wrong or (sign < 0 and goal > mine) or (sign > 0 and goal < mine)
        elif _TOWARD_RE.search(sentence) and re.search(
            r"\bother\s+(?:floors|rooms|zones|levels)\b|\baverage\b|\brest\b", sentence, re.I
        ):
            avg = sum(others) / len(others)
            wrong = wrong or (sign < 0 and mine < avg) or (sign > 0 and mine > avg)
        if wrong:
            return "drop"
    return None


def fix_advice_direction(text: str) -> str:
    """Drop advice whose action would move the named entity's value the wrong way."""
    return _direction(text).text


def _direction(text: str) -> NarrationResult:
    if not text or not re.search(r"ventilat|humidif|heating|set[\s-]?point|cooling", text, re.I):
        return NarrationResult(text or "")
    changes: List[Change] = []
    lines = _classify(text)
    whole = "\n".join(ln.raw for ln in lines)
    _edit_sentences(lines, lambda s: _direction_decision(s, whole), "fix_advice_direction", changes)
    return _result(text, lines, changes)


# ── the pipeline ─────────────────────────────────────────────────────────────


def validate_narration(
    question: Optional[str],
    text: str,
    intent: Optional[str] = None,
    evidence: Optional[str] = None,
) -> NarrationResult:
    """Run every validator in a fixed order, to a fixed point, and report each edit. Never raises."""
    current = text or ""
    changes: List[Change] = []
    # Imported here, not at the top: narration_totals reads this module's line machinery, so a
    # module-level import either way round is a cycle.
    from orchestrator.services.narration_totals import validate_totals

    # Advice goes BEFORE norms: a number that only the advice mentioned ("if the mean rises above
    # 24 C") must not vouch for a norm that then stands once the advice is gone.
    steps: Tuple[Callable[[str], NarrationResult], ...] = (
        _counts,
        lambda t: validate_totals(t, intent),
        _range_delta,
        _direction,
        lambda t: _advice(question, t, intent),
        lambda t: _norms(question, t, intent, evidence),
    )
    for _ in range(3):  # a cached answer is polished again, so one pass must be a fixed point
        before = current
        for step in steps:
            try:
                res = step(current)
            except Exception:  # pragma: no cover - a wording pass must never cost the answer
                continue
            current = res.text
            changes.extend(res.changes)
        if current == before:
            break
    return NarrationResult(current, changes)


def apply_validators(
    question: Optional[str],
    text: str,
    intent: Optional[str] = None,
    evidence: Optional[str] = None,
) -> str:
    """The cleaned text alone (what ``polish_answer`` uses)."""
    return validate_narration(question, text, intent, evidence).text
