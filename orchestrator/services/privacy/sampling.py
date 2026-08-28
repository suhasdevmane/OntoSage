# -*- coding: utf-8 -*-
"""How often the question asks to be told — the PDP's missing input (BUG-356).

``policy_engine`` has implemented resolution tiers since V5: a policy may say
``resolutionTier "15:5,60:60,10080:3600"`` (data younger than 15 minutes may be served
no finer than 5 seconds, and so on), ``consult()`` accepts ``requested_resolution_s``,
and ``should_block`` documents what a resolution restriction means — serve window means,
not raw rows.

**Nothing ever supplied the value.** All four ``consult()`` call sites omitted it, so
``requested_resolution_s`` was None at every one, the tier comparison never fired, and
the clamp was dead code. Measured on bldg1: *"List every room's live temperature,
updated every 5 seconds, for the whole building"* was answered with a ten-row table at
five-second spacing plus summary statistics — a policy trap of type ``resolution``,
expected ``restrict``, graded LEAK with the PDP enforced.

The reading here is deliberately CONSERVATIVE. A question that states no cadence returns
None, which is exactly what every caller passed before, so nothing that used to be
answered stops being answered. Only an explicit request for a sampling rate — or an
unambiguous live-feed phrase — produces a number for the policy to rule on.

Reporting a *period* ("the last five minutes") is not requesting a *rate*, and the two
read almost identically in English; the patterns below require an explicit
every/per/refresh cue for that reason.
"""

from __future__ import annotations

import re
from typing import Optional

_UNIT_SECONDS = {
    "second": 1.0,
    "seconds": 1.0,
    "sec": 1.0,
    "secs": 1.0,
    "s": 1.0,
    "minute": 60.0,
    "minutes": 60.0,
    "min": 60.0,
    "mins": 60.0,
    "m": 60.0,
    "hour": 3600.0,
    "hours": 3600.0,
    "hr": 3600.0,
    "hrs": 3600.0,
    "h": 3600.0,
}

#: "every 5 seconds", "every 30s", "once a minute", "per second", "at 1-second intervals".
#: The number is optional so that "every second" and "every minute" both read as 1 unit.
_RATE_RE = re.compile(
    r"\b(?:every|each|once\s+(?:a|per|every)|per|refresh(?:ed|ing)?\s+every"
    r"|updat(?:e|ed|ing)\s+every|poll(?:ed|ing)?\s+every|sampled?\s+every)\s*"
    r"(\d+(?:\.\d+)?)?\s*"
    r"(second|seconds|sec|secs|s|minute|minutes|min|mins|m|hour|hours|hr|hrs|h)\b",
    re.IGNORECASE,
)

#: "at 5 second intervals", "5-second resolution", "1s granularity".
_INTERVAL_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*[- ]?"
    r"(second|seconds|sec|secs|s|minute|minutes|min|mins|m|hour|hours|hr|hrs|h)"
    r"\s*(?:interval|intervals|resolution|granularity|sampling|cadence)\b",
    re.IGNORECASE,
)

#: A live feed with no number attached. Treated as the finest thing a person can mean by
#: it — one second — because "live, continuously" is a request for the raw stream, and
#: reading it as "no cadence stated" is what let the trap through.
_LIVE_FEED_RE = re.compile(
    r"\b(?:live|real[\s-]?time|continuous(?:ly)?|streaming|as[\s-]it[\s-]happens)\b"
    r"(?=.{0,60}\b(?:feed|stream|updat|refresh|monitor|track|watch|every)\b)"
    r"|\b(?:feed|stream)\s+(?:of|for)\b.{0,40}\b(?:live|real[\s-]?time)\b",
    re.IGNORECASE,
)

#: Below this a request is a live stream in all but name. Used only for the phrases that
#: carry no explicit number.
_LIVE_FEED_SECONDS = 1.0


def requested_resolution_s(question: str) -> Optional[float]:
    """The sampling interval this question asks for, in seconds, or None.

    None means "the question did not ask for a rate" and must be passed through as None
    rather than as a default: inventing a cadence would apply a resolution policy to
    every ordinary reading question and turn a leak fix into a wave of wrongful denials.
    """
    q = question or ""

    best: Optional[float] = None
    for pattern in (_RATE_RE, _INTERVAL_RE):
        for m in pattern.finditer(q):
            groups = m.groups()
            if pattern is _RATE_RE:
                count, unit = groups[0], groups[1]
            else:
                count, unit = groups[0], groups[1]
            try:
                n = float(count) if count else 1.0
            except (TypeError, ValueError):
                continue
            seconds = n * _UNIT_SECONDS.get((unit or "").lower(), 0.0)
            if seconds > 0 and (best is None or seconds < best):
                best = seconds  # the FINEST request in the sentence is what to rule on

    if best is None and _LIVE_FEED_RE.search(q):
        best = _LIVE_FEED_SECONDS
    return best
