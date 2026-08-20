# -*- coding: utf-8 -*-
"""
reformulation.py — a denial proposes the nearest ALLOWED question (V5-T41).

A bare refusal teaches the user nothing: they rephrase blindly, hit the same
wall, and conclude the system is broken. This module turns every PDP verdict
into **concrete alternatives the same user could ask right now** — computed
from the verdict's own parameters, never invented:

  aggregate-up     below a k-anonymity floor → ask across the floor/building
  coarsen-window   below the resolution tier → ask for the hourly/daily mean
  public-scope     cross-space request → ask about public spaces only
  drop-identity    individual-inference denial → the room-level counterpart
  retry-later      rate limited → when the window frees up

The plain-language *why* comes from the policy triple's own ``rdfs:comment``
when the building authored one, so an operator can change the explanation by
editing the policy, not the code.

Pure functions over a verdict — no I/O, unit-testable, building-agnostic.
"""

from __future__ import annotations

import re
from typing import List, Optional

from orchestrator.services.privacy.policy_engine import PolicyVerdict


def _room_free_phrasing(question: str) -> Optional[str]:
    """Rewrite a person question into its room-level counterpart, if obvious."""
    q = (question or "").strip().rstrip("?")
    patterns = (
        (
            r"\bis\s+(?:the\s+)?\w+\s+in\s+(?:his|her|their)\s+office\b",
            "Is anyone in that office right now? (a count, not an identity)",
        ),
        (r"\bwho(?:'s| is)\s+in\b(.*)", "How many people are in{} right now?"),
        (r"\bwhen did\b.*\bleave\b", "What were the occupancy levels in that space today?"),
        (r"\bbadge (?:history|records?)\b", "How many entries were recorded at that door today?"),
        (r"\btrack\b.*\bdesk\b", "What is the average desk occupancy for that area this week?"),
    )
    for pat, template in patterns:
        m = re.search(pat, q, re.IGNORECASE)
        if m:
            if "{}" in template:
                tail = (m.group(1) if m.lastindex else "") or " that space"
                return template.format(tail.rstrip(" ,."))
            return template
    return None


def alternatives_for(verdict: PolicyVerdict, question: str = "") -> List[str]:
    """Concrete alternative asks derived from THIS verdict. Never generic."""
    out: List[str] = []
    if verdict.decision == "restrict":
        if verdict.min_sensors > 1 or verdict.min_spaces > 1:
            out.append(
                f"ask the same thing across at least {verdict.min_sensors} sensors / "
                f"{verdict.min_spaces} spaces — e.g. the floor average instead of one room"
            )
        if verdict.resolution_s:
            unit = (
                f"{verdict.resolution_s / 3600:g}-hour"
                if verdict.resolution_s >= 3600
                else f"{verdict.resolution_s:g}-second"
            )
            out.append(f"ask for the {unit} average instead of raw per-reading detail")
        out.append("ask about a more recent window — recent data is available at finer detail")
    elif verdict.decision == "deny":
        reason = (verdict.reason or "").lower()
        if "rate limit" in reason:
            out.append(verdict.alternative or "retry shortly")
        elif "no access policy" in reason:
            out.append("ask an administrator to register a policy for your role")
        else:
            rewritten = _room_free_phrasing(question)
            if rewritten:
                out.append(f'ask "{rewritten}"')
            out.append("ask for room or floor level counts and conditions (never individuals)")
            out.append("ask about spaces you are assigned to, at full detail")
    return out


def explain(verdict: PolicyVerdict, policy_comment: str = "") -> str:
    """Plain-language why: the building's own policy comment when it has one."""
    if policy_comment:
        return policy_comment.strip()
    if verdict.decision == "deny" and "never individuals" in (verdict.reason or ""):
        return (
            "This system explains the building — occupancy counts, conditions, "
            "bookings — and never identifies or tracks a person."
        )
    return verdict.reason or ""


def render_refusal(verdict: PolicyVerdict, question: str = "", policy_comment: str = "") -> str:
    """The user-facing refusal: what, why, and what to ask instead."""
    head = (
        "**I can't answer that at the level you asked.**"
        if verdict.decision == "restrict"
        else "**I can't answer that.**"
    )
    lines = [f"{head} {explain(verdict, policy_comment)}"]
    alts = alternatives_for(verdict, question)
    if alts:
        lines.append("")
        lines.append("You can instead:")
        lines += [f"- {a}" for a in alts]
    if verdict.policy_iri:
        lines.append("")
        lines.append(f"_Policy: `{verdict.policy_iri.rsplit('#', 1)[-1]}`._")
    return "\n".join(lines)
