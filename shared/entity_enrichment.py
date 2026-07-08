"""Entity enrichment inference (Part D) — pure, testable, no I/O.

Derives a Brick **class + human-readable label + relationships** for a time-series
point from its URI local-name, so any naming scheme (BMS/Haystack, e.g.
``bldgx.ZONE.AHU01.RM123.Zone_Air_Temp``) becomes queryable through the standard
class/label/relationship resolver — the raw URI is never parsed at query time.

The service layer (``orchestrator/services/entity_enricher.py``) feeds local-names
here and writes the emitted triples into a dedicated GraphDB named graph. This
module holds only the deterministic inference so it can be unit-tested offline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_DELIM_RE = re.compile(r"[^A-Za-z0-9]+")


@dataclass
class EnrichmentConfig:
    point_classes: Dict[str, str] = field(default_factory=dict)
    equipment_patterns: List[Tuple[re.Pattern, str]] = field(default_factory=list)
    location_patterns: List[Tuple[re.Pattern, str]] = field(default_factory=list)
    ignore_tokens: frozenset = field(default_factory=frozenset)

    @classmethod
    def from_dict(cls, data: Dict) -> "EnrichmentConfig":
        data = data or {}
        eq = [
            (re.compile(e["pattern"]), e["class"])
            for e in (data.get("equipment_patterns") or [])
            if e.get("pattern")
        ]
        loc = [
            (re.compile(e["pattern"]), e["class"])
            for e in (data.get("location_patterns") or [])
            if e.get("pattern")
        ]
        return cls(
            point_classes={k.lower(): v for k, v in (data.get("point_classes") or {}).items()},
            equipment_patterns=eq,
            location_patterns=loc,
            ignore_tokens=frozenset(t.lower() for t in (data.get("ignore_tokens") or [])),
        )

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "EnrichmentConfig":
        import yaml

        for p in (
            [path]
            if path
            else [Path("/app/config/entity_enrichment.yaml"), Path("config/entity_enrichment.yaml")]
        ):
            if p and p.is_file():
                with open(p, "r", encoding="utf-8") as fh:
                    return cls.from_dict(yaml.safe_load(fh) or {})
        return cls.from_dict({})


@dataclass
class EnrichmentResult:
    brick_class: Optional[str]
    label: str
    # (predicate, target_local) e.g. ("brick:isPointOf", "AHU01")
    relationships: List[Tuple[str, str]]
    # (stub_local, stub_class) entities to create so relationships resolve
    stubs: List[Tuple[str, str]]

    @property
    def is_mapped(self) -> bool:
        return self.brick_class is not None


def local_name(uri_or_local: str) -> str:
    """Strip a namespace: 'bldg:X' -> 'X', 'http://..#X' -> 'X', '..#bldgx.A.B' -> 'bldgx.A.B'."""
    s = uri_or_local.strip().lstrip("<").rstrip(">")
    if "#" in s:
        s = s.rsplit("#", 1)[1]
    elif s.startswith("http") and "/" in s:
        s = s.rsplit("/", 1)[1]
    elif ":" in s and not s.startswith("http"):
        s = s.split(":", 1)[1]
    return s


def normalize_tokens(local: str) -> List[str]:
    """Split a local-name into lowercased tokens (delimiters + camelCase)."""
    spaced = _CAMEL_RE.sub(" ", local)
    return [t.lower() for t in _DELIM_RE.split(spaced) if t]


def infer_point_class(local: str, point_classes: Dict[str, str]) -> Optional[str]:
    """Longest matching point-type token-phrase wins (so 'zone_air_temp' beats 'temp')."""
    tokens = normalize_tokens(local)
    best: Optional[str] = None
    best_len = 0
    n = len(tokens)
    for i in range(n):
        for j in range(i + 1, n + 1):
            key = "_".join(tokens[i:j])
            if key in point_classes and (j - i) > best_len:
                best, best_len = point_classes[key], j - i
    return best


def _segments(local: str) -> List[str]:
    """Top-level segments for relationship detection (split on . _ - / only)."""
    return [s for s in re.split(r"[._\-/]+", local) if s]


def infer_relationships(
    local: str, cfg: EnrichmentConfig
) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """Return (relationships, stubs). Equipment → brick:isPointOf; location →
    brick:hasLocation. Each linked target gets a typed stub so it resolves."""
    rels: List[Tuple[str, str]] = []
    stubs: List[Tuple[str, str]] = []
    seen = set()
    for seg in _segments(local):
        segl = seg.lower()
        if seg in seen:
            continue
        for pat, klass in cfg.equipment_patterns:
            if pat.match(segl):
                rels.append(("brick:isPointOf", seg))
                stubs.append((seg, klass))
                seen.add(seg)
                break
        else:
            for pat, klass in cfg.location_patterns:
                if pat.match(segl):
                    rels.append(("brick:hasLocation", seg))
                    stubs.append((seg, klass))
                    seen.add(seg)
                    break
    return rels, stubs


def humanize_label(local: str, brick_class: Optional[str], cfg: EnrichmentConfig) -> str:
    """Readable label: class words + equipment/room context.

    'bldgx.ZONE.AHU01.RM123.Zone_Air_Temp' + Zone_Air_Temperature_Sensor
      -> 'Zone Air Temperature — AHU01 / RM123'
    Falls back to a title-cased local-name when no class was inferred."""
    rels, _ = infer_relationships(local, cfg)
    context = " / ".join(t for _, t in rels)
    if brick_class:
        base = brick_class.split(":", 1)[-1]
        base = re.sub(r"_(Sensor|Setpoint|Status|Command)$", "", base).replace("_", " ").strip()
        return f"{base} — {context}" if context else base
    # No class: humanize the whole local-name minus ignored markers.
    words = [w for w in normalize_tokens(local) if w not in cfg.ignore_tokens]
    pretty = " ".join(w.upper() if len(w) <= 3 else w.capitalize() for w in words)
    return pretty or local


def enrich_entity(uri_or_local: str, cfg: EnrichmentConfig) -> EnrichmentResult:
    """Full inference for one entity: class + label + relationships + stubs."""
    local = local_name(uri_or_local)
    brick_class = infer_point_class(local, cfg.point_classes)
    rels, stubs = infer_relationships(local, cfg)
    label = humanize_label(local, brick_class, cfg)
    return EnrichmentResult(brick_class=brick_class, label=label, relationships=rels, stubs=stubs)
