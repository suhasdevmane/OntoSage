# -*- coding: utf-8 -*-
"""
enforcement.py — PDP consultation at the data-fetch chokepoints (V5-T39).

Every lane that FETCHES readings consults the PolicyEngine here, so no lane
can bypass policy by construction. Rollout is staged by ``PROTECT_ENFORCE``:

  off     — never consult (pre-V5 behaviour)
  shadow  — consult + LOG the verdict ("[protect] …"), enforce NOTHING
            (the default: verdicts accumulate in logs for validation first)
  on      — deny → the lane returns a structured refusal WITHOUT touching the
            DB; restrict → clamps are applied/declared by the caller

Role comes ONLY from the RBAC session (``user_role`` in intermediate results)
— personas bias framing, never permissions. The k-anonymity floors are
enforced only for PRESENCE-ADJACENT modalities (occupancy, door/window
contacts, access events): an occupancy count over 3 sensors can expose who is
where; a temperature over 3 sensors cannot identify anyone. Environmental
reads keep the tier clamps but skip the k-floor — otherwise "what's the
temperature in RM119?" would be blocked for occupants, which protects nobody.

Building-agnostic throughout: the engine is built from the ACTIVE building's
settings and its own policy triples.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from orchestrator.services.privacy.policy_engine import (
    DENY,
    PolicyEngine,
    PolicyVerdict,
)
from shared.utils import get_logger

logger = get_logger(__name__)

#: modalities whose per-sensor readings can expose individual presence
PRESENCE_ADJACENT = {"occupancy", "door_contact", "window_contact", "access", "presence"}

_engine: Optional[PolicyEngine] = None
_engine_building: Optional[str] = None


def enforcement_mode() -> str:
    from shared.config import settings

    mode = str(getattr(settings, "PROTECT_ENFORCE", "shadow") or "shadow").lower()
    return mode if mode in ("off", "shadow", "on") else "shadow"


async def get_policy_engine() -> Optional[PolicyEngine]:
    """Process-wide engine for the ACTIVE building; None when load fails."""
    global _engine, _engine_building
    from shared.config import settings

    if _engine is not None and _engine_building == settings.BUILDING_ID:
        return _engine
    try:
        engine = PolicyEngine(settings.BUILDING_ID, settings.BUILDING_NAMESPACE)
        n = await engine.load()
        if n == 0:
            logger.warning(
                "[protect] no AccessPolicy triples in the graph — PDP idle "
                "(upload policies via scripts/generate_access_policies.py)"
            )
        _engine, _engine_building = engine, settings.BUILDING_ID
        return _engine
    except Exception as exc:
        logger.warning(f"[protect] policy engine unavailable: {exc}")
        return None


async def reload_policies() -> int:
    """Best-effort reload after a TTL upload touches policies."""
    engine = await get_policy_engine()
    if engine is None:
        return 0
    try:
        return await engine.reload()
    except Exception as exc:
        logger.warning(f"[protect] policy reload failed: {exc}")
        return 0


async def consult(
    lane: str,
    role: Optional[str],
    *,
    scope: str = "any",
    modality: Optional[str] = None,
    inference_class: Optional[str] = None,
    n_sensors: Optional[int] = None,
    n_spaces: Optional[int] = None,
    data_age_minutes: Optional[float] = None,
    requested_resolution_s: Optional[float] = None,
    user_id: Optional[str] = None,
) -> Optional[PolicyVerdict]:
    """Evaluate + log the verdict for one fetch. None = PDP off/unavailable.

    The k-floor inputs (n_sensors/n_spaces) are forwarded ONLY for
    presence-adjacent modalities — see the module docstring.
    """
    if enforcement_mode() == "off":
        return None
    engine = await get_policy_engine()
    if engine is None or not engine._policies:
        return None
    presence = (modality or "").lower() in PRESENCE_ADJACENT
    verdict = engine.evaluate(
        role or "readonly",
        scope=scope,
        inference_class=inference_class,
        n_sensors=n_sensors if presence else None,
        n_spaces=n_spaces if presence else None,
        data_age_minutes=data_age_minutes,
        requested_resolution_s=requested_resolution_s,
        user_id=user_id,
    )
    logger.info(
        f"[protect] lane={lane} mode={enforcement_mode()} role={role or 'readonly'} "
        f"modality={modality or '-'} n_sensors={n_sensors} -> {verdict.decision.upper()} "
        f"({verdict.reason[:90]})"
    )
    return verdict


def should_block(verdict: Optional[PolicyVerdict], *, n_sensors: Optional[int] = None) -> bool:
    """True when enforcement is ON and serving raw rows would violate policy.

    Denials always block. A RESTRICT verdict blocks too when the k-anonymity
    floor is UNMET for this fetch (n_sensors below the policy floor): the SQL
    lane serves raw per-sensor rows, so an unmet floor cannot be "declared
    away" — the honest outcome is the aggregate alternative, not the rows.
    Resolution-only restrictions do NOT block (window means satisfy them).
    """
    if verdict is None or enforcement_mode() != "on":
        return False
    if verdict.decision == DENY:
        return True
    if (
        verdict.decision == "restrict"
        and n_sensors is not None
        and n_sensors < (verdict.min_sensors or 1)
    ):
        return True
    return False


def refusal_payload(verdict: PolicyVerdict, lane: str, question: str = "") -> Dict[str, Any]:
    """Structured refusal a lane returns WITHOUT touching the database.

    V5-T41: the text proposes the nearest ALLOWED reformulations computed
    from this verdict's own parameters, and explains WHY in the building's
    own policy language when the policy carries an rdfs:comment.
    """
    from orchestrator.services.privacy.reformulation import render_refusal

    comment = ""
    engine = _engine
    if engine is not None and getattr(engine, "_policies", None):
        for pol in engine._policies:
            if pol.iri == verdict.policy_iri and pol.comment:
                comment = pol.comment
                break
    return {
        "success": False,
        "denied_by_policy": verdict.policy_iri,
        "lane": lane,
        "formatted_response": render_refusal(verdict, question, comment),
        "results": {"data": []},
        "analytics_required": False,
    }


def reset_engine_for_tests() -> None:
    global _engine, _engine_building
    _engine, _engine_building = None, None
