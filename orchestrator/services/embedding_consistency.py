"""One boot-time answer to "do all the vector stores match the model?"

Every indexer already checks the width of the collection IT owns, but each check
only fires when that indexer happens to run. A collection whose documents are
unchanged, whose floor plans are already ingested, or whose building is parked is
never looked at — so a mismatch introduced by swapping the embedding model sits
there until someone asks a question and gets an empty result back. Vectors of
different widths cannot be compared, and a failed similarity search returns no
rows rather than raising, so the symptom is silence.

This runs once at startup and states the position for the whole instance: every
collection, its width, and whether it agrees with the model that is loaded.

Building-agnostic by construction: it enumerates whatever collections exist rather
than a list of expected names, so a building onboarded tomorrow — with collections
nobody has named in code — is covered the moment it creates them.

Derived caches are dropped so their owner rebuilds them at the right width. A store
holding data that cannot be regenerated is only ever REPORTED: an unusable
collection is bad, but deleting the only copy of something is worse, and that call
belongs to its owner rather than to a boot sweep.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

# Prefixes whose contents are derived from source material still on disk (documents,
# TTL, floor plans) and can therefore be rebuilt from scratch at any time.
_REBUILDABLE_PREFIXES = ("documents_", "capability_", "floor_plans", "brick_schema", "building_")


@dataclass
class CollectionState:
    name: str
    width: Optional[int]
    expected: int
    rebuildable: bool
    action: str = "ok"  # ok | dropped | reported | unknown

    @property
    def matches(self) -> bool:
        return self.width == self.expected


@dataclass
class ConsistencyReport:
    expected: int
    model: str
    collections: List[CollectionState] = field(default_factory=list)

    @property
    def mismatched(self) -> List[CollectionState]:
        return [c for c in self.collections if c.width is not None and not c.matches]

    def summary(self) -> str:
        if not self.collections:
            return f"[embedding] no vector collections yet — model {self.model} ({self.expected}d)"
        bad = self.mismatched
        if not bad:
            return (
                f"[embedding] {len(self.collections)} collections all at {self.expected}d, "
                f"matching {self.model}"
            )
        parts = ", ".join(f"{c.name}={c.width}d→{c.action}" for c in bad)
        return (
            f"[embedding] {len(bad)} of {len(self.collections)} collections did not match "
            f"{self.model} ({self.expected}d): {parts}"
        )


def _is_rebuildable(name: str) -> bool:
    return any(name.startswith(p) for p in _REBUILDABLE_PREFIXES)


def _width_of(info: Any) -> Optional[int]:
    """Vector width from a Qdrant collection description, unnamed or named."""
    try:
        vectors = info.config.params.vectors
    except AttributeError:
        return None
    size = getattr(vectors, "size", None)
    if size is not None:
        return int(size)
    # Named-vector collections: {"": VectorParams(size=...)}
    if isinstance(vectors, dict):
        for params in vectors.values():
            size = getattr(params, "size", None)
            if size is not None:
                return int(size)
    return None


async def check_embedding_consistency(qdrant_client: Any, expected_dim: int, model: str = ""):
    """Compare every collection's width to the model's, dropping stale derived ones."""
    report = ConsistencyReport(expected=expected_dim, model=model or "the configured model")
    try:
        listing = await qdrant_client.get_collections()
        names = sorted(c.name for c in listing.collections)
    except Exception as e:
        logger.warning(f"[embedding] consistency check skipped — cannot list collections: {e}")
        return report

    for name in names:
        rebuildable = _is_rebuildable(name)
        try:
            width = _width_of(await qdrant_client.get_collection(name))
        except Exception as e:
            logger.debug(f"[embedding] could not read {name}: {e}")
            report.collections.append(
                CollectionState(name, None, expected_dim, rebuildable, "unknown")
            )
            continue

        state = CollectionState(name, width, expected_dim, rebuildable)
        if width is None or state.matches:
            report.collections.append(state)
            continue

        if rebuildable:
            try:
                await qdrant_client.delete_collection(name)
                state.action = "dropped"
                logger.warning(
                    f"[embedding] {name} was built at {width}d but the model produces "
                    f"{expected_dim}d — dropped so it rebuilds. Searches against it would "
                    f"have returned nothing rather than failing."
                )
            except Exception as e:
                state.action = "reported"
                logger.error(f"[embedding] {name} is {width}d and could not be dropped: {e}")
        else:
            state.action = "reported"
            logger.error(
                f"[embedding] {name} is {width}d but the model produces {expected_dim}d. It "
                f"holds data that cannot be regenerated, so it is left alone — searches "
                f"against it will return nothing until it is re-embedded deliberately."
            )
        report.collections.append(state)

    logger.info(report.summary())
    return report
