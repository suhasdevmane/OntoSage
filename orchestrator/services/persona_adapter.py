"""
PersonaAdapter — Post-Process Response Based on Persona
=========================================================
Applies persona-specific framing, format, and emphasis to any OntoSage
response without changing factual content.

Personas handled:
  executive           → KPI framing, £/$ cost emphasis, bullet summary
  researcher          → Provenance metadata, statistical notation, confidence
  occupant/guest      → Simple language, emoji, comfort-focused framing
  student             → Educational context, definitions of jargon
  safety_officer      → Threshold alerts, immediate action items
  energy_manager      → kWh/carbon/cost metrics prominently
  facility_manager    → Actionable items, maintenance priorities
  sustainability_officer → Standards citations (BREEAM, WELL, ISO 50001)
  it_admin            → Schema info, UUIDs, connectivity status
  general             → No transformation (pass-through)

Usage:
    from orchestrator.services.persona_adapter import PersonaAdapter

    adapter = PersonaAdapter()
    enhanced = await adapter.enhance(response, persona="executive", intent="analytics")
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# Per-persona post-processing instructions injected into an LLM reformat call
PERSONA_ENHANCEMENTS: Dict[str, Dict[str, str]] = {
    "executive": {
        "style": "concise KPI-focused summary for a C-level executive",
        "rules": (
            "- Lead with the 1–2 most important numbers in bold\n"
            "- Convert energy to cost (£/kWh = ~0.25 by default) where possible\n"
            "- Use a 3-bullet 'Highlights' section\n"
            "- Add a one-line 'Action Recommended' if applicable\n"
            "- Omit raw sensor UUIDs and technical details"
        ),
    },
    "researcher": {
        "style": "precise and data-provenance-aware academic framing",
        "rules": (
            "- Include confidence level (High/Medium/Low) for inferred values\n"
            "- State the sensor count and time range used for aggregations\n"
            "- Mention data gaps or sensor outages if any\n"
            "- Use ISO 8601 timestamps and SI units\n"
            "- Suggest follow-up statistical tests where relevant"
        ),
    },
    "occupant": {
        "style": "friendly, jargon-free comfort-focused response",
        "rules": (
            "- Use everyday language and avoid acronyms (write 'CO2 levels' not 'ppm')\n"
            "- Add a comfort emoji at the start: ✅ = comfortable, ⚠️ = borderline, ❌ = uncomfortable\n"
            "- Keep the response under 3 sentences\n"
            "- End with a simple action tip if comfort is not ideal"
        ),
    },
    "guest": {
        "style": "friendly, jargon-free comfort-focused response",
        "rules": (
            "- Use everyday language and avoid acronyms (write 'CO2 levels' not 'ppm')\n"
            "- Add a comfort emoji at the start: ✅ = comfortable, ⚠️ = borderline, ❌ = uncomfortable\n"
            "- Keep the response under 3 sentences\n"
            "- End with a simple action tip if comfort is not ideal"
        ),
    },
    "student": {
        "style": "educational and explanatory for a building systems student",
        "rules": (
            "- Define any technical term on first use (e.g., 'CO2 — carbon dioxide, a proxy for ventilation quality')\n"
            "- Add a 'Learn More' one-liner explaining why this matters\n"
            "- Use an analogy if it helps clarify a concept\n"
            "- Encourage curiosity at the end"
        ),
    },
    "safety_officer": {
        "style": "alert-style compliance-focused safety briefing",
        "rules": (
            "- Lead with 🚨 ALERT if any threshold is exceeded, ✅ OK otherwise\n"
            "- State the applicable standard and threshold for each parameter (e.g., ASHRAE 62.1: CO2 < 1000 ppm)\n"
            "- List violated thresholds first\n"
            "- End with 'Recommended Action' if any violation found"
        ),
    },
    "energy_manager": {
        "style": "energy efficiency dashboard style with cost and carbon framing",
        "rules": (
            "- Lead with the headline kWh figure and equivalent CO2e (use 0.233 kg/kWh UK grid)\n"
            "- Show cost estimate (£0.25/kWh default) in brackets\n"
            "- Highlight period-over-period change as % (+/- arrow)\n"
            "- Add 'Energy Saving Opportunity' if there is an obvious recommendation"
        ),
    },
    "facility_manager": {
        "style": "operational maintenance-focused briefing",
        "rules": (
            "- Lead with actionable items (numbered list)\n"
            "- Highlight zone/sensor IDs that need attention\n"
            "- Include estimated maintenance priority: P1 (urgent), P2 (this week), P3 (monitor)\n"
            "- Reference relevant maintenance schedule if applicable"
        ),
    },
    "sustainability_officer": {
        "style": "ESG reporting style with standards citations",
        "rules": (
            "- Reference specific clauses/credits of applicable standards (BREEAM, WELL v2, ISO 50001, EN 15251)\n"
            "- Frame results as 'compliant / non-compliant / borderline' with margin\n"
            "- Suggest if this data can be used as evidence in an audit\n"
            "- Include carbon emission equivalent where energy data is present"
        ),
    },
    "it_admin": {
        "style": "technical system administrator diagnostic style",
        "rules": (
            "- Include sensor UUIDs and storage locations (database names)\n"
            "- State data pipeline status (SPARQL → SQL latency if available)\n"
            "- Highlight any sensors with NULL or missing data\n"
            "- Use table format for lists of sensors/UUIDs"
        ),
    },
}

# Intents that benefit most from persona enhancement (skip for trivial general queries)
_ENHANCE_INTENTS = {
    "analytics",
    "compliance",
    "report",
    "anomaly",
    "trend",
    "compare",
    "export",
    "planner",
}


class PersonaAdapter:
    """
    Lightweight post-processor that re-frames LLM responses per persona.

    Thread-safe, stateless (immutable config).
    """

    async def enhance(
        self,
        response: str,
        persona: str,
        intent: str = "general",
        llm_manager=None,
    ) -> str:
        """
        Apply persona-specific post-processing to a response.

        Args:
            response:    The raw response from the OntoSage pipeline.
            persona:     Target persona (must be in PERSONA_ENHANCEMENTS or 'general').
            intent:      Current intent (enhancement only applied for data intents).
            llm_manager: Optional LLM manager for deeper reframing. If None, applies
                         simple prefix-only enhancement.

        Returns:
            Enhanced response string (factually identical but differently framed).
        """
        # Normalise aliases
        _alias = {
            "stakeholder": "facility_manager",
            "guest": "occupant",
            "officer": "safety_officer",
        }
        persona = _alias.get(persona, persona)

        config = PERSONA_ENHANCEMENTS.get(persona)
        if not config:
            return response  # no enhancement for 'general' or unknown

        # Skip for trivial intents (greetings, clarification, discovery)
        if intent not in _ENHANCE_INTENTS and len(response) < 150:
            return response

        if not llm_manager:
            logger.debug(
                f"PersonaAdapter: no llm_manager — returning raw response for persona={persona}"
            )
            return response

        prompt = f"""{config['style'].capitalize()} persona response rewriter.

Rewrite the following building-data response to match the persona rules below.
Keep ALL factual data, numbers, sensor names, and units EXACTLY as given.
Only adjust tone, structure, and emphasis.

=== PERSONA RULES ===
Style: {config['style']}
{config['rules']}

=== ORIGINAL RESPONSE ===
{response}

=== REWRITTEN RESPONSE ==="""

        try:
            rewritten = await llm_manager.generate(prompt)
            if rewritten and len(rewritten.strip()) > 20:
                logger.info(f"PersonaAdapter: enhanced response for persona={persona}")
                return rewritten.strip()
        except Exception as e:
            logger.warning(f"PersonaAdapter: LLM enhancement failed for {persona}: {e}")

        return response


# Module-level singleton
_adapter_instance: Optional[PersonaAdapter] = None


def get_persona_adapter() -> PersonaAdapter:
    """Return the shared PersonaAdapter singleton."""
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = PersonaAdapter()
    return _adapter_instance
