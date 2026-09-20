# -*- coding: utf-8 -*-
"""What the building can and cannot do on its own, answered for the question that was asked.

The automation-capability lane answered every "can the building ... automatically ...?" question
with the same paragraph about a measured quantity it could not identify: "Can the building alert
someone to a task?" and "is there a manual override for standby mode?" both got *"I couldn't tell
which measured quantity the condition corresponds to ... No notification channel is set up"*, which
answers neither (defect class C19 on the 2026-09-18 held-out reads).

Three kinds of question are told apart here, and each gets its own answer:

* **override / actuation** -- switch something on or off, override a mode, take manual control. This
  service reads and reports; it does not operate equipment, and it says so plainly, then says what it
  CAN tell (the state, if the building measures it) and where an override belongs.
* **a task or a person** -- alert someone to a job. Alerts are raised from measured quantities
  against a limit, not from tasks; a condition held as a record can be read on request but no rule
  watches it. Said plainly, with what the building does keep.
* **a quantity that could not be identified** -- the general answer: what it can watch, which rules
  exist, whether an alert can reach a person, and what it does not do.

A question that DID identify a quantity keeps the existing answers, which are pinned by tests; this
module only supplies the parts around them. Everything about the building (measured quantities,
record classes, rules, channels) is passed in, read live by the caller, and never written here.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

from orchestrator.services.fallback_wording import and_list
from shared.utils import get_logger

logger = get_logger(__name__)

KIND_OVERRIDE = "override"
KIND_TASK = "task"
KIND_QUANTITY = "quantity"
KIND_PROVISION = "provision"

#: Words a record class uses when it holds emergency or notification provisions. English, not a
#: building's vocabulary: whichever of the building's OWN record classes carry these are named.
_PROVISION_RECORD_WORDS = (
    "coordination",
    "evacuation",
    "emergency",
    "fire",
    "alarm",
    "warden",
    "marshal",
    "refuge",
    "accessible",
    "accessibility",
    "continuity",
    "incident",
    "peep",
    "safety",
)

_OVERRIDE_RE = re.compile(
    r"\b(?:manual(?:ly)?\s+(?:override|control|mode)|override\w*|stand-?by|"
    r"(?:switch|turn)(?:ed|ing|es|s)?\s+(?:\w+\s+){0,3}?(?:on|off)|"
    r"shut\s?(?:down|off)|power(?:ed|ing)?\s+(?:down|off|on)|take\s+(?:manual\s+)?control|"
    r"force\s+(?:on|off)|set\s?points?|thermostat)\b",
    re.IGNORECASE,
)
_PERSON = (
    r"someone|somebody|anyone|staff|the team|a team|cleaner|cleaners|porter|security|technician|"
    r"engineer|maintenance|caretaker|person|people|owner|manager|contractor"
)
_TASK_RE = re.compile(
    rf"\b(?:alert|notify|tell|remind|page|message|inform|warn|send)\b[^?.!]{{0,50}}\b(?:{_PERSON})\b"
    r"|\b(?:task|tasks|to-?do|chore|chores|job|jobs|rota|schedule)\b",
    re.IGNORECASE,
)


#: A question about what NOTIFICATION PROVISIONS the building has, rather than about watching a
#: measured quantity. Measured live: "I may not see visual alerts. Which verified audible or
#: staff-assisted notification provision is available?" was answered "This building does measure
#: **empty space** (270 sensor point(s))" -- a measurand that does not exist, about the wrong
#: subject. The provisions are in the building's own records (coordination function, evacuation),
#: never in a sensor count.
_PROVISION_RE = re.compile(
    r"\b(?:audible|visual|tactile|vibrating|staff[- ]assisted|buddy|assisted)\b[^?.!]{0,40}"
    r"\b(?:alert\w*|alarm\w*|notification\w*|warning\w*|provision\w*|signal\w*|beacon\w*)\b"
    r"|\b(?:alert\w*|alarm\w*|notification\w*|warning\w*)\b[^?.!]{0,40}"
    r"\b(?:provision\w*|arrangement\w*|available|in\s+place|exist\w*|offered|provided)\b"
    r"|\bhow\s+(?:will|would|do|am)\s+(?:i|we|people|occupants)\s+(?:be\s+)?"
    r"(?:told|alerted|notified|warned|made\s+aware)\b",
    re.IGNORECASE,
)


def question_kind(question: str) -> str:
    """'provision', 'override', 'task' or 'quantity', from the wording of the question alone."""
    q = question or ""
    if _PROVISION_RE.search(q):
        return KIND_PROVISION
    if _OVERRIDE_RE.search(q):
        return KIND_OVERRIDE
    if _TASK_RE.search(q):
        return KIND_TASK
    return KIND_QUANTITY


@dataclass
class RuleView:
    """One standing rule, as much of it as a reader needs."""

    name: str
    watches: str = ""  # the quantity or point the rule watches, in words


@dataclass
class Facts:
    """What the active building holds, read live by the caller."""

    building: str = "this building"
    measured: List[str] = field(default_factory=list)
    record_labels: List[str] = field(default_factory=list)
    rules: List[RuleView] = field(default_factory=list)
    delivers: bool = False
    for_admin: bool = False


NO_CHANNEL = (
    "No notification channel is set up for this building, so I can't send you an automatic alert."
)
ACTUATION_LINE = (
    "- Automatically change a physical system (e.g. open a valve, adjust a thermostat "
    "setpoint) — that needs a building-control connection that is not set up for this "
    "building."
)


def load_rule_views(building_id: Optional[str]) -> List[RuleView]:
    """The building's enabled standing rules, read from its own rules file; [] when there are none.

    Reads only the configuration the rules engine itself loads, so what is said here is what the
    engine is actually running. Never raises: an unreadable file is "no rules known", not a fault.
    """
    try:
        from orchestrator.services.rules_engine import RulesEngine

        engine = RulesEngine(building_id=str(building_id or ""))
        engine.load()
        views: List[RuleView] = []
        for rule in engine.rules:
            trigger = rule.trigger
            watches = str(trigger.concept or "").replace("_", " ") or "one named sensor"
            views.append(RuleView(name=str(rule.name or rule.id), watches=watches))
        return views
    except Exception as exc:
        logger.debug(f"[automation_answer] rules unreadable: {exc}")
        return []


def _rules_line(rules: Sequence[RuleView]) -> str:
    if not rules:
        return "- **Standing rules:** none are set up, so nothing is being watched for you yet."
    shown = and_list([r.name for r in rules], 3)
    more = f" and {len(rules) - 3} more" if len(rules) > 3 else ""
    noun = "rule is" if len(rules) == 1 else "rules are"
    return f"- **Standing rules:** {len(rules)} {noun} set up: {shown}{more}."


def _watch_line(facts: Facts) -> str:
    if facts.measured:
        shown = and_list(facts.measured, 6)
        more = " and more" if len(facts.measured) > 6 else ""
        return f"- **What it can watch:** the quantities it measures — {shown}{more}."
    return "- **What it can watch:** the quantities it measures; ask what this building measures."


def _delivery_line(facts: Facts) -> str:
    if facts.delivers:
        return "- **Delivery:** alerts can reach a person through the configured channel."
    return f"- **Delivery:** {NO_CHANNEL}"


def _admin_channel_hint(facts: Facts) -> List[str]:
    if facts.for_admin and not facts.delivers:
        return [
            "",
            "Configure a delivering channel (for example a webhook) in the building's "
            "channels.yaml and the rules engine can send alerts on it — no code change is needed.",
        ]
    return []


def compose_override(facts: Facts) -> str:
    """The answer to 'is there a manual override for ...?' and 'can it switch X off?'."""
    lines = [
        "**This service cannot operate equipment or override a mode.** It reads what the "
        "building measures and reports it; it does not send commands, so it can neither switch "
        "something on or off nor take manual control of it.",
        "",
        "- **Where an override belongs:** the building's control system, used by the facilities or "
        "estates team. The building-control connection that would let me act is not set up here.",
    ]
    if facts.measured:
        lines.append(
            f"- **What I can tell you:** the current reading or recent history of "
            f"{and_list(facts.measured, 5)}, so you can see the effect of a change someone else makes."
        )
    return "\n".join(lines)


def compose_task(facts: Facts) -> str:
    """The answer to 'can the building alert someone to a task?'."""
    lines = [
        "**Not on its own.** Alerts here are raised from measured quantities crossing a limit, not "
        "from tasks, and this service does not assign work or page a named person.",
        "",
        _watch_line(facts),
    ]
    if facts.record_labels:
        lines.append(
            f"- **Records it keeps:** {and_list(facts.record_labels, 4)}. I can read these when "
            "you ask, but no rule watches them, so a condition held only as a record (a fill level, "
            "a due date) does not trigger an alert by itself."
        )
    lines += [_rules_line(facts.rules), _delivery_line(facts)]
    lines += _admin_channel_hint(facts)
    return "\n".join(lines)


def compose_overview(facts: Facts) -> str:
    """The general answer when the quantity could not be identified: nothing is assumed either way."""
    lines = [
        "Here is what this building can do about alerts. Tell me the reading you have in mind "
        "and I will check it is measured.",
        "",
        _watch_line(facts),
        _rules_line(facts.rules),
        _delivery_line(facts),
        "- **What it does not do:** operate equipment (valves, setpoints) — that needs a "
        "building-control connection that is not set up here.",
    ]
    lines += _admin_channel_hint(facts)
    return "\n".join(lines)


def provision_records(record_labels: Sequence[str]) -> List[str]:
    """The building's own record classes that could hold a notification provision; [] when none."""
    out: List[str] = []
    for label in record_labels or ():
        low = str(label).lower()
        if any(word in low for word in _PROVISION_RECORD_WORDS) and label not in out:
            out.append(str(label))
    return out[:3]


def compose_provision(facts: Facts) -> str:
    """What notification provisions the building HAS -- from its records, never from a sensor count.

    The question asks which provisions exist, so the answer names the records that hold them and
    offers to read them. With no such record the lane declines, and it never claims a measured
    quantity: "this building does measure **empty space**" was both invented and off the subject.
    """
    name = facts.building or "this building"
    held = provision_records(facts.record_labels)
    if held:
        return (
            f"**{name} records its notification and emergency provisions, and I can read them.** "
            f"They are kept in the {and_list(held)} records — which cover the alerting "
            "arrangements in place and who assists.\n\n"
            f"Ask me for the {held[0].lower()} records and I will list what is recorded, "
            "including anything marked unverified.\n\n"
            "Separately, I can raise an alert myself only from a measured quantity crossing a "
            f"limit: {_delivery_line(facts)[len('- **Delivery:** '):]}"
        )
    return (
        f"**I can't tell you which notification provisions {name} has.** They would be kept as "
        "records of the emergency or evacuation arrangements, and I found none I can read.\n\n"
        "What I can do is raise an alert from a measured quantity crossing a limit, which is a "
        "different thing from the provisions you asked about."
    )


def compose(kind: str, facts: Facts) -> str:
    """The answer for ``kind``; the quantity-identified answers live with the node."""
    if kind == KIND_PROVISION:
        return compose_provision(facts)
    if kind == KIND_OVERRIDE:
        return compose_override(facts)
    if kind == KIND_TASK:
        return compose_task(facts)
    return compose_overview(facts)


async def record_labels(timeout_s: float = 5.0) -> List[str]:
    """Labels of the record classes the building holds, most numerous first; [] when unreadable."""
    try:
        from orchestrator.services.record_registry import record_classes

        records = await asyncio.wait_for(record_classes(), timeout=timeout_s)
        return [str(r.label) for r in sorted(records, key=lambda r: -r.instances) if r.label]
    except Exception as exc:  # a slow or absent registry means the line is left out, not guessed
        logger.debug(f"[automation_answer] record classes unavailable: {exc}")
        return []


async def compose_for(
    question: str,
    *,
    building_id: Optional[str],
    building: str,
    measured: Sequence[str],
    delivers: bool,
    for_admin: bool,
) -> str:
    """Read the rules and record classes live and compose the answer for this question's kind."""
    facts = Facts(
        building=building,
        measured=[str(m) for m in measured or []],
        record_labels=await record_labels(),
        rules=load_rule_views(building_id),
        delivers=bool(delivers),
        for_admin=bool(for_admin),
    )
    return compose(question_kind(question), facts)


def facts_from(
    *,
    building: str,
    measured: Sequence[str],
    records: Sequence[Any],
    rules: Sequence[RuleView],
    delivers: bool,
    for_admin: bool,
) -> Facts:
    """Build :class:`Facts` from what the node has already read."""
    return Facts(
        building=building,
        measured=[str(m) for m in measured or []],
        record_labels=[
            str(getattr(r, "label", r)) for r in records or [] if getattr(r, "label", r)
        ],
        rules=list(rules or []),
        delivers=bool(delivers),
        for_admin=bool(for_admin),
    )
