# -*- coding: utf-8 -*-
"""A backup that shares the primary's failure mode is not a backup (V6-T36).

Rule R-10, spelled out with its independence condition in both the PhD and Research Staff
catalogues. The naive implementation — offer the top two ranked options — is precisely what
the catalogues warn against, because ranking is by quality and the two best rooms are usually
the two best rooms *on the same floor, off the same air handler, behind the same switch*. When
the AHU fails, both recommendations fail, and the person following the advice discovers this
at the worst moment.

**Independence is computed from the building's own declared dependencies**, never from
distance or floor number. Two rooms on different floors can share a riser; two adjacent rooms
can be on separate circuits. Only the graph knows, which is why this takes asserted
dependency sets rather than coordinates — the same reason `spatial_facts` has no notion of
distance.

**When nothing independent exists, that is the answer.** Returning the second-best option
labelled "backup" when it shares every dependency would be a fabrication of resilience — the
one thing a backup is for. The honest output names the shared dependency, which also tells the
estate what single point of failure to fix.

Pure and I/O-free: the caller supplies each candidate's dependency set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)


@dataclass
class Candidate:
    """One option, with everything it depends on to keep working."""

    identifier: str
    label: str = ""
    score: Optional[float] = None
    #: Equipment, circuits, network paths and services this option relies on — IRIs from the
    #: building's own graph. Two candidates sharing any of these share a failure mode.
    dependencies: Set[str] = field(default_factory=set)

    def name(self) -> str:
        return self.label or self.identifier.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


@dataclass
class BackupVerdict:
    """A primary, an independent backup if one exists, and the reason when none does."""

    primary: Optional[Candidate] = None
    backup: Optional[Candidate] = None
    shared_with_runner_up: Set[str] = field(default_factory=set)
    reason: str = ""

    @property
    def has_independent_backup(self) -> bool:
        return self.backup is not None

    def describe(self) -> str:
        if self.primary is None:
            return ""
        if self.backup is not None:
            return (
                f"**Primary:** {self.primary.name()}. **Backup:** {self.backup.name()} — "
                f"chosen because it shares none of the primary's dependencies, so a single "
                f"failure cannot take both."
            )
        shared = ", ".join(sorted(d.rsplit("#", 1)[-1] for d in self.shared_with_runner_up))
        tail = f" Every alternative shares: {shared}." if shared else ""
        return (
            f"**Primary:** {self.primary.name()}. **No independent backup exists** — every "
            f"other option depends on something the primary also depends on, so a single "
            f"failure would take both.{tail} That is a single point of failure worth raising "
            f"with the estate team."
        )


def choose(candidates: Sequence[Candidate]) -> BackupVerdict:
    """Best option, plus the best option independent of it.

    Candidates are assumed ranked best-first by the caller; ties are left in the caller's
    order rather than re-sorted, because this module knows nothing about what makes an option
    good and should not silently reorder a ranking it did not compute.
    """
    ranked = [c for c in candidates if c]
    if not ranked:
        return BackupVerdict(reason="no candidates were offered")
    primary = ranked[0]
    verdict = BackupVerdict(primary=primary)

    for other in ranked[1:]:
        if not (other.dependencies & primary.dependencies):
            verdict.backup = other
            verdict.reason = "an independent alternative was found"
            return verdict

    # Nothing independent. Record WHAT is shared, because the shared dependency is the
    # actionable fact — it names the single point of failure.
    shared: Set[str] = set()
    for other in ranked[1:]:
        shared |= other.dependencies & primary.dependencies
    verdict.shared_with_runner_up = shared
    verdict.reason = (
        "every alternative shares a dependency with the primary"
        if len(ranked) > 1
        else "only one option was available, so there is nothing to fall back to"
    )
    return verdict


def dependencies_from_rows(rows: Sequence[Dict[str, str]]) -> Dict[str, Set[str]]:
    """``{space IRI: dependency IRIs}`` from a SPARQL result of (space, dependency) pairs."""
    out: Dict[str, Set[str]] = {}
    for row in rows or []:
        space, dep = row.get("space"), row.get("dep")
        if space and dep:
            out.setdefault(str(space), set()).add(str(dep))
    return out


#: What counts as a shared dependency, as Brick relations. Equipment that FEEDS a space, and
#: the space's containing structure. Deliberately not distance, and deliberately not "same
#: floor" — a floor is not a failure mode, an air handler is.
DEPENDENCY_QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?space ?dep WHERE {
  VALUES ?space { %s }
  { ?dep brick:feeds ?space }
  UNION
  { ?space brick:isPartOf ?dep . ?dep a ?dt . FILTER(!CONTAINS(STR(?dt), "Floor")) }
  UNION
  { ?dep brick:hasPoint ?pt . ?pt brick:hasLocation ?space }
}
"""


def build_query(space_iris: Sequence[str]) -> str:
    """The dependency query for a specific candidate set."""
    values = " ".join(f"<{iri}>" for iri in space_iris if iri)
    return DEPENDENCY_QUERY % values


__all__ = [
    "BackupVerdict",
    "Candidate",
    "DEPENDENCY_QUERY",
    "build_query",
    "choose",
    "dependencies_from_rows",
]
