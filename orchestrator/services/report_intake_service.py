"""
Report Intake Service — Phase 19.

Unified intake for every kind of user-submitted issue: maintenance faults,
complaints, feedback, safety concerns, and suggestions.  All land in the single
`user_reports` Postgres table (viewable + triageable in pgAdmin on port 5050).

Design goals:
  * ONE table, ONE acknowledgment flow, ONE status lifecycle for every category
  * Persona-stamped — captures the blended Phase-14A persona of the reporter
  * Auto-prioritised — safety/urgent keywords escalate priority deterministically
  * Honest acknowledgments — the user always gets a report ID and a clear
    "an administrator will review this" message; never a silent drop
  * Admin-friendly — status lifecycle maps cleanly onto pgAdmin column edits

Status lifecycle:
    OPEN → ACKNOWLEDGED → IN_PROGRESS → RESOLVED → CLOSED        (+ REJECTED)

The service is pure data + logic; the workflow node owns conversation flow and
the FastAPI admin endpoints own HTTP.  Both call into this one service so the
behaviour is identical whether a report is created via chat or inspected via API.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)


# ── Category taxonomy ──────────────────────────────────────────────────────────
# Maps the dialogue agent's intent label → a report category.  Adding a new
# report-style intent only needs an entry here + the intent's `node_method`
# pointing at `_report_intake_node`.
INTENT_TO_CATEGORY: Dict[str, str] = {
    "maintenance": "maintenance",
    "complaint": "complaint",
    "feedback": "feedback",
    "safety_report": "safety",
    "suggestion": "suggestion",
}

VALID_CATEGORIES = frozenset(
    {"maintenance", "complaint", "feedback", "safety", "suggestion", "other"}
)

# Status lifecycle — ordered; used for validating admin status changes.
VALID_STATUSES = ("OPEN", "ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "CLOSED", "REJECTED")
VALID_PRIORITIES = ("LOW", "NORMAL", "HIGH", "URGENT")

# ── Priority derivation keyword sets ───────────────────────────────────────────
# URGENT — life-safety / property-damage signals; escalate regardless of category.
_URGENT_KW = frozenset(
    {
        "fire",
        "smoke",
        "gas leak",
        "gas smell",
        "flood",
        "flooding",
        "electrical",
        "sparks",
        "exposed wire",
        "trapped",
        "stuck in",
        "injury",
        "injured",
        "hurt",
        "collapse",
        "burst",
        "carbon monoxide",
        "co alarm",
        "evacuat",
        "emergency",
        "danger",
        "hazard",
        "water everywhere",
    }
)
# HIGH — broken / non-functional infrastructure that disrupts use.
_HIGH_KW = frozenset(
    {
        "broken",
        "not working",
        "doesn't work",
        "won't turn",
        "no power",
        "no heating",
        "no cooling",
        "no water",
        "leak",
        "leaking",
        "stuck",
        "blocked",
        "overflowing",
        "very cold",
        "very hot",
        "freezing",
        "boiling",
        "won't open",
        "won't close",
        "out of order",
    }
)


class ReportIntakeService:
    """CRUD-lite + triage logic over the `user_reports` table."""

    def __init__(self, postgres_manager=None):
        self.postgres = postgres_manager
        self._report_re = re.compile(r"\bREP[- ]?[A-Z0-9]{6}\b", re.IGNORECASE)

    # ── Public: create ─────────────────────────────────────────────────────────

    async def create_report(
        self,
        *,
        description: str,
        building_id: str,
        category: str = "maintenance",
        reporter_id: Optional[str] = None,
        persona: Optional[str] = None,
        location: Optional[str] = None,
        device: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert a new report; return {success, report_id, category, priority, message}."""
        if not self.postgres or getattr(self.postgres, "pool", None) is None:
            return {
                "success": False,
                "message": (
                    "The reporting service is temporarily unavailable. "
                    "Please contact facilities directly or try again shortly."
                ),
            }

        # V5-T40 — redact identifying carriers BEFORE anything is derived or
        # stored: the database never holds emails/phones/typed names. The
        # reporter's account id stays on the row (authentication, not PII).
        from orchestrator.services.pii_redaction import redact_pii

        description, _pii = redact_pii(description)
        if location:
            location, _pii_loc = redact_pii(location)
            for k, v in _pii_loc.items():
                _pii[k] = _pii.get(k, 0) + v
        if _pii:
            logger.info(f"[report_intake] PII redacted at write time: {_pii}")

        category = category if category in VALID_CATEGORIES else "other"
        # V6-T23: resolve the space ONCE, here, against the active building's graph. Doing it
        # at read time with an LLM would be unqueryable and would bind the same report
        # differently on different days; an unresolvable name stays NULL rather than guessed.
        space_iri = await self._resolve_space(f"{location or ''} {description}")
        priority = self._derive_priority(description, category)
        title = self._derive_title(description)
        report_id = self._new_report_id()

        try:
            async with self.postgres.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO user_reports
                        (id, building_id, category, priority, status, title,
                         description, location, device, reporter_id, persona,
                         session_id, space_iri, observed_at)
                    VALUES ($1,$2,$3,$4,'OPEN',$5,$6,$7,$8,$9,$10,$11,$12,NOW())
                    """,
                    report_id,
                    building_id,
                    category,
                    priority,
                    title,
                    description,
                    location,
                    device,
                    reporter_id,
                    persona,
                    session_id,
                    space_iri,
                )
            logger.info(
                f"[report_intake] created {report_id} space={space_iri or '(unbound)'} "
                f"category={category} "
                f"priority={priority} persona={persona} reporter={reporter_id}"
            )
            return {
                "success": True,
                "report_id": report_id,
                "category": category,
                "priority": priority,
                "message": self._acknowledgment(report_id, category, priority, location, device),
            }
        except Exception as e:
            logger.error(f"[report_intake] create failed: {e}", exc_info=True)
            return {
                "success": False,
                "message": (
                    "I couldn't log your report just now. Please try again, or "
                    "contact facilities directly if it's urgent."
                ),
            }

    # ── Public: status lookup ──────────────────────────────────────────────────

    async def get_report_status(
        self, report_id: str, reporter_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Return the status of one report.  When reporter_id is given, scope to
        that user's own reports (so users can only see their own)."""
        if not self.postgres or getattr(self.postgres, "pool", None) is None:
            return {"success": False, "message": "Reporting service unavailable."}
        rid = self._normalise_id(report_id)
        try:
            async with self.postgres.pool.acquire() as conn:
                if reporter_id:
                    row = await conn.fetchrow(
                        "SELECT * FROM user_reports WHERE id=$1 AND reporter_id=$2",
                        rid,
                        reporter_id,
                    )
                else:
                    row = await conn.fetchrow("SELECT * FROM user_reports WHERE id=$1", rid)
            if not row:
                return {
                    "success": False,
                    "message": (
                        f"I couldn't find a report with ID **{rid}** under your "
                        "account. Double-check the ID (format REP-XXXXXX)."
                    ),
                }
            d = dict(row)
            return {"success": True, "report": d, "message": self._status_message(d)}
        except Exception as e:
            logger.error(f"[report_intake] status lookup failed: {e}", exc_info=True)
            return {"success": False, "message": "I couldn't retrieve that report's status."}

    # ── Public: list a user's own reports ──────────────────────────────────────

    async def list_user_reports(self, reporter_id: str, limit: int = 10) -> Dict[str, Any]:
        if not self.postgres or getattr(self.postgres, "pool", None) is None:
            return {"success": False, "message": "Reporting service unavailable.", "reports": []}
        try:
            async with self.postgres.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, category, priority, status, title, created_at
                    FROM user_reports WHERE reporter_id=$1
                    ORDER BY created_at DESC LIMIT $2
                    """,
                    reporter_id,
                    limit,
                )
            reports = [dict(r) for r in rows]
            return {"success": True, "reports": reports, "message": self._list_message(reports)}
        except Exception as e:
            logger.error(f"[report_intake] list failed: {e}", exc_info=True)
            return {"success": False, "message": "I couldn't list your reports.", "reports": []}

    # ── Public: admin list + status update (used by /admin/reports) ─────────────

    async def list_admin_reports(
        self,
        *,
        status: Optional[str] = None,
        category: Optional[str] = None,
        building_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List reports for admin triage with optional filters, URGENT first."""
        if not self.postgres or getattr(self.postgres, "pool", None) is None:
            return []
        clauses, params = [], []
        if status:
            params.append(status.upper())
            clauses.append(f"status = ${len(params)}")
        if category:
            params.append(category.lower())
            clauses.append(f"category = ${len(params)}")
        if building_id:
            params.append(building_id)
            clauses.append(f"building_id = ${len(params)}")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        sql = (
            "SELECT * FROM user_reports"
            + where
            + " ORDER BY CASE priority WHEN 'URGENT' THEN 0 WHEN 'HIGH' THEN 1 "
            "WHEN 'NORMAL' THEN 2 ELSE 3 END, created_at DESC "
            f"LIMIT ${len(params)}"
        )
        try:
            async with self.postgres.pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"[report_intake] admin list failed: {e}", exc_info=True)
            return []

    async def update_status(
        self,
        report_id: str,
        *,
        status: Optional[str] = None,
        assignee: Optional[str] = None,
        admin_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Admin status/assignee/notes update.  Sets resolved_at when RESOLVED."""
        if not self.postgres or getattr(self.postgres, "pool", None) is None:
            return {"success": False, "error": "Reporting service unavailable."}
        if status and status.upper() not in VALID_STATUSES:
            return {"success": False, "error": f"Invalid status. Use one of {VALID_STATUSES}."}

        sets, params = [], []
        if status:
            params.append(status.upper())
            sets.append(f"status = ${len(params)}")
            if status.upper() == "RESOLVED":
                sets.append("resolved_at = NOW()")
        if assignee is not None:
            params.append(assignee)
            sets.append(f"assignee = ${len(params)}")
        if admin_notes is not None:
            params.append(admin_notes)
            sets.append(f"admin_notes = ${len(params)}")
        if not sets:
            return {"success": False, "error": "Nothing to update."}
        sets.append("updated_at = NOW()")
        params.append(self._normalise_id(report_id))
        sql = f"UPDATE user_reports SET {', '.join(sets)} WHERE id = ${len(params)}"
        try:
            async with self.postgres.pool.acquire() as conn:
                result = await conn.execute(sql, *params)
            # asyncpg returns e.g. "UPDATE 1"
            if not result.endswith("1"):
                return {"success": False, "error": f"Report {report_id} not found."}
            logger.info(f"[report_intake] admin updated {report_id}: {sets}")
            return {"success": True, "report_id": self._normalise_id(report_id)}
        except Exception as e:
            logger.error(f"[report_intake] update failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # ── Action classification (create vs status vs list) ───────────────────────

    async def _resolve_space(self, text: str) -> Optional[str]:
        """The space IRI this report is about, or None (V6-T23).

        Goes through the SAME resolver the answering pipeline uses, so "does this building
        have a space called X" has one definition. Never raises and never guesses: a report
        naming a space the building does not have is stored unbound, because a fabricated
        location on a maintenance record is worse than a missing one.
        """
        try:
            from orchestrator.services.evidence.spatial_facts import (
                active_namespace,
                default_run_select,
                resolve_space_iri,
            )
            from orchestrator.services.referent_resolver import detect_referent

            token = detect_referent(text or "")
            if not token:
                return None
            ns = active_namespace()
            # The bare identifier is often ambiguous: "5.16" matches Room5.16 AND Zone_5.16,
            # and resolve_space_iri rightly refuses to pick one. The reporter usually said
            # which they meant ("the radiator in ROOM 5.16"), so the fuller phrase is tried
            # first and the bare token only as a fallback. Still no guessing — an ambiguous
            # phrase resolves to nothing and the report stays unbound.
            import re as _re

            m = _re.search(
                r"\b(room|zone|floor|level|space|lab|office)\s+" + _re.escape(token),
                text or "",
                _re.I,
            )
            for candidate in ([m.group(0)] if m else []) + [token]:
                iri = await resolve_space_iri(candidate, ns, default_run_select)
                if iri:
                    return iri
            return None
        except Exception as exc:
            logger.debug(f"[report_intake] space resolution skipped: {exc}")
            return None

    async def reports_for_space(
        self, space_iri: str, building_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Reports bound to one space — the queryable half of V6-T23.

        Human-reported evidence, labelled as such by the caller. It belongs to the INFERENCE
        tier in the precedence contract (T21): a person saying a room is cold is real evidence
        and is not a temperature.
        """
        if not self.postgres or getattr(self.postgres, "pool", None) is None or not space_iri:
            return []
        try:
            async with self.postgres.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, category, priority, status, title, description,
                           space_iri, observed_at, created_at
                      FROM user_reports
                     WHERE building_id = $1 AND space_iri = $2
                     ORDER BY created_at DESC
                     LIMIT $3
                    """,
                    building_id,
                    space_iri,
                    int(limit),
                )
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning(f"[report_intake] reports_for_space failed: {exc}")
            return []

    async def link_to_work_order(self, report_id: str, work_order_id: str) -> bool:
        """Record that a filed report became a work order (V6-T24).

        Explicit, because nothing else may create this link: two tickets in one room on one
        day are not necessarily one issue.
        """
        if not self.postgres or getattr(self.postgres, "pool", None) is None:
            return False
        try:
            async with self.postgres.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE user_reports SET work_order_id = $1, updated_at = NOW() "
                    "WHERE id = $2",
                    str(work_order_id),
                    self._normalise_id(report_id),
                )
            return True
        except Exception as exc:
            logger.warning(f"[report_intake] link_to_work_order failed: {exc}")
            return False

    async def tickets_from_reports(self, building_id: str, limit: int = 500) -> List[Any]:
        """Every report as a canonical Ticket, for the joined ticket view (V6-T24)."""
        if not self.postgres or getattr(self.postgres, "pool", None) is None:
            return []
        from orchestrator.services.tickets import ticket_from_report

        try:
            async with self.postgres.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, status, title, space_iri, created_at, work_order_id "
                    "FROM user_reports WHERE building_id = $1 "
                    "ORDER BY created_at DESC LIMIT $2",
                    building_id,
                    int(limit),
                )
            return [ticket_from_report(dict(r)) for r in rows]
        except Exception as exc:
            logger.warning(f"[report_intake] tickets_from_reports failed: {exc}")
            return []

    def classify_action(self, message: str) -> str:
        """Heuristic: is the user creating, checking, or listing reports?"""
        m = (message or "").lower()
        if self._report_re.search(message or ""):
            return "status"
        if any(
            k in m
            for k in (
                "status of",
                "check report",
                "check my report",
                "is rep",
                "what happened to my report",
                "any update on",
            )
        ):
            return "status"
        if any(
            k in m
            for k in (
                "my reports",
                "my tickets",
                "my complaints",
                "list report",
                "all my reports",
                "reports i",
                "reports i've",
            )
        ):
            return "list"
        return "create"

    def extract_report_id(self, message: str) -> Optional[str]:
        m = self._report_re.search(message or "")
        return self._normalise_id(m.group(0)) if m else None

    # ── Internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _new_report_id() -> str:
        return f"REP-{uuid.uuid4().hex[:6].upper()}"

    @staticmethod
    def _normalise_id(raw: str) -> str:
        """Normalise 'rep a1b2c3' / 'REPA1B2C3' / 'rep-a1b2c3' → 'REP-A1B2C3'."""
        s = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
        if s.startswith("REP") and len(s) >= 9:
            return f"REP-{s[3:9]}"
        return (raw or "").upper()

    @staticmethod
    def category_for_intent(intent: Optional[str]) -> str:
        return INTENT_TO_CATEGORY.get((intent or "").lower(), "other")

    def _derive_priority(self, description: str, category: str) -> str:
        d = (description or "").lower()
        if any(kw in d for kw in _URGENT_KW):
            return "URGENT"
        # Safety reports are HIGH by default even without urgent keywords.
        if category == "safety":
            return "HIGH"
        if any(kw in d for kw in _HIGH_KW):
            return "HIGH"
        # Feedback / suggestions are low-priority by nature.
        if category in ("feedback", "suggestion"):
            return "LOW"
        return "NORMAL"

    @staticmethod
    def _derive_title(description: str) -> str:
        """First sentence / first ~90 chars, cleaned — a scannable admin title."""
        text = " ".join((description or "").split())
        for sep in (". ", "? ", "! ", "\n"):
            if sep in text[:120]:
                text = text.split(sep, 1)[0]
                break
        return (text[:90] + "…") if len(text) > 90 else (text or "(no description)")

    @staticmethod
    def _acknowledgment(
        report_id: str,
        category: str,
        priority: str,
        location: Optional[str],
        device: Optional[str],
    ) -> str:
        cat_label = {
            "maintenance": "Maintenance request",
            "complaint": "Complaint",
            "feedback": "Feedback",
            "safety": "Safety report",
            "suggestion": "Suggestion",
            "other": "Report",
        }.get(category, "Report")
        lines = [
            f"✅ Thank you — your **{cat_label.lower()}** has been logged as **{report_id}**.",
            "",
            f"- **Category:** {cat_label}",
            f"- **Priority:** {priority}",
        ]
        if location:
            lines.append(f"- **Location:** {location}")
        if device:
            lines.append(f"- **Device:** {device}")
        lines += [
            "- **Status:** OPEN",
            "",
            "An administrator has been notified and will review it. "
            f'You can check progress any time by asking *"what\'s the status of {report_id}"*.',
        ]
        if priority == "URGENT":
            lines.append(
                "\n⚠️ This looks **urgent** — if it is a fire, gas, flood or injury "
                "emergency, please also call the building's emergency line immediately."
            )
        return "\n".join(lines)

    @staticmethod
    def _status_message(d: Dict[str, Any]) -> str:
        lines = [
            f"**Report {d.get('id')}** — {d.get('title') or (d.get('description', '') or '')[:80]}",
            "",
            f"- **Category:** {d.get('category')}",
            f"- **Priority:** {d.get('priority')}",
            f"- **Status:** {d.get('status')}",
        ]
        if d.get("assignee"):
            lines.append(f"- **Assigned to:** {d['assignee']}")
        if d.get("admin_notes"):
            lines.append(f"- **Admin note:** {d['admin_notes']}")
        if d.get("resolved_at"):
            lines.append(f"- **Resolved:** {d['resolved_at']}")
        return "\n".join(lines)

    @staticmethod
    def _list_message(reports: List[Dict[str, Any]]) -> str:
        if not reports:
            return "You have no reports on record yet."
        lines = [f"You have **{len(reports)}** report(s):", ""]
        for r in reports:
            lines.append(
                f"- **{r['id']}** ({r['category']}, {r['priority']}) — "
                f"{r['status']} — {r.get('title') or ''}"
            )
        return "\n".join(lines)


# ── Module-level singleton ─────────────────────────────────────────────────────
_service: Optional[ReportIntakeService] = None


def get_report_intake_service(postgres_manager=None) -> ReportIntakeService:
    global _service
    if _service is None:
        _service = ReportIntakeService(postgres_manager=postgres_manager)
    elif postgres_manager is not None and _service.postgres is None:
        _service.postgres = postgres_manager
    if _service.postgres is None:
        # V6-T24: acquire it lazily rather than depending on call ORDER. The singleton was
        # only ever handed a connection by the report-intake node, so any other caller — the
        # events lane's joined ticket view, the rules engine — got a service that silently
        # returned nothing unless somebody had happened to file a report in this process
        # first. A read that returns [] because of initialisation order is indistinguishable
        # from a building with no reports, which is exactly the wrong thing to be ambiguous
        # about in a count that is supposed to reconcile.
        try:
            from orchestrator import main as _main

            if getattr(_main, "postgres_manager", None) is not None:
                _service.postgres = _main.postgres_manager
        except Exception as exc:  # pragma: no cover - import cycle / not booted
            logger.debug(f"[report_intake] lazy postgres acquisition skipped: {exc}")
    return _service
