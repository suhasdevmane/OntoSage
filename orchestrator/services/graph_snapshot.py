# -*- coding: utf-8 -*-
"""Which graph state a turn used, and whether it changed underneath (V12-13, review A16).

    A16  "The defined snapshot policy prevents an unexplained mixed result when a mapping
          changes mid-turn."

THE WINDOW THIS CLOSES
-----------------------
A turn resolves a sensor's storage in the SPARQL lane — `?sensor ref:hasExternalReference
?ref . ?ref ref:hasTimeseriesId ?uuid ; ref:storedAt ?storage` — and fetches from that store
in the SQL lane, seconds later. Between the two, a TTL re-upload, an admin edit or a
`delete_subject` can move a sensor from one store to another.

Nothing recorded which graph state produced the answer. There was no revision, no
fingerprint and no mapping snapshot anywhere in the codebase, so a mixed result — rows from
the old store described by metadata from the new one — was not merely possible but
*unexplainable afterwards*. That is the word the review uses, and it is the right one: the
failure is not that the mapping changed, it is that nothing could say so.

WHAT THIS MEASURES, AND WHAT IT HONESTLY CANNOT
------------------------------------------------
Two signals, because one of them is cheap and weak and the other is precise and narrow.

`repository_fingerprint()` reads GraphDB's statement count — one integer, one HTTP call.
It detects any net addition or removal. It CANNOT detect an equal-count replace (delete one
triple, add one), so it is a change DETECTOR and never a proof of stability. Saying
otherwise would make it worse than nothing, because a reader would trust it.

`mapping_snapshot()` pins the uuid -> store mapping the turn actually resolved, and
`compare()` names every uuid whose store moved. That is exact for the thing A16 names, and
blind to everything else. The two together: the fingerprint says "something changed", the
mapping says "and here is whether it was YOUR sensors".

WHY IT REPORTS AND DOES NOT RETRY
----------------------------------
A retry would answer from the new mapping and say nothing about the old one, which is the
same silent substitution one layer up. The turn states that its mapping moved and which
sensors are affected; a reader who asks again gets a clean answer and knows why they needed
to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class GraphSnapshot:
    """The graph state a turn is working against."""

    #: GraphDB's statement count, or None when it could not be read. None is NOT zero:
    #: an unreadable count means "unknown", and comparing an unknown to anything is how a
    #: missing measurement becomes a false negative.
    statements: Optional[int] = None
    #: uuid -> ref:storedAt key, as resolved once at discovery.
    mapping: Dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, object]:
        return {"statements": self.statements, "mapping_size": len(self.mapping)}


@dataclass(frozen=True)
class SnapshotDrift:
    """What moved between two snapshots of the same turn."""

    statements_changed: bool = False
    before: Optional[int] = None
    after: Optional[int] = None
    #: uuid -> (store at discovery, store at retrieval)
    moved: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    #: uuids that had a store at discovery and none at retrieval.
    lost: List[str] = field(default_factory=list)

    @property
    def mapping_changed(self) -> bool:
        return bool(self.moved or self.lost)

    @property
    def unexplained(self) -> bool:
        """True when the graph moved and we cannot say whether it touched this turn.

        This is the state A16 exists to eliminate. The statement count changed, the mapping
        did not, and an equal-count replace is invisible to the count — so "nothing relevant
        changed" cannot be asserted, only hoped.
        """
        return self.statements_changed and not self.mapping_changed

    def note(self) -> str:
        """The sentence to append, or "" when nothing moved.

        Never says the answer is wrong. A mapping that moved mid-turn does not establish
        that the rows already fetched were the wrong ones — it establishes that two parts of
        this answer may describe different graph states, which is a different and narrower
        claim.
        """
        if self.moved or self.lost:
            n = len(self.moved) + len(self.lost)
            names = ", ".join(sorted(self.moved)[:3]) or ", ".join(sorted(self.lost)[:3])
            return (
                f"**The data mapping for this building changed while I was answering.** "
                f"{n} sensor(s) moved to a different store mid-request ({names}"
                f"{', …' if n > 3 else ''}). The readings above were fetched under the "
                "earlier mapping, so part of this answer may describe a different graph "
                "state from the rest. Asking again gives a consistent answer."
            )
        if self.statements_changed:
            return (
                "_The building's graph changed while I was answering. None of the sensors "
                "in this answer moved store, so the figures are consistent._"
            )
        return ""


async def repository_fingerprint(client=None) -> Optional[int]:
    """GraphDB's statement count, or None when it cannot be read.

    One integer, one call. Deliberately not a content hash: hashing 298,219 statements per
    turn to detect a change that almost never happens would cost every turn to protect a
    rare one.
    """
    try:
        from shared.config import settings

        host = getattr(settings, "GRAPHDB_HOST", "graphdb")
        port = getattr(settings, "GRAPHDB_PORT", 7200)
        repo = getattr(settings, "GRAPHDB_REPOSITORY", "bldg")
        url = f"http://{host}:{port}/repositories/{repo}/size"

        if client is None:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as c:
                resp = await c.get(url)
        else:
            resp = await client.get(url)
        if getattr(resp, "status_code", 0) != 200:
            return None
        return int(str(resp.text).strip())
    except Exception:  # pragma: no cover - a fingerprint must never cost a turn
        return None


def mapping_snapshot(storage_map: Optional[Dict[str, str]], statements: Optional[int] = None):
    """Pin the uuid -> store mapping this turn resolved."""
    return GraphSnapshot(
        statements=statements,
        mapping={str(k): str(v) for k, v in (storage_map or {}).items() if k and v},
    )


def compare(before: GraphSnapshot, after: GraphSnapshot) -> SnapshotDrift:
    """What moved between discovery and retrieval.

    An unreadable count on EITHER side means the comparison cannot be made, and
    `statements_changed` stays False rather than True: reporting drift because a health
    check failed would put a caveat on every turn during a GraphDB hiccup, and a caveat on
    every turn is read as boilerplate and then not read at all.
    """
    changed = (
        before.statements is not None
        and after.statements is not None
        and before.statements != after.statements
    )
    moved: Dict[str, Tuple[str, str]] = {}
    lost: List[str] = []
    for uuid, was in before.mapping.items():
        now = after.mapping.get(uuid)
        if now is None:
            lost.append(uuid)
        elif now != was:
            moved[uuid] = (was, now)
    return SnapshotDrift(
        statements_changed=changed,
        before=before.statements,
        after=after.statements,
        moved=moved,
        lost=lost,
    )
