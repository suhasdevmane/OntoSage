# -*- coding: utf-8 -*-
"""
policy_engine.py — the deterministic Policy Decision Point (V5-T38).

ONE evaluator for every lane: (role × inference-class × sensor/space counts ×
data age × requested resolution × rate) → allow | restrict(clamps) |
deny(reason + nearest allowed alternative). No LLM anywhere in the decision;
same inputs give the same verdict on every run and every restart.

Policies are the building's OWN ontosage:AccessPolicy triples (uploaded by
scripts/generate_access_policies.py or authored in the admin portal):

    appliesToRole "facility_manager" | "*"
    inferenceClass "individual_presence:deny"          (per-class denials)
    minAggregationSensors / minAggregationSpaces       (k-anonymity floors)
    resolutionTier "15:5,60:60,10080:3600"             (recency_min:max_res_s;
                                                        "0:1" = unrestricted)
    rateLimit "600:60"                                 (max_queries:per_minutes;
                                                        "0:0" = unlimited)

The verdict carries the policy IRI and the parameters used, so enforcement
(T39) can cite the exact policy in the dossier — privacy provenance, not a
silent mutation. Building-agnostic: nothing here names a building; the
namespace scopes the SPARQL and that is all.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

_ONTOSAGE = "http://ontosage.org/capabilities#"

#: verdict decisions
ALLOW, RESTRICT, DENY = "allow", "restrict", "deny"


@dataclass
class Policy:
    iri: str
    role: str  # exact role or "*"
    inference_class: Optional[str] = None  # e.g. "individual_presence:deny"
    scope_spaces: str = "any"
    min_sensors: int = 1
    min_spaces: int = 1
    tiers: List[Tuple[float, float]] = field(default_factory=list)  # (recency_min, max_res_s)
    rate_max: int = 0  # 0 = unlimited
    rate_window_min: int = 0
    comment: str = ""


@dataclass
class PolicyVerdict:
    decision: str  # allow | restrict | deny
    policy_iri: str
    reason: str
    resolution_s: Optional[float] = None  # restrict: coarsest resolution allowed
    min_sensors: int = 1
    min_spaces: int = 1
    alternative: str = ""  # deny: the nearest allowed ask
    parameters: Dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.decision != DENY


def _parse_tiers(raw: str) -> List[Tuple[float, float]]:
    tiers: List[Tuple[float, float]] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        a, b = part.split(":", 1)
        try:
            tiers.append((float(a), float(b)))
        except ValueError:
            continue
    return sorted(tiers)


class PolicyEngine:
    """Loads a building's policy triples once; ``evaluate`` is a pure function.

    ``rate_store`` is injectable (tests use a dict-backed fake); live wiring
    uses Redis via ``redis_manager``. ``reload()`` re-reads the graph — call it
    after a TTL upload touches policies.
    """

    def __init__(
        self,
        building_id: str,
        namespace: str,
        sparql_exec: Optional[Callable] = None,
        rate_store: Optional[Any] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.building_id = building_id
        self.namespace = namespace
        self._sparql = sparql_exec
        self._policies: Optional[List[Policy]] = None
        self._rate_store = rate_store if rate_store is not None else {}
        self._clock = clock

    # ── loading ────────────────────────────────────────────────────────────

    _QUERY = (
        "SELECT ?p ?role ?inf ?scope ?minSensors ?minSpaces ?tiers ?rate ?comment WHERE {{\n"
        f"  ?p a <{_ONTOSAGE}AccessPolicy> ; <{_ONTOSAGE}appliesToRole> ?role .\n"
        f"  OPTIONAL {{ ?p <{_ONTOSAGE}inferenceClass> ?inf }}\n"
        f"  OPTIONAL {{ ?p <{_ONTOSAGE}scopeSpaces> ?scope }}\n"
        f"  OPTIONAL {{ ?p <{_ONTOSAGE}minAggregationSensors> ?minSensors }}\n"
        f"  OPTIONAL {{ ?p <{_ONTOSAGE}minAggregationSpaces> ?minSpaces }}\n"
        f"  OPTIONAL {{ ?p <{_ONTOSAGE}resolutionTier> ?tiers }}\n"
        f"  OPTIONAL {{ ?p <{_ONTOSAGE}rateLimit> ?rate }}\n"
        "  OPTIONAL { ?p <http://www.w3.org/2000/01/rdf-schema#comment> ?comment }\n"
        '  FILTER(STRSTARTS(STR(?p), "{ns}"))\n'
        "}}"
    )

    async def load(self) -> int:
        sparql = self._sparql
        if sparql is None:  # pragma: no cover - live wiring
            from orchestrator.services.deliberation.live import sparql_exec as sparql

        res = await sparql(
            self._QUERY.replace("{ns}", self.namespace).replace("{{", "{").replace("}}", "}")
        )
        policies: List[Policy] = []
        for b in (res or {}).get("results", {}).get("bindings", []):

            def _v(key: str, default: str = "") -> str:
                return str(b.get(key, {}).get("value", default) or default)

            rate_raw = _v("rate", "0:0")
            rate_parts = rate_raw.split(":", 1) if ":" in rate_raw else ["0", "0"]
            try:
                rate_max, rate_window = int(float(rate_parts[0])), int(float(rate_parts[1]))
            except ValueError:
                rate_max, rate_window = 0, 0
            policies.append(
                Policy(
                    iri=_v("p"),
                    role=_v("role", "*"),
                    inference_class=_v("inf") or None,
                    scope_spaces=_v("scope", "any"),
                    min_sensors=int(float(_v("minSensors", "1") or 1)),
                    min_spaces=int(float(_v("minSpaces", "1") or 1)),
                    tiers=_parse_tiers(_v("tiers", "0:1")),
                    rate_max=rate_max,
                    rate_window_min=rate_window,
                    comment=_v("comment"),
                )
            )
        self._policies = policies
        logger.info(f"[pdp] loaded {len(policies)} policies for {self.building_id}")
        return len(policies)

    async def reload(self) -> int:
        """Call after a TTL upload touches AccessPolicy triples."""
        self._policies = None
        return await self.load()

    def set_policies(self, policies: List[Policy]) -> None:
        """Test/offline injection — bypasses the graph."""
        self._policies = list(policies)

    # ── evaluation (pure) ──────────────────────────────────────────────────

    def _role_policy(self, role: str, scope: str) -> Optional[Policy]:
        """Scope-aware selection: exact scope first, then 'any'.

        Roles may carry several scoped policies (the occupant model: 'own' is
        unrestricted, 'public' is tiered, 'any' cross-space carries the
        k-floors). Callers that cannot PROVE a narrower scope must use the
        default 'any' — the conservative cross-space policy.
        """
        assert self._policies is not None, "PolicyEngine.load() before evaluate()"
        named = [p for p in self._policies if p.role == role and p.inference_class is None]
        if not named:
            return None
        for p in named:
            if p.scope_spaces == scope:
                return p
        for p in named:
            if p.scope_spaces == "any":
                return p
        return None

    def _inference_denials(self, role: str) -> List[Policy]:
        assert self._policies is not None
        return [p for p in self._policies if p.inference_class and p.role in ("*", role)]

    def evaluate(
        self,
        role: str,
        *,
        scope: str = "any",
        inference_class: Optional[str] = None,
        n_sensors: Optional[int] = None,
        n_spaces: Optional[int] = None,
        data_age_minutes: Optional[float] = None,
        requested_resolution_s: Optional[float] = None,
        user_id: Optional[str] = None,
    ) -> PolicyVerdict:
        """The verdict. Order: inference denials → role policy → rate → k-floors → tiers.

        ``scope`` defaults to 'any' (cross-space) — the CONSERVATIVE policy.
        Pass 'own' / 'public' only when the enforcement layer has verified it.
        """
        role = (role or "").strip() or "readonly"

        # 1 — inference-class denials bind EVERY profile (user decision #2)
        if inference_class:
            for p in self._inference_denials(role):
                cls, _, action = (p.inference_class or "").partition(":")
                if cls == inference_class and action == "deny":
                    return PolicyVerdict(
                        decision=DENY,
                        policy_iri=p.iri,
                        reason=(
                            f"'{inference_class}' requests are denied for every role — the "
                            "system explains the building, never individuals"
                        ),
                        alternative=(
                            "ask for aggregate occupancy or environmental conditions instead "
                            "(counts and averages over rooms, never persons)"
                        ),
                        parameters={"inference_class": inference_class, "applies_to": p.role},
                    )

        # 2 — the role must have a policy for this scope
        policy = self._role_policy(role, scope)
        if policy is None:
            return PolicyVerdict(
                decision=DENY,
                policy_iri="",
                reason=f"no access policy is registered for role '{role}'",
                alternative="ask an administrator to add a policy for this role",
                parameters={"role": role, "scope": scope},
            )

        params: Dict[str, Any] = {"role": role, "scope": scope, "policy": policy.iri}

        # 3 — rate limiting (sliding window per user)
        if policy.rate_max > 0 and user_id:
            window_s = policy.rate_window_min * 60
            key = f"pdp_rate:{self.building_id}:{role}:{user_id}"
            now = self._clock()
            hits = [t for t in self._rate_store.get(key, []) if now - t < window_s]
            if len(hits) >= policy.rate_max:
                retry_s = int(window_s - (now - hits[0])) + 1
                return PolicyVerdict(
                    decision=DENY,
                    policy_iri=policy.iri,
                    reason=(
                        f"rate limit reached: {policy.rate_max} queries per "
                        f"{policy.rate_window_min} min for role '{role}'"
                    ),
                    alternative=f"retry in ~{retry_s}s",
                    parameters={**params, "rate": f"{policy.rate_max}/{policy.rate_window_min}min"},
                )
            hits.append(now)
            self._rate_store[key] = hits

        # 4 — k-anonymity floors → restrict with clamps
        clamps_needed = False
        if n_sensors is not None and n_sensors < policy.min_sensors:
            clamps_needed = True
        if n_spaces is not None and n_spaces < policy.min_spaces:
            clamps_needed = True

        # 5 — resolution tiers by data age
        allowed_res: Optional[float] = None
        if policy.tiers and data_age_minutes is not None:
            if policy.tiers == [(0.0, 1.0)]:
                allowed_res = None  # unrestricted marker
            else:
                allowed_res = policy.tiers[-1][1]  # older than every tier → coarsest
                for recency_min, res_s in policy.tiers:
                    if data_age_minutes <= recency_min:
                        allowed_res = res_s
                        break
        resolution_clamp = None
        if allowed_res is not None and (
            requested_resolution_s is None or requested_resolution_s < allowed_res
        ):
            resolution_clamp = allowed_res

        if clamps_needed or resolution_clamp is not None:
            reasons = []
            if clamps_needed:
                reasons.append(
                    f"aggregation floor: ≥{policy.min_sensors} sensors / "
                    f"≥{policy.min_spaces} spaces for role '{role}'"
                )
            if resolution_clamp is not None:
                reasons.append(
                    f"resolution clamped to {resolution_clamp:g}s for data "
                    f"{data_age_minutes:g} min old"
                )
            return PolicyVerdict(
                decision=RESTRICT,
                policy_iri=policy.iri,
                reason="; ".join(reasons),
                resolution_s=resolution_clamp,
                min_sensors=policy.min_sensors,
                min_spaces=policy.min_spaces,
                parameters={
                    **params,
                    "data_age_minutes": data_age_minutes,
                    "requested_resolution_s": requested_resolution_s,
                },
            )

        return PolicyVerdict(
            decision=ALLOW,
            policy_iri=policy.iri,
            reason=f"allowed by role policy for '{role}'",
            min_sensors=policy.min_sensors,
            min_spaces=policy.min_spaces,
            parameters=params,
        )
