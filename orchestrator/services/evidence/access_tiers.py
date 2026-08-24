# -*- coding: utf-8 -*-
"""The Master Report's six access tiers, mapped onto OntoSage RBAC (V6-T28).

Read-only metadata. **This module maps; it does not grant.** Authorisation stays where it
already works -- ``require_permission()`` over ``ROLE_PERMISSIONS`` -- and nothing here is
consulted to decide whether a request may proceed. Master 11.2 requires the conversational
layer to enforce the *same* permissions as the underlying systems rather than a parallel set,
so introducing a second authorisation path would be the specific mistake it warns against.

What it is for:

* stamping ``EvidenceRecord.access_tier`` so an answer records which tier produced it;
* telling a user which tier a question *would* need, so a refusal can name the route to the
  data instead of implying the data does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from shared.utils import get_logger

logger = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
_PATH = _REPO / "config" / "access_tiers.yaml"

#: Used only when the config cannot be read. Public-only on purpose: a mapping failure must
#: never widen what an answer claims to have been entitled to see.
_FALLBACK = {
    "tiers": {
        "public": {
            "rank": 0,
            "label": "Public",
            "roles": [],
            "requires_permission": "metadata:read",
        }
    },
    "by_shape": {},
}


@dataclass(frozen=True)
class AccessTier:
    name: str
    rank: int
    label: str
    description: str
    roles: List[str]
    requires_permission: str


@lru_cache(maxsize=1)
def _raw() -> Dict:
    try:
        data = yaml.safe_load(_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("tiers"):
            raise ValueError("access_tiers.yaml has no 'tiers' mapping")
        return data
    except Exception as exc:
        logger.error(f"[access_tiers] could not read {_PATH}: {exc}; falling back to public-only")
        return _FALLBACK


def all_tiers() -> Dict[str, AccessTier]:
    out: Dict[str, AccessTier] = {}
    for name, spec in (_raw().get("tiers") or {}).items():
        out[name] = AccessTier(
            name=name,
            rank=int(spec.get("rank", 0)),
            label=str(spec.get("label", name)),
            description=str(spec.get("description", "")).strip(),
            roles=list(spec.get("roles") or []),
            requires_permission=str(spec.get("requires_permission", "")),
        )
    return out


def tier_for_role(role: str) -> AccessTier:
    """The HIGHEST-ranked tier a role appears in.

    Highest rather than lowest because a role listed in several tiers can legitimately answer
    at any of them, and the record should state the broadest scope that was available. A role
    in no tier resolves to public -- the floor, never a guess upward.
    """
    tiers = all_tiers()
    matches = [t for t in tiers.values() if role in t.roles]
    if not matches:
        return tiers.get("public") or AccessTier("public", 0, "Public", "", [], "metadata:read")
    return max(matches, key=lambda t: t.rank)


def tier_for_shape(shape: str) -> Optional[AccessTier]:
    """The tier a question SHAPE demands, where the shape alone determines it.

    Returns None when the shape does not fix a tier, in which case the asker's role decides.
    Listed shapes are those whose tier is a property of the question rather than of the
    asker: an access-event query is a security-tier question no matter who asks it.
    """
    name = (_raw().get("by_shape") or {}).get((shape or "").lower())
    return all_tiers().get(name) if name else None


def permission_for_tier(tier_name: str) -> str:
    """The RBAC permission that actually gates this tier.

    The one place the two vocabularies meet. Everything else in this module is description;
    this is the line that ties a tier back to the authorisation system that enforces it.
    """
    t = all_tiers().get(tier_name)
    return t.requires_permission if t else "metadata:read"
