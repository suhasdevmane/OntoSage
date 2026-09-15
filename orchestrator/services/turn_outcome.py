# -*- coding: utf-8 -*-
"""What actually happened to a turn, typed (V12-19, review B15, CAVEAT-415/500/502).

    B15  "An injected lane timeout, backend outage and delayed completion each produce an
          explicit partial or failure outcome; first-pass and retry status remain
          separately reportable everywhere a number is published."

WHY A STRING WAS NOT ENOUGH
----------------------------
`_safe_node` caught every exception as one undifferentiated `Exception` and recorded
`{node}_error: str(e)` plus a "degraded_services" line. Three genuinely different events
therefore looked identical to everything downstream:

  the lane TIMED OUT           — the data probably exists; ask again or ask for less
  the backend was UNREACHABLE  — nothing about this building is knowable right now
  the lane RAISED              — a defect, and re-asking will reproduce it

And when the exception carried no message — `httpx.ReadTimeout`, `asyncio.TimeoutError`, a
bare `Exception()` — `str(e)` was the empty string, so the record was not merely untyped
but blank. That is CAVEAT-415 measured from the other end: 62 warnings in six hours that
said nothing, 52 of them the capability lane abandoning the ontology on a SPARQL timeout.

CAVEAT-500 IS THE REASON TIMEOUT IS ITS OWN TYPE
--------------------------------------------------
The same question measured 10.7 s, 61.1 s and 13.3 s on three consecutive asks — a 10×
spread, once past a 121 s client timeout, every answer correct. A timeout on this system is
frequently LATENCY rather than a defect, and folding it in with a genuine failure makes a
probe run unreadable in both directions: a real defect hides among the slow cases, and a
slow case is reported as broken.

FIRST PASS IS NOT AN ATTRIBUTE OF SUCCESS
-------------------------------------------
`first_pass` travels with the outcome rather than being reconstructed by whoever publishes
a number. A retry that succeeds is still a first-pass failure, and every place that has
ever had to re-derive that has eventually folded it into a success total.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Outcome(str, Enum):
    """What happened, in the only five kinds this system can tell apart honestly."""

    OK = "ok"
    #: Ran, produced something, and something else it needed did not arrive.
    PARTIAL = "partial"
    #: Exceeded its deadline. NOT a synonym for failure — see CAVEAT-500.
    TIMEOUT = "timeout"
    #: A store or service could not be reached at all.
    BACKEND_UNAVAILABLE = "backend_unavailable"
    #: Raised. Re-asking reproduces it.
    FAILED = "failed"


#: Exception class NAMES that mean "deadline", not "broken". Matched by name rather than by
#: `isinstance` so this module imports nothing: importing httpx here to identify an httpx
#: error would make the outcome classifier depend on the transport it classifies.
_TIMEOUT_NAMES = frozenset(
    {
        "TimeoutError",
        "ReadTimeout",
        "WriteTimeout",
        "ConnectTimeout",
        "PoolTimeout",
        "TimeoutException",
        "CancelledError",
    }
)

#: …and the ones that mean "nothing is there to talk to".
_UNAVAILABLE_NAMES = frozenset(
    {
        "ConnectError",
        "ConnectionError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "OperationalError",
        "InterfaceError",
        "ServerDisconnectedError",
        "RemoteProtocolError",
        "SSLError",
        "gaierror",
    }
)


def classify(exc: BaseException) -> Outcome:
    """Which kind of failure this exception is.

    Walks the cause chain: a timeout wrapped in a RuntimeError by a helper is still a
    timeout, and the wrapper is the thing most likely to be the arbitrary one.
    """
    seen = 0
    cur: Optional[BaseException] = exc
    while cur is not None and seen < 8:
        name = type(cur).__name__
        if isinstance(cur, asyncio.TimeoutError) or name in _TIMEOUT_NAMES:
            return Outcome.TIMEOUT
        if name in _UNAVAILABLE_NAMES:
            return Outcome.BACKEND_UNAVAILABLE
        cur = cur.__cause__ or cur.__context__
        seen += 1
    return Outcome.FAILED


@dataclass
class LaneOutcome:
    """One lane's result. `first_pass` is carried, never re-derived."""

    lane: str
    outcome: Outcome
    detail: str = ""
    #: False only when this lane was re-run after an earlier attempt in the SAME turn.
    first_pass: bool = True
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.OK

    def as_dict(self) -> Dict[str, Any]:
        return {
            "lane": self.lane,
            "outcome": self.outcome.value,
            "detail": self.detail,
            "first_pass": self.first_pass,
            "duration_ms": self.duration_ms,
        }


#: The external sentence for each kind. ONE authorised wording each, for the same reason
#: the retrieval-outcome taxonomy has one: a taxonomy the reader cannot perceive has
#: achieved nothing, and two wordings for one state is how a reader learns to ignore both.
_WORDING = {
    Outcome.TIMEOUT: (
        "Part of this answer timed out rather than failing — the data may well be there. "
        "Asking again, or for a narrower scope, usually reaches it."
    ),
    Outcome.BACKEND_UNAVAILABLE: (
        "I could not reach one of this building's data stores, so this answer is "
        "incomplete. This is an availability problem, not a gap in the building's data."
    ),
    Outcome.FAILED: (
        "Part of this request failed and re-asking it will reproduce the same failure. "
        "The diagnostic is in the turn's trace."
    ),
    Outcome.PARTIAL: (
        "I answered part of this request. What is missing is named above rather than "
        "left for you to notice."
    ),
}


@dataclass
class TurnOutcome:
    """The roll-up for one turn."""

    lanes: List[LaneOutcome] = field(default_factory=list)

    def record(self, lane: LaneOutcome) -> None:
        self.lanes.append(lane)

    @property
    def outcome(self) -> Outcome:
        """The worst thing that happened, with TIMEOUT ranked below FAILED.

        A turn where one lane timed out and another raised is reported as FAILED: the
        reproducible defect is the more actionable fact, and reporting the timeout would
        send the reader to re-ask a question that will fail the same way.
        """
        order = [
            Outcome.FAILED,
            Outcome.BACKEND_UNAVAILABLE,
            Outcome.TIMEOUT,
            Outcome.PARTIAL,
            Outcome.OK,
        ]
        found = {lo.outcome for lo in self.lanes}
        for candidate in order:
            if candidate in found:
                return candidate
        return Outcome.OK

    @property
    def first_pass_ok(self) -> bool:
        """True only when nothing needed a second attempt AND nothing failed.

        Separate from `outcome` on purpose: a turn that recovered on retry has
        `outcome == OK` and `first_pass_ok == False`, and folding those together is the
        thing this project keeps having to undo in its own measurements.
        """
        return all(lo.ok and lo.first_pass for lo in self.lanes)

    @property
    def retried(self) -> List[str]:
        return [lo.lane for lo in self.lanes if not lo.first_pass]

    def note(self) -> str:
        """The sentence to show the user, or "" when the turn was clean."""
        worst = self.outcome
        return _WORDING.get(worst, "") if worst is not Outcome.OK else ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "first_pass_ok": self.first_pass_ok,
            "retried": self.retried,
            "lanes": [lo.as_dict() for lo in self.lanes],
        }


def from_state(results: Optional[Dict[str, Any]]) -> TurnOutcome:
    """Rebuild the turn outcome from the bus, for a reader that only has the state."""
    turn = TurnOutcome()
    for entry in (results or {}).get("lane_outcomes", []) or []:
        if not isinstance(entry, dict):
            continue
        try:
            turn.record(
                LaneOutcome(
                    lane=str(entry.get("lane", "?")),
                    outcome=Outcome(str(entry.get("outcome", "failed"))),
                    detail=str(entry.get("detail", "")),
                    first_pass=bool(entry.get("first_pass", True)),
                    duration_ms=int(entry.get("duration_ms") or 0),
                )
            )
        except ValueError:
            continue
    return turn
