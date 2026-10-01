# -*- coding: utf-8 -*-
"""What the reader is told when no lane produced an answer, in the reader's words.

The previous wording ("I understood the question but could not put an answer together for it. I
read it as a question about **general** ... I could not match **moment** or **empty** to anything
this building records") was measured on the held-out reads as defect class C5: it names the
pipeline's own classification, prints filler words back at the reader as though they were things a
building might record, and offers nothing. Five things are decided here instead:

* no lane, intent or classifier vocabulary is ever shown;
* a missing referent is asked about ONCE, as a question, and only when it is a word that can name
  a thing (never "moment", "recently", "anything");
* what the building can answer is derived from the building's own measured quantities and record
  classes, ranked by how close they are to the question, never written down here;
* nothing claims the building lacks the data, because not answering and not holding are
  different facts;
* no figure appears.

Pure functions: the caller supplies what the building holds, so the wording is testable offline.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence, Set, Tuple

from orchestrator.services.grounding_guard import content_terms

#: Words that can survive the unmatched-term test and still never name a thing a building records.
_NOT_A_REFERENT = frozenset(
    {
        "moment",
        "moments",
        "minute",
        "minutes",
        "period",
        "recently",
        "earlier",
        "later",
        "almost",
        "nearly",
        "around",
        "roughly",
        "approximately",
        "possible",
        "anything",
        "something",
        "everything",
        "otherwise",
        "instead",
        "actually",
        "already",
        "whether",
        "whats",
        "thats",
        "tell",
    }
)


def and_list(items: Sequence[str], limit: int = 3) -> str:
    """'a, b and c' -- the form a reader expects, not a comma-joined dump."""
    kept = [str(i).strip() for i in list(items)[:limit] if str(i).strip()]
    if len(kept) <= 1:
        return kept[0] if kept else ""
    return ", ".join(kept[:-1]) + f" and {kept[-1]}"


def pick_referent(entities: Sequence[str], unmatched: Sequence[str]) -> str:
    """The one word worth asking about: the first unmatched term that can name a thing, or ''."""
    for term in unmatched or ():
        word = str(term).strip()
        if word and word.lower() not in _NOT_A_REFERENT:
            return word
    return ""


def _record_terms(record: Any) -> str:
    parts = [str(getattr(record, "label", "") or "")]
    parts.extend(str(t) for t in (getattr(record, "terms", ()) or ()))
    return " ".join(parts)


#: Non-alphanumerics, for comparing a measurand written any of the ways people write it.
_SQUASH_RE = re.compile(r"[^a-z0-9]+")


def _close(a: str, b: str) -> bool:
    """Two terms name the same thing: equal, or one is the other's prefix ('humid'/'humidity').

    PUNCTUATION IN A MEASURAND'S NAME DEFEATED BOTH TESTS (BUG-950). "pm2.5" and the modality
    "pm25" are not equal and neither prefixes the other, so they scored as unrelated. Measured
    on the held-out tail M, 2026-09-29: "why is pl 2.5 increasing" resolved correctly to PM2.5
    — the answer said so in bold — and then declined with "the nearest things I can answer are
    … the readings of air quality, carbon monoxide, co2 and damper position". Those are the
    first four modalities ALPHABETICALLY, because nothing overlapped and ties keep the
    building's own order. This building holds 210 PM2.5 sensors, so the one modality that WAS
    the answer was the only one the list could not reach, and the decline read as though PM2.5
    were unavailable.

    Comparing with non-alphanumerics stripped is narrow and is the right shape: the written
    forms people produce for one measurand are "PM2.5", "PM 2.5", "pm-2.5" and "pm25". The
    `len >= 4` guard on the prefix test is untouched and still does its job — squashed "pm1" is
    three characters, so PM1 cannot prefix-match PM10, which would be a worse answer than none.
    """
    if a == b:
        return True
    sa, sb = _SQUASH_RE.sub("", a), _SQUASH_RE.sub("", b)
    if sa and sa == sb:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 4 and long_.startswith(short)


def nearest_holdings(
    question: str,
    measured: Sequence[str],
    records: Sequence[Any],
    *,
    max_measured: int = 4,
    max_records: int = 3,
    resolved: Sequence[str] = (),
) -> Tuple[List[str], List[str]]:
    """``(measured names, record labels)`` closest to the question, most relevant first.

    Closeness is shared content terms; ties keep the building's own order (records arrive sorted
    by how many the building holds), so with no overlap the answer is what the building has most
    of. Both lists may be empty -- an unreadable building is not padded with a guess.

    ``resolved`` is what a lane ALREADY IDENTIFIED in the question, and it is the difference
    between a useful list and an alphabetical one (BUG-950). The question's own words are often
    not the building's: "why is pl 2.5 increasing" carries the content terms {'2.5','increas'}
    and shares nothing with any modality, so every score tied and the list came back as the
    first four alphabetically -- air quality, carbon monoxide, co2, damper position -- while the
    building holds 210 PM2.5 sensors. The resolver had ALREADY turned "pl 2.5" into PM2.5; the
    answer printed it in bold one sentence earlier. Ranking against that as well puts pm25
    first, which tells the reader the opposite of what the old list told them.
    """
    asked = content_terms(question or "")
    for name in resolved or ():
        asked |= content_terms(str(name))

    def _overlap(text: str) -> int:
        return sum(1 for a in asked for t in content_terms(text) if _close(a, t))

    def _rank(seq: Sequence[Any], text_of) -> List[Any]:
        scored = [(-_overlap(text_of(item)), pos, item) for pos, item in enumerate(seq)]
        return [item for _, _, item in sorted(scored, key=lambda t: (t[0], t[1]))]

    names = [str(m) for m in _rank([m for m in (measured or []) if m], lambda m: str(m))]
    recs = _rank(
        [r for r in (records or []) if getattr(r, "label", "")], lambda r: _record_terms(r)
    )
    return names[:max_measured], [str(r.label) for r in recs[:max_records]]


def holdings_sentence(building: str, names: Sequence[str], record_labels: Sequence[str]) -> str:
    """One sentence saying what the building can answer about; '' when nothing is known."""
    parts: List[str] = []
    if names:
        parts.append(f"what {building} measures ({and_list(names, 4)})")
    if record_labels:
        parts.append(f"the records it keeps ({and_list(record_labels)})")
    if not parts:
        return ""
    return f"I can answer about {' and '.join(parts)}."


def suggestion_sentence(names: Sequence[str], record_labels: Sequence[str]) -> str:
    """A concrete way to ask, built from the building's own holdings; '' when none is known."""
    bits: List[str] = []
    if names:
        bits.append(f"for the current {names[0]} in a named room")
    if record_labels:
        bits.append(f"how many {record_labels[0].lower()} records there are")
    if not bits:
        return ""
    return "Try asking " + ", or ".join(bits) + "."


def compose_unanswered(
    *,
    building: str,
    question: str = "",
    entities: Sequence[str] = (),
    unmatched: Sequence[str] = (),
    measured: Sequence[str] = (),
    records: Sequence[Any] = (),
    step_error: Optional[str] = None,
) -> str:
    """The fallback text. ``step_error`` is passed only for a reader who can act on it."""
    from orchestrator.services.clarification import readable_names

    named = readable_names(entities)
    if named:
        lead = f"I couldn't answer that about **{', '.join(named[:3])}** from {building}'s records."
    else:
        lead = f"I couldn't answer that from {building}'s records."
    referent = pick_referent(named, unmatched)
    if referent:
        lead += f" Which measurement or record do you mean by **{referent}**?"
    lines = [lead]

    names, labels = nearest_holdings(question, measured, records)
    held = holdings_sentence(building, names, labels)
    if held:
        lines += ["", held]
        hint = suggestion_sentence(names, labels)
        if hint and not referent:
            lines.append(hint)
    elif not referent:
        lines += [
            "",
            "Naming one room, floor or date usually gives me enough to answer from those.",
        ]

    if step_error:
        lines += ["", f"- A step reported: {str(step_error)[:160]}"]
    return "\n".join(lines)


def _pointer_reaches(asked: Set[str], record: Any) -> bool:
    """The matcher THIS MODULE's decline pointers use: content terms, crudely singularised.

    ``asked`` is the question's terms, hoisted by the caller: a register lane holds ~44 classes
    and re-tokenising the question per class is work no decline needs to pay for (CAVEAT-922).
    """
    return any(_close(a, t) for a in asked for t in content_terms(_record_terms(record)))


def _near_records(question: str, records: Sequence[Any]) -> List[Any]:
    """The held records whose vocabulary the question's terms reach, in the building's order."""
    asked = content_terms(question or "")
    return [r for r in records or () if getattr(r, "label", "") and _pointer_reaches(asked, r)]


def compose_boundary_pointer(building: str, question: str, records: Sequence[Any]) -> str:
    """A closing line for an honest decline: what the building's records CAN answer, or ''."""
    _, labels = nearest_holdings(question, (), _near_records(question, records), max_records=3)
    if not labels:
        return ""  # nothing the building keeps is near the question; a guess would be padding
    return f"\n\n{building} does keep {and_list(labels)} records, which I can read for you."


def pointer_only_registers(
    question: str, records: Sequence[Any], *, max_named: int = 3
) -> List[str]:
    """Registers the DECLINE can name that the register SELECTOR cannot reach (BUG-947).

    THE MECHANISM BEHIND "IT NAMES THE RIGHT REGISTER IN THE SAME SENTENCE AS THE REFUSAL."
    Four of the seven false declines hand-read on tail M (2026-09-29) named the register that
    holds the answer while refusing to answer, and the reason is that the two halves of that
    sentence are decided by DIFFERENT matchers:

    * the decline's pointer (``compose_boundary_pointer``, ``nearest_holdings``) compares
      ``grounding_guard.content_terms``, which singularises — so "escalation routes" and
      "escalation route" both reduce to {escalation, rout} and MATCH;
    * the register selector (``record_registry.rank_record_classes``) matches a declared term
      with ``\\b<term>\\b``, which a trailing "s" ends — so the same pair does NOT match.

    Measured offline against the vocabulary as it stood: "Are emergency contacts, duty managers
    and escalation routes current, reachable and authorised for tonight?" selected NO register
    and its decline opened "does keep Department … records, which I can read for you". The
    wording was not accidentally accurate; the decline is built with the more capable matcher.

    This is the countable version of the hand read — a fail-open component needs a count of
    how often it ACTED (lessons #126). It decides nothing: broadening the selector to close
    the gap was measured on the 2,960-question catalogue and rejected (BUG-948), because the
    same tolerance that recovers a specific phrase captures a generic one and the selector
    cannot tell them apart.

    WHAT A NAME HERE MEANS, AND WHAT IT DOES NOT (BUG-1073, measured 2026-09-30 over the
    2,960-question catalogue, against the schema on disk and the 2026-09-19 instance snapshot
    the register guard tests use: 42 held classes). This docstring used to say "each name
    returned is one declared form away from being reachable". That is false: the selector is
    silent on 1,746 questions and this function names registers on **1,742 of them (99.8%)**,
    three of them in 1,684. The reason is structural rather than incidental — ``_near_records``
    admits a register on ONE shared crude stem, and ``nearest_holdings`` then returns its
    top-3 whether or not anything is genuinely near, because with no overlap every score ties
    and ties keep the building's own order. On a thirty-word stakeholder question almost every
    register clears a one-stem bar. So a name here is a DISAGREEMENT between the two matchers,
    which is a place to look; it is not on its own evidence that the register holds the answer,
    and BUG-947's tell ("four of seven declines named the right register") has to be read
    against a mechanism that names three registers on nearly every decline.

    ONLY THE REGISTERS THE DECLINE ACTUALLY PRINTS are reported, which is the same top-N
    ``nearest_holdings`` narrows the pointer to. Reporting every register the fuzzy matcher
    merely touches was measured first and is useless: a long question shares a content term
    with almost everything, and tail M #28 produced fifteen names — a dump, not a work order.
    """
    try:
        from orchestrator.services.record_registry import rank_record_classes

        selected = {
            r.local_name for _score, r in rank_record_classes(question or "", list(records))
        }
    except Exception:  # pragma: no cover - a diagnostic must never raise into a decline
        return []
    near = _near_records(question, records)
    _, printed = nearest_holdings(question, (), near, max_records=max_named)
    by_label = {str(getattr(r, "label", "")): r for r in near}
    return [
        str(getattr(by_label[label], "local_name", "") or label)
        for label in printed
        if getattr(by_label.get(label), "local_name", "") not in selected
    ]
