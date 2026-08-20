"""
rules_engine.py — ECA (Event-Condition-Action) rule engine core (T20).

Evaluates standing rules against live sensor telemetry.
Actions: notify only in Phase F (actuate comes in Phase G).

Rules are loaded from input/<building_id>/rules.yaml.

YAML schema example:
    rules:
      - id: co2_high_room501
        name: CO2 elevated in room 5.01
        enabled: true
        trigger:
          sensor_uuid: "abc123-..."       # direct UUID, OR
          concept: stuffy                 # HBCO concept (resolved -> Brick class -> UUID)
          op: ">"                         # >, <, >=, <=, ==, !=
          threshold: 1000.0
          duration_min: 10               # 0 = single sample; N = sustained for N minutes
        action:
          type: notify                   # only type in Phase F
          message: "CO2 {value:.0f} ppm in room 5.01 (threshold {threshold:.0f})"
          severity: warning              # info | warning | critical

Duration window: Redis key rules:breach_start:<rule_id>:<uuid> = ISO timestamp
  First breach: key written.  Subsequent checks: fire if (now - start) >= duration_min.
Cooldown: rules:fired:<rule_id>:<uuid> with TTL = 30 min (prevents re-fire flood).

Notifications: stored in user_reports with category='other', title prefixed '[RULE ALERT]'.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

_YAML_SEARCH_PATHS = [
    "/app/input/{building_id}/rules.yaml",
    "input/{building_id}/rules.yaml",
]

_OPS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}

_COOLDOWN_TTL_S = 1800  # 30-minute re-fire suppression


class RuleTrigger(BaseModel):
    sensor_uuid: Optional[str] = None
    concept: Optional[str] = None
    op: str = Field(default=">", pattern=r"^(>|<|>=|<=|==|!=)$")
    threshold: float = 0.0
    duration_min: int = Field(default=0, ge=0)


class RuleAction(BaseModel):
    type: str = "notify"
    message: str = ""
    severity: str = "warning"


class EcaRule(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = ""
    enabled: bool = True
    trigger: RuleTrigger
    action: RuleAction = Field(default_factory=RuleAction)


class RulesEngine:
    """Evaluate ECA rules against live sensor values.

    Args:
        building_id: Building context (used to locate rules.yaml).
        value_fetcher: async (uuid: str) -> Optional[float]; injected for tests.
        notifier: async (rule: EcaRule, uuid: str, value: float) -> None; injected for tests.
    """

    def __init__(
        self,
        building_id: str,
        *,
        value_fetcher: Optional[Callable] = None,
        notifier: Optional[Callable] = None,
    ) -> None:
        self._building_id = building_id
        self._rules: List[EcaRule] = []
        self._value_fetcher = value_fetcher or self._default_value_fetcher
        self._notifier = notifier or self._default_notifier

    # ── Loading ───────────────────────────────────────────────────────────────

    def load(self) -> int:
        """Load rules.yaml for the building. Returns number of enabled rules."""
        yaml_path = self._find_yaml()
        if yaml_path is None:
            logger.info(f"[rules_engine] no rules.yaml for '{self._building_id}' — engine idle")
            return 0

        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            logger.warning(f"[rules_engine] could not parse {yaml_path}: {e}")
            return 0

        rule_defs = data.get("rules", [])
        loaded = 0
        for entry in rule_defs:
            try:
                rule = EcaRule(**entry)
            except Exception as e:
                logger.warning(f"[rules_engine] invalid rule spec {entry.get('id', '?')}: {e}")
                continue
            if rule.enabled:
                self._rules.append(rule)
                loaded += 1

        logger.info(
            f"[rules_engine] building='{self._building_id}' loaded {loaded} rule(s) "
            f"from {yaml_path}"
        )
        return loaded

    @property
    def rules(self) -> List[EcaRule]:
        return list(self._rules)

    async def load_user_rules(self) -> int:
        """Append user-tier alert rules (from Redis) to the evaluation cycle. Returns count added."""
        try:
            from orchestrator.services.user_alert_store import get_user_alert_store

            store = get_user_alert_store()
            docs = await store.get_all_building_alerts(self._building_id)
            added = 0
            existing_ids = {r.id for r in self._rules}
            for doc in docs:
                if doc.get("id") in existing_ids:
                    continue  # already loaded
                try:
                    rule = EcaRule(**{k: v for k, v in doc.items() if k != "user_id"})
                    self._rules.append(rule)
                    added += 1
                except Exception as e:
                    logger.debug(f"[rules_engine] user rule parse error: {e}")
            if added:
                logger.info(
                    f"[rules_engine] loaded {added} user-tier rule(s) for {self._building_id}"
                )
            return added
        except Exception as e:
            logger.debug(f"[rules_engine] load_user_rules error: {e}")
            return 0

    # ── Evaluation ───────────────────────────────────────────────────────────

    async def evaluate_all(self) -> int:
        """Evaluate all enabled rules (operator + user tier). Returns count of rules that fired."""
        # Refresh user-tier rules each cycle (Redis may have new rules since last poll)
        await self.load_user_rules()

        if not self._rules:
            return 0

        fired = 0
        for rule in self._rules:
            try:
                if await self._evaluate_rule(rule):
                    fired += 1
            except Exception as e:
                logger.error(f"[rules_engine] error evaluating rule {rule.id}: {e}", exc_info=True)
        return fired

    async def _evaluate_rule(self, rule: EcaRule) -> bool:
        """Return True if rule fires (breach sustained + cooldown passed)."""
        uuid = await self._resolve_uuid(rule)
        if not uuid:
            logger.debug(f"[rules_engine] rule {rule.id}: could not resolve UUID — skip")
            return False

        value = await self._value_fetcher(uuid)
        if value is None:
            logger.debug(f"[rules_engine] rule {rule.id}: no value for {uuid[:16]}... — skip")
            return False

        op_fn = _OPS.get(rule.trigger.op)
        if op_fn is None:
            logger.warning(f"[rules_engine] unknown op '{rule.trigger.op}' in rule {rule.id}")
            return False

        breach = op_fn(value, rule.trigger.threshold)

        if not breach:
            await self._clear_breach(rule.id, uuid)
            return False

        # Breach detected — check duration requirement
        if rule.trigger.duration_min > 0:
            if not await self._breach_sustained(rule.id, uuid, rule.trigger.duration_min):
                return False

        # Check cooldown (avoid re-firing)
        if await self._in_cooldown(rule.id, uuid):
            logger.debug(f"[rules_engine] rule {rule.id}: in cooldown — skip")
            return False

        # FIRE
        await self._mark_cooldown(rule.id, uuid)
        await self._clear_breach(rule.id, uuid)
        await self._notifier(rule, uuid, value)
        logger.info(
            f"[rules_engine] FIRED rule={rule.id} uuid={uuid[:16]}... "
            f"value={value} op={rule.trigger.op} threshold={rule.trigger.threshold}"
        )
        return True

    async def _resolve_uuid(self, rule: EcaRule) -> Optional[str]:
        """Return the sensor UUID for a rule trigger (direct UUID or concept resolution)."""
        if rule.trigger.sensor_uuid:
            return rule.trigger.sensor_uuid

        if rule.trigger.concept:
            try:
                from orchestrator.services.concept_resolver import concept_resolver

                matches = await concept_resolver.resolve(rule.trigger.concept)
                if matches:
                    bc = matches[0].brick_classes or []
                    if bc:
                        # Get first UUID for this brick class from GraphDB
                        return await self._uuid_for_class(bc[0])
            except Exception as e:
                logger.warning(
                    f"[rules_engine] concept resolve failed for {rule.trigger.concept}: {e}"
                )
        return None

    async def _uuid_for_class(self, brick_class: str) -> Optional[str]:
        """Query GraphDB for the first sensor UUID of a given Brick class."""
        bldg_ns = settings.ONTOLOGY_NAMESPACE
        q = f"""PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
SELECT ?uuid WHERE {{
  ?sensor a {brick_class} .
  ?sensor brick:hasExternalReference ?ref .
  ?ref ref:hasTimeseriesId ?uuid .
  FILTER(STRSTARTS(STR(?sensor), "{bldg_ns}"))
}} LIMIT 1"""
        try:
            import httpx

            endpoint = (
                f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}"
                f"/repositories/{settings.GRAPHDB_REPOSITORY}"
            )
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    endpoint,
                    content=q.encode(),
                    headers={
                        "Content-Type": "application/sparql-query",
                        "Accept": "application/sparql-results+json",
                    },
                )
                if resp.status_code == 200:
                    bindings = resp.json().get("results", {}).get("bindings", [])
                    if bindings:
                        return bindings[0]["uuid"]["value"]
        except Exception as e:
            logger.debug(f"[rules_engine] uuid_for_class query failed: {e}")
        return None

    # ── Duration / cooldown via Redis ─────────────────────────────────────────

    async def _breach_sustained(self, rule_id: str, uuid: str, duration_min: int) -> bool:
        """Returns True if breach has been sustained for at least duration_min minutes."""
        key = f"rules:breach_start:{rule_id}:{uuid}"
        try:
            from orchestrator.redis_manager import redis_manager

            raw = await redis_manager.get_cache(key)
            if raw is None:
                # First detection — record start time
                await redis_manager.set_cache(
                    key, datetime.now(tz=timezone.utc).isoformat(), ttl=duration_min * 60 + 300
                )
                return False
            start = datetime.fromisoformat(raw if isinstance(raw, str) else str(raw))
            elapsed_min = (datetime.now(tz=timezone.utc) - start).total_seconds() / 60
            return elapsed_min >= duration_min
        except Exception as e:
            logger.debug(f"[rules_engine] breach_sustained Redis error: {e}")
            return True  # degrade gracefully: treat as sustained

    async def _clear_breach(self, rule_id: str, uuid: str) -> None:
        """Remove breach start timestamp when value returns to normal."""
        try:
            from orchestrator.redis_manager import redis_manager

            await redis_manager.delete_cache(f"rules:breach_start:{rule_id}:{uuid}")
        except Exception:
            pass

    async def _in_cooldown(self, rule_id: str, uuid: str) -> bool:
        """Return True if this rule+uuid recently fired and is in cooldown."""
        try:
            from orchestrator.redis_manager import redis_manager

            val = await redis_manager.get_cache(f"rules:fired:{rule_id}:{uuid}")
            return val is not None
        except Exception:
            return False

    async def _mark_cooldown(self, rule_id: str, uuid: str) -> None:
        try:
            from orchestrator.redis_manager import redis_manager

            await redis_manager.set_cache(f"rules:fired:{rule_id}:{uuid}", "1", ttl=_COOLDOWN_TTL_S)
        except Exception:
            pass

    # ── Default implementations (replaced in tests) ───────────────────────────

    async def _default_value_fetcher(self, uuid: str) -> Optional[float]:
        """Fetch the latest value for a UUID from MySQL sensor_data."""
        try:
            from orchestrator.services.adapters.mysql_adapter import MySQLAdapter

            adapter = MySQLAdapter()
            backtick_uuid = f"`{uuid}`"
            result = await adapter.execute_query(
                f"SELECT {backtick_uuid} FROM sensordb.sensor_data "
                f"WHERE {backtick_uuid} IS NOT NULL "
                f"ORDER BY Datetime DESC LIMIT 1"
            )
            if result.success and result.data:
                row = result.data[0]
                v = row.get(uuid) or row.get(next(iter(row), None))
                if v is not None:
                    return float(v)
        except Exception as e:
            logger.debug(f"[rules_engine] default_value_fetcher failed for {uuid[:16]}...: {e}")
        return None

    async def _default_notifier(self, rule: EcaRule, uuid: str, value: float) -> None:
        """Write alert to user_reports and dispatch through notification service (T33)."""
        msg = rule.action.message or (
            f"{rule.name}: value {value} {rule.trigger.op} {rule.trigger.threshold}"
        )
        try:
            msg = msg.format(
                value=value,
                threshold=rule.trigger.threshold,
                duration_min=rule.trigger.duration_min,
            )
        except Exception:
            pass

        title = f"[RULE ALERT] {rule.name or rule.id}"

        # Write to user_reports (persistent record)
        try:
            from orchestrator.services.report_intake_service import (
                get_report_intake_service,
            )

            svc = get_report_intake_service()
            await svc.create_report(
                description=f"{title}: {msg}",
                building_id=self._building_id,
                category="other",
                reporter_id="rules_engine",
                location=uuid,
                session_id=rule.id,
            )
        except Exception as e:
            logger.warning(f"[rules_engine] user_reports write failed: {e}")

        # Dispatch through configured channels (log always fires; webhook/smtp if configured)
        try:
            from orchestrator.services.notification_service import (
                get_notification_service,
            )

            notif_svc = get_notification_service(self._building_id)
            await notif_svc.dispatch(
                title=title,
                message=msg,
                severity=rule.action.severity,
                building_id=self._building_id,
                source=f"rules_engine:{rule.id}",
            )
        except Exception as e:
            logger.warning(f"[rules_engine] notification dispatch failed: {e}")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def run_forever(self, interval_s: int = 60) -> None:
        """Polling loop — called as an asyncio task from FastAPI lifespan."""
        logger.info(
            f"[rules_engine] starting poll loop interval={interval_s}s rules={len(self._rules)}"
        )
        while True:
            try:
                fired = await self.evaluate_all()
                if fired:
                    logger.info(f"[rules_engine] evaluation cycle: {fired} rule(s) fired")
            except Exception as e:
                logger.error(f"[rules_engine] evaluation error: {e}", exc_info=True)
            await asyncio.sleep(interval_s)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_yaml(self) -> Optional[Path]:
        for tmpl in _YAML_SEARCH_PATHS:
            p = Path(tmpl.format(building_id=self._building_id))
            if p.exists():
                return p
        return None
