"""
Role-Based Access Control (RBAC) model for the OntoSage API layer.

This module holds only the permission catalogue and the ``UserContext`` data
class. The live auth path is session-based:
  • session/token validation → orchestrator/auth_manager.py
  • FastAPI permission gate   → require_permission() in orchestrator/main.py

require_permission() resolves a session into a UserContext (via
get_user_context()) and checks it against ROLE_PERMISSIONS below.

Built-in roles and permissions:
  admin            — full access (manage users, config, all data)
  facility_manager — read+write config, read all data, generate reports
  analyst          — read all data, run analytics, export
  operator         — read own building data, cannot change config
  occupant         — read own zone data only, no exports, no config
  readonly         — read-only access to aggregated metrics only
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set

# ─────────────────────────────────────────────────────────────────────────────
# Permissions catalogue
# ─────────────────────────────────────────────────────────────────────────────

# Format: "resource:action"
ALL_PERMISSIONS = {
    # Data read
    "sensor:read",
    "analytics:read",
    "metadata:read",
    "report:read",
    "export:read",
    "anomaly:read",
    "trend:read",
    "compliance:read",
    "comparison:read",
    # Data write / config
    "config:read",
    "config:write",
    "user:read",
    "user:write",
    "user:delete",
    "building:read",
    "building:write",
    "building:delete",
    # Device control
    "device:control",
    "control:write",   # T24: write setpoints via actuation gateway (admin + facility only)
    # System
    "system:admin",
    "system:health",
}

# Role → granted permissions
ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "admin": ALL_PERMISSIONS,
    "facility_manager": {
        "sensor:read",
        "analytics:read",
        "metadata:read",
        "report:read",
        "export:read",
        "anomaly:read",
        "trend:read",
        "compliance:read",
        "comparison:read",
        "config:read",
        "config:write",
        "building:read",
        "building:write",
        "device:control",
        "control:write",  # T24: actuation gateway write access
        "system:health",
    },
    "analyst": {
        "sensor:read",
        "analytics:read",
        "metadata:read",
        "report:read",
        "export:read",
        "anomaly:read",
        "trend:read",
        "compliance:read",
        "comparison:read",
        "building:read",
        "system:health",
    },
    "operator": {
        "sensor:read",
        "analytics:read",
        "metadata:read",
        "anomaly:read",
        "trend:read",
        "building:read",
        "device:control",
        "system:health",
    },
    "occupant": {
        "sensor:read",
        "metadata:read",
        "system:health",
    },
    "readonly": {
        "metadata:read",
        "system:health",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class UserContext:
    user_id: str
    username: str
    role: str
    tenant_id: str  # building_id / organisation
    allowed_buildings: List[str]  # empty = all buildings
    permissions: Set[str] = field(default_factory=set)
    custom_permissions: Set[str] = field(default_factory=set)
    token_expiry: float = 0.0

    @property
    def all_permissions(self) -> Set[str]:
        return self.permissions | self.custom_permissions

    def has_permission(self, permission: str) -> bool:
        return permission in self.all_permissions

    def can_access_building(self, building_id: str) -> bool:
        if "system:admin" in self.all_permissions:
            return True
        if not self.allowed_buildings:
            return True
        return building_id in self.allowed_buildings

    def to_dict(self) -> Dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "tenant_id": self.tenant_id,
            "allowed_buildings": self.allowed_buildings,
            "permissions": list(self.all_permissions),
        }
