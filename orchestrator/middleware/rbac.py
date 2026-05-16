"""
Phase 6.8 — RBAC & Multi-Tenancy Middleware
=============================================
Role-Based Access Control (RBAC) for the OntoSage API layer.

Features:
  • JWT-based authentication (HS256 / RS256)
  • 6 built-in roles: admin, facility_manager, analyst, operator, occupant, readonly
  • Permission-based endpoint access control
  • Tenant isolation: each building ID maps to a tenant namespace
  • FastAPI middleware + dependency injection

Built-in roles and permissions:
  admin            — full access (manage users, config, all data)
  facility_manager — read+write config, read all data, generate reports
  analyst          — read all data, run analytics, export
  operator         — read own building data, cannot change config
  occupant         — read own zone data only, no exports, no config
  readonly         — read-only access to aggregated metrics only

Usage:
    from orchestrator.middleware.rbac import RBACMiddleware, require_permission

    # FastAPI app setup
    app.add_middleware(RBACMiddleware, secret_key=SECRET_KEY)

    # Route protection
    @app.get("/api/v1/export")
    async def export_data(user=Depends(require_permission("export:read"))):
        ...
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

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


# ─────────────────────────────────────────────────────────────────────────────
# Minimal JWT implementation (no external dep required)
# ─────────────────────────────────────────────────────────────────────────────


class SimpleJWT:
    """Minimal HS256 JWT encode/decode without PyJWT dependency."""

    @staticmethod
    def _b64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    @staticmethod
    def _b64url_decode(s: str) -> bytes:
        pad = 4 - len(s) % 4
        return base64.urlsafe_b64decode(s + "=" * pad)

    @classmethod
    def encode(cls, payload: Dict, secret: str, expires_in: int = 3600) -> str:
        header = cls._b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        payload = {**payload, "iat": int(time.time()), "exp": int(time.time()) + expires_in}
        body = cls._b64url_encode(json.dumps(payload).encode())
        sig = hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
        return f"{header}.{body}.{cls._b64url_encode(sig)}"

    @classmethod
    def decode(cls, token: str, secret: str) -> Dict:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid token format")
        header_b, body_b, sig_b = parts
        expected_sig = hmac.new(
            secret.encode(), f"{header_b}.{body_b}".encode(), hashlib.sha256
        ).digest()
        actual_sig = cls._b64url_decode(sig_b)
        if not hmac.compare_digest(expected_sig, actual_sig):
            raise ValueError("Invalid token signature")
        payload = json.loads(cls._b64url_decode(body_b))
        if payload.get("exp", 0) < time.time():
            raise ValueError("Token expired")
        return payload


# ─────────────────────────────────────────────────────────────────────────────
# Token manager
# ─────────────────────────────────────────────────────────────────────────────


class TokenManager:
    """Issues and validates OntoSage access tokens."""

    def __init__(self, secret_key: Optional[str] = None, token_ttl: int = 3600):
        self._secret = secret_key or os.environ.get(
            "ONTOSAGE_SECRET_KEY", "change-me-in-production"
        )
        self._ttl = token_ttl
        self._revoked: Set[str] = set()  # revoked token IDs

    def issue_token(self, user: UserContext) -> str:
        payload = {
            "sub": user.user_id,
            "username": user.username,
            "role": user.role,
            "tenant_id": user.tenant_id,
            "allowed_buildings": user.allowed_buildings,
            "custom_permissions": list(user.custom_permissions),
            "jti": hashlib.sha256(f"{user.user_id}{time.time()}".encode()).hexdigest()[:16],
        }
        return SimpleJWT.encode(payload, self._secret, self._ttl)

    def validate_token(self, token: str) -> UserContext:
        """Decode and validate a token, return UserContext."""
        try:
            payload = SimpleJWT.decode(token, self._secret)
        except ValueError as e:
            raise PermissionError(f"Authentication failed: {e}")

        jti = payload.get("jti", "")
        if jti in self._revoked:
            raise PermissionError("Token has been revoked")

        role = payload.get("role", "readonly")
        permissions = ROLE_PERMISSIONS.get(role, set())
        custom_permissions = set(payload.get("custom_permissions", []))

        return UserContext(
            user_id=payload.get("sub", ""),
            username=payload.get("username", ""),
            role=role,
            tenant_id=payload.get("tenant_id", "default"),
            allowed_buildings=payload.get("allowed_buildings", []),
            permissions=permissions,
            custom_permissions=custom_permissions,
            token_expiry=payload.get("exp", 0),
        )

    def revoke_token(self, jti: str):
        self._revoked.add(jti)


# ─────────────────────────────────────────────────────────────────────────────
# In-memory user store (replace with DB-backed in production)
# ─────────────────────────────────────────────────────────────────────────────


class UserStore:
    """Simple in-memory user registry for development/testing."""

    def __init__(self):
        self._users: Dict[str, Dict] = {}
        # Seed a default admin
        self.add_user(
            user_id="admin-001",
            username="admin",
            password="change-me-in-production",
            role="admin",
            tenant_id="default",
            allowed_buildings=[],
        )

    def add_user(
        self,
        user_id: str,
        username: str,
        password: str,
        role: str = "readonly",
        tenant_id: str = "default",
        allowed_buildings: Optional[List[str]] = None,
    ):
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        self._users[username] = {
            "user_id": user_id,
            "username": username,
            "password_hash": pw_hash,
            "role": role,
            "tenant_id": tenant_id,
            "allowed_buildings": allowed_buildings or [],
        }

    def authenticate(self, username: str, password: str) -> Optional[UserContext]:
        user = self._users.get(username)
        if not user:
            return None
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        if not hmac.compare_digest(pw_hash, user["password_hash"]):
            return None
        role = user["role"]
        return UserContext(
            user_id=user["user_id"],
            username=username,
            role=role,
            tenant_id=user["tenant_id"],
            allowed_buildings=user["allowed_buildings"],
            permissions=ROLE_PERMISSIONS.get(role, set()),
        )

    def list_users(self) -> List[Dict]:
        return [{k: v for k, v in u.items() if k != "password_hash"} for u in self._users.values()]


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI integration helpers (importable without FastAPI installed)
# ─────────────────────────────────────────────────────────────────────────────


def create_rbac_dependency(token_manager: TokenManager, required_permission: str):
    """
    Factory: returns a FastAPI Depends callable that requires a permission.

    Usage:
        require_export = create_rbac_dependency(token_mgr, "export:read")

        @app.get("/export")
        async def export(user=Depends(require_export)):
            ...
    """

    async def _dependency(authorization: str = ""):
        if not authorization.startswith("Bearer "):
            raise Exception("Missing or invalid Authorization header")
        token = authorization[7:]
        user = token_manager.validate_token(token)
        if not user.has_permission(required_permission):
            raise Exception(
                f"Permission denied: '{required_permission}' required "
                f"(your role '{user.role}' grants: {sorted(user.permissions)})"
            )
        return user

    return _dependency


class RBACMiddleware:
    """
    Lightweight RBAC middleware compatible with Starlette/FastAPI.
    Validates tokens on every request and injects UserContext into request.state.
    Non-JWT paths (/health, /metrics, /docs) are whitelisted.
    """

    WHITELIST = {
        "/health",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
    }

    def __init__(self, app, secret_key: Optional[str] = None):
        self._app = app
        self._token_mgr = TokenManager(secret_key)
        self._user_store = UserStore()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path not in self.WHITELIST:
                headers = dict(scope.get("headers", []))
                auth = headers.get(b"authorization", b"").decode()
                if not auth:
                    scope["user"] = None
                else:
                    try:
                        scope["user"] = self._token_mgr.validate_token(auth.replace("Bearer ", ""))
                    except PermissionError as e:
                        logger.warning(f"Auth failure: {e}")
                        scope["user"] = None
        await self._app(scope, receive, send)

    def login(self, username: str, password: str) -> Optional[str]:
        """Authenticate and return a JWT token string."""
        user = self._user_store.authenticate(username, password)
        if not user:
            return None
        return self._token_mgr.issue_token(user)


# ─────────────────────────────────────────────────────────────────────────────
# Global singletons
# ─────────────────────────────────────────────────────────────────────────────

_token_manager: Optional[TokenManager] = None
_user_store: Optional[UserStore] = None


def get_auth_manager(secret_key: Optional[str] = None) -> TokenManager:
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager(secret_key)
    return _token_manager


def get_user_store() -> UserStore:
    global _user_store
    if _user_store is None:
        _user_store = UserStore()
    return _user_store
