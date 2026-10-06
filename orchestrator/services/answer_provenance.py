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
    r"|\bprove it\b|\bis that (?:reliable|trustworthy|auditable)\b"
    # D7 (QA-trial plan, 2026-10-02): five phrasings a live detector probe found matching
    # NEITHER this regex nor session_recall's ("which one did you check?", "which data
    # sources/records/sensors did you use?", "what data/sources did you use?") -- so they
    # reached no lane at all. Deliberately NOT added here: "what is the evidence behind
    # your answer?" and "how did you arrive at that?", which session_recall already owns
    # (BUG-1397, VERIFIED_LIVE) -- widening here would re-open that fix, not close a gap.
    # Measured over the 4,060-question bank before shipping: exactly 1 move, a correct one
    # ("Which sensors did you use to answer my last question?"), 0 lost.
    r"|\bwhich (?:data )?(?:sources?|records?|sensors?|ones?) did you (?:use|check|read)\b"
    r"|\bwhat (?:data|sources?) did you use\b",
    re.IGNORECASE,
)


def is_provenance_question(query: str) -> bool:
    """True when the user is asking how the previous answer was arrived at."""
    return bool(PROVENANCE_RE.search(query or ""))


def _fmt_time(value: Any) -> str:
    text = str(value or "").strip()
    return text.replace("T", " ")[:19] if text else ""


def render(
    record: Optional[Dict[str, Any]],
    question: str = "",
    for_admin: bool = False,
    inline: bool = False,
) -> Optional[str]:
    """Read an evidence record back as prose, or None when there is nothing to read.

    Returns None rather than a placeholder: with no record, the honest answer is that the
    previous turn did not carry one, and the caller says so in its own words.

    ``for_admin`` adds the record's remedy. The default is the plain read-back, so a caller
    that does not know who is reading fails toward it.

    ``inline`` (D11/D16, QA-trial plan 2026-10-02): the SAME record, read for the CURRENT
    answer rather than for a follow-up question about a PAST one. Three differences only —
    no new prose, no second renderer: the heading says "this answer" not "that answer", the
    closing sentence (which only makes sense as a read-back of a past turn) is dropped, and
    the whole block is wrapped in a collapsible ``<details type="evidence">`` the way
    ``render_dossier_details`` already wraps its own panel, so the two read the same way in
    the client.
    """
    if not record:
        return None

    from orchestrator.services.provenance import readable_source_label

    heading = "How this answer was arrived at" if inline else "How that answer was arrived at"
    lines: List[str] = [f"**{heading}**", ""]

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
        # D6 (QA-trial plan, 2026-10-02): the authority tier that led -- "what kind of
        # thing answered you" (W4-02) -- now set on every turn with at least one source,
        # not only when two tiers disagreed.
        if record.get("source_tier"):
            lines.append(f"- **Kind of source that led:** {record['source_tier']}")

    sources = record.get("sources") or []
    if sources:
        lines.append(f"- **Sources ({len(sources)}):**")
        for src in sources[:8]:
            # D15 (QA-trial plan, 2026-10-02): this printed `source_id` verbatim -- a bare
            # timeseries UUID or a raw record IRI in front of every reader, BUG-1407's shape
            # at the evidence layer. A record built after D15's fix carries a reader-facing
            # `label`; one built before it (an old cached turn) did not, so this still never
            # falls back to the bare id, only to a readable derivation of it.
            _sid = str(src.get("source_id") or "?")
            bits = [f"`{src.get('label') or readable_source_label(_sid)}`"]
            if src.get("kind"):
                bits.append(str(src["kind"]).replace("_", " "))
            if src.get("owner"):
                bits.append(f"owned by {src['owner']}")
            if src.get("record_version"):
                bits.append(f"version {src['record_version']}")
            # The declaration stays in the record and is no longer rendered as a caveat on
            # the answer (user decision, 2026-09-16): this deployment's readings are
            # placeholder data for the building's own feed, replaced wholesale at connection
            # time, so the marker described the stage rather than the source. The honesty
            # this file exists for is untouched — every figure still names where it came
            # from, and an absent one is still reported as absent.
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
        when_line = "- **When:** " + ", ".join(when)
        # D16 (QA-trial plan, 2026-10-02): `_serve_from_cache` restores this record on a
        # repeated question and deliberately does NOT refresh `retrieved_at` — so without
        # this, a tester who asks the same question twice and then asks how it knows that
        # is shown a true timestamp with a false implication: that THIS turn re-read the
        # store. It did not; nothing was re-read for it.
        if record.get("served_from_cache"):
            when_line += (
                " (this answer was replayed from a cached result; nothing was re-read for it)"
            )
        lines.append(when_line)

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
        # E7 (2026-10-06): one line per fired advisory gate, each with its reason. A single
        # comma-joined line named the gate but not why, and an advisory failure is only
        # worth reading once you know what it objected to. Entries are "gate: reason" as
        # assemble.py writes them; a bare name still renders, with no reason to add.
        lines.append("- **Checks that flagged in advisory mode** (recorded, changed nothing):")
        for entry in advisory[:6]:
            name, _, reason = str(entry).partition(": ")
            detail = f" — {reason.strip()}" if reason.strip() else ""
            lines.append(f"    - `{name.strip()}`{detail}")

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

    # The "Kind of claim" line above already tells every reader the evidence could not
    # support an answer. HOW to make it answerable is a data change ("connect the stream",
    # "install a sensor"), which only an administrator can make. Told to anyone else it reads as a broken system
    # (2026-09-17 user decision), so it is withheld unless the reader holds system:admin.
    if for_admin and record.get("remedy"):
        lines.append(f"- **To make it answerable:** {record['remedy']}")

    if inline:
        # D18 (QA-trial plan, 2026-10-02): an empty working-out is not working-out
        # (render_dossier_details's own rule, dossier.py:481-483). Injected into EVERY
        # answer unprompted, a panel holding only the heading and a "Kind of claim" line
        # with no sources, no gates and no conflicts is noise, not evidence. A FOLLOW-UP
        # question ("how do you know that?") still gets the full read-back even when it is
        # this sparse — that is a direct answer to a direct question, not an unprompted
        # addition — so this guard applies only here.
        if len(lines) <= 2:  # just the heading and a blank line: nothing was added at all
            return ""
        # D11: collapsible, the same convention render_dossier_details uses, so the two
        # panels read the same way in the client. No closing sentence here — "kept at the
        # time it was given, not a reconstruction after the fact" is a claim about reading
        # a PAST turn's record; this IS the current turn's record.
        body = "\n".join(lines)
        return "\n".join(
            [
                "",
                '<details type="evidence">',
                "<summary>How I know this</summary>",
                "",
                body,
                "",
                "</details>",
            ]
        )

    lines += [
        "",
        "_This is the answer's own evidence record, kept at the time it was given — not a "
        "reconstruction after the fact._",
    ]
    return "\n".join(lines)


#: D9: how much of a turn's evidence record is kept in `turn_memory`. A projection, never the
#: whole record: the record can carry hundreds of sources and full claim-binding detail, and
#: a row that grows with the data it describes is a second store, not a memo.
PROJECTION_MAX_SOURCES = 25
PROJECTION_MAX_GATES = 20
_PROJECTION_TEXT_MAX = 200
_PROJECTION_SOURCE_FIELDS = ("source_id", "kind", "store", "owner", "observed_at")
_PROJECTION_COUNT_FIELDS = (
    "total",
    "bound",
    "derived",
    "unbound",
    "skipped",
    "unbound_numeric",
    "unbound_universal",
)


def _cap_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    return text[:_PROJECTION_TEXT_MAX]


def project_for_storage(record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The bounded subset of an evidence record that is kept per turn, or None.

    Holds what the "how do you know that?" read-back and the evidence endpoint need: the
    status and operation, the sources (capped at PROJECTION_MAX_SOURCES, each with only its
    identity fields), the two evidence times, the gates that fired, and the claim-binding
    COUNTS. Free text is cut at _PROJECTION_TEXT_MAX characters. The remedy is kept because
    the endpoint shows it to a system:admin reader and strips it for everyone else.

    Never raises: a turn's evidence failing to project must not cost the turn's memory row.
    """
    if not isinstance(record, dict) or not record:
        return None
    try:
        sources: List[Dict[str, Any]] = []
        for src in (record.get("sources") or [])[:PROJECTION_MAX_SOURCES]:
            if isinstance(src, dict):
                sources.append({f: _cap_text(src.get(f)) for f in _PROJECTION_SOURCE_FIELDS})

        gates = [_cap_text(g) for g in (record.get("gates_applied") or [])]
        advisory = [_cap_text(g) for g in (record.get("gates_advisory") or [])]
        binding = record.get("claim_binding") or {}
        counts_src = binding.get("counts") if isinstance(binding, dict) else None
        counts = {
            f: int(counts_src[f])
            for f in _PROJECTION_COUNT_FIELDS
            if isinstance(counts_src, dict) and isinstance(counts_src.get(f), int)
        }

        out: Dict[str, Any] = {
            "status": _cap_text(record.get("status")),
            "operation": _cap_text(record.get("operation")),
            "sources": sources,
            "sources_total": len(record.get("sources") or []),
            "latest_evidence_at": _cap_text(record.get("latest_evidence_at")),
            "retrieved_at": _cap_text(record.get("retrieved_at")),
            "gates_applied": gates[:PROJECTION_MAX_GATES],
            "gates_advisory": advisory[:PROJECTION_MAX_GATES],
            "claim_binding": {
                "mode": _cap_text(binding.get("mode")) if isinstance(binding, dict) else None,
                "counts": counts,
            },
        }
        if record.get("remedy"):
            out["remedy"] = _cap_text(record.get("remedy"))
        return out
    except Exception as exc:  # the projection must never cost the turn its memory row
        logger.warning(f"[evidence] projection skipped: {exc}")
        return None


def for_reader(projection: Optional[Dict[str, Any]], *, is_admin: bool) -> Optional[Dict[str, Any]]:
    """The stored projection as one reader may see it. The remedy is for system:admin only."""
    if not projection:
        return None
    shown = dict(projection)
    if not is_admin:
        shown.pop("remedy", None)
    return shown
