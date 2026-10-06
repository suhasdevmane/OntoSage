"""Mirror OntoSage accounts into Open WebUI, so one set of credentials works in both.

Open WebUI keeps its own user store. When an admin creates an OntoSage account, the
matching Open WebUI account is created here with the same email and the password the
admin supplied. This is one-way: a later password change in Open WebUI is NOT copied
back, because Open WebUI's store is the only place that password lives.

Every failure is reported in the returned result and never raised: the OntoSage account
has already been created by the time this runs, and an Open WebUI outage must not undo it.

Endpoints relied on (Open WebUI 0.8.x; not verified against the running image):
  POST /api/v1/auths/signin   {email, password} -> {token, ...}    (admin token)
  GET  /api/v1/users/?query=&page=N -> {users: [...], total}        (admin only)
  POST /api/v1/auths/add      {name, email, password, role}        (admin only)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

_TIMEOUT_SECONDS = 10.0
_MAX_USER_PAGES = 20


@dataclass(frozen=True)
class OpenWebUISyncResult:
    """Outcome of one account sync. ``status`` is created | exists | skipped | failed."""

    status: str
    reason: str
    email: str = ""

    def as_dict(self) -> Dict[str, str]:
        """Serialisable form for an API response."""
        return {"status": self.status, "reason": self.reason, "email": self.email}


def _norm(email: str) -> str:
    return (email or "").strip().lower()


def _users_from(payload: Any) -> List[Dict[str, Any]]:
    """Open WebUI returns either a bare list or ``{"users": [...]}`` depending on version."""
    if isinstance(payload, dict):
        payload = payload.get("users", [])
    if not isinstance(payload, list):
        return []
    return [u for u in payload if isinstance(u, dict)]


async def _signin(client: httpx.AsyncClient, base: str, email: str, password: str) -> str:
    resp = await client.post(
        f"{base}/api/v1/auths/signin", json={"email": email, "password": password}
    )
    if resp.status_code != 200:
        raise PermissionError(f"admin sign-in returned HTTP {resp.status_code}")
    token = (resp.json() or {}).get("token")
    if not token:
        raise PermissionError("admin sign-in returned no token")
    return str(token)


async def _find_user(
    client: httpx.AsyncClient, base: str, headers: Dict[str, str], email: str
) -> bool:
    """True when an Open WebUI account with this email (case-insensitive) exists."""
    for page in range(1, _MAX_USER_PAGES + 1):
        resp = await client.get(
            f"{base}/api/v1/users/",
            params={"query": email, "page": page},
            headers=headers,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"user listing returned HTTP {resp.status_code}")
        users = _users_from(resp.json())
        if any(_norm(u.get("email", "")) == email for u in users):
            return True
        if not users:
            return False
    return False


async def ensure_openwebui_user(
    email: str,
    name: str,
    password: str,
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> OpenWebUISyncResult:
    """Create the Open WebUI account for ``email`` if it does not exist. Never raises.

    ``transport`` is for tests (httpx.MockTransport); production leaves it None.
    """
    clean = _norm(email)
    try:
        admin_email = (settings.OPENWEBUI_ADMIN_EMAIL or "").strip()
        admin_password = settings.OPENWEBUI_ADMIN_PASSWORD or ""
        if not admin_email:
            return OpenWebUISyncResult("skipped", "OPENWEBUI_ADMIN_EMAIL is not set", clean)
        if not admin_password:
            return OpenWebUISyncResult("skipped", "OPENWEBUI_ADMIN_PASSWORD is not set", clean)
        if not clean or "@" not in clean:
            return OpenWebUISyncResult("skipped", "account has no email address", clean)
        if not password:
            return OpenWebUISyncResult("skipped", "no password supplied to sync", clean)

        base = (settings.OPENWEBUI_URL or "").rstrip("/")
        client_kwargs: Dict[str, Any] = {"timeout": _TIMEOUT_SECONDS}
        if transport is not None:
            client_kwargs["transport"] = transport

        async with httpx.AsyncClient(**client_kwargs) as client:
            token = await _signin(client, base, admin_email, admin_password)
            headers = {"Authorization": f"Bearer {token}"}

            if await _find_user(client, base, headers, clean):
                logger.info(f"[openwebui_sync] {clean} already exists in Open WebUI")
                return OpenWebUISyncResult("exists", "account already exists", clean)

            resp = await client.post(
                f"{base}/api/v1/auths/add",
                json={"name": name or clean, "email": clean, "password": password, "role": "user"},
                headers=headers,
            )
            if resp.status_code == 200:
                logger.info(f"[openwebui_sync] created Open WebUI account for {clean}")
                return OpenWebUISyncResult("created", "account created", clean)
            # Another request created it between the check and the add.
            if resp.status_code == 400 and "already" in resp.text.lower():
                return OpenWebUISyncResult("exists", "account already exists", clean)
            return OpenWebUISyncResult(
                "failed", f"Open WebUI add returned HTTP {resp.status_code}", clean
            )
    except PermissionError as e:
        logger.warning(f"[openwebui_sync] {e} — check OPENWEBUI_ADMIN_EMAIL/PASSWORD")
        return OpenWebUISyncResult("failed", str(e), clean)
    except Exception as e:  # never let an Open WebUI problem reach the caller
        logger.warning(f"[openwebui_sync] failed for {clean}: {type(e).__name__}: {e}")
        return OpenWebUISyncResult("failed", f"{type(e).__name__}: {e}", clean)
