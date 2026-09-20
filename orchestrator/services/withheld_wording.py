# -*- coding: utf-8 -*-
"""The message a reader sees when figures are held back, in the reader's words (2D-16 wave 2).

Wave-1 held-out read, "What is the current load on the system?":

    *I have withheld the figures for this answer. The grounding check did not pass
    (grounded=False and confidence=0.20) ... What the answer claimed but the data did not support:
    time_series_data. ... Attempted via the sql path.*

Every one of those terms is the verifier's own vocabulary: a boolean, a score, a bus key and a lane
name. None of it helps a facility manager, and "grounded=False" reads as a fault report. The
decision to withhold is unchanged and lives in ``publication_gate``; this module only writes the
sentence, and keeps the three promises the tests pin: it says the figures were WITHHELD, it says
that this is not a statement that they are WRONG, and it says what to ask instead.
"""

from __future__ import annotations

import re
from typing import Iterable, List

#: The verifier's bus keys and internal tokens, in a reader's words. Anything not listed and still
#: shaped like an identifier (snake_case, dotted, camelCase) is dropped rather than shown.
#: What each internal token means as the SOURCE a figure should have come from, worded to finish
#: the sentence "I could not check the figures in this answer against ___".
_PLAIN = {
    "time_series_data": "the building's stored readings",
    "ontology_bindings": "the building's own records",
    "sql_result": "the building's stored readings",
    "sparql_result": "the building's own records",
    "analytics_result": "the calculation they came from",
    "capability_result": "the documents they cite",
}

_IDENTIFIER = re.compile(r"[A-Za-z]+_[A-Za-z_0-9]+|[a-z]+[A-Z][A-Za-z]+|\w+\.\w+\.\w+")


def plain_missing(missing: Iterable[object]) -> List[str]:
    """What could not be backed up, as short plain phrases, without repeats or identifiers."""
    out: List[str] = []
    for item in missing or ():
        text = str(item or "").strip()
        if not text:
            continue
        phrase = _PLAIN.get(text.lower())
        if phrase is None:
            if _IDENTIFIER.search(text) or "=" in text:
                continue
            phrase = text
        if phrase not in out:
            out.append(phrase)
    return out[:3]


def withheld_text(missing: Iterable[object] = ()) -> str:
    """The reader-facing text for a withheld answer; no scores, flags, bus keys or lane names."""
    parts = plain_missing(missing)
    against = parts[0] if parts else "this building's data"
    lines = [
        "**I have withheld the figures this answer had worked out.**",
        "",
        f"I could not check them against {against}, so I won't show numbers I cannot stand "
        "behind.",
    ]
    if len(parts) > 1:
        lines += ["", "I could not check them against " + "; ".join(parts[1:]) + " either."]
    lines += [
        "",
        "This is not a statement that the figures are wrong — only that I could not confirm them "
        "against the data this time.",
        "",
        "Asking for a narrower scope — one room, one day, one quantity — usually lets me check "
        "the answer against the data. For example, ask for the latest reading of one quantity in "
        "one named room.",
    ]
    return "\n".join(lines)
