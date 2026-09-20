# -*- coding: utf-8 -*-
"""The points a building lets the assistant WRITE, named the way a person names them (CAVEAT-817).

The failure this prevents (demo rehearsal run 1, item D42; tail A row F37): asked to open the
windows on floor 3 or to turn off the lights in a room, the control lane declined correctly and
then said *"the points this building lets me write are: `AHU-F5-SP`, `LIGHTING-3F-SP`,
`VAV-501-SP`"* -- three internal identifiers, to a person who has no way to know what any of them
is or what a valid request looks like.

Where a label comes from, in order (first hit wins, so the operator's words outrank a guess):

1. ``actuation.point_labels`` in the building's ``building.yaml`` -- operational config, sitting
   next to ``points_writable`` which is the list it describes;
2. an ``rdfs:label`` on the point's own IRI in the graph (TTL-first: a building that authors the
   point as a triple gets its label with no config);
3. the identifier itself, expanded only where the expansion is certain (``SP`` is a setpoint,
   ``AHU`` an air handling unit) and never where it would be a guess (``501`` is not "room 5.01").
   An identifier-only label keeps the identifier in brackets, because that is all there is.

A request may name a point by its label as well as by its identifier: a message that tells the
reader to "name one of these" must accept the name it printed.

Nothing here writes anything. Choosing a point only fills in a request that still needs a
facility manager's approval before the driver is touched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence

from shared.utils import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PointRef:
    """A writable point: the IRI the driver takes, its local name, and how to show it."""

    uri: str
    local: str
    label: str
    labelled: bool  # True when a person wrote the label; False when it is the identifier expanded

    def shown(self) -> str:
        """The point as the reader sees it; an unlabelled point keeps its identifier."""
        return self.label if self.labelled else f"{self.label} (`{self.local}`)"


def local_name(uri: str) -> str:
    """A point IRI's local name: 'urn:site:VAV-501-SP' or 'http://x#VAV-501-SP' -> 'VAV-501-SP'."""
    return str(uri).rsplit(":", 1)[-1].rsplit("#", 1)[-1].rsplit("/", 1)[-1]


#: Abbreviations whose expansion is certain. Anything else in an identifier is left as written.
_EXPANSIONS = {
    "sp": "setpoint",
    "ahu": "air handling unit",
    "vav": "variable air volume box",
    "fcu": "fan coil unit",
    "temp": "temperature",
    "hvac": "HVAC",
}


def humanise(local: str) -> str:
    """An identifier read aloud: 'AHU-F5-SP' -> 'air handling unit F5 setpoint'."""
    words: List[str] = []
    for token in re.split(r"[-_\s]+", str(local)):
        if not token:
            continue
        words.append(_EXPANSIONS.get(token.lower(), token))
    text = " ".join(words) or str(local)
    return text[:1].upper() + text[1:]


def build_points(
    uris: Sequence[str],
    *,
    configured: Optional[Mapping[str, str]] = None,
    graph_labels: Optional[Mapping[str, str]] = None,
) -> List[PointRef]:
    """Writable points with the best label available for each."""
    configured = configured or {}
    graph_labels = graph_labels or {}
    out: List[PointRef] = []
    for uri in uris:
        local = local_name(uri)
        text = str(configured.get(uri) or configured.get(local) or "").strip()
        if not text:
            text = str(graph_labels.get(uri) or "").strip()
        if text:
            out.append(PointRef(uri, local, text, True))
        else:
            out.append(PointRef(uri, local, humanise(local), False))
    return out


# ── where the labels live ───────────────────────────────────────────────────


def configured_labels(building_id: str) -> Dict[str, str]:
    """``actuation.point_labels`` from the building's own config; {} when absent or unreadable."""
    try:
        import yaml

        from shared.config import resolve_building_file

        path = resolve_building_file(building_id, "building.yaml")
        if path is None:
            return {}
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        block = (data.get("actuation") or {}).get("point_labels") or {}
        return {str(k): str(v) for k, v in block.items() if str(v).strip()}
    except Exception as exc:
        logger.debug(f"[writable_points] configured labels unavailable: {exc}")
        return {}


def labels_query(uris: Sequence[str]) -> str:
    """One read-only SELECT for the rdfs:label of each point IRI."""
    values = " ".join(f"<{u}>" for u in uris)
    return (
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        f"SELECT ?p ?l WHERE {{ VALUES ?p {{ {values} }} ?p rdfs:label ?l }} LIMIT 200"
    )


RunSelect = Callable[..., Awaitable[Any]]


async def graph_labels(uris: Sequence[str], run_select: Optional[RunSelect] = None) -> Dict[str, str]:
    """The graph's own label for each point IRI it describes; {} when it describes none."""
    if not uris:
        return {}
    try:
        if run_select is None:
            from orchestrator.services.evidence.spatial_facts import default_run_select

            run_select = default_run_select
        res = await run_select(labels_query(uris), limit=200)
        rows = res.get("rows") if isinstance(res, dict) else res
        out: Dict[str, str] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            iri, label = row.get("p"), row.get("l")
            if isinstance(iri, dict):
                iri = iri.get("value")
            if isinstance(label, dict):
                label = label.get("value")
            if iri and label:
                out.setdefault(str(iri), str(label))
        return out
    except Exception as exc:
        logger.debug(f"[writable_points] graph labels unavailable: {exc}")
        return {}


async def describe_points(
    uris: Sequence[str], building_id: str, run_select: Optional[RunSelect] = None
) -> List[PointRef]:
    """Every writable point with a label, resolved config-first then graph-first then by name."""
    configured = configured_labels(building_id)
    missing = [u for u in uris if not (configured.get(u) or configured.get(local_name(u)))]
    from_graph = await graph_labels(missing, run_select) if missing else {}
    return build_points(uris, configured=configured, graph_labels=from_graph)


# ── naming a point in a request ─────────────────────────────────────────────

#: Words that describe the ACT or a KIND of point rather than identify one. A label whose every
#: word is one of these names nothing, and a question made only of them selects nothing.
_STOP_TOKENS = frozenset(
    {"the", "a", "an", "of", "to", "in", "on", "at", "for", "and", "set", "setpoint", "point", "please"}
)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def _tokens(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _identifying(label: str) -> List[str]:
    """The words of a label that pick it out, without brackets or filler."""
    bare = re.sub(r"\(.*?\)", " ", label or "")
    seen: List[str] = []
    for tok in _tokens(bare):
        if tok not in _STOP_TOKENS and tok not in seen:
            seen.append(tok)
    return seen


def match_point(question: str, points: Sequence[PointRef]) -> Optional[PointRef]:
    """The ONE point a request names, by identifier or by label; None when it names none or many.

    A label matches only when ALL of its identifying words are in the question, and at least two
    are -- "set the temperature" names no point however many labels contain that word. Two points
    that both match are ambiguous, and asking is cheaper than writing to the wrong one.
    """
    squashed = _squash(question)
    by_id = [p for p in points if len(_squash(p.local)) >= 4 and _squash(p.local) in squashed]
    if by_id:
        return max(by_id, key=lambda p: len(p.local))
    asked = set(_tokens(question))
    hits = []
    for p in points:
        words = _identifying(p.label)
        if len(words) >= 2 and all(w in asked for w in words):
            hits.append((len(words), p))
    if not hits:
        return None
    hits.sort(key=lambda item: -item[0])
    if len(hits) > 1 and hits[0][0] == hits[1][0]:
        return None
    return hits[0][1]


# ── what the assistant says ─────────────────────────────────────────────────


def _example(points: Sequence[PointRef]) -> str:
    """One worked request, built from a real point and never from an invented value."""
    if not points:
        return ""
    first = points[0]
    name = first.label if first.labelled else first.local
    return f"*Set {name} to [value]*"


def needs_detail_message(
    *, missing: str, points: Sequence[PointRef], named_device: str = ""
) -> str:
    """The decline for a request that names no writable point or no value (nothing is queued)."""
    if not points:
        return (
            "Nothing has been queued. This building has no setpoints I am allowed to request a "
            "change to."
        )
    if named_device:
        head = (
            f"I can't control **{named_device}** — it isn't something this building lets me "
            "change, so nothing has been queued."
        )
    else:
        head = f"Nothing has been queued — to request a change I need {missing}."
    listing = "\n".join(f"- {p.shown()}" for p in points)
    return (
        f"{head}\n\n"
        "I can only ask for a change to these setpoints, and nothing changes until a facility "
        f"manager approves the request:\n\n{listing}\n\n"
        f"Name one and the value you want, for example: {_example(points)}."
    )


def queued_target(point: PointRef) -> str:
    """The target line of a queued request: the plain label first, the identifier beside it."""
    if point.labelled:
        return f"**{point.label}** (`{point.local}`)"
    return f"`{point.local}`"
