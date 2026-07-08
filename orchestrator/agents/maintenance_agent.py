"""
MaintenanceAgent — conversational work-order CRUD with 5-state machine.

States: OPEN → ASSIGNED → IN_PROGRESS → RESOLVED → CLOSED
All DB operations are async stubs that return a result dict.
The actual DB writes are done by _maintenance_node in workflow.py using postgres_manager.
"""

import re
from typing import Any, Dict, Optional

from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)

# Operation detection patterns (order matters — more specific first)
_OP_PATTERNS = [
    ("ASSIGN", re.compile(r"\bassign\b", re.I)),
    ("RESOLVE", re.compile(r"\b(resolve|resolved|mark.*resolved)\b", re.I)),
    ("CLOSE", re.compile(r"\bclose\b", re.I)),
    ("STATUS", re.compile(r"\b(check|status|MT-\d{4})\b", re.I)),
    ("LIST", re.compile(r"\b(list|show|what).*(open|all|ticket)", re.I)),
    (
        "CREATE",
        re.compile(r"\b(broken|not working|fault|report|raise ticket|fix the|maintenance)\b", re.I),
    ),
]

_ASSIGN_ROLES = {"admin", "facility_manager"}
_RESOLVE_ROLES = {"admin", "facility_manager", "operator"}
_CLOSE_ROLES = {"admin", "facility_manager"}


def _entity_value(entities: Any, etype: str, default: Optional[str] = None) -> Optional[str]:
    """Extract an entity value by type, tolerating both dict and plain-string
    entity shapes (the dialogue LLM emits either; crash fix 2026-06-12)."""
    for e in entities or []:
        if isinstance(e, dict) and e.get("type") == etype:
            value = e.get("value")
            return str(value) if value is not None else default
    return default


def _detect_operation(query: str) -> str:
    """Return the operation name for a user query."""
    for op, pattern in _OP_PATTERNS:
        if pattern.search(query):
            return op
    return "CREATE"


class MaintenanceAgent:
    """Handle maintenance ticket operations."""

    def _generate_ticket_id(self, counter: int) -> str:
        """Format counter as MT-XXXX ticket ID."""
        return f"MT-{counter:04d}"

    async def handle(self, state: ConversationState) -> Dict[str, Any]:
        """Route to the correct sub-operation based on query content."""
        query = state.user_message or ""
        operation = _detect_operation(query)
        role = state.intermediate_results.get("user_role", "readonly")

        if operation == "ASSIGN" and role not in _ASSIGN_ROLES:
            return self._denied(role, "assign tickets")
        if operation in ("RESOLVE",) and role not in _RESOLVE_ROLES:
            return self._denied(role, "resolve tickets")
        if operation == "CLOSE" and role not in _CLOSE_ROLES:
            return self._denied(role, "close tickets")

        if operation == "CREATE":
            return await self._create_ticket(state)
        elif operation == "STATUS":
            return await self._status_ticket(state)
        elif operation == "LIST":
            return await self._list_tickets(state)
        elif operation == "ASSIGN":
            return await self._assign_ticket(state)
        elif operation == "RESOLVE":
            return await self._resolve_ticket(state)
        elif operation == "CLOSE":
            return await self._close_ticket(state)
        return self._denied(role, "perform this operation")

    def _denied(self, role: str, action: str) -> Dict[str, Any]:
        """Return a standardised permission-denied result."""
        return {
            "status": "denied",
            "message": (
                f"🔒 {role.replace('_', ' ').title()} role cannot {action}.\n"
                "Contact your facility manager if you need this access."
            ),
        }

    async def _create_ticket(self, state: ConversationState) -> Dict[str, Any]:
        """Extract location and description, return CREATE result dict."""
        entities = state.intermediate_results.get("entities", [])
        location = _entity_value(entities, "location", "Unknown")
        description = _entity_value(entities, "fault_description", state.user_message)
        building_id = (
            getattr(state, "building_id", None)
            or state.intermediate_results.get("building_id")
            or "unknown"
        )
        user_id = state.intermediate_results.get("user_id", "unknown")
        return {
            "status": "created",
            "operation": "CREATE",
            "building_id": building_id,
            "location": location,
            "description": description,
            "reporter_id": user_id,
            "session_id": state.conversation_id,
        }

    async def _status_ticket(self, state: ConversationState) -> Dict[str, Any]:
        """Extract ticket ID from entities or query text."""
        entities = state.intermediate_results.get("entities", [])
        ticket_id = _entity_value(entities, "ticket_id")
        query = state.user_message or ""
        if not ticket_id:
            m = re.search(r"MT-\d{4}", query, re.I)
            ticket_id = m.group(0).upper() if m else None
        return {"status": "lookup", "operation": "STATUS", "ticket_id": ticket_id}

    async def _list_tickets(self, state: ConversationState) -> Dict[str, Any]:
        """Return LIST result for building's open tickets."""
        building_id = (
            getattr(state, "building_id", None)
            or state.intermediate_results.get("building_id")
            or "unknown"
        )
        return {"status": "list", "operation": "LIST", "building_id": building_id, "filter": "OPEN"}

    async def _assign_ticket(self, state: ConversationState) -> Dict[str, Any]:
        """Extract ticket ID and assignee from entities."""
        entities = state.intermediate_results.get("entities", [])
        ticket_id = _entity_value(entities, "ticket_id")
        assignee = _entity_value(entities, "assignee")
        return {
            "status": "assigned",
            "operation": "ASSIGN",
            "ticket_id": ticket_id,
            "assignee": assignee,
        }

    async def _resolve_ticket(self, state: ConversationState) -> Dict[str, Any]:
        """Extract ticket ID from entities or query text."""
        entities = state.intermediate_results.get("entities", [])
        ticket_id = _entity_value(entities, "ticket_id")
        query = state.user_message or ""
        if not ticket_id:
            m = re.search(r"MT-\d{4}", query, re.I)
            ticket_id = m.group(0).upper() if m else None
        return {"status": "resolved", "operation": "RESOLVE", "ticket_id": ticket_id}

    async def _close_ticket(self, state: ConversationState) -> Dict[str, Any]:
        """Extract ticket ID from entities or query text."""
        entities = state.intermediate_results.get("entities", [])
        ticket_id = _entity_value(entities, "ticket_id")
        query = state.user_message or ""
        if not ticket_id:
            m = re.search(r"MT-\d{4}", query, re.I)
            ticket_id = m.group(0).upper() if m else None
        return {"status": "closed", "operation": "CLOSE", "ticket_id": ticket_id}
