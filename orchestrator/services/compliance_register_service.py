# -*- coding: utf-8 -*-
"""
compliance_register_service.py — the S3 register QA lane (V5-T26).

Answers compliance-REGISTER questions ("what's overdue?", "when was the fire
alarm last tested?", "what's due this month?") via SPARQL over the
ComplianceCheck triples that generate_compliance_register.py (T05) or a real
building's admin upload put in the graph. Deterministic end to end: kind and
window by rules, dates from the graph, narration templated over those dates.

This lane is DISTINCT from the legacy 'compliance' intent, which checks SENSOR
READINGS against standards (ASHRAE bands) — that stays untouched.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

_ONTOSAGE = "http://ontosage.org/capabilities#"

#: item keyword -> label fragments used in the register (template T05 labels)
_ITEM_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("fire alarm", re.compile(r"\bfire alarm\b", re.IGNORECASE)),
    ("emergency lighting", re.compile(r"\bemergency light", re.IGNORECASE)),
    ("legionella", re.compile(r"\blegionella|outlet flush", re.IGNORECASE)),
    ("water temperature", re.compile(r"\bwater temperature\b", re.IGNORECASE)),
    ("fire door", re.compile(r"\bfire door", re.IGNORECASE)),
    ("fire extinguisher", re.compile(r"\bextinguisher", re.IGNORECASE)),
    ("lift", re.compile(r"\bloler\b|\blift (?:examination|inspection|thorough)", re.IGNORECASE)),
    ("PAT", re.compile(r"\bpat test|\bportable appliance", re.IGNORECASE)),
    ("F-gas", re.compile(r"\bf-?gas\b|\brefrigerant leak", re.IGNORECASE)),
    ("fire risk assessment", re.compile(r"\brisk assessment", re.IGNORECASE)),
]

_FMT = "%Y-%m-%dT%H:%M:%S"


def classify_register_question(question: str) -> str:
    q = (question or "").lower()
    if re.search(r"\boverdue|past due|missed|late\b", q):
        return "overdue_list"
    if re.search(
        r"\bwhen (was|did)\b.*\blast\b|\blast (tested|serviced|inspected|checked|done|flushed|examined)\b|\bhistory\b",
        q,
    ):
        return "last_done"
    if re.search(r"\bdue\b|\bcoming up\b|\bupcoming\b|\bcalendar\b", q):
        return "due_soon"
    # A QUESTION THIS CANNOT PLACE IS NOT AN OVERDUE QUESTION. The default used to be
    # "overdue_list", so anything the register lane claimed came back as a due-date verdict:
    # measured live on the held-out run, "What minimum evidence is still missing before the
    # responsible person can make the planned start-or-continue decision?" was answered
    # "**Nothing is overdue** — every open compliance item is within its due date", and a
    # lone-worker question got the identical sentence. One canned answer for two questions that
    # asked different things is worse than saying which of them this register can answer.
    return ""


def match_item(question: str) -> Optional[str]:
    for name, pat in _ITEM_PATTERNS:
        if pat.search(question or ""):
            return name
    return None


def _horizon_days(question: str) -> int:
    q = (question or "").lower()
    m = re.search(r"next\s+(\d{1,3})\s+days?", q)
    if m:
        return max(1, min(365, int(m.group(1))))
    if "this week" in q or "next week" in q:
        return 7
    if "this month" in q or "next month" in q:
        return 31
    if "quarter" in q:
        return 92
    return 30


class ComplianceRegisterService:
    """sparql_exec is injected (same callable the deliberate node uses)."""

    def __init__(self, sparql_exec: Callable, namespace: str):
        self._sparql = sparql_exec
        self._ns = namespace

    async def _select(self, query: str) -> List[Dict[str, str]]:
        res = await self._sparql(query)
        out = []
        for b in res.get("results", {}).get("bindings", []):
            out.append({k: v.get("value", "") for k, v in b.items()})
        return out

    @staticmethod
    def _fmt(dt_str: str) -> str:
        try:
            return datetime.strptime(dt_str[:19], _FMT).strftime("%d %b %Y")
        except ValueError:
            return dt_str[:10]

    def _base_where(self, extra: str = "") -> str:
        return (
            f"  ?c a <{_ONTOSAGE}ComplianceCheck> ; <{_ONTOSAGE}dueDate> ?due . \n"
            f"  OPTIONAL {{ ?c <http://www.w3.org/2000/01/rdf-schema#label> ?label }}\n"
            f"  OPTIONAL {{ ?c <{_ONTOSAGE}responsibleRole> ?role }}\n"
            f'  FILTER(STRSTARTS(STR(?c), "{self._ns}"))\n' + extra
        )

    async def answer(
        self, question: str, now: Optional[datetime] = None, for_admin: bool = False
    ) -> Dict[str, Any]:
        """Answer a register question. ``for_admin`` adds how to load a missing register.

        Every reader is told the register is not held; only an administrator is told how
        to load one, because a supervisor cannot and the instruction reads as a fault.
        """
        now = now or datetime.utcnow()
        kind = classify_register_question(question)
        if not kind:
            return await self._unplaced(question)
        try:
            handler = {
                "overdue_list": self._overdue,
                "due_soon": self._due_soon,
                "last_done": self._last_done,
            }[kind]
            result = await handler(question, now)
            if result.get("register_empty"):
                text = (
                    "**No compliance register is held for this building**, so I can't say "
                    "which inspections are overdue, due soon or were last done — and I won't "
                    "guess."
                )
                if for_admin:
                    text += (
                        " Upload the register as ComplianceCheck triples (admin portal → "
                        "Ontology → upload) and these questions unlock."
                    )
                return {"success": False, "kind": kind, "formatted_response": text}
            return result
        except Exception as exc:
            logger.error(f"[register] {kind} failed: {exc}", exc_info=True)
            return {
                "success": False,
                "kind": kind,
                "formatted_response": "I couldn't read the compliance register just now — please try again.",
            }

    async def _unplaced(self, question: str) -> Dict[str, Any]:
        """Say what was searched and what it holds, for a question this register cannot place.

        The alternative, and what happened before, is a due-date verdict answering a question
        nobody asked. Naming the register and its fields lets the reader see the scope of the
        search and take the question elsewhere.
        """
        size = await self._register_size()
        if not size:
            return {
                "success": False,
                "kind": "unplaced",
                "formatted_response": (
                    "**No compliance register is held for this building**, so I can't answer "
                    "this from one — and I won't guess."
                ),
            }
        return {
            "success": True,
            "kind": "unplaced",
            "count": size,
            "source": "compliance register (graph)",
            "formatted_response": (
                f"I searched the building's **compliance register** ({size} checks). It records, "
                "for each check, what it is, when it is next due, when it was last completed and "
                "which role is responsible — and nothing else, so it cannot answer what this "
                "question asks. Tell me which of those you need, or which register or system "
                "holds the rest, and I will read it."
            ),
        }

    async def _register_size(self) -> int:
        rows = await self._select("SELECT (COUNT(?c) AS ?n) WHERE {\n" + self._base_where() + "}")
        try:
            return int(rows[0].get("n", "0")) if rows else 0
        except ValueError:
            return 0

    async def _overdue(self, question: str, now: datetime) -> Dict[str, Any]:
        q = (
            "SELECT ?c ?label ?due ?role WHERE {\n"
            + self._base_where(
                f'  ?c <{_ONTOSAGE}recordStatus> "open" .\n'
                f"  FILTER NOT EXISTS {{ ?c <{_ONTOSAGE}completedDate> ?any }}\n"
                f'  FILTER (?due < "{now.strftime(_FMT)}"^^<http://www.w3.org/2001/XMLSchema#dateTime>)\n'
            )
            + "} ORDER BY ?due"
        )
        rows = await self._select(q)
        size = await self._register_size()
        if not rows and size == 0:
            return {"register_empty": True}
        items = [
            f"- **{r.get('label') or r['c'].rsplit('#', 1)[-1]}** — due {self._fmt(r['due'])}"
            + (f" (responsible: {r['role']})" if r.get("role") else "")
            for r in rows[:10]
        ]
        # THE SENTENCE NAMES WHAT IT SEARCHED. "Nothing is overdue" on its own was returned to a
        # question about lone-worker check-ins, which this register does not record at all, and
        # read as a verdict on them; saying which register was read, and how big it is, keeps the
        # claim inside its own scope.
        text = (
            f"**{len(rows)} compliance item(s) overdue**:\n" + "\n".join(items)
            if rows
            else (
                f"**Nothing is overdue in the building's compliance register** "
                f"({size} checks): every open item in it is within its "
                "due date. That register covers compliance checks only."
            )
        )
        return {
            "success": True,
            "kind": "overdue_list",
            "count": len(rows),
            # the register's own size is quoted in the sentence, so the numeric guard must find
            # it here: without this field the no-overdue sentence carried an "unbacked" number
            # and was replaced by a system message
            "register_size": size,
            # numeric-guard provenance (V5-T29): every narrated date is a field
            "items": [
                {"label": r.get("label", ""), "due": self._fmt(r["due"]), "role": r.get("role", "")}
                for r in rows[:10]
            ],
            "source": "compliance register (graph)",
            "formatted_response": text,
        }

    async def _due_soon(self, question: str, now: datetime) -> Dict[str, Any]:
        days = _horizon_days(question)
        until = now + timedelta(days=days)
        q = (
            "SELECT ?c ?label ?due ?role WHERE {\n"
            + self._base_where(
                f'  ?c <{_ONTOSAGE}recordStatus> "open" .\n'
                f"  FILTER NOT EXISTS {{ ?c <{_ONTOSAGE}completedDate> ?any }}\n"
                f'  FILTER (?due >= "{now.strftime(_FMT)}"^^<http://www.w3.org/2001/XMLSchema#dateTime>)\n'
                f'  FILTER (?due <= "{until.strftime(_FMT)}"^^<http://www.w3.org/2001/XMLSchema#dateTime>)\n'
            )
            + "} ORDER BY ?due"
        )
        rows = await self._select(q)
        if not rows and await self._register_size() == 0:
            return {"register_empty": True}
        items = [
            f"- **{r.get('label') or r['c'].rsplit('#', 1)[-1]}** — due {self._fmt(r['due'])}"
            for r in rows[:10]
        ]
        text = (
            f"**{len(rows)} compliance item(s) due in the next {days} days**:\n" + "\n".join(items)
            if rows
            else f"**Nothing falls due in the next {days} days.**"
        )
        return {
            "success": True,
            "kind": "due_soon",
            "count": len(rows),
            "horizon_days": days,
            "items": [{"label": r.get("label", ""), "due": self._fmt(r["due"])} for r in rows[:10]],
            "source": "compliance register (graph)",
            "formatted_response": text,
        }

    async def _last_done(self, question: str, now: datetime) -> Dict[str, Any]:
        item = match_item(question)
        if not item:
            return {
                "success": False,
                "kind": "last_done",
                "formatted_response": (
                    "Which compliance item do you mean? I track: "
                    + ", ".join(name for name, _ in _ITEM_PATTERNS)
                    + "."
                ),
            }
        q = (
            "SELECT ?label ?done WHERE {\n"
            + self._base_where(f"  ?c <{_ONTOSAGE}completedDate> ?done .\n")
            + f'  FILTER(CONTAINS(LCASE(STR(?label)), "{item.lower()}"))\n'
            + "} ORDER BY DESC(?done) LIMIT 1"
        )
        rows = await self._select(q)
        if not rows:
            if await self._register_size() == 0:
                return {"register_empty": True}
            return {
                "success": True,
                "kind": "last_done",
                "item": item,
                "found": False,
                "formatted_response": (
                    f"**No completed '{item}' check is on record** — the register has no "
                    "completion for that item yet."
                ),
            }
        done = self._fmt(rows[0]["done"])
        # next due for the same item (open check)
        q2 = (
            "SELECT ?due WHERE {\n"
            + self._base_where(
                f'  ?c <{_ONTOSAGE}recordStatus> "open" .\n'
                f"  FILTER NOT EXISTS {{ ?c <{_ONTOSAGE}completedDate> ?x }}\n"
            )
            + f'  FILTER(CONTAINS(LCASE(STR(?label)), "{item.lower()}"))\n'
            + "} ORDER BY ?due LIMIT 1"
        )
        nxt = await self._select(q2)
        next_due = self._fmt(nxt[0]["due"]) if nxt else None
        next_txt = f" Next one due **{next_due}**." if next_due else ""
        return {
            "success": True,
            "kind": "last_done",
            "item": item,
            "found": True,
            "last_done": done,
            "next_due": next_due,
            "source": "compliance register (graph)",
            "formatted_response": f"**The {item} check was last completed on {done}.**{next_txt}",
        }
