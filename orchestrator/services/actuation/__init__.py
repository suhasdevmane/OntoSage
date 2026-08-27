"""Actuation gateway — Phase G (T23/T24/T25).

Public surface:
    ActuationDriver   — ABC, import from actuation.base
    SimDriver         — simulation driver (logs only, no physical write)
    ActuationRegistry — singleton; resolves driver for the active building
    read_actuation_log — reads the audit trail SimDriver writes (see audit_log.py)

Usage:
    from orchestrator.services.actuation import ActuationRegistry
    registry = ActuationRegistry()
    driver = await registry.driver_for(building_id)
    result = await driver.set_point(point_uri, value, user_id=user_id)
"""

from orchestrator.services.actuation.approval_store import (
    ActuationApprovalStore,
    get_approval_store,
)
from orchestrator.services.actuation.audit_log import format_actions, read_actuation_log
from orchestrator.services.actuation.base import ActuationDriver, ActuationResult
from orchestrator.services.actuation.registry import ActuationRegistry
from orchestrator.services.actuation.sim_driver import SimDriver

__all__ = [
    "ActuationDriver",
    "ActuationResult",
    "ActuationRegistry",
    "SimDriver",
    "ActuationApprovalStore",
    "get_approval_store",
    "read_actuation_log",
    "format_actions",
]
