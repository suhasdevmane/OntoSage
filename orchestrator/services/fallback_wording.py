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

from typing import Any, List, Optional, Sequence, Tuple

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


def _close(a: str, b: str) -> bool:
    """Two terms name the same thing: equal, or one is the other's prefix ('humid'/'humidity')."""
    if a == b:
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
) -> Tuple[List[str], List[str]]:
    """``(measured names, record labels)`` closest to the question, most relevant first.

    Closeness is shared content terms; ties keep the building's own order (records arrive sorted
    by how many the building holds), so with no overlap the answer is what the building has most
    of. Both lists may be empty -- an unreadable building is not padded with a guess.
    """
    asked = content_terms(question or "")

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


def compose_boundary_pointer(building: str, question: str, records: Sequence[Any]) -> str:
    """A closing line for an honest decline: what the building's records CAN answer, or ''."""
    asked = content_terms(question or "")
    near = [
        r
        for r in records or ()
        if getattr(r, "label", "")
        and any(_close(a, t) for a in asked for t in content_terms(_record_terms(r)))
    ]
    _, labels = nearest_holdings(question, (), near, max_records=3)
    if not labels:
        return ""  # nothing the building keeps is near the question; a guess would be padding
    return f"\n\n{building} does keep {and_list(labels)} records, which I can read for you."
