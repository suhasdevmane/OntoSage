# -*- coding: utf-8 -*-
"""Evidence policy: the thresholds every V6 gate consults (V6-T04).

Loads ``config/evidence_policy.yaml`` and merges an optional per-building overlay from
``input/evidence_policy.yaml``.

Three properties this module exists to guarantee:

1. **No threshold is a code constant.** A "5 minutes" written in Python is a building
   literal wearing a number: a building archiving at 15-minute resolution would be
   permanently stale against it. Every value resolves from config, per modality, with a
   citation attached.
2. **Absence fails safe, never open.** A missing overlay leaves the defaults in force; an
   unparseable one logs and is ignored. A building must never end up with *no* gate because
   its config had a typo.
3. **Gates start advisory.** A gate arriving in enforcing mode changes answers on the commit
   that introduces it, entangled with everything else in that run -- which is precisely what
   makes a regression indistinguishable from an intended tightening (V6-T55).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from shared.utils import get_logger

logger = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
_DEFAULT_PATH = _REPO / "config" / "evidence_policy.yaml"

#: Used when even the packaged default cannot be read. Deliberately permissive on
#: thresholds and advisory on every gate: a config failure must not start silently
#: refusing answers, which would look exactly like a system-wide regression.
_FALLBACK: Dict[str, Any] = {
    "version": 0,
    "freshness": {"default_max_age_minutes": 15, "by_modality": {}},
    "completeness": {"min_window_coverage": 0.90, "report_even_when_passing": True},
    "agreement": {"by_modality": {}},
    "spatial_adequacy": {
        "space_scope_allows": ["in_room", "served_zone"],
        "floor_scope_allows": ["in_room", "served_zone", "proxy"],
        "building_scope_allows": ["in_room", "served_zone", "proxy"],
        "proxy_requires_labelling": True,
    },
    "consequence": {"classes": {}, "by_shape": {}},
    "gates": {},
}


class GateMode(str, Enum):
    """Whether a gate's verdict is enforced or merely recorded."""

    ADVISORY = "advisory"
    ENFORCING = "enforcing"


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Merge overlay INTO base, key by key.

    Dicts merge recursively; anything else replaces. That distinction matters: a building
    overriding one modality's freshness must not silently delete the other twelve, which is
    what a wholesale replace would do.
    """
    out = copy.deepcopy(base)
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


@dataclass
class EvidencePolicy:
    """Resolved policy for one building."""

    raw: Dict[str, Any] = field(default_factory=dict)
    building_id: str = ""
    sources: List[str] = field(default_factory=list)

    # ── freshness ────────────────────────────────────────────────────────────
    def max_age_minutes(self, modality: str) -> float:
        f = self.raw.get("freshness") or {}
        per = (f.get("by_modality") or {}).get((modality or "").lower())
        if isinstance(per, dict) and per.get("max_age_minutes") is not None:
            return float(per["max_age_minutes"])
        return float(f.get("default_max_age_minutes", 15))

    def freshness_citation(self, modality: str) -> str:
        f = self.raw.get("freshness") or {}
        per = (f.get("by_modality") or {}).get((modality or "").lower())
        if isinstance(per, dict) and per.get("citation"):
            return str(per["citation"]).strip()
        return str(f.get("default_citation", "")).strip()

    # ── completeness ─────────────────────────────────────────────────────────
    def min_completeness(self, consequence_class: str = "") -> float:
        """Floor for an aggregate, raised by the consequence class where one applies."""
        base = float((self.raw.get("completeness") or {}).get("min_window_coverage", 0.90))
        cls = (self.raw.get("consequence") or {}).get("classes", {}).get(consequence_class)
        if isinstance(cls, dict) and cls.get("min_completeness") is not None:
            return max(base, float(cls["min_completeness"]))
        return base

    def completeness_citation(self) -> str:
        return str((self.raw.get("completeness") or {}).get("citation", "")).strip()

    # ── agreement ────────────────────────────────────────────────────────────
    def agreement_tolerance(self, modality: str) -> Optional[float]:
        """Max permitted spread, or None when this modality declares none.

        None means "do not judge", NOT "any spread is fine": a caller must treat an absent
        tolerance as unknown rather than as agreement.
        """
        per = ((self.raw.get("agreement") or {}).get("by_modality") or {}).get(
            (modality or "").lower()
        )
        if isinstance(per, dict) and per.get("max_delta") is not None:
            return float(per["max_delta"])
        return None

    # ── spatial adequacy ─────────────────────────────────────────────────────
    def allowed_adequacy(self, scope: str) -> List[str]:
        """Evidence grades a given answer scope may rest on."""
        sa = self.raw.get("spatial_adequacy") or {}
        key = {
            "space": "space_scope_allows",
            "room": "space_scope_allows",
            "zone": "space_scope_allows",
            "floor": "floor_scope_allows",
            "building": "building_scope_allows",
        }.get((scope or "").lower(), "space_scope_allows")
        return list(sa.get(key) or ["in_room"])

    # ── consequence ──────────────────────────────────────────────────────────
    def consequence_class(self, shape: str) -> str:
        """Class for a question shape.

        Unlisted shapes default to `informational` -- the permissive end -- so a NEW shape
        can never silently acquire a safety threshold it was not designed for. Safety shapes
        are listed explicitly, which also makes the safety set auditable at a glance.
        """
        by_shape = (self.raw.get("consequence") or {}).get("by_shape") or {}
        return str(by_shape.get((shape or "").lower(), "informational"))

    def requires_calibration(self, consequence_class: str) -> bool:
        cls = (self.raw.get("consequence") or {}).get("classes", {}).get(consequence_class)
        return bool(isinstance(cls, dict) and cls.get("requires_calibration"))

    def forbids_unknown_calibration(self, consequence_class: str) -> bool:
        cls = (self.raw.get("consequence") or {}).get("classes", {}).get(consequence_class)
        return bool(isinstance(cls, dict) and cls.get("forbid_unknown_calibration"))

    def requires_authoritative_source(self, consequence_class: str) -> bool:
        cls = (self.raw.get("consequence") or {}).get("classes", {}).get(consequence_class)
        return bool(isinstance(cls, dict) and cls.get("requires_authoritative_source"))

    # ── gate mode ────────────────────────────────────────────────────────────
    def source_tiers(self) -> Dict[str, str]:
        """Source kind -> precedence tier, from config (V6-T21).

        Empty when undeclared, and `precedence.tier_for_kind` then falls to its conservative
        built-in map — an unrecognised kind becomes `unknown`, which can neither outrank
        anything nor satisfy a claim that demands authority.
        """
        raw = (self.raw.get("source_precedence") or {}).get("by_kind") or {}
        return {str(k).lower(): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}

    def entitlement_requires_authority(self, kind: str) -> bool:
        """Whether this entitlement claim type demands an authoritative source (V6-T22)."""
        listed = (self.raw.get("entitlement") or {}).get("requires_authoritative") or []
        if not listed:
            return True  # absence fails SAFE: an undeclared policy must not license inference
        return (kind or "").lower() in {str(x).lower() for x in listed}

    def gate_mode(self, gate: str) -> GateMode:
        """Advisory unless a gate is explicitly switched to enforcing.

        Defaulting to advisory means a gate added without a config entry records but does
        not act -- the safe direction while a plan is in flight.
        """
        g = ((self.raw.get("gates") or {}).get(gate) or {}).get("mode", "advisory")
        try:
            return GateMode(str(g).lower())
        except ValueError:
            logger.warning(
                f"[evidence_policy] gate '{gate}' has unknown mode {g!r}; using advisory"
            )
            return GateMode.ADVISORY

    def is_enforcing(self, gate: str) -> bool:
        return self.gate_mode(gate) is GateMode.ENFORCING


def _read_yaml(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.is_file():
            return None
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if data is None:
            return {}
        if not isinstance(data, dict):
            logger.warning(f"[evidence_policy] {path} is not a mapping; ignoring")
            return None
        return data
    except Exception as exc:
        # Ignored rather than fatal: a typo in an optional overlay must not take the whole
        # building's evidence policy down with it.
        logger.warning(f"[evidence_policy] could not read {path}: {exc}; ignoring")
        return None


def load_policy(building_id: str = "", input_dir: Optional[Path] = None) -> EvidencePolicy:
    """Load the default policy, merged with a per-building overlay when present."""
    sources: List[str] = []
    base = _read_yaml(_DEFAULT_PATH)
    if base is None:
        logger.error(
            f"[evidence_policy] default policy unreadable at {_DEFAULT_PATH}; "
            "using permissive fallback with every gate advisory"
        )
        base = copy.deepcopy(_FALLBACK)
    else:
        sources.append(str(_DEFAULT_PATH.relative_to(_REPO)))

    root = input_dir if input_dir is not None else (_REPO / "input")
    overlay = _read_yaml(root / "evidence_policy.yaml")
    if overlay:
        base = _deep_merge(base, overlay)
        sources.append(f"{root.name}/evidence_policy.yaml")
        logger.info(f"[evidence_policy] merged per-building overlay for {building_id or 'active'}")

    return EvidencePolicy(raw=base, building_id=building_id, sources=sources)
