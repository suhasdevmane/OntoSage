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
        #: uuid -> sensor IRI, so a log can name the point a rule actually watches.
        self._sensor_of: Dict[str, str] = {}
        #: uuid -> ref:storedAt, so a value is read from the store that holds it
        #: rather than from one table named in this file.
        self._storage_of: Dict[str, str] = {}
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
            # A direct uuid never passes through the class query, so nothing has recorded
            # WHERE it is stored. Look it up once; without this the value fetch would fall
            # back to the default adapter and miss any point in a narrow table.
            if rule.trigger.sensor_uuid not in self._storage_of:
                await self._note_storage_for(rule.trigger.sensor_uuid)
            return rule.trigger.sensor_uuid

        if rule.trigger.concept:
            try:
                from orchestrator.services.concept_resolver import concept_resolver

                matches = await concept_resolver.resolve(rule.trigger.concept)
                if matches:
                    bc = matches[0].brick_classes or []
                    for cls in bc:
                        # PREFER A POINT THAT IS ACTUALLY REPORTING.
                        #
                        # Taking the first IRI the graph returns binds the rule to an
                        # arbitrary point, and arbitrary can mean dead: `damp` resolved to
                        # `RH_Sensor_F0`, which holds ZERO rows, for a rule named
                        # `humidity_damp_floor3`. It bound and still could not fire — the
                        # failure simply moved one step later, which is worse than the
                        # original because now nothing logs a problem at all.
                        #
                        # The engine already knows how to read a point, so ask. This does
                        # not make the choice RIGHT — a concept rule still watches one
                        # point of however many carry the class (BUG-482) — but it makes
                        # it meaningful instead of arbitrary.
                        candidates = await self._uuids_for_class(cls)
                        for uuid in candidates:
                            if await self._value_fetcher(uuid) is not None:
                                # SAY WHICH POINT, once the choice is real. A concept rule
                                # watches ONE point of however many carry the class -- 288
                                # for Temperature_Sensor here -- and which one is invisible
                                # from the rule definition, so a reader assumes it covers
                                # the building (BUG-482).
                                logger.info(
                                    "[rules_engine] rule=%s concept %r -> %s "
                                    "(%d candidate(s) of %s) — this rule watches THIS "
                                    "point only",
                                    rule.id,
                                    rule.trigger.concept,
                                    self._sensor_of.get(uuid, uuid[:8]),
                                    len(candidates),
                                    cls,
                                )
                                return uuid
                    if bc:
                        logger.warning(
                            "[rules_engine] rule=%s concept %r matched %s but no point of "
                            "those classes is reporting a value — this rule cannot fire",
                            rule.id,
                            rule.trigger.concept,
                            ", ".join(bc),
                        )
            except Exception as e:
                # NAME THE FAILING COMPONENT, not the step being attempted.
                #
                # This said "concept resolve failed for <concept>", which reads as "the
                # concept resolver could not map this lay term" -- a data problem someone
                # would fix in hbco_mappings.ttl. What it actually reported for months was
                # `'Settings' object has no attribute 'ONTOLOGY_NAMESPACE'`, a programming
                # error two calls away in `_uuid_for_class` (BUG-481). A message that
                # misattributes its own cause is worse than no message: it sends the
                # reader to the wrong file.
                logger.warning(
                    "[rules_engine] rule=%s could not resolve a sensor for concept %r: "
                    "%s: %s — this rule cannot fire until it does",
                    rule.id,
                    rule.trigger.concept,
                    type(e).__name__,
                    e,
                )
        return None

    def _namespace(self) -> str:
        """This engine's building namespace (BUG-481).

        Was `settings.ONTOLOGY_NAMESPACE`, which does not exist on Settings and never has.
        The AttributeError was raised outside this method's own try, so it propagated to
        `_resolve_uuid`'s broad `except Exception` and was logged as a WARNING reading
        "concept resolve failed for <concept>" -- which describes the concept resolver,
        not a missing setting. Every concept-triggered rule therefore resolved to no UUID
        and could never fire, on every cycle, silently, for as long as the code has
        existed. The rules engine was reported live in the V10 notes as newly loaded; it
        was loaded and inert.

        Resolved from the engine's OWN building rather than the process-global, because
        `RulesEngine` is constructed per building and a background loop has no request
        context to read one from.
        """
        try:
            from orchestrator.services.building_context import resolve_building_context

            bctx = resolve_building_context(self._building_id)
            if bctx and getattr(bctx, "namespace", ""):
                return bctx.namespace
        except Exception as exc:  # pragma: no cover - the global default is a fine fallback
            logger.debug(f"[rules_engine] building context unavailable: {exc}")
        return settings.BUILDING_NAMESPACE or ""

    #: How many candidate points to consider before giving up on a class.
    #:
    #: Bounded because this runs on a polling loop and each candidate costs a store
    #: read. Large enough to get past a run of dead points, small enough that a class
    #: with hundreds of instances does not turn one rule evaluation into hundreds of
    #: queries.
    CLASS_CANDIDATES = 10

    async def _note_storage_for(self, uuid: str) -> None:
        """Record where one point's readings live, for a rule that named it directly."""
        q = f"""PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
SELECT ?sensor ?storage WHERE {{
  ?ref ref:hasTimeseriesId "{uuid}" .
  OPTIONAL {{ ?ref ref:storedAt ?storage }}
  OPTIONAL {{ ?sensor ref:hasExternalReference ?ref }}
}} LIMIT 1"""
        rows = await self._select(q)
        if rows:
            self._storage_of[uuid] = rows[0].get("storage", {}).get("value", "")
            self._sensor_of.setdefault(uuid, rows[0].get("sensor", {}).get("value", "?"))

    async def _select(self, query: str) -> List[Dict[str, Any]]:
        """Run a SELECT against this building's repository. [] on any failure."""
        try:
            import httpx

            endpoint = (
                f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}"
                f"/repositories/{settings.GRAPHDB_REPOSITORY}"
            )
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    endpoint,
                    content=query.encode(),
                    headers={
                        "Content-Type": "application/sparql-query",
                        "Accept": "application/sparql-results+json",
                    },
                )
            if resp.status_code == 200:
                return resp.json().get("results", {}).get("bindings", [])
            logger.debug("[rules_engine] SELECT returned HTTP %s", resp.status_code)
        except Exception as e:
            logger.debug(f"[rules_engine] SELECT failed: {e}")
        return []

    async def _uuids_for_class(self, brick_class: str) -> List[str]:
        """Candidate timeseries ids for a Brick class, in a stable order."""
        bldg_ns = self._namespace()
        # `ref:hasExternalReference`, NOT `brick:` (BUG-481, second layer).
        #
        # Fixing the namespace AttributeError removed the error and not the failure: every
        # concept still resolved to None, now silently. Measured against the live graph:
        #
        #     ?s brick:hasExternalReference ?o  ->     2 triples
        #     ?s ref:hasExternalReference   ?o  -> 2,860 triples
        #
        # The two in `brick:` come from the Brick vocabulary itself, so the join never
        # matched a real sensor and the query returned empty for EVERY class, including
        # `brick:Temperature_Sensor`, of which this building has 288.
        #
        # `rdfs:subClassOf*` because an instance may be typed to a subclass of the class
        # the concept names. It changes nothing on this building (288 either way) and
        # costs nothing; on a building that types its points more specifically it is the
        # difference between finding them and not.
        q = f"""PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
SELECT ?sensor ?uuid ?storage WHERE {{
  ?sensor a/rdfs:subClassOf* {brick_class} .
  ?sensor ref:hasExternalReference ?ref .
  ?ref ref:hasTimeseriesId ?uuid .
  OPTIONAL {{ ?ref ref:storedAt ?storage }}
  FILTER(STRSTARTS(STR(?sensor), "{bldg_ns}"))
}} ORDER BY ?sensor LIMIT {self.CLASS_CANDIDATES}"""
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
                        # Candidates only. WHICH one a rule ends up watching is decided by
                        # the caller, which keeps the first that is actually reporting —
                        # so naming a point here would be the BUG-481 mistake again: a
                        # message describing something other than what happened.
                        for b in bindings:
                            if not b.get("uuid"):
                                continue
                            _u = b["uuid"]["value"]
                            self._sensor_of[_u] = b.get("sensor", {}).get("value", "?")
                            self._storage_of[_u] = b.get("storage", {}).get("value", "")
                        return [b["uuid"]["value"] for b in bindings if b.get("uuid")]
                    logger.debug(
                        "[rules_engine] no point of class %s has a timeseries id in %s",
                        brick_class,
                        bldg_ns,
                    )
        except Exception as e:
            logger.debug(f"[rules_engine] uuids_for_class query failed: {e}")
        return []

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
        """The latest value for a point, from whichever store actually holds it.

        THIS USED TO NAME ONE TABLE IN ONE DATABASE:

            SELECT `<uuid>` FROM sensordb.sensor_data WHERE ... ORDER BY Datetime DESC

        Two things wrong with that. It is a database and table LITERAL in a core service,
        which contract rule 3 forbids and which no second building would satisfy. And it
        only ever saw the WIDE table: this building keeps occupancy, humidity, CO2 and the
        rest in narrow per-modality tables, so every point living there read as "no value"
        — the ECA engine could only ever have fired on wide-table sensors. `busyness`
        resolves to a point with 11,812 rows and this returned None for it.

        Routing by `ref:storedAt` through the adapter registry is how every other lane
        already does this, and it is the same mechanism that makes a new backend a new
        adapter rather than an edit here.
        """
        try:
            from orchestrator.services.adapters.registry import adapter_registry

            storage_key = self._storage_of.get(uuid, "")
            adapter = adapter_registry.get(storage_key)
            if adapter is None:
                return None
            ts_col = adapter_registry.get_timestamp_column(storage_key)
            query = adapter.build_timeseries_query(
                uuids=[uuid], ts_col=ts_col, start_date=None, end_date=None, limit=1
            )
            if not query:
                # SQL adapters return None here and expect the caller's own builder. One
                # point, newest row, quoted through the adapter's own identifier rules.
                query = self._latest_value_sql(uuid, ts_col, adapter)
            result = await adapter.execute_query(query)
            if result.success and result.data:
                row = result.data[0]
                for key in ("value", uuid, "val"):
                    if key in row and row[key] is not None:
                        return float(row[key])
                for v in row.values():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        return float(v)
        except Exception as e:
            logger.debug(f"[rules_engine] value fetch failed for {uuid[:16]}...: {e}")
        return None

    @staticmethod
    def _latest_value_sql(uuid: str, ts_col: str, adapter: Any) -> str:
        """Newest reading for one point in a WIDE table, as SQL.

        Only reached when the adapter declines to build its own query, which the SQL
        adapters do. The table name comes from the adapter's discovered schema rather
        than from a literal here — that literal is what made this method building-specific.
        """
        table = "sensor_data"
        try:
            schema = getattr(adapter, "_schema", None) or getattr(adapter, "schema", None)
            tables = list(getattr(schema, "tables", []) or [])
            # The wide table is the one carrying this uuid as a COLUMN.
            for candidate in tables:
                cols = {c for c, _t in (getattr(schema, "columns", {}) or {}).get(candidate, [])}
                if uuid in cols:
                    table = candidate
                    break
        except Exception:  # pragma: no cover - fall back to the conventional name
            pass
        col = f"`{uuid}`"
        return (
            f"SELECT {col} AS value FROM `{table}` "
            f"WHERE {col} IS NOT NULL ORDER BY `{ts_col}` DESC LIMIT 1"
        )

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
        """Locate this building's rules.yaml, in EITHER input layout.

        The search paths below name the nested form only, and the canonical layout is
        FLAT: under swap-by-rename the active building's files sit directly in ``input/``.
        So this could never find rules.yaml for any building this repo ships. The loader ran,
        found nothing, logged "no rules.yaml" and the feature was silently off -- which reads
        in a log exactly like a building that chose not to configure it.

        Five other per-building loaders had the same shape: the same search logic written
        six ways, five of the copies wrong (CAVEAT-448). ``shared/building_paths`` is the
        one implementation; the literal list is kept only as a fallback for a caller that
        has neither layout under a standard root.
        """
        from shared.building_paths import resolve_building_file

        resolved = resolve_building_file(self._building_id, "rules.yaml")
        if resolved is not None:
            return resolved
        for tmpl in _YAML_SEARCH_PATHS:
            p = Path(tmpl.format(building_id=self._building_id))
            if p.exists():
                return p
        return None
