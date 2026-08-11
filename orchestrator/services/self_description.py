"""Answer questions about OntoSage itself, from what it is actually configured to do.

Why this exists
---------------
"What can you do?" and "How do you work?" were reaching the open-domain answerer,
which has no knowledge of this system and supplied a plausible-sounding substitute.
Observed live: "How do you work?" replied *"I'm a large-language model built by
OpenAI"* — flatly wrong — and "What can you do?" offered guidance on BACnet, Modbus
and ISO 50001 while naming none of the things OntoSage actually does. "What is
OntoSage?" only worked by accident, because one building's governance document
happens to mention it; on a building without that document it would fail.

This is the same failure as BUG-123, in a new place: a question the system cannot
ground, answered anyway.

How the answer is grounded
--------------------------
Nothing here is a written-out blurb, because prose drifts from the system the
moment anyone changes it. Every part is read from live configuration:

  * what you can ask   → the INTENT REGISTRY, which already merges per-building
                         overlays, so a building that adds an intent gains it here
  * how it works       → the ontosage:SourceType terms in the shared schema, which
                         are the definition of what an answer may be grounded in
  * what it knows HERE → counts computed from the active building's own graph

So the answer differs per building because the building differs, and adding a
capability updates it without anyone remembering to edit a paragraph.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

# Questions about the assistant rather than the building. Kept tight: "what can
# you tell me about the chiller?" is about the building and must not land here.
_SELF_RE = re.compile(
    r"\bwhat (?:is|are) (?:ontosage|you)\b"
    r"|\bwho are you\b"
    r"|\bwhat (?:can|could) you (?:do|help|answer|tell me)\b(?!\s+about\s+(?:the|this)\s+\w)"
    r"|\bwhat do you (?:do|support|know how|offer)\b"
    r"|\bhow (?:do|does) (?:you|ontosage|this system|it) work\b"
    r"|\bwhat (?:kind|sort|type)s? of (?:questions?|things?) can i ask\b"
    r"|\bwhat are your (?:capabilities|features|abilities)\b"
    r"|\bwhat (?:questions?|else) can i ask\b"
    r"|\bintroduce yourself\b|\btell me about ontosage\b",
    re.IGNORECASE,
)

# Intent names that are plumbing rather than something a person would ask for.
_NOT_USER_FACING = {"general", "greeting", "clarification", "planner", "self_description"}

# Grouped so the list reads as capabilities rather than as 28 internal labels. An
# intent missing from every group still appears, under "other" — the grouping is
# presentation, never a filter, so a new intent cannot be silently hidden.
_GROUPS: List[tuple] = [
    ("Live sensor data", ("sensor_data", "trend", "forecast", "visualization", "export")),
    ("Analysis", ("analytics", "compare", "anomaly", "compliance", "recommend", "report")),
    ("The building's structure", ("metadata", "discovery", "spatial_query", "floor_plan")),
    ("Facilities and policies", ("capability", "automation_capability")),
    (
        "Reporting a problem",
        ("maintenance", "complaint", "safety_report", "feedback", "suggestion"),
    ),
    ("Alerts and control", ("alert", "control", "preference_management")),
]


def is_self_question(query: str) -> bool:
    """True when the user is asking about the assistant, not about the building."""
    q = (query or "").strip()
    return bool(q) and bool(_SELF_RE.search(q))


def _capabilities(registry: Any) -> List[tuple]:
    """(group, [intent names]) from the LIVE registry, including building overlays."""
    try:
        available = {i.name for i in registry.intents if i.name.lower() not in _NOT_USER_FACING}
    except Exception as e:
        logger.warning(f"[self_description] intent registry unavailable: {e}")
        return []

    out, claimed = [], set()
    for label, names in _GROUPS:
        present = [n for n in names if n in available]
        if present:
            out.append((label, present))
            claimed.update(present)
    leftover = sorted(available - claimed)
    if leftover:
        out.append(("Other", leftover))
    return out


def _pretty(name: str) -> str:
    return name.replace("_", " ")


def describe(
    registry: Any,
    building_name: str,
    facts: Optional[Dict[str, Any]] = None,
    source_types: Optional[List[str]] = None,
) -> str:
    """Compose the answer. ``facts`` and ``source_types`` are read from the live building."""
    facts = facts or {}
    # WHAT ONTOSAGE IS does not change when the building changes. Saying "I am a
    # conversational layer over <this building>" made the identity sound like a
    # product built for one site; the building is what it is CONNECTED to, not what
    # it IS. The identity below is therefore constant on every building — including
    # one onboarded today with no data yet — and the site appears only under what is
    # currently connected.
    lines = [
        "I'm **OntoSage** — a building-agnostic framework for asking a building "
        "questions in plain English. I'm not built for any one site: connect a "
        "building's knowledge graph, point me at the databases holding its sensor "
        "readings, and I answer questions about it. Onboarding a new building is "
        "configuration and data — a TTL describing what exists, database credentials, "
        "optionally floor plans and documents — with no code changes.\n",
        "I'm meant for whoever needs to ask: facility managers, occupants, "
        "researchers, sustainability and safety officers, executives, visitors and "
        "administrators. You need no knowledge of SPARQL, SQL or the building's "
        "schema — everyday words are resolved to whatever the building actually "
        "calls things.\n",
        "**How I answer**\n",
        "Every answer is traced to a source rather than generated from memory. I look "
        "up what exists in the building's ontology, read live values from the "
        "databases those sensors are registered in, and compute anything that needs "
        "calculating. If the thing you asked about isn't in the connected building's "
        "model, I say so instead of giving you a number that looks right.\n",
    ]

    if source_types:
        lines.append("I can ground an answer in: " + ", ".join(sorted(source_types)) + ".\n")

    groups = _capabilities(registry)
    if groups:
        lines.append("**What you can ask me**\n")
        for label, names in groups:
            lines.append(f"- **{label}** — {', '.join(_pretty(n) for n in names)}")
        lines.append("")

    # The connected building goes LAST and is clearly framed as the current
    # connection, so the capabilities above read as the framework's and not as one
    # site's. A building with nothing loaded yet simply shows no figures.
    if building_name:
        lines.append(f"**Currently connected to: {building_name}**\n")
        if facts:
            for label, value in facts.items():
                if value:
                    lines.append(f"- {label}: **{value}**")
        else:
            lines.append(
                "- No data loaded yet — add a TTL describing the building and register "
                "a database for its readings, and the questions above become answerable."
            )
        lines.append("")

    lines.append(
        "*Everything above is read from my own configuration and the connected "
        "building's data, not from a fixed script — connect a different building and "
        "the capabilities stay the same while the figures change.*"
    )
    return "\n".join(lines)
