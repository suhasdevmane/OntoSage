# -*- coding: utf-8 -*-
"""What has been REPORTED in a window: "has anything been reported broken this week?".

The failure this prevents (BUG-828, tail B row B23, 2026-09-18). The question was answered by
the capability lane from two uploaded registers -- "the projector in Room 2.01 failed during
maintenance on 2026-09-02" -- which is not this week and is not a report; the second run said
"documents do not answer this". The building has a store for exactly this: `user_reports`,
where every fault, complaint, safety concern and suggestion filed through the assistant lands
with a category, a status, a priority and a place.

Deterministic, no LLM: the question shape, the window and the aggregation are rules, and every
number the prose states is carried in the payload so the numeric guard can trace it.

Privacy, decided here and not left to a caller:

* the SELECT names its columns -- reporter, persona, session, assignee, free-text description
  and admin notes are never read, so nothing downstream can leak them;
* only roles holding ``report:read`` see the breakdown; every other role gets a plain decline
  that points at the one thing it may see (its own reports).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: The permission that lets a role see reports filed by OTHER people, in aggregate.
REPORT_PERMISSION = "report:read"

#: Default window when the question names none. A week is what "lately" means to a person
#: asking whether anything has gone wrong; a day would answer "nothing" for most of a weekend.
DEFAULT_WINDOW_DAYS = 7

#: Rows read from the store for one answer. The count in the text is of THESE rows, so hitting
#: the ceiling is stated ("at least"), never hidden.
ROW_CEILING = 500

#: Reports listed by name in the answer; the rest are counted.
LISTED = 8

_FILED = r"(?:reported|filed|logged|raised|submitted|lodged|flagged)"
_REPORTABLE = (
    r"(?:faults?|issues?|problems?|defects?|breakdowns?|complaints?|incidents?|near[- ]?misses?|"
    r"hazards?|reports?)"
)
_PEOPLE = r"(?:people|users|staff|occupants|anyone|someone|everyone|tenants|students|visitors)"

#: A question about the reports themselves, not about a thing that may be broken. Deliberately
#: needs a REPORTING word: "is the lift broken?" is asset state, "how do I report a fault?" is a
#: procedure, and "the toilet is leaking" is a report being made -- none of them match.
REPORT_ACTIVITY_RE = re.compile(
    rf"\b(?:anything|something)\b[^.?!]{{0,30}}\b{_FILED}\b"
    # "what has been reported", and "which faults have been reported" -- the subject must be the
    # thing REPORTED: "which accountability sources have reported" is a roll call, not a fault list
    rf"|\bwhat\s+(?:has|have|had|was|were|is|are)\s+(?:been\s+)?{_FILED}\b"
    rf"|\b(?:what|which)\s+(?:\w+\s+){{0,3}}?{_REPORTABLE}\b[^.?!]{{0,30}}"
    rf"\b(?:has|have|had|was|were|is|are)\s+(?:been\s+)?{_FILED}\b"
    rf"|\b(?:what|which)\b[^.?!]{{0,40}}\b(?:did|do|have)\s+{_PEOPLE}\s+(?:report|file|log|raise|submit)\w*"
    rf"|\bany\s+(?:new\s+|recent\s+|other\s+)?{_REPORTABLE}\b[^.?!]{{0,40}}\b{_FILED}\b"
    rf"|\bhow\s+many\b[^.?!]{{0,30}}\b{_REPORTABLE}\b[^.?!]{{0,40}}"
    rf"\b(?:{_FILED}|received|open|outstanding|unresolved|this|last|today|yesterday|so\s+far)\b"
    rf"|\b(?:were|are)\s+there\s+(?:any\s+)?(?:new\s+)?{_REPORTABLE}\b[^.?!]{{0,30}}"
    rf"\b(?:{_FILED}|this|last|today|yesterday|recently)\b",
    re.IGNORECASE,
)

#: A statement is somebody making a report, and belongs to intake. The shape test above is
#: loose enough ("something is broken and I already reported it") to need this second half.
_QUESTION_LEAD_RE = re.compile(
    r"^\s*(?:has|have|had|was|were|is|are|any|anything|what|which|how\s+many|"
    r"show|list|give|tell|did|do|does|can\s+you|were\s+there|are\s+there)\b",
    re.IGNORECASE,
)


def is_report_activity_question(question: str) -> bool:
    """True when the question asks what people have REPORTED (a query over the report store)."""
    q = (question or "").strip()
    if not q or not REPORT_ACTIVITY_RE.search(q):
        return False
    return bool(_QUESTION_LEAD_RE.search(q) or q.endswith("?"))


# ── category ────────────────────────────────────────────────────────────────

_CATEGORY_WORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("safety", ("safety", "hazard", "hazards", "incident", "incidents", "near miss", "unsafe")),
    ("complaint", ("complaint", "complaints", "complained")),
    ("feedback", ("feedback",)),
    ("suggestion", ("suggestion", "suggestions")),
    (
        "maintenance",
        (
            "broken",
            "fault",
            "faults",
            "defect",
            "defects",
            "breakdown",
            "breakdowns",
            "repair",
            "repairs",
            "not working",
            "out of order",
            "maintenance",
        ),
    ),
)


def category_asked(question: str) -> str:
    """The report category a question names, or "" when it asks about every kind."""
    low = (question or "").lower()
    for name, words in _CATEGORY_WORDS:
        if any(re.search(rf"\b{re.escape(w)}\b", low) for w in words):
            return name
    return ""


# ── window ──────────────────────────────────────────────────────────────────

_MONTH_RE = re.compile(r"\b(this|last|previous)\s+month\b", re.IGNORECASE)
_QUARTER_YEAR_RE = re.compile(r"\b(this|last|previous)\s+(quarter|year)\b", re.IGNORECASE)
_PAST_N_RE = re.compile(
    r"\b(?:past|last|previous)\s+(\d{1,3})\s+(day|days|week|weeks)\b", re.IGNORECASE
)
_NAMED_WINDOW_RE = re.compile(
    r"\b(?:today|yesterday|tonight|this\s+(?:morning|afternoon|evening|week)|last\s+week)\b",
    re.IGNORECASE,
)


def report_window(question: str, now_local: datetime) -> Tuple[datetime, datetime, str]:
    """(start, end, label) on the BUILDING's clock for the period a question names.

    Calendar words reuse the events lane's own parser, so "yesterday" and "this week" mean the
    same thing in both lanes. What that parser lacks -- months and "past N days" -- is added
    here, and a question naming no period at all gets a rolling week rather than "today so far".
    """
    from orchestrator.services.event_query_service import parse_window

    q = (question or "").lower()
    day0 = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    m = _MONTH_RE.search(q)
    if m:
        first = day0.replace(day=1)
        if m.group(1).lower() == "this":
            return first, now_local, "this month"
        prev_end = first
        prev_start = (first - timedelta(days=1)).replace(day=1)
        return prev_start, prev_end, "last month"
    qy = _QUARTER_YEAR_RE.search(q)
    if qy:
        current = qy.group(1).lower() == "this"
        if qy.group(2).lower() == "year":
            start = day0.replace(month=1, day=1)
            if current:
                return start, now_local, "this year"
            return start.replace(year=start.year - 1), start, "last year"
        first_month = 3 * ((day0.month - 1) // 3) + 1
        start = day0.replace(month=first_month, day=1)
        if current:
            return start, now_local, "this quarter"
        prev_end = start
        pm = first_month - 3
        prev_start = start.replace(year=start.year - 1, month=pm + 12) if pm < 1 else start.replace(month=pm)
        return prev_start, prev_end, "last quarter"
    n = _PAST_N_RE.search(q)
    if n:
        amount = int(n.group(1)) * (7 if n.group(2).lower().startswith("week") else 1)
        return now_local - timedelta(days=amount), now_local, f"in the past {amount} days"
    if _NAMED_WINDOW_RE.search(q):
        start, end, label = parse_window(question, now_local)
        # "today" and "this week" end at the end of their calendar span; nothing can have been
        # reported in the future, so cap at now and keep the label the reader used.
        return start, min(end, now_local), label
    return (
        now_local - timedelta(days=DEFAULT_WINDOW_DAYS),
        now_local,
        f"in the last {DEFAULT_WINDOW_DAYS} days",
    )


# ── access ──────────────────────────────────────────────────────────────────


def may_view_reports(role: Optional[str]) -> bool:
    """True when ``role`` holds ``report:read``. Unknown or missing roles fail CLOSED."""
    if not isinstance(role, str) or not role.strip():
        return False
    try:
        from orchestrator.middleware.rbac import ROLE_PERMISSIONS
    except Exception:  # pragma: no cover - the catalogue is a plain module
        return False
    return REPORT_PERMISSION in ROLE_PERMISSIONS.get(role.strip().lower(), set())


def not_permitted_answer() -> Dict[str, Any]:
    """The decline for a role that may not see other people's reports."""
    return {
        "success": True,
        "kind": "report_activity_not_permitted",
        "formatted_response": (
            "**Fault reports filed by other people are visible to facility staff only.** "
            "I can show you the reports you filed yourself: ask *\"show my reports\"*."
        ),
        "source": "user_reports",
    }


# ── the store ───────────────────────────────────────────────────────────────

#: Named columns only. `reporter_id`, `persona`, `session_id`, `assignee`, `description`,
#: `title` and `admin_notes` are deliberately absent: the free text may carry a name or a
#: personal detail, and an aggregate answer has no use for any of them.
_SELECT_SQL = (
    "SELECT category, status, priority, "
    "       COALESCE(NULLIF(location, ''), space_iri) AS place, "
    "       NULLIF(device, '') AS device, created_at "
    "  FROM user_reports "
    " WHERE building_id = $1 AND created_at >= $2 AND created_at < $3"
)


def _utc(value: datetime) -> datetime:
    """A tz-aware UTC datetime; a naive one is taken to be the store's UTC clock."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


#: A place a question names. "reported broken on floor 3" must not answer with the whole building's
#: reports: the answer would be about a different subject than the one asked.
_FLOOR_RE = re.compile(
    r"\b(?:floor|level)\s*(\d{1,2})\b|\b(\d{1,2})(?:st|nd|rd|th)\s+floor\b", re.IGNORECASE
)
_ROOM_RE = re.compile(r"\b(?:room|rm|zone)\s*([A-Za-z]?\d{1,2}\.\d{1,3})\b", re.IGNORECASE)


def place_scope(question: str) -> Tuple[str, str]:
    """(POSIX regex over a report's place, how to say it); ("", "") when no place is named.

    A room id is matched as written ("2.01"); a floor is matched by its own words or by the
    room-number convention of "N.xx". Both read the `location` text and the space IRI, because a
    report may carry either.
    """
    q = question or ""
    room = _ROOM_RE.search(q)
    if room:
        ident = re.escape(room.group(1))
        return rf"(^|[^0-9.]){ident}([^0-9]|$)", f"in Room {room.group(1)}"
    floor = _FLOOR_RE.search(q)
    if floor:
        n = floor.group(1) or floor.group(2)
        return (
            rf"(floor|level)\s*{n}([^0-9]|$)|(^|[^0-9.]){n}\.[0-9]{{1,3}}([^0-9]|$)",
            f"on floor {n}",
        )
    return "", ""


async def fetch_reports(
    postgres: Any,
    building_id: str,
    start_utc: datetime,
    end_utc: datetime,
    category: str = "",
    place_regex: str = "",
) -> Optional[List[Dict[str, Any]]]:
    """Reports created in [start, end), newest first; None when the store cannot be read.

    None is not "no reports": the caller must say the store is unavailable rather than report a
    quiet week that nobody measured.
    """
    if postgres is None or getattr(postgres, "pool", None) is None:
        return None
    args: List[Any] = [building_id, _utc(start_utc), _utc(end_utc)]
    sql = _SELECT_SQL
    if category:
        args.append(category)
        sql += f" AND category = ${len(args)}"
    if place_regex:
        args.append(place_regex)
        sql += f" AND (COALESCE(location, '') ~* ${len(args)} OR COALESCE(space_iri, '') ~* ${len(args)})"
    sql += f" ORDER BY created_at DESC LIMIT {int(ROW_CEILING)}"
    try:
        async with postgres.pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning(f"[report_activity] read failed: {exc}")
        return None


# ── the answer ──────────────────────────────────────────────────────────────

_CLOSED_STATUSES = frozenset({"RESOLVED", "CLOSED", "REJECTED"})
_CATEGORY_LABEL = {
    "maintenance": "fault",
    "complaint": "complaint",
    "safety": "safety",
    "feedback": "feedback",
    "suggestion": "suggestion",
    "other": "other",
}


def _plural(n: int, one: str, many: Optional[str] = None) -> str:
    return one if n == 1 else (many or one + "s")


def _place(raw: Any) -> str:
    """A place as a person writes it; the IRI a report was bound to is reduced to its label."""
    from orchestrator.services.event_query_service import _place_label

    text = str(raw or "").strip()
    return _place_label(text) if text else "no location given"


def _short(text: Any, limit: int = 40) -> str:
    """A stored free-text field, single-line and bounded. Never a place for markup."""
    flat = re.sub(r"[\r\n\t|`*_<>]+", " ", str(text or ""))
    flat = " ".join(flat.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _stamp(value: Any, tz_name: Optional[str]) -> str:
    """The day a report was filed, on the building's calendar."""
    if not isinstance(value, datetime):
        return str(value or "")[:10]
    from orchestrator.services.requested_interval import to_local

    return to_local(_utc(value).replace(tzinfo=None), tz_name).strftime("%d %b")


def summarise_reports(
    rows: Sequence[Mapping[str, Any]],
    *,
    label: str,
    category: str = "",
    tz_name: Optional[str] = None,
) -> Dict[str, Any]:
    """The payload and prose for a set of reports. Pure: rows in, answer out."""
    total = len(rows)
    at_least = "at least " if total >= ROW_CEILING else ""
    scope = f"{_CATEGORY_LABEL.get(category, category)} " if category else ""

    if total == 0:
        text = (
            f"**No {scope}reports were filed {label}.** That counts what people reported through "
            "this assistant; a problem nobody reported will not appear, and work orders raised "
            "another way are in the work-order records (ask *\"how many open work orders are "
            "there?\"*)."
        )
        return {
            "success": True,
            "kind": "report_activity",
            "window": label,
            "category": category,
            "count": 0,
            "open": 0,
            "formatted_response": text,
            "source": "user_reports",
        }

    open_n = sum(1 for r in rows if str(r.get("status") or "").upper() not in _CLOSED_STATUSES)
    by_category: Dict[str, int] = {}
    for r in rows:
        key = str(r.get("category") or "other").lower()
        by_category[key] = by_category.get(key, 0) + 1
    placed = sum(1 for r in rows if str(r.get("place") or "").strip())

    lines: List[str] = []
    for r in list(rows)[:LISTED]:
        bits = [_stamp(r.get("created_at"), tz_name), _place(r.get("place"))]
        if r.get("device"):
            bits.append(_short(r.get("device")))
        bits.append(str(r.get("category") or "other").lower())
        priority = str(r.get("priority") or "").upper()
        if priority in {"HIGH", "URGENT"}:
            bits.append(priority.lower() + " priority")
        bits.append(str(r.get("status") or "").replace("_", " ").lower())
        lines.append("- " + " · ".join(b for b in bits if b))

    head = (
        f"**{at_least}{total} {scope}{_plural(total, 'report')} filed {label}**, "
        f"{open_n} still open"
    )
    parts = [head + (":" if lines else ".")]
    if len(by_category) > 1:
        ranked = sorted(by_category.items(), key=lambda kv: -kv[1])
        mix = ", ".join(f"{n} {_CATEGORY_LABEL.get(k, k)}" for k, n in ranked)
        parts.append(f"_By kind: {mix}._")
    parts.extend(lines)
    more = total - len(lines)
    if more > 0:
        parts.append(f"…and {more} more, older than these.")
    without_location = total - placed
    foot = "_Counted from reports people filed through this assistant. Reporter identities are "
    foot += "never shown"
    if without_location:
        foot += f"; {without_location} of these gave no location"
    parts.append(foot + "._")

    return {
        "success": True,
        "kind": "report_activity",
        "window": label,
        "category": category,
        "count": total,
        "open": open_n,
        "by_category": by_category,
        "with_location": placed,
        "without_location": without_location,
        "more": max(more, 0),
        "listed": len(lines),
        "reports": lines,
        "formatted_response": "\n".join(parts),
        "source": "user_reports",
    }


def unavailable_answer() -> Dict[str, Any]:
    """The answer when the report store could not be read (never "nothing was reported")."""
    return {
        "success": False,
        "kind": "report_activity",
        "formatted_response": (
            "I couldn't read the report records just now, so I can't say whether anything was "
            "reported — please try again in a moment."
        ),
        "source": "user_reports",
    }


async def answer_report_activity(
    question: str,
    *,
    building_id: str,
    now_utc: datetime,
    tz_name: Optional[str],
    reader_role: Optional[str],
    postgres: Any = None,
) -> Dict[str, Any]:
    """Answer a "what has been reported" question from the report store, for a permitted role."""
    if not may_view_reports(reader_role):
        return not_permitted_answer()
    from orchestrator.services.requested_interval import to_local, to_store

    local_now = to_local(now_utc, tz_name)
    start_l, end_l, label = report_window(question, local_now)
    category = category_asked(question)
    place_regex, place_phrase = place_scope(question)
    if place_phrase:
        label = f"{label} {place_phrase}"  # "this week on floor 3": the subject stays what was asked
    if postgres is None:
        from orchestrator.services.report_intake_service import get_report_intake_service

        postgres = get_report_intake_service().postgres
    rows = await fetch_reports(
        postgres,
        building_id,
        to_store(start_l, tz_name),
        to_store(end_l, tz_name),
        category,
        place_regex,
    )
    if rows is None:
        return unavailable_answer()
    return summarise_reports(rows, label=label, category=category, tz_name=tz_name)
