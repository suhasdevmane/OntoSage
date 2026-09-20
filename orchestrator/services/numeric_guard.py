# -*- coding: utf-8 -*-
"""
numeric_guard.py — ONE allowed-numbers builder for every data-carrying
narration (V5-T29).

The deliberate lane has always enforced "every number in the prose exists in
the dossier". The V5 lanes (events, register, diagnosis) build their prose
from deterministic templates over structured payloads — the same invariant
holds by construction, and THIS module makes it checked rather than assumed:
a template bug that interpolates the wrong field now suppresses the narration
instead of shipping a wrong number.

``guard_payload`` walks a lane's structured result: every numeric leaf becomes
an allowed number (in the same formats the dossier guard accepts), every
string leaf becomes a quotable text blob. The lane's ``formatted_response``
is then scanned; any number backed by neither is a violation. On violation the
response is replaced with the STANDARD suppression text — identical wording in
every lane, so honesty failures look the same everywhere.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Set, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")

#: numbers that carry no factual claim (list indices, tiny ordinals)
INNOCUOUS = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "24", "25", "100"}

#: What a reader is told when a figure in a drafted answer could not be traced to the data.
#:
#: REWORDED (2D-16 wave 5). It used to read *"I computed an answer but its narration failed the
#: evidence check ... The structured result is still available; please try rephrasing."* -- a
#: message about the pipeline ("narration", "the evidence check", "the structured result") that a
#: reader cannot act on, and "try rephrasing" is wrong advice, because rephrasing does not change
#: which figure could not be checked. It now says plainly that a figure could not be checked and
#: what to ask instead. A payload that names its source gets the source-named form in
#: `_plain_decline`; the figure itself is NOT echoed, because a number that failed the check is a
#: number this system has declined to state.
SUPPRESSION_TEXT = (
    "I worked out an answer but I'm not showing it: a figure in it could not be checked against "
    "this building's data. Ask for one room, one day or one quantity and I can check it."
)


def add_number(allowed: Set[str], x: Any) -> None:
    """Register one numeric value in every rendering the templates use."""
    if x is None or isinstance(x, bool):
        return
    try:
        v = float(x)
    except (TypeError, ValueError):
        return
    for s in (
        f"{v:g}",
        f"{v:.0f}",
        f"{v:.1f}",
        f"{v:.2f}",
        f"{v:.3f}",
        str(int(v)) if v == int(v) else None,
    ):
        if s is not None:
            allowed.add(s.lstrip("-"))
    if v == int(v):  # thousands-formatted integers ("1,316")
        allowed.add(f"{int(v):,}".lstrip("-"))


def collect(payload: Any, allowed: Set[str], blobs: List[str], _depth: int = 0) -> None:
    """Recursive walk: numeric leaves → allowed; string leaves → quotable blobs."""
    if _depth > 8:
        return
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k == "formatted_response":
                continue  # the text under test must not vouch for itself
            collect(v, allowed, blobs, _depth + 1)
    elif isinstance(payload, (list, tuple, set)):
        for v in payload:
            collect(v, allowed, blobs, _depth + 1)
    elif isinstance(payload, bool):
        return
    elif isinstance(payload, (int, float)):
        add_number(allowed, payload)
    elif isinstance(payload, str):
        blobs.append(payload)
    else:  # datetimes and friends quote via their string form
        blobs.append(str(payload))


def _strip_thousands(text: str) -> str:
    """'1,316 bookings' scans as 1316, not as 1 and 316."""
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", text or "")


def find_unbacked(text: str, allowed: Set[str], blobs: Iterable[str]) -> List[str]:
    """Numbers in ``text`` backed by neither the allowed set nor any blob."""
    quoted: Set[str] = set()
    for blob in blobs:
        for tok in _NUM_RE.findall(_strip_thousands(blob)):
            quoted.add(tok.lstrip("-"))
    violations = []
    text = _strip_thousands(text)
    for tok in _NUM_RE.findall(text or ""):
        t = tok.lstrip("-")
        if t in INNOCUOUS or t in allowed or t in quoted:
            continue
        # zero-padded clock/date fragments ("14:00" -> "00", "08:30" -> "08")
        # are the same number as their unpadded form; without this a perfectly
        # backed time renders as a guard violation and suppresses the answer
        unpadded = t.lstrip("0") or "0"
        if unpadded in INNOCUOUS or unpadded in allowed or unpadded in quoted:
            continue
        # a bare fragment of an allowed decimal ("32" from "32.117") is backed
        if any(a.startswith(t + ".") or a.startswith(t + ",") for a in allowed):
            continue
        violations.append(tok)
    return violations


def guard_payload(payload: Any, lane: str) -> Any:
    """Scan a lane result's formatted_response against its own fields.

    Returns the payload unchanged when clean; on violation, logs ERROR and
    swaps the narration for the standard suppression text (the structured
    fields stay intact for downstream consumers).
    """
    if not isinstance(payload, dict):
        return payload
    text = payload.get("formatted_response") or ""
    if not text:
        return payload
    allowed: Set[str] = set()
    blobs: List[str] = []
    collect(payload, allowed, blobs)
    violations = find_unbacked(text, allowed, blobs)
    if violations:
        logger.error(f"[numeric-guard] lane={lane} unbacked numbers {violations} — suppressed")
        payload = dict(payload)
        payload["formatted_response"] = _plain_decline(payload)
        payload["guard_violations"] = violations
    return payload


def _plain_decline(payload: dict) -> str:
    """What the reader sees when a narration is withheld: a decline naming the source.

    "I computed an answer but its narration failed the evidence check" is a system message; a
    reader cannot act on it. When the payload says which register or store it came from, the
    decline names it and says what to do; without a source the standard text stands.
    """
    source = str(payload.get("source") or "").strip()
    if not source:
        return SUPPRESSION_TEXT
    return (
        f"I read the {source}, but I could not confirm every figure in the answer I drafted "
        "against what it holds, so I am not stating it. Try asking about one thing that source "
        "records, or name the register or system that holds the rest."
    )
