# -*- coding: utf-8 -*-
"""What a sensor class measures, and what a count of it swept in (CAVEAT-286).

Brick 1.4 asserts ``brick:TVOC_Sensor rdfs:subClassOf
brick:Particulate_Matter_Sensor``. Under Brick's own definition of that class —
"Detects pollutants in the ambient air" — that is defensible; the NAME is what
misleads, because a reader hearing "particulate matter" means suspended solids.
Measured on bldg1: 35 TVOC sensors are inferred as particulate matter, beside 34
PM1, 34 PM10 and 35 PM2.5.

The fix is not to fight the taxonomy. Editing the vendored Brick file would make
"we use Brick 1.4" false, and asserting ``owl:disjointWith`` against a superclass
would make TVOC_Sensor unsatisfiable — every TVOC sensor a contradiction, which is
a worse answer than the one being corrected.

Instead ``ontology/measurand_kinds.ttl`` states what each confusable class
measures, in OntoSage's own vocabulary, and this module reads it so a count rolled
up the hierarchy can say what it included.

Two design points worth keeping:

* **The roll-up map is DERIVED, not hand-written.** ``scripts/derive_measurand_rollups.py``
  computes it from Brick's asserted hierarchy plus the declarations, so it stays
  true if Brick changes. A hand-maintained list would drift from the ontology it
  describes, which is the failure this codebase keeps paying for.
* **Everything degrades to silence.** A missing file, an unparseable one, a class
  nobody declared — all yield "no note", never a guess. A disclosure that fires on
  incomplete information is worse than none.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[2]
_KINDS_TTL = _REPO / "ontology" / "measurand_kinds.ttl"
_ROLLUPS_JSON = _REPO / "config" / "measurand_rollups.json"

_ASSERTION_RE = re.compile(
    r"^\s*brick:([\w.\-]+)\s+ontosage:measuresQuantityKind\s+ontosage:([\w.\-]+)", re.M
)
_LABEL_RE = re.compile(
    r"^\s*ontosage:([\w.\-]+)\s+a\s+ontosage:Measurand\s*;?\s*\n?\s*" r'rdfs:label\s+"([^"]+)"',
    re.M,
)


@lru_cache(maxsize=1)
def _kinds() -> Dict[str, str]:
    """{brick class local name: measurand local name}. {} when undeclared."""
    if not _KINDS_TTL.is_file():
        logger.debug("[measurand] no measurand_kinds.ttl; roll-up notes disabled")
        return {}
    try:
        text = _KINDS_TTL.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover
        logger.warning(f"[measurand] measurand_kinds.ttl unreadable: {exc}")
        return {}
    return {cls: kind for cls, kind in _ASSERTION_RE.findall(text)}


@lru_cache(maxsize=1)
def _labels() -> Dict[str, str]:
    """{measurand local name: human label}, for prose."""
    if not _KINDS_TTL.is_file():
        return {}
    try:
        text = _KINDS_TTL.read_text(encoding="utf-8")
    except OSError:  # pragma: no cover
        return {}
    out = dict(_LABEL_RE.findall(text))
    # A measurand declared without a label still needs printable prose.
    for kind in set(_kinds().values()):
        out.setdefault(kind, re.sub(r"(?<!^)(?=[A-Z])", " ", kind).lower())
    return out


def measurand_of(class_local: str) -> str:
    """The measurand a Brick class measures, or "" when nobody declared one."""
    return _kinds().get((class_local or "").strip(), "")


def measurand_label(kind: str) -> str:
    return _labels().get(kind, kind)


@lru_cache(maxsize=1)
def _rollups() -> Dict[str, List[str]]:
    """{class: [descendant classes measuring something else]}. Derived, not typed."""
    if not _ROLLUPS_JSON.is_file():
        logger.debug("[measurand] no measurand_rollups.json; run derive_measurand_rollups.py")
        return {}
    try:
        data = json.loads(_ROLLUPS_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # pragma: no cover
        logger.warning(f"[measurand] rollups unreadable: {exc}")
        return {}
    return {k: list(v) for k, v in (data.get("rollups") or {}).items()}


def foreign_descendants(class_local: str) -> Tuple[str, ...]:
    """Subclasses of `class_local` that measure something DIFFERENT."""
    return tuple(_rollups().get((class_local or "").strip(), ()))


def rollup_note(class_local: str) -> Optional[str]:
    """One line saying what a count of this class also included. None when clean.

    Names the classes rather than only the quantity, because "includes gases" tells
    a reader something is off and not what to do about it, while naming
    TVOC_Level_Sensor tells them exactly which figure to subtract.
    """
    foreign = foreign_descendants(class_local)
    if not foreign:
        return None
    own = measurand_of(class_local)
    kinds = sorted({measurand_of(f) for f in foreign if measurand_of(f)})
    others = ", ".join(measurand_label(k) for k in kinds) or "a different quantity"
    names = ", ".join(f"`{f}`" for f in sorted(foreign))
    own_txt = f" measures {measurand_label(own)}, but it" if own else ""
    return (
        f"_Note: in Brick, `{class_local}`{own_txt} is also the parent of {names}, "
        f"which measure {others}. This count includes them — Brick uses that class as a "
        f"general pollutant supertype, so the total is broader than the name suggests._"
    )
