"""
orchestrator.intents — Phase 6 intent registry.

Single source of truth for the system's intent taxonomy.  All consumers
(dialogue_agent prompt, multi_intent_detector validation, planner_agent
pipeline groups) read from this registry instead of maintaining their own
hardcoded lists.

Adding a new intent: edit `intent_definitions.yaml`.  No Python edits.
"""

from .registry import IntentDefinition, IntentRegistry, get_intent_registry

__all__ = [
    "IntentDefinition",
    "IntentRegistry",
    "get_intent_registry",
]
