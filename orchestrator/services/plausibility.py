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

#: WB-22: a number followed by a noun that counts things.
#: ``data`` is the qualifier that actually turns up in front of a count and was not allowed for.
#: A humidity forecast prints "**History used:** 193 data points", and because the noun after the
#: number was "data" rather than "points" the count was judged as a reading and the answer opened
#: with "the recorded humidity value (193, -0.029) is outside the range this quantity can take in
#: %, so it is most likely raw or unscaled sensor output ... the sensor's scaling should be checked
#: before this reading is relied on". The stored series for that sensor is a clean 30-70 %RH with
#: not one impossible value, and the forecast's own predictions were 52.66 %RH (BUG-872).
_COUNT_NOUN_RE = re.compile(
    r"^\s*(?:data\s+)?(?:readings?|sensors?|samples?|rooms?|spaces?|points?|records?|rows?|series|"
    r"floors?|meters?|devices?|values?|measurements?|people|persons?|times|occurrences?|"
    r"episodes?|findings?|reports?|days?|hours?|minutes?|seconds?|weeks?)\b",
    re.IGNORECASE,
)


#: BUG-590: the unit written after a number says which quantity it is. A two-measurand report
#: ("temperature and CO2 on floor 2") opened with "the recorded temperature value (669, 943)
#: is outside the range" — CO2 ppm judged against the first measurand in the question.
_UNIT_KINDS = (
    (re.compile(r"^\s*(?:ppm|parts per million)\b", re.IGNORECASE), "co2"),
    (re.compile(r"^\s*(?:%|percent\b|pct\b)", re.IGNORECASE), "humidity"),
    (re.compile(r"^\s*(?:°\s*[cf]\b|deg(?:rees)?\s*[cf]?\b|℃|℉)", re.IGNORECASE), "temperature"),
    (re.compile(r"^\s*(?:lux|lx)\b", re.IGNORECASE), "illuminance"),
    (re.compile(r"^\s*(?:db\s*a?|decibels?)\b", re.IGNORECASE), "sound"),
    (re.compile(r"^\s*(?:k?pa|hpa|bar|mbar)\b", re.IGNORECASE), "pressure"),
    (re.compile(r"^\s*(?:m/s|km/h|kph|mph|knots?)\b", re.IGNORECASE), "wind"),
    (re.compile(r"^\s*(?:k?wh|mwh|kw|mw)\b", re.IGNORECASE), "energy"),
    (re.compile(r"^\s*(?:µg|μg|ug)\s*/\s*m", re.IGNORECASE), "pm25"),
)


#: BUG-838: the FIRST number of a range carries no unit — the unit is written after the range's
#: other end. "Keep CO2 between 600-800 ppm" has " ppm" after 800 and "-800 ppm" after 600, so
#: 600 read as unitless and was judged as an impossible TEMPERATURE, opening an energy-saving
#: answer with a warning about a value nothing had measured. The range's unit governs both ends.
_RANGE_TAIL_RE = re.compile(r"^\s*(?:[-‐-―−]|to|and)\s*\d[\d,]*(?:\.\d+)?\s*")


def _unit_kind(after: str) -> Optional[str]:
    """The quantity named by the unit that follows a number, or None when there is none."""
    for candidate in (after or "", _RANGE_TAIL_RE.sub("", after or "", count=1)):
        for pattern, kind in _UNIT_KINDS:
            if pattern.match(candidate):
                return kind
    return None


def _nearest_measurand(before: str) -> Optional[str]:
    """The measurand named closest before a number, or None when none is named.

    BUG-838: a value is only judged against the quantity it is actually quoted as. The guard
    inferred one measurand for the WHOLE answer from any mention of the word, so an answer that
    discusses five quantities had every bare number judged against whichever was named first.
    """
    best: Optional[str] = None
    best_at = -1
    low = (before or "").lower()
    for measurand, hints in _MEASURAND_HINTS:
        for hint in hints:
            for m in re.finditer(rf"(?<![a-z0-9]){re.escape(hint)}(?![a-z0-9])", low):
                if m.start() > best_at:
                    best, best_at = measurand, m.start()
    return best


def _is_reading(raw: str, before: str, after: str) -> bool:
    """False for a number that is plainly part of a date, a clock time or an identifier."""
    if _CLOCK_CONTEXT_RE.search(before) or _CLOCK_CONTEXT_RE.match(after):
        return False
    # An identifier is a name that happens to contain digits. Judging it as a quantity
    # produces a warning about a value nothing measured, attached to an answer that was
    # correct — which teaches readers to skip the caveat exactly when it is real.
    if _IDENTIFIER_PREFIX_RE.search(before):
        return False
    # A COUNT is not a reading (WB-22): "across 17 sensors and 1,020 readings" produced
    # "the recorded humidity value (1020) is outside the range this quantity can take".
    if _COUNT_NOUN_RE.match(after):
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


#: A question about a mode, a state or a schedule is answered by an ENUMERATION value ("mode 3960"
#: is a code, not a temperature), so a bare number in its answer is never judged as a reading.
_ENUMERATION_QUESTION_RE = re.compile(
    r"\b(?:mode|modes|status|state|states|enabled|disabled|schedule|scheduled|occupied|"
    r"unoccupied|running|on\s+or\s+off|active|inactive)\b",
    re.IGNORECASE,
)


#: Words that mark a number as a MODEL-EVALUATION metric rather than a reading of the building.
#: A forecast publishes how well each candidate model scored -- RMSE, MAE, MAPE, R-squared -- and
#: those numbers sit in the same answer as the prediction. Measured live: a CO2 forecast printed
#: "Linear Trend ... R² -0.065" beside "SeasonalNaive ... R² 0.946", and the guard reported
#: "the recorded co2 value (-0.065) is outside the range this quantity can take in ppm" at the top
#: of an otherwise correct forecast. An error in ppm is not a reading in ppm, so the unit cannot
#: separate them; the metric's own name is what does.
_METRIC_WORDS = (
    "rmse", "mae", "mape", "r²", "r2", "r-squared", "mse", "smape", "aic", "bic",
    "hold-out", "holdout", "score", "accuracy", "error", "residual", "coefficient",
)


#: How far back a metric header can sit from the number it labels. Measured on a real forecast:
#: the "R²" column header was about 130 characters before its value, because the whole table
#: renders as tab-and-newline separated tokens.
_METRIC_LOOKBACK = 320

#: A number inside a table ROW -- tabs or pipes immediately around it. Required alongside the
#: header, so a metric word merely appearing in nearby prose cannot suppress a real reading.
_TABLE_CELL_RE = re.compile(r"[|\t]\s*$")


def _in_metric_context(before: str, after: str) -> bool:
    """True when a number sits in a model-evaluation table rather than being a reading.

    BOTH conditions are needed. A forecast prints its candidate models' RMSE, MAE, MAPE and
    R-squared beside the prediction, and an R-squared of -0.028 was reported as an impossible CO2
    reading at the top of three otherwise correct forecasts -- an error expressed in ppm is not a
    reading in ppm, so the unit cannot separate them. But a forecast's PREDICTED values are still
    readings and must still be checked, so requiring the number to sit in a table cell as well as
    near a metric label keeps the guard on everything outside the metrics block.
    """
    head = before[-_METRIC_LOOKBACK:].lower()
    if not any(word in head for word in _METRIC_WORDS):
        return False
    return bool(_TABLE_CELL_RE.search(before)) or "\t" in after[:4] or "|" in after[:4]


def implausible_values(text: str, measurand: Optional[str] = None, strict: bool = False) -> list:
    """Numbers in ``text`` that cannot be a reading of ``measurand`` in any usual unit.

    ``strict`` is for a draft whose QUESTION named no quantity: the measurand was inferred from a
    word in the answer, so a number is judged only when the answer itself quotes it as that
    quantity -- by its unit, or by the quantity named right before it. Without that, "3960" from a
    mode sensor was reported as an impossible temperature because the answer mentioned one.
    """
    kind = measurand or measurand_of(text)
    if not kind or kind not in _PLAUSIBLE:
        return []
    low, high, _units = _PLAUSIBLE[kind]
    body = text or ""
    out = []
    for m in _NUMBER_RE.finditer(body):
        raw = m.group(1)
        if not _is_reading(
            raw, body[max(0, m.start() - 2) : m.start()], body[m.end() : m.end() + 24]
        ):
            continue
        # A model's error or fit statistic is not a reading, whatever unit it carries.
        #
        # SLICE TO _METRIC_LOOKBACK, NOT TO 90. This passed 90 characters into a function whose
        # whole job is to look back _METRIC_LOOKBACK (320) of them, so the constant and the
        # comment explaining WHY it is 320 -- "the R-squared column header was about 130
        # characters before its value" -- were both dead. The fix for the CO2 case was written,
        # tested, and then handed a third of the window it needed; measured again 2026-09-23 on a
        # humidity forecast, where R-squared -0.029 was once more reported as an impossible
        # reading (BUG-872). A constant is not in force until its caller lets it be.
        if _in_metric_context(
            body[max(0, m.start() - _METRIC_LOOKBACK) : m.start()], body[m.end() : m.end() + 30]
        ):
            continue
        _named = _unit_kind(body[m.end() : m.end() + 24])
        if _named and _named != kind:
            continue  # written as another quantity's figure (BUG-590)
        _near = _nearest_measurand(body[max(0, m.start() - 80) : m.start()])
        if not _named and _near not in (kind, None):
            continue  # a bare number belongs to the quantity named nearest it (BUG-838)
        if strict and _named != kind and _near != kind:
            continue  # the answer never quotes this number as that quantity
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
    asked = measurand_of(question)
    kind = asked or measurand_of(draft)
    if not kind or kind not in _PLAUSIBLE:
        return None
    if not asked and _ENUMERATION_QUESTION_RE.search(question or ""):
        return None  # "what mode is the HVAC in?" is answered by a code, not a reading
    if not asserts_verdict(draft):
        return None
    bad = implausible_values(draft, kind, strict=not asked)
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
