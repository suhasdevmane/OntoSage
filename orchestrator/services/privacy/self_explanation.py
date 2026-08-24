# -*- coding: utf-8 -*-
"""The building explaining how it watches you (V6-T31).

An explicit PhD-catalogue expectation, and the honest counterpart to enforcement: *a system
that refuses to explain its own surveillance is not trustworthy even when its refusals are
correct.*

**The explanation is composed from DECLARATIONS, never from data.** It reads
``config/privacy_disclosure.yaml`` and the building's modality declarations; it never touches
a reading. That is not merely tidy -- answering *"there are 3 people in room 2.15 and one of
them is you"* under the banner of transparency would be the exact disclosure the policy
exists to prevent, and the surest way to get there is to let a transparency lane read live
data "just to be accurate".

**It states granularity as well as protections.** Saying "occupancy is anonymous" without
saying "per room, per minute" understates what a small enough space reveals: a count of one
in a single-occupancy office is a statement about a person. The disclosure says both, because
a partial truth here reads as reassurance and is worse than silence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from shared.utils import get_logger

logger = get_logger(__name__)

_REPO = Path(__file__).resolve().parents[3]
_PATH = _REPO / "config" / "privacy_disclosure.yaml"

#: Question shapes this lane answers. Deliberately narrow: a question about a PERSON
#: ("where is Dr Smith") is a privacy REFUSAL, not a transparency request, and must keep
#: reaching the refusal path rather than being softened into an explanation.
_ASK_RE = re.compile(
    r"\bwhat (?:data )?(?:do you|does (?:this|the) building) (?:collect|know|hold|store|monitor)\b"
    r"|\bhow (?:am i|are we) (?:being )?monitor\w*\b"
    r"|\bwhat do you know about me\b"
    r"|\bam i being (?:watched|tracked|recorded|monitored)\b"
    r"|\bhow long (?:do you|is (?:my|the) data) (?:keep|kept|retain\w*|stored)\b"
    r"|\b(?:data )?retention (?:policy|period)\b"
    r"|\bprivacy (?:policy|notice|impact)\b"
    r"|\bis (?:there|this) (?:a )?(?:camera|microphone|facial recognition)\b"
    r"|\bhow do i (?:challenge|complain about|object to) (?:the )?monitoring\b",
    re.IGNORECASE,
)


@dataclass
class Disclosure:
    never_collected: List[str] = field(default_factory=list)
    granularity: Dict[str, str] = field(default_factory=dict)
    retention: List[Dict[str, str]] = field(default_factory=list)
    governance: Dict[str, str] = field(default_factory=dict)
    citation: str = ""


@lru_cache(maxsize=1)
def load_disclosure() -> Disclosure:
    """Read the declarations. A missing file yields an EMPTY disclosure, not a reassuring one.

    Silence is the honest failure here: inventing "we protect your privacy" from a file that
    does not exist would be the most damaging possible thing this module could do.
    """
    try:
        raw: Dict[str, Any] = yaml.safe_load(_PATH.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.error(f"[privacy_disclosure] could not read {_PATH}: {exc}")
        return Disclosure()
    return Disclosure(
        never_collected=[
            str(x.get("statement", "")).strip() for x in (raw.get("never_collected") or [])
        ],
        granularity={k: str(v).strip() for k, v in (raw.get("granularity") or {}).items()},
        retention=[{k: str(v) for k, v in item.items()} for item in (raw.get("retention") or [])],
        governance={k: str(v).strip() for k, v in (raw.get("governance") or {}).items()},
        citation=str(raw.get("citation", "")).strip(),
    )


def is_self_explanation_question(question: str) -> bool:
    """True for a question ABOUT the monitoring, not one asking to use it."""
    return bool(question and _ASK_RE.search(question))


def explain(
    question: str = "",
    monitored_modalities: Optional[List[str]] = None,
    building_name: str = "this building",
) -> str:
    """Compose the disclosure. Reads declarations only; never reads a reading.

    `monitored_modalities` comes from the building's own declared modality set, so a building
    that measures three things discloses three things. Passing nothing yields a disclosure
    that omits the sensing list rather than inventing one.
    """
    d = load_disclosure()
    if not (d.never_collected or d.retention or d.granularity):
        return (
            f"No privacy disclosure has been published for {building_name}, so I cannot "
            "describe what it collects or how long it keeps it. Your building's data "
            "controller can tell you."
        )

    parts: List[str] = [f"**How {building_name} monitors its spaces**", ""]

    if monitored_modalities:
        listed = ", ".join(sorted(set(monitored_modalities)))
        parts += [f"**What is measured:** {listed}.", ""]

    if d.granularity:
        parts.append("**At what resolution:**")
        for key in ("spatial", "temporal", "derivation"):
            if d.granularity.get(key):
                parts.append(f"- {d.granularity[key]}")
        parts.append("")

    if d.never_collected:
        parts.append("**What is never collected:**")
        parts += [f"- {s}" for s in d.never_collected if s]
        parts.append("")

    if d.retention:
        parts.append("**How long things are kept:**")
        for item in d.retention:
            stream, period = item.get("stream", ""), item.get("period", "")
            reason = item.get("reason", "")
            parts.append(f"- **{stream}** — {period}" + (f" ({reason})" if reason else ""))
        parts.append("")

    gov = d.governance
    if gov:
        parts.append("**Governance:**")
        for key in ("access_logging", "combination_risk", "dpia"):
            if gov.get(key):
                parts.append(f"- {gov[key]}")
        route = gov.get("challenge_route") or gov.get("challenge_fallback")
        if route:
            parts += ["", f"**To challenge or report this:** {route}"]

    return "\n".join(parts).strip()


def combination_risk_note() -> str:
    """Why a question can be refused although every field behind it is visible.

    Worth surfacing on a refusal: without it, declining a question whose inputs the user can
    each see individually looks arbitrary, and an arbitrary-seeming refusal invites people to
    work around it.
    """
    return load_disclosure().governance.get("combination_risk", "")
