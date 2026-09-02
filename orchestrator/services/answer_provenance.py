# -*- coding: utf-8 -*-
"""Answer the question "how do you know that?" from the evidence record (V7-T74).

V6 built a machine-readable evidence record for every consequential answer — sources and
their owners, the operation performed, the gates that fired, when the evidence was
observed and when it was retrieved, how complete it was. It is assembled at one
chokepoint and carried on every turn.

**Nothing reached it by asking.** Measured on the stakeholder probe: auditors asked "can
every extraction, join, filter and chart be rerun from authorised inputs?" and got a
document search; "how do you know that?" was classified as a question about the system's
own capabilities. The record was sitting in the previous turn's state the whole time.

That makes this the twelfth instance of the pattern this project keeps hitting — a
capability built, correct, tested, and with no invoker — and the cheapest to close,
because the answer already exists and only has to be read out.

The record of the PREVIOUS turn is what a provenance question is about: "how do you know
that" refers to the answer just given, never to the question being asked now.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

#: A question about how the LAST answer was arrived at.
#:
#: Deliberately narrow. "Where did that come from?" is a provenance question; "where is
#: the nearest toilet?" is wayfinding, and a looser pattern would take it. Every shape
#: here refers back to something already said.
PROVENANCE_RE = re.compile(
    r"\bhow do(?:es)? (?:you|it) know\b"
    r"|\bhow did you (?:know|work (?:that|this) out|get (?:that|this)|arrive at)\b"
    # "that came from" and "that NUMBER came from" are the same question, so the noun
    # after the determiner is optional — the first version required one form or the other
    # and missed the more natural phrasing.
    r"|\bwhere (?:did|does) (?:that|this|it|the)"
    r"(?:\s+(?:number|figure|answer|value|data|reading|result))?\s+come from\b"
    r"|\bwhat(?:'s| is| are) (?:your|the) sources?\b"
    r"|\bwhat (?:is|was) (?:that|this) based on\b"
    r"|\bcan (?:that|this|it|the (?:answer|figure|result)) be (?:rerun|reproduced|repeated|audited|verified)\b"
    r"|\bhow (?:was|were) (?:that|this|it) (?:calculated|computed|derived|measured)\b"
    r"|\bshow (?:me )?(?:your|the) (?:working|provenance|evidence|audit trail)\b"
    r"|\bprove it\b|\bis that (?:reliable|trustworthy|auditable)\b",
    re.IGNORECASE,
)


def is_provenance_question(query: str) -> bool:
    """True when the user is asking how the previous answer was arrived at."""
    return bool(PROVENANCE_RE.search(query or ""))


def _fmt_time(value: Any) -> str:
    text = str(value or "").strip()
    return text.replace("T", " ")[:19] if text else ""


def render(record: Optional[Dict[str, Any]], question: str = "") -> Optional[str]:
    """Read an evidence record back as prose, or None when there is nothing to read.

    Returns None rather than a placeholder: with no record, the honest answer is that the
    previous turn did not carry one, and the caller says so in its own words.
    """
    if not record:
        return None

    lines: List[str] = ["**How that answer was arrived at**", ""]

    status = str(record.get("status") or "")
    operation = str(record.get("operation") or "")
    if status or operation:
        kind = {
            "observed": "read from an instrument",
            "calculated": "arithmetic over observations",
            "inferred": "reasoned from observations, not itself measured",
            "predicted": "a forecast",
            "recommended": "an action proposed, with its basis",
            "not_assessable": "the evidence could not support an answer",
        }.get(status, status)
        # The gloss follows the OPERATION where the two disagree. A permit register is not
        # an instrument, and "observed — read from an instrument" over an authoritative
        # lookup describes the wrong kind of evidence entirely. The catalogues separate a
        # lookup from an observation for exactly this reason: both are OBSERVED, and only
        # one of them read a sensor.
        if status == "observed" and operation == "authoritative_lookup":
            kind = "read from a system of record, not from an instrument"
        # A comparison reports how things differ. Saying only "read from an instrument" or
        # "arithmetic over observations" describes the ingredients and hides the act, which
        # is the whole reason COMPARISON became an operation (CAVEAT-365).
        elif operation == "comparison":
            kind = "two or more things set against each other, and the difference reported"
        lines.append(
            f"- **Kind of claim:** {status or 'unstated'}" + (f" — {kind}" if kind else "")
        )
        if operation:
            lines.append(f"- **Operation performed:** {operation.replace('_', ' ')}")

    sources = record.get("sources") or []
    if sources:
        lines.append(f"- **Sources ({len(sources)}):**")
        for src in sources[:8]:
            bits = [f"`{src.get('source_id', '?')}`"]
            if src.get("kind"):
                bits.append(str(src["kind"]).replace("_", " "))
            if src.get("owner"):
                bits.append(f"owned by {src['owner']}")
            if src.get("record_version"):
                bits.append(f"version {src['record_version']}")
            # simulated is TRI-state: None means nobody declared, which is not the same
            # as real and must never be rendered as such.
            if src.get("simulated") is True:
                bits.append("**declared synthetic**")
            lines.append("    - " + " · ".join(bits))

    observed = _fmt_time(record.get("latest_evidence_at"))
    retrieved = _fmt_time(record.get("retrieved_at"))
    if observed or retrieved:
        # The two times are reported separately on purpose: stale evidence is not current
        # status, and collapsing them is what makes an old reading look like a live one.
        when = []
        if observed:
            when.append(f"newest evidence {observed}")
        if retrieved:
            when.append(f"retrieved {retrieved}")
        lines.append("- **When:** " + ", ".join(when))

    if record.get("completeness") is not None:
        lines.append(
            f"- **Completeness:** {float(record['completeness']) * 100:.0f}% of expected samples"
        )
    if record.get("analysis_method"):
        lines.append(f"- **Method:** {record['analysis_method']}")
    if record.get("comparison_baseline"):
        lines.append(f"- **Compared against:** {record['comparison_baseline']}")
    if record.get("uncertainty"):
        lines.append(f"- **Uncertainty:** {record['uncertainty']}")
    if record.get("thresholds_applied"):
        lines.append(f"- **Standard applied:** {', '.join(record['thresholds_applied'][:3])}")

    gates = record.get("gates_applied") or []
    advisory = record.get("gates_advisory") or []
    if gates:
        lines.append(f"- **Checks that fired:** {', '.join(gates[:6])}")
    if advisory:
        lines.append(f"- **Checks that flagged in advisory mode:** {', '.join(advisory[:6])}")

    conflicts = record.get("conflicts") or []
    if conflicts:
        # Reported, never averaged away: an averaged pair yields a value neither source
        # measured.
        lines.append(f"- **Disagreements between sources:** {'; '.join(conflicts[:3])}")

    omitted = record.get("omitted_criteria") or []
    if omitted:
        lines.append(
            f"- **Left out of the answer:** {len(omitted)} criterion(s), listed in the record"
        )

    if record.get("remedy"):
        lines.append(f"- **To make it answerable:** {record['remedy']}")

    lines += [
        "",
        "_This is the answer's own evidence record, kept at the time it was given — not a "
        "reconstruction after the fact._",
    ]
    return "\n".join(lines)
