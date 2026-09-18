# -*- coding: utf-8 -*-
"""Is this number a reading at all? (BUG-439, V10 W1-3)

WHY THIS EXISTS
---------------
On 2026-09-06 the building answered a floor comparison with "157 ppm" and "111 ppm" of
carbon dioxide, called both compliant, and recommended an HVAC upgrade. Outdoor air is
about 420 ppm. Neither number was a low reading; neither was a reading. 174 sensors had
been generating an air-quality INDEX for seven weeks because a hand-written map typed them
by a Brick supertype.

Eighteen lanes could have caught it and none did, for one reason: the only plausibility
bands in the system lived inside the deliberation scorer, as a Python dict, used by the
ranking path alone. `sql`, `compare`, `analytics` and every evidence gate had no notion
that a number could be impossible.

WHAT A BAND IS, AND WHAT IT IS NOT
----------------------------------
`ontosage:physicalMin/physicalMax` in `ontology/measurand_kinds.ttl` say what a quantity
CAN be, deliberately far wider than any comfort or compliance band. ASHRAE 62.1's 420-1500
ppm describes what is COMFORTABLE; 5,000 ppm is an evacuation, and it is still a reading.

So this module answers exactly one question -- *is this a measurement of this quantity?* --
and never *is this good?*. A guard that encoded comfort would suppress the readings a
building most needs to report, which is a worse failure than the one it prevents.

WHAT CALLERS MUST DO WITH THE ANSWER
------------------------------------
An implausible value is REPORTED, naming the sensor. It is never averaged into a figure,
never ranked, never compared and never turned into a recommendation. Dropping it silently
would leave the remaining average looking authoritative, which is how "157 ppm" reached a
user with a capital-expenditure suggestion attached.

BUILDING-AGNOSTIC
-----------------
Every band is read from the active graph. No quantity, class, unit or number appears here.
A building whose graph declares no bands gets `None` from every lookup and every caller
must then say it could not check -- which is a true statement, and different from passing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

_ONTOSAGE = "http://ontosage.org/capabilities#"

_REPO = Path(__file__).resolve().parents[2]
_KINDS_TTL = _REPO / "ontology" / "measurand_kinds.ttl"

#: One query, resolved per UUID, because that is how every reading arrives: the caller has
#: a uuid and a number, not a class. Joining in the lane would make each lane re-derive it.
#:
#: THE EXPLICIT `LIMIT` IS LOAD-BEARING. `SPARQLAgent._execute_query` appends
#: `LIMIT 1000` to any SELECT that does not carry one -- a safety cap meant for
#: model-generated queries, and correct there. This is not one of those: it is an
#: exhaustive map, and the cap silently truncated it to 1,000 of the building's 2,841
#: instrumented uuids.
#:
#: The symptom was a right-looking answer. The floor comparison reported 797 ppm against
#: 775 ppm -- both plausible, both an improvement on the 157/111 that started this -- while
#: a sensor reading 190 ppm was still folded into the average, because its uuid fell
#: outside the truncated map. The gate reported nothing wrong, and only the round number
#: 1,000 in the log gave it away.
#:
#: A cap on an exhaustive query does not fail; it under-reports, and under-reporting from a
#: GUARD reads exactly like having nothing to report.
_BANDS_BY_UUID = """
PREFIX ref:  <https://brickschema.org/schema/Brick/ref#>
PREFIX o:    <http://ontosage.org/capabilities#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?uuid ?kind ?lo ?hi ?unit (COUNT(DISTINCT ?anc) AS ?depth) WHERE {
  ?s ref:hasExternalReference ?r .
  ?r ref:hasTimeseriesId ?uuid .
  ?s a ?cls . ?cls o:measuresQuantityKind ?kind .
  ?kind o:physicalMin ?lo ; o:physicalMax ?hi .
  OPTIONAL { ?kind o:physicalUnit ?unit }
  OPTIONAL { ?cls rdfs:subClassOf+ ?anc }
} GROUP BY ?uuid ?kind ?lo ?hi ?unit
LIMIT 100000
"""


@dataclass(frozen=True)
class Band:
    """What a quantity can physically be, and where the bound comes from."""

    kind: str
    low: float
    high: float
    unit: str = ""

    def holds(self, value: float) -> bool:
        return self.low <= value <= self.high

    def describe(self) -> str:
        u = f" {self.unit}" if self.unit else ""
        return f"{self.kind} {self.low:g}..{self.high:g}{u}"


@dataclass(frozen=True)
class Implausible:
    """One reading that is not a measurement of the quantity it is filed under."""

    uuid: str
    value: float
    band: Band
    label: str = ""

    def render(self) -> str:
        who = self.label or self.uuid[:8]
        return (
            f"{who}: {self.value:g} is outside the possible range for "
            f"{self.band.describe()}"
        )


class PhysicalBands:
    """Bands for the ACTIVE building, loaded once and cached.

    `sparql_exec` is injected so this is unit-testable without a graph, the same shape the
    asset-state lane uses. A load failure is not fatal: the cache stays empty, every lookup
    returns None, and callers report that they could not check.
    """

    def __init__(self, sparql_exec: Callable):
        self._sparql = sparql_exec
        self._by_uuid: Optional[Dict[str, Band]] = None

    async def _load(self) -> Dict[str, Band]:
        if self._by_uuid is not None:
            return self._by_uuid
        out: Dict[str, Band] = {}
        try:
            res = await self._sparql(_BANDS_BY_UUID)
            # THE MOST SPECIFIC CLASS OWNS THE BAND (2026-09-16).
            #
            # A sensor matches every class it inherits, and more than one of them may declare
            # a band. Boiler flow water is typed Leaving_Water_Temperature_Sensor, which is a
            # Water_Temperature_Sensor and also a Temperature_Sensor — and Temperature_Sensor
            # declares the AIR band, -30..70 degC. SAMPLE() picked whichever the store
            # returned first, so 1,035 perfectly ordinary readings of a 72 degC heating flow
            # were announced to the reader as "physically impossible". Depth is the number of
            # ancestors the declaring class has, so the narrowest declaration wins.
            depth_by_uuid: Dict[str, int] = {}
            for b in (res or {}).get("results", {}).get("bindings", []):
                uuid_ = b["uuid"]["value"]
                depth = int((b.get("depth") or {}).get("value", 0) or 0)
                if uuid_ in out and depth <= depth_by_uuid.get(uuid_, -1):
                    continue
                depth_by_uuid[uuid_] = depth
                out[uuid_] = Band(
                    kind=str(b["kind"]["value"]).rsplit("#", 1)[-1],
                    low=float(b["lo"]["value"]),
                    high=float(b["hi"]["value"]),
                    unit=(b.get("unit") or {}).get("value", ""),
                )
        except Exception as exc:
            # Not fatal, and not silent. An empty cache means every caller says it could
            # not check -- which is honest -- but a lane that never logs why would look
            # like a lane with nothing to report.
            logger.warning(f"[physical_bands] could not load bands: {exc}")
        self._by_uuid = out
        # A ROUND NUMBER IS A CAP, NOT A COUNT. Said out loud because that is the only
        # thing that revealed the truncation above: the figure was exactly 1,000.
        _suspicious = len(out) > 0 and len(out) % 1000 == 0
        logger.info(
            f"[physical_bands] {len(out)} sensor(s) carry a declared physical band"
            + (
                "  <-- SUSPICIOUS: an exact multiple of 1,000 usually means a query cap "
                "truncated the map, not that the building has that many"
                if _suspicious
                else ""
            )
        )
        return out

    async def band_for(self, uuid: str) -> Optional[Band]:
        return (await self._load()).get(uuid)

    async def check(
        self, readings: Sequence[Tuple[str, float]], labels: Optional[Dict[str, str]] = None
    ) -> Tuple[List[Tuple[str, float]], List[Implausible]]:
        """Split readings into (usable, implausible).

        Returns BOTH halves rather than filtering. A caller that only received the survivors
        would compute an average over them and present it as the answer, which is precisely
        the failure this exists to prevent: the reader must be told what was excluded.

        A reading whose sensor declares no band is USABLE. Absence of a band is not evidence
        of implausibility, and treating it as such would suppress every quantity the
        ontology has not got to yet.
        """
        bands = await self._load()
        labels = labels or {}
        keep: List[Tuple[str, float]] = []
        bad: List[Implausible] = []
        for uuid, value in readings:
            band = bands.get(uuid)
            try:
                v = float(value)
            except (TypeError, ValueError):
                keep.append((uuid, value))
                continue
            if band is None or band.holds(v):
                keep.append((uuid, v))
            else:
                bad.append(Implausible(uuid=uuid, value=v, band=band, label=labels.get(uuid, "")))
        return keep, bad


# ── THE SAME BANDS, REACHABLE WITHOUT A GRAPH HANDLE ─────────────────────────
#
# `PhysicalBands` above resolves a band per UUID, which is right for every lane that
# starts from a uuid and a number. The RANKING lane does not: it works in MODALITIES
# ("co2", "occupancy"), it has no SPARQL executor in its signature, and it is the lane
# that printed `occupancy: -7.719` and `co2: -260.986` as the evidence behind a
# recommendation on 2026-09-17 (run-3 row 99). Those were FORECASTS -- a linear trend
# extrapolated straight through zero -- so nothing was wrong with the readings and
# everything was wrong with the projection presented as one.
#
# Rather than thread a graph handle through the executor, the declarations are read from
# the shared TBox file they live in. It is the same source `_BANDS_BY_UUID` queries; the
# join from a modality to a measurand goes through the building's own modality config, so
# no quantity, class or number appears here either.


def _statements(text: str) -> List[str]:
    """Turtle statements, comments stripped. Split on a '.' that ENDS a line.

    A period inside a decimal (`41.5`) never ends a line in valid Turtle, and the
    lookbehind requires whitespace, a quote or '>' before the terminator, so `2000 .`
    splits and `20.95 ;` does not.
    """
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    return re.split(r'(?<=[\s>"])\.\s*(?:\n|$)', body)


_SUBJECT_RE = re.compile(r"^\s*(?:ontosage|o):([\w.\-]+)", re.M)
_MIN_RE = re.compile(r"ontosage:physicalMin\s+(-?\d+(?:\.\d+)?)")
_MAX_RE = re.compile(r"ontosage:physicalMax\s+(-?\d+(?:\.\d+)?)")
_UNIT_RE = re.compile(r'ontosage:physicalUnit\s+"([^"]*)"')


@lru_cache(maxsize=1)
def declared_bands() -> Dict[str, Band]:
    """{measurand local name: Band} from `ontology/measurand_kinds.ttl`.

    `{}` when the file is missing or unreadable -- which makes every lookup return None
    and every caller say it could not check, the same failure mode as an empty graph.
    """
    if not _KINDS_TTL.is_file():
        logger.debug("[physical_bands] no measurand_kinds.ttl; declared bands unavailable")
        return {}
    try:
        text = _KINDS_TTL.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - unreadable file
        logger.warning(f"[physical_bands] measurand_kinds.ttl unreadable: {exc}")
        return {}
    out: Dict[str, Band] = {}
    for stmt in _statements(text):
        subject = _SUBJECT_RE.search(stmt)
        lo, hi = _MIN_RE.search(stmt), _MAX_RE.search(stmt)
        if not (subject and lo and hi):
            continue
        unit = _UNIT_RE.search(stmt)
        out[subject.group(1)] = Band(
            kind=subject.group(1),
            low=float(lo.group(1)),
            high=float(hi.group(1)),
            unit=unit.group(1) if unit else "",
        )
    return out


def band_for_measurand(kind: str) -> Optional[Band]:
    """The declared band for a measurand local name, or None when undeclared."""
    return declared_bands().get((kind or "").strip())


def _class_local(name: str) -> str:
    s = str(name or "").strip()
    for sep in ("#", "/", ":"):
        s = s.rsplit(sep, 1)[-1]
    return s


@lru_cache(maxsize=256)
def band_for_modality(modality: str, building_id: Optional[str] = None) -> Optional[Band]:
    """The widest declared band across the Brick classes this modality is made of.

    WIDEST, not narrowest, and deliberately. A modality may span classes with different
    bands -- `occupancy` covers a counting sensor (0..10000 people) and a motion contact
    (0..1) -- and a guard that took the narrower one would announce every ordinary
    headcount as impossible. The union still rejects a negative, which is the whole of
    what this catches.

    None when the modality is unknown or no class under it declares a band. Absence of a
    band is never evidence of implausibility.
    """
    try:
        from orchestrator.services.deliberation.coverage_audit import load_modalities
        from orchestrator.services.measurand_kinds import measurand_of
    except Exception as exc:  # pragma: no cover - config is optional
        logger.debug(f"[physical_bands] modality config unavailable: {exc}")
        return None
    try:
        specs = load_modalities(building_id)
    except Exception as exc:  # pragma: no cover
        logger.debug(f"[physical_bands] modality config unreadable: {exc}")
        return None
    spec = next((s for s in specs if s.name == modality), None)
    if spec is None:
        return None
    classes = list(spec.brick_classes) + [str((spec.sat or {}).get("brick_class") or "")]
    bands = [
        b
        for b in (band_for_measurand(measurand_of(_class_local(c))) for c in classes if c)
        if b is not None
    ]
    if not bands:
        return None
    kinds = sorted({b.kind for b in bands})
    units = {b.unit for b in bands if b.unit}
    return Band(
        kind=kinds[0] if len(kinds) == 1 else "/".join(kinds),
        low=min(b.low for b in bands),
        high=max(b.high for b in bands),
        unit=units.pop() if len(units) == 1 else "",
    )


def excluded_sentence(implausible: Sequence[Implausible], limit: int = 3) -> str:
    """One sentence COUNTING what was excluded and naming it. Empty when nothing was.

    A reading outside its quantity's possible range is not a low reading; it is a broken
    one. It must not be averaged, ranked or recommended on -- and it must not vanish
    either, because an answer computed over the survivors and presented bare reads as an
    answer computed over everything.
    """
    n = len(implausible)
    if not n:
        return ""
    shown = "; ".join(i.render() for i in implausible[:limit])
    more = f", and {n - limit} more" if n > limit else ""
    noun = "reading was" if n == 1 else "readings were"
    return (
        f"**{n} {noun} outside the physically possible range and {'was' if n == 1 else 'were'} "
        f"excluded** from the figures above: {shown}{more}. A value outside what a quantity "
        f"can be is a stream or a projection that has gone wrong, not a measurement of the "
        f"building."
    )


def caveat(implausible: Sequence[Implausible], limit: int = 3) -> str:
    """One sentence naming what was excluded and why. Empty when nothing was."""
    if not implausible:
        return ""
    shown = "; ".join(i.render() for i in implausible[:limit])
    more = f" and {len(implausible) - limit} more" if len(implausible) > limit else ""
    return (
        f"**{len(implausible)} reading(s) were excluded as physically impossible** and are "
        f"not in the figures above: {shown}{more}. A value outside its quantity's possible "
        f"range is usually a stream carrying a different quantity's scale, not a fault in "
        f"the building."
    )
