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

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

_ONTOSAGE = "http://ontosage.org/capabilities#"

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
