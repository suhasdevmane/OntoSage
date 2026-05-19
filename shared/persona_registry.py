"""
Persona Registry — seeded from survey D3_user_personas.md + E1_topic_priority_table.csv.

Survey justification (Phase 3):
  D3 gives hard per-persona domain priors; G4 says "response generator must
  consult a persona registry, not just template strings."  Current
  persona_adapter.py only restyles the finished answer.

  This module injects persona priors BEFORE generation:
    (a) entity/domain disambiguation — break ties toward persona's top domains
    (b) sensor selection ordering — prefer sensors in persona's primary domain
    (c) answer depth — controls how much detail is included

Usage:
    registry = get_persona_registry()
    priors = registry.get_priors("occupant")
    # priors.top_domains, priors.default_complexity, priors.clarification_threshold
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, FrozenSet, List, Optional


@dataclass(frozen=True)
class PersonaPriors:
    """Per-persona routing and retrieval priors derived from survey D3/E1."""
    name: str
    # Ordered list of domain_l1 labels most relevant to this persona (D3)
    top_domains: List[str]
    # Fraction of queries expected to be LOOKUP (vs analytical) — D3 stat
    lookup_share: float
    # Default query complexity expected from this persona
    default_complexity: str  # "SIMPLE" | "MODERATE" | "COMPLEX"
    # How aggressively to ask for clarification (lower = fewer round-trips)
    clarification_threshold: float  # 0=never, 1=always; default 0.5
    # Borda-ranked topics (E1 table) — drives sensor selection ordering
    borda_topics: List[str] = field(default_factory=list)
    # Brief description (from D3)
    description: str = ""


# ── Registry data ─────────────────────────────────────────────────────────────
# Sourced from:
#   D3_user_personas.md  — domain mixes, lookup shares, complexity
#   E1_topic_priority_table.csv — Borda topic rankings per persona
#   G4_gap_analysis.md  — clarification recommendations
# ──────────────────────────────────────────────────────────────────────────────

_REGISTRY: Dict[str, PersonaPriors] = {
    "occupant": PersonaPriors(
        name="occupant",
        description="Building occupant (staff/student using the building day-to-day)",
        top_domains=["THERMAL", "AIR_QUALITY", "LIGHTING", "INFORMATIONAL"],
        lookup_share=0.88,   # D3: LOOKUP 88% for occupants
        default_complexity="SIMPLE",
        clarification_threshold=0.3,  # occupants tolerate fewer round-trips
        borda_topics=["Temperature", "Air Quality", "Lighting", "Humidity", "Energy"],
    ),
    "facility_manager": PersonaPriors(
        name="facility_manager",
        description="Responsible for building operations and maintenance",
        top_domains=["ENERGY", "THERMAL", "OCCUPANCY", "FIRE_SAFETY"],
        lookup_share=0.62,   # more analytical queries than occupants
        default_complexity="MODERATE",
        clarification_threshold=0.5,
        borda_topics=["Energy", "Temperature", "Occupancy", "Fire Safety", "Air Quality"],
    ),
    "researcher": PersonaPriors(
        name="researcher",
        description="Academic researcher analysing building data",
        top_domains=["AIR_QUALITY", "ENERGY", "THERMAL", "OCCUPANCY"],
        lookup_share=0.55,
        default_complexity="COMPLEX",
        clarification_threshold=0.6,
        borda_topics=["Air Quality", "Energy", "Temperature", "Humidity", "Occupancy"],
    ),
    "it_admin": PersonaPriors(
        name="it_admin",
        description="IT/operator managing building systems and sensors",
        top_domains=["ACCESS_SECURITY", "ENERGY", "INFORMATIONAL"],
        lookup_share=0.68,
        default_complexity="MODERATE",
        clarification_threshold=0.5,
        borda_topics=["Security", "Energy", "IT Infrastructure", "Temperature"],
    ),
    "safety_officer": PersonaPriors(
        name="safety_officer",
        description="Health & safety officer, fire safety focus",
        top_domains=["FIRE_SAFETY", "AIR_QUALITY", "OCCUPANCY", "ACCESS_SECURITY"],
        lookup_share=0.80,
        default_complexity="MODERATE",
        clarification_threshold=0.4,
        borda_topics=["Fire Safety", "Air Quality", "Occupancy", "Security"],
    ),
    "student": PersonaPriors(
        name="student",
        description="Student using building spaces for study/research",
        top_domains=["THERMAL", "AIR_QUALITY", "INFORMATIONAL", "LIGHTING"],
        lookup_share=0.92,   # D3: students are overwhelmingly LOOKUP
        default_complexity="SIMPLE",
        clarification_threshold=0.25,  # students want direct answers
        borda_topics=["Temperature", "Air Quality", "Lighting", "Noise", "Humidity"],
    ),
    "executive": PersonaPriors(
        name="executive",
        description="Senior management / building owner wanting KPI summaries",
        top_domains=["ENERGY", "OCCUPANCY", "THERMAL"],
        lookup_share=0.50,   # needs aggregates and summaries
        default_complexity="COMPLEX",
        clarification_threshold=0.4,
        borda_topics=["Energy", "Temperature", "Occupancy", "Cost", "Sustainability"],
    ),
    "sustainability_officer": PersonaPriors(
        name="sustainability_officer",
        description="Sustainability and energy management focus",
        top_domains=["ENERGY", "AIR_QUALITY", "THERMAL"],
        lookup_share=0.58,
        default_complexity="MODERATE",
        clarification_threshold=0.5,
        borda_topics=["Energy", "CO2", "Temperature", "Lighting", "Occupancy"],
    ),
    "visitor": PersonaPriors(
        name="visitor",
        description="Visitor or guest with minimal building context",
        top_domains=["INFORMATIONAL", "ACCESS_SECURITY", "FIRE_SAFETY"],
        lookup_share=0.93,
        default_complexity="SIMPLE",
        clarification_threshold=0.2,  # visitors need immediate clear answers
        borda_topics=["Accessibility", "Fire Safety", "WiFi", "Amenities", "Access"],
    ),
    "general": PersonaPriors(
        name="general",
        description="Default / unknown persona",
        top_domains=["THERMAL", "AIR_QUALITY", "ENERGY"],
        lookup_share=0.75,
        default_complexity="SIMPLE",
        clarification_threshold=0.4,
        borda_topics=["Temperature", "Air Quality", "Energy", "Lighting"],
    ),
}

# Alias maps for flexible lookup
_ALIASES: Dict[str, str] = {
    "occupant": "occupant",
    "user": "occupant",
    "student": "student",
    "researcher": "researcher",
    "research": "researcher",
    "facility_manager": "facility_manager",
    "facilities": "facility_manager",
    "facility manager": "facility_manager",
    "it_admin": "it_admin",
    "it": "it_admin",
    "it admin": "it_admin",
    "operator": "it_admin",
    "safety_officer": "safety_officer",
    "safety": "safety_officer",
    "h&s": "safety_officer",
    "hs": "safety_officer",
    "executive": "executive",
    "owner": "executive",
    "building_owner": "executive",
    "sustainability_officer": "sustainability_officer",
    "sustainability": "sustainability_officer",
    "energy_manager": "sustainability_officer",
    "visitor": "visitor",
    "guest": "visitor",
    "general": "general",
}


class PersonaRegistry:
    """Lookup persona priors by role name (with alias support)."""

    def get_priors(self, persona: Optional[str]) -> PersonaPriors:
        if not persona:
            return _REGISTRY["general"]
        key = _ALIASES.get(persona.lower().strip(), persona.lower().strip())
        return _REGISTRY.get(key, _REGISTRY["general"])

    def domain_score(
        self, persona: Optional[str], domain: str, base_score: float = 1.0
    ) -> float:
        """
        Boost score for a domain match with a persona's top_domains list.
        Returns base_score × boost where boost diminishes by rank.
        Used by sparql_agent to order candidate sensor groups.
        """
        priors = self.get_priors(persona)
        try:
            rank = priors.top_domains.index(domain)
            return base_score * (1.0 + max(0, (3 - rank)) * 0.15)
        except ValueError:
            return base_score  # domain not in persona's top list — no boost

    def should_clarify(
        self, persona: Optional[str], ambiguity_score: float
    ) -> bool:
        """True if the ambiguity warrants a clarification question for this persona."""
        priors = self.get_priors(persona)
        return ambiguity_score >= priors.clarification_threshold

    def all_personas(self) -> List[str]:
        return list(_REGISTRY.keys())


@lru_cache(maxsize=1)
def get_persona_registry() -> PersonaRegistry:
    return PersonaRegistry()
