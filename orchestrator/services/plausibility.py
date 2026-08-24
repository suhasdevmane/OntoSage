"""Is a reading physically possible for what it claims to measure? (CAVEAT-053)

A comparative verdict — "strong", "high", "too warm" — is a claim that the value
was compared against something. When the value is raw or unscaled there is nothing
to compare it to, and asserting one is a fabrication wearing a real number.

Observed live: "is the wind strong?" answered *"Yes - the wind is very strong right
now. The most recent reading shows a value of approximately 8308 (the unit used in
your data)."* The reply admits it cannot name the unit and delivers a confident
verdict anyway. The underlying column ranges 0.14 to 9998.58 with a mean of 4506 —
not wind speed in any unit anyone uses.

Why this is building-agnostic
-----------------------------
The bounds below are facts about the physical world, not about any building: air
temperature spans the same range on every site on the planet. They are keyed on
MEASURAND words that come from Brick class names — the shared TBox — so a building
that calls its sensor anything at all is still covered. Nothing here knows a site,
a namespace or a sensor id.

Deliberately wide: the job is to catch a value that is impossible in EVERY unit a
measurand is normally reported in (8308 is not a wind speed in m/s, km/h, mph or
knots), not to police borderline readings. A guard that fires on plausible values
would suppress real answers, which is the worse failure.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

# measurand token -> (low, high, the units this span covers)
# The span is the UNION of the normal ranges across the units the quantity is
# commonly reported in, so a value outside it is wrong under every reading.
_PLAUSIBLE: Dict[str, Tuple[float, float, str]] = {
    "wind": (0.0, 250.0, "m/s, km/h, mph or knots"),
    "temperature": (-90.0, 200.0, "°C or °F"),
    "humidity": (0.0, 100.0, "%"),
    "co2": (0.0, 50000.0, "ppm"),
    "pressure": (0.0, 200000.0, "Pa, hPa or bar"),
    "illuminance": (0.0, 200000.0, "lux"),
    "sound": (0.0, 200.0, "dB"),
    "occupancy": (0.0, 100000.0, "people"),
    "voltage": (0.0, 500000.0, "V"),
    "current": (0.0, 100000.0, "A"),
    "flow": (0.0, 100000.0, "flow units"),
    "ph": (0.0, 14.0, "pH"),
}

# Which measurand a piece of text is about. Longest first so "wind" does not
# swallow a phrase that also mentions temperature.
_MEASURAND_HINTS = (
    ("wind", ("wind speed", "wind")),
    ("temperature", ("temperature", "temp")),
    ("humidity", ("humidity", "humid")),
    ("co2", ("co2", "co₂", "carbon dioxide")),
    # No _PLAUSIBLE range on purpose — "air quality" may be an index or a ppm figure,
    # so no single span is impossible-in-every-unit. The hint still matters: it is
    # what lets the capability door recognise an air-quality question as a READING
    # request, so a question naming an absent place gets the referent gate rather
    # than a document match (TODO-133 family).
    ("air quality", ("air quality", "aqi", "iaq")),
    ("pressure", ("pressure",)),
    ("illuminance", ("illuminance", "lux", "light level")),
    ("sound", ("sound", "noise", "decibel")),
    ("occupancy", ("occupancy", "people count")),
    ("voltage", ("voltage", "volts")),
    ("current", ("amperage", "amps")),
    (
        "flow",
        ("flow rate", "flow"),
    ),
    (
        "ph",
        ("ph level", "ph of"),
    ),
)

# A verdict asserts a comparison. These are the words that make a reply a judgement
# rather than a report.
_VERDICT_RE = re.compile(
    r"\b(?:very\s+)?(?:strong|weak|high|low|elevated|excessive|hot|cold|warm|chilly|"
    r"comfortable|uncomfortable|poor|good|excellent|dangerous|safe|normal|abnormal)\b",
    re.IGNORECASE,
)

# The leading minus is captured as a SIGN, not skipped: -273 must be judged as
# minus 273. It cannot swallow a date's separator, because the lookbehind rejects a
# hyphen that directly follows a digit ("2026-08").
_NUMBER_RE = re.compile(r"(?<![\w.])(-?\d{1,3}(?:,\d{3})+|-?\d+(?:\.\d+)?)(?![\w])")
# A reply carries numbers that are not readings — the year in a timestamp, the
# hour and minute of a reading time. Flagging "2026" as an impossible wind speed
# would discredit the whole caveat, so these are excluded before judging. Only ':'
# and '/' count as separators here; '-' is left out because it is also a minus.
_CLOCK_CONTEXT_RE = re.compile(r"[:/]\s*$|^\s*[:/]")

#: An identifier's numeric tail — REP-571188, WO-4471, #90210. The lookbehind in _NUMBER_RE
#: rejects a preceding word character but NOT a hyphen, so every hyphenated id in an answer
#: was a candidate reading. A report acknowledgement is largely made of one, which is how
#: "logged as REP-571188" became "the recorded sound value (571188) is outside the range".
_IDENTIFIER_PREFIX_RE = re.compile(r"(?:[A-Za-z]-|#|\bno\.\s*|\bref\s*)$")


def _is_reading(raw: str, before: str, after: str) -> bool:
    """False for a number that is plainly part of a date, a clock time or an identifier."""
    if _CLOCK_CONTEXT_RE.search(before) or _CLOCK_CONTEXT_RE.match(after):
        return False
    # An identifier is a name that happens to contain digits. Judging it as a quantity
    # produces a warning about a value nothing measured, attached to an answer that was
    # correct — which teaches readers to skip the caveat exactly when it is real.
    if _IDENTIFIER_PREFIX_RE.search(before):
        return False
    try:
        val = float(raw.replace(",", ""))
    except ValueError:
        return False
    # A bare four-digit integer in calendar range is a year, not a measurement.
    if "." not in raw and "," not in raw and 1900 <= val <= 2100 and len(raw) == 4:
        return False
    return True


def measurand_of(text: str) -> Optional[str]:
    """Which physical quantity this text is about, or None.

    BUG-169: hints match on WORD BOUNDARIES, never substrings — plain `in`
    made "2h window" read as WIND (and would make "attempt" read as
    temperature), which mislabelled a dossier's CO2 numbers as impossible
    wind speeds the moment an availability answer mentioned its window.
    """
    t = (text or "").lower()
    for measurand, hints in _MEASURAND_HINTS:
        for h in hints:
            if re.search(rf"(?<![a-z0-9]){re.escape(h)}(?![a-z0-9])", t):
                return measurand
    return None


def implausible_values(text: str, measurand: Optional[str] = None) -> list:
    """Numbers in ``text`` that cannot be a reading of ``measurand`` in any usual unit."""
    kind = measurand or measurand_of(text)
    if not kind or kind not in _PLAUSIBLE:
        return []
    low, high, _units = _PLAUSIBLE[kind]
    body = text or ""
    out = []
    for m in _NUMBER_RE.finditer(body):
        raw = m.group(1)
        if not _is_reading(
            raw, body[max(0, m.start() - 2) : m.start()], body[m.end() : m.end() + 2]
        ):
            continue
        val = float(raw.replace(",", ""))
        if val < low or val > high:
            out.append(val)
    return out


def asserts_verdict(text: str) -> bool:
    """True when the text characterises a value rather than merely reporting it."""
    return bool(_VERDICT_RE.search(text or ""))


def implausibility_note(question: str, draft: str) -> Optional[str]:
    """A caveat to attach when a draft judges a reading that cannot be real.

    Returns None unless the answer BOTH renders a verdict and rests on a value
    outside every plausible range — a raw number reported as a raw number is fine,
    and so is a verdict over a believable one.
    """
    kind = measurand_of(question) or measurand_of(draft)
    if not kind or kind not in _PLAUSIBLE:
        return None
    if not asserts_verdict(draft):
        return None
    bad = implausible_values(draft, kind)
    if not bad:
        return None
    low, high, units = _PLAUSIBLE[kind]
    shown = ", ".join(f"{v:g}" for v in bad[:3])
    logger.info(f"[plausibility] {kind} value(s) {shown} outside {low}–{high} ({units})")
    return (
        f"⚠️ The recorded {kind} value ({shown}) is outside the range this quantity "
        f"can take in {units}, so it is most likely raw or unscaled sensor output. "
        f"I can report the number but cannot say whether it is high or low, and the "
        f"sensor's scaling should be checked before this reading is relied on."
    )
